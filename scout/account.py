"""Transactional virtual account. Quotes, orders, fills and balances commit together."""
from contextlib import contextmanager, closing
from dataclasses import asdict
from datetime import datetime, timezone
import csv
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import time
from .core import Settings

APP_ID = 0x42575033


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def encode(value):
    return json.dumps(value, separators=(',', ':'), allow_nan=False)


class Account:
    def __init__(self, path):
        self.path = Path(path)
        if not self.path.is_file():
            raise ValueError('Paper account does not exist. Start forward.py to create one.')
        with closing(self.connection()) as conn:
            if conn.execute('PRAGMA application_id').fetchone()[0] != APP_ID or conn.execute('PRAGMA user_version').fetchone()[0] != 1:
                raise ValueError('Unsupported paper database. Existing files are never reset automatically.')
            self._state(conn)

    @classmethod
    def create(cls, path, symbols, settings, source, provider, bar_seconds=300,
               max_receipt_age=90, max_fetch_latency=10, max_order_age=900, max_gap=180):
        settings.validate()
        if not 1 <= len(symbols) <= 4 or len(set(symbols)) != len(symbols) or not all(isinstance(s, str) and re.fullmatch(r'[A-Z0-9]{1,16}-USD', s) for s in symbols):
            raise ValueError('Use 1–4 unique uppercase crypto USD pairs.')
        if source not in ('synthetic_live_demo', 'robinhood_crypto_v2') or not isinstance(provider, str) or not 1 <= len(provider) <= 200:
            raise ValueError('Invalid observation source or provider identity.')
        if type(bar_seconds) is not int or not 60 <= bar_seconds <= 3600:
            raise ValueError('Sampled candle size must be 60–3,600 seconds.')
        if not all(finite(v) and v > 0 for v in (max_receipt_age, max_fetch_latency, max_order_age, max_gap)):
            raise ValueError('Freshness and expiry limits must be positive finite numbers.')
        config = {'symbols': sorted(symbols), 'settings': asdict(settings), 'source': source,
                  'provider': provider, 'bar_seconds': bar_seconds, 'max_receipt_age': max_receipt_age,
                  'max_fetch_latency': max_fetch_latency, 'max_order_age': max_order_age, 'max_gap': max_gap}
        path = Path(path);path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(descriptor)
        state = {'config': config, 'cash': settings.capital, 'positions': {s: 0.0 for s in symbols},
                 'quotes': {}, 'peak': settings.capital, 'equity': settings.capital, 'drawdown': 0.0,
                 'max_drawdown': 0.0, 'fees': 0.0, 'slippage': 0.0, 'pending': [], 'paused': False,
                 'halted': False, 'seq': 0, 'last_received': None, 'last_decided_bar': 0,
                 'control_revision': 0, 'health': 'waiting_for_quotes', 'last_error': None,
                 'building': {}, 'history': {s: [] for s in symbols}, 'last_completed_bar': 0}
        with closing(sqlite3.connect(path)) as conn:
            conn.executescript(f'''
                PRAGMA journal_mode=WAL;
                PRAGMA synchronous=FULL;
                PRAGMA application_id={APP_ID};
                PRAGMA user_version=1;
                CREATE TABLE account (id INTEGER PRIMARY KEY CHECK(id=1), payload TEXT NOT NULL);
                CREATE TABLE events (id INTEGER PRIMARY KEY, at REAL NOT NULL, kind TEXT NOT NULL, payload TEXT NOT NULL);
                CREATE TABLE observations (seq INTEGER PRIMARY KEY, received REAL NOT NULL, payload TEXT NOT NULL);
                CREATE TABLE candles (symbol TEXT NOT NULL, end INTEGER NOT NULL, complete INTEGER NOT NULL,
                    payload TEXT NOT NULL, PRIMARY KEY(symbol,end));
                CREATE TABLE lease (id INTEGER PRIMARY KEY CHECK(id=1), owner TEXT NOT NULL, expires REAL NOT NULL);
            ''')
            conn.execute('INSERT INTO account VALUES (1,?)', (encode(state),))
            conn.execute('INSERT INTO events(at,kind,payload) VALUES (?,?,?)', (time.time(), 'created', encode(config)))
            conn.commit()
        return cls(path)

    def connection(self):
        conn = sqlite3.connect(self.path.resolve().as_uri()+'?mode=rw', uri=True, timeout=10, isolation_level=None)
        conn.execute('PRAGMA busy_timeout=10000');conn.execute('PRAGMA synchronous=FULL')
        return conn

    @contextmanager
    def transaction(self):
        conn = self.connection()
        try:
            conn.execute('BEGIN IMMEDIATE')
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback();raise
        finally:
            conn.close()

    def _state(self, conn):
        row = conn.execute('SELECT payload FROM account WHERE id=1').fetchone()
        if row is None:raise ValueError('Missing paper state; refusing to reset funds.')
        state = json.loads(row[0])
        if not finite(state['cash']) or state['cash'] < -1e-8 or any(not finite(q) or q < 0 for q in state['positions'].values()):
            raise ValueError('Invalid paper balances; inspect a database backup.')
        return state

    def _save(self, conn, state):
        conn.execute('UPDATE account SET payload=? WHERE id=1', (encode(state),))

    def _event(self, conn, at, kind, payload):
        conn.execute('INSERT INTO events(at,kind,payload) VALUES (?,?,?)', (at, kind, encode(payload)))

    def claim(self, owner, seconds=180, now=None):
        now = time.time() if now is None else now
        with self.transaction() as conn:
            row = conn.execute('SELECT owner,expires FROM lease WHERE id=1').fetchone()
            if row and row[0] != owner and row[1] > now:
                raise ValueError('Another worker is running for this paper account.')
            conn.execute('INSERT OR REPLACE INTO lease VALUES (1,?,?)', (owner, now + seconds))

    def release(self, owner):
        with self.transaction() as conn:
            conn.execute('DELETE FROM lease WHERE id=1 AND owner=?', (owner,))

    def _check_owner(self, conn, owner, now):
        lease = conn.execute('SELECT owner,expires FROM lease WHERE id=1').fetchone()
        if lease and (owner != lease[0] or lease[1] <= now):
            raise ValueError('Worker lease lost or expired. Stop this worker.')
        if owner is not None and lease is None:
            raise ValueError('Worker has no active lease.')

    def control(self, paused, now=None):
        if type(paused) is not bool:raise ValueError('paused must be true or false.')
        now = time.time() if now is None else now
        with self.transaction() as conn:
            state = self._state(conn);state['paused'] = paused;state['control_revision'] += 1
            state['pending'] = []
            self._event(conn, now, 'paused' if paused else 'resumed', {'positions_retained': True, 'halt_remains': state['halted']})
            self._save(conn, state)

    def error(self, error_type, owner=None, now=None):
        now = time.time() if now is None else now
        with self.transaction() as conn:
            self._check_owner(conn, owner, now)
            state = self._state(conn);state['health'] = 'degraded';state['last_error'] = str(error_type)[:80]
            state['pending'] = []
            self._event(conn, now, 'provider_error', {'error_type': state['last_error'], 'pending_cancelled': True})
            self._save(conn, state)

    def validate_snapshot(self, snapshot, state, now):
        config = state['config']
        if snapshot.get('source') != config['source']:raise ValueError('Observation source changed.')
        received = snapshot.get('received_at_unix');latency = snapshot.get('elapsed_seconds')
        if not finite(received) or not -5 <= now - received <= config['max_receipt_age']:
            raise ValueError('Quote receipt is stale or in the future.')
        if not finite(latency) or not 0 <= latency <= config['max_fetch_latency']:
            raise ValueError('Quote fetch latency is too high or unknown.')
        rows = snapshot.get('quotes')
        if not isinstance(rows, list) or len(rows) != len(config['symbols']):raise ValueError('Missing quote batch.')
        quotes = {}
        for row in rows:
            symbol = row.get('symbol');bid = row.get('bid');ask = row.get('ask')
            if symbol not in config['symbols'] or symbol in quotes or not finite(bid) or not finite(ask) or not 0 < bid <= ask:
                raise ValueError('Invalid, missing or duplicate quote.')
            quotes[symbol] = {'bid': bid, 'ask': ask}
        return received, quotes

    def _mark(self, state):
        settings = state['config']['settings'];fee = settings['fees_bps']['crypto']/10000;slip = settings['slippage_bps']['crypto']/10000
        equity = state['cash'] + sum(q * state['quotes'][s]['bid'] * (1-slip) * (1-fee) for s,q in state['positions'].items() if q)
        state['equity'] = equity;state['peak'] = max(state['peak'], equity)
        state['drawdown'] = (state['peak']-equity)/state['peak']
        state['max_drawdown'] = max(state['max_drawdown'],state['drawdown'])
        if state['drawdown'] >= settings['max_drawdown']:
            state['halted'] = True
        return equity

    def _candles(self, conn, state, received, quotes, gap):
        width = state['config']['bar_seconds'];bucket = int(received//width)*width;completed = False
        for symbol, quote in quotes.items():
            mid = (quote['bid']+quote['ask'])/2;old = state['building'].get(symbol)
            if old is not None and old['bucket'] != bucket:
                complete = (bucket-old['bucket'] == width and not gap and not old.get('gapped',False)
                            and old['samples']>=2 and old['first_received']<=old['bucket']+width*.25
                            and old['last_received']>=old['bucket']+width*.75)
                candle = {'timestamp': datetime.fromtimestamp(old['bucket']+width, timezone.utc).isoformat(),
                          'open': old['open'], 'high': old['high'], 'low': old['low'], 'close': old['close'],
                          'volume': 0, 'samples': old['samples'], 'provenance': 'sampled_quote_midpoints_not_exchange_trades'}
                conn.execute('INSERT INTO candles VALUES (?,?,?,?)', (symbol,old['bucket']+width,int(complete),encode(candle)))
                if complete:
                    state['history'][symbol] = (state['history'][symbol]+[candle])[-60:]
                    state['last_completed_bar'] = old['bucket']+width;completed = True
                else:
                    state['history'][symbol] = []
            if old is None or old['bucket'] != bucket:
                state['building'][symbol] = {'bucket': bucket, 'open': mid,'high': mid,'low': mid,'close': mid,'samples': 1, 'first_received':received, 'last_received':received, 'gapped':False}
            else:
                old['high']=max(old['high'],mid);old['low']=min(old['low'],mid);old['close']=mid;old['samples']+=1;old['last_received']=received
                if gap:
                    old['gapped']=True;state['history'][symbol]=[]
        return completed

    def ingest(self, snapshot, owner=None, now=None):
        now = time.time() if now is None else now
        with self.transaction() as conn:
            self._check_owner(conn, owner, now);state = self._state(conn)
            received, quotes = self.validate_snapshot(snapshot,state,now)
            if state['last_received'] is not None and received <= state['last_received']:
                return {'accepted': False, 'completed': False, 'seq': state['seq']}
            gap = state['last_received'] is not None and received-state['last_received'] > state['config']['max_gap']
            if gap:
                state['pending']=[];self._event(conn,now,'observation_gap',{'seconds':received-state['last_received'],'pending_cancelled':True})
            seq = state['seq']+1;was_halted=state['halted'];state['quotes']=quotes
            self._mark(state)
            if state['halted']:
                state['pending']=[p for p in state['pending'] if p['side']=='sell']
            settings=state['config']['settings'];fee_rate=settings['fees_bps']['crypto']/10000;slip_rate=settings['slippage_bps']['crypto']/10000
            pending=sorted(state['pending'],key=lambda p:(p['side']=='buy',p['symbol']))
            state['pending']=[]
            for order in pending:
                if state['paused'] or order['created_seq']>=seq or received-order['created_at']>state['config']['max_order_age']:
                    self._event(conn,now,'order_cancelled',{'symbol':order['symbol'],'side':order['side'],'reason':'paused, expired or not a later observation'})
                    continue
                symbol=order['symbol'];side=order['side'];held=state['positions'][symbol]
                if side=='sell' and held>0:
                    reference=quotes[symbol]['bid'];price=reference*(1-slip_rate);quantity=held;fee=quantity*price*fee_rate
                    state['cash']+=quantity*price-fee;state['positions'][symbol]=0
                elif side=='buy' and not state['halted'] and held==0:
                    reference=quotes[symbol]['ask'];price=reference*(1+slip_rate)
                    total=self._mark(state)
                    exposure=sum(q*quotes[s]['bid'] for s,q in state['positions'].items())
                    weight=min(settings['max_position'],settings['crypto_weight']/len(quotes))
                    # Enforce gross bid exposure caps against equity AFTER entry/estimated exit costs.
                    # For q units: new equity = total - q*(cost_per_unit-liquidation_per_unit).
                    cost_per_unit=price*(1+fee_rate)
                    bid=quotes[symbol]['bid'];liquidation_per_unit=bid*(1-slip_rate)*(1-fee_rate)
                    loss_per_unit=cost_per_unit-liquidation_per_unit
                    cap=min(.9,settings['crypto_weight'])
                    quantity=min(state['cash']/cost_per_unit,
                                 max(0,total*cap-exposure)/(bid+cap*loss_per_unit),
                                 total*weight/(bid+weight*loss_per_unit))
                    if quantity<=1e-12:continue
                    fee=quantity*price*fee_rate;state['cash']-=quantity*price+fee;state['positions'][symbol]=quantity
                else:continue
                slippage=quantity*abs(price-reference);state['fees']+=fee;state['slippage']+=slippage
                self._event(conn,received,'fill',{'seq':seq,'symbol':symbol,'side':side,'quantity':quantity,'reference_quote':reference,
                                                'fill_price':price,'fee':fee,'slippage_cost':slippage,'decision_id':order['decision_id']})
                self._mark(state)
            self._mark(state)
            if state['halted'] and not was_halted:self._event(conn,now,'drawdown_halt',{'drawdown':state['drawdown']})
            if state['halted'] and not state['paused']:
                state['pending']=[{'symbol':s,'side':'sell','created_seq':seq,'created_at':received,'decision_id':'risk_halt'} for s,q in state['positions'].items() if q]
            completed=self._candles(conn,state,received,quotes,gap)
            state.update(seq=seq,last_received=received,health='observing',last_error=None)
            conn.execute('INSERT INTO observations VALUES (?,?,?)',(seq,received,encode(snapshot)))
            # Keep a bounded recent quote cache; fills/decisions and sampled candles remain in the journal.
            if seq%100==0:conn.execute('DELETE FROM observations WHERE seq<=?',(seq-10000,))
            self._save(conn,state)
            return {'accepted':True,'completed':completed,'seq':seq,'bar_end':state['last_completed_bar'],
                    'control_revision':state['control_revision']}

    def evidence(self):
        with closing(self.connection()) as conn:state=self._state(conn)
        return {'timestamp':datetime.fromtimestamp(state['last_completed_bar'],timezone.utc).isoformat(),
                'cash':state['cash'],'equity':state['equity'],'net_equity':state['equity'],
                'positions':state['positions'],'drawdown':state['drawdown'],'max_drawdown':state['max_drawdown'],
                'bars':{s:hist[-30:] for s,hist in state['history'].items()},'source':state['config']['source'],
                'settings':state['config']['settings'],'quote_provenance':'Receipt times only. Sampled midpoint bars, not exchange OHLCV.'}

    def queue(self, proposal, expected_seq, control_revision, bar_end, owner=None, now=None):
        now=time.time() if now is None else now
        with self.transaction() as conn:
            self._check_owner(conn,owner,now);state=self._state(conn)
            if state['paused'] or state['halted'] or state['seq']!=expected_seq or state['control_revision']!=control_revision or bar_end<=state['last_decided_bar'] or bar_end!=state['last_completed_bar'] or now-state['last_received']>state['config']['max_receipt_age']:
                self._event(conn,now,'decision_discarded',{'bar_end':bar_end,'reason':'account changed, paused/halted, repeated bar, or quote receipt expired'})
                return False
            actions=proposal.get('actions');reason=proposal.get('reason')
            if not isinstance(actions,dict) or set(actions)!=set(state['positions']) or any(a not in ('buy','sell','hold') for a in actions.values()) or not isinstance(reason,str) or len(reason)>2000:
                raise ValueError('Invalid forward paper proposal.')
            if len(encode(proposal))>20000:raise ValueError('Proposal is too large.')
            decision_id=f"bar-{bar_end}";state['pending']=[]
            for symbol,action in actions.items():
                held=state['positions'][symbol]>0
                if (action=='buy' and not held) or (action=='sell' and held):
                    state['pending'].append({'symbol':symbol,'side':action,'created_seq':expected_seq,'created_at':now,'decision_id':decision_id})
            self._event(conn,now,'decision',{'decision_id':decision_id,'bar_end':bar_end,'proposal':proposal,'provider':state['config']['provider']})
            state['last_decided_bar']=bar_end;self._save(conn,state)
            return True

    def snapshot(self, now=None):
        now=time.time() if now is None else now
        with closing(self.connection()) as conn:
            conn.execute('BEGIN')
            state=self._state(conn)
            events=[{'id':row[0],'at':row[1],'kind':row[2],**json.loads(row[3])} for row in conn.execute('SELECT id,at,kind,payload FROM events ORDER BY id DESC LIMIT 100')]
            fills=[{'at':row[0],**json.loads(row[1])} for row in conn.execute("SELECT at,payload FROM events WHERE kind='fill' ORDER BY id DESC LIMIT 100")]
            counts={s:n for s,n in conn.execute('SELECT symbol,COUNT(*) FROM candles WHERE complete=1 GROUP BY symbol')}
            lease=conn.execute('SELECT expires FROM lease WHERE id=1').fetchone()
            conn.commit()
        age=None if state['last_received'] is None else now-state['last_received']
        return {'version':'0.3.0','mode':'forward_virtual_crypto_account','state':state,'events':events,'fills':fills,
                'completed_candles':counts,'receipt_age_seconds':age,
                'receipt_fresh':age is not None and -5<=age<=state['config']['max_receipt_age'],
                'worker_active':bool(lease and lease[0]>now),
                'net_profit':state['equity']-state['config']['settings']['capital'],
                'limitations':['Virtual account only; no real orders.',
                    'Robinhood endpoint has no exchange timestamp; receipt/latency checks cannot establish upstream quote freshness.',
                    'Sampled midpoint candles omit trades/volume and can miss intrabar highs/lows.',
                    'Bid/ask fills add illustrative slippage and fees; no size-based liquidity, partial fills or real execution modeled.',
                    'Pause cancels orders and holds positions. It does not liquidate. A sticky drawdown halt resumes exits on fresh observations.',
                    'Entry caps can drift after price changes; drawdown exits may exceed the threshold during gaps/outages.']}

    def export_csv(self, path):
        path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
        with closing(self.connection()) as conn, path.open('x',newline='',encoding='utf-8') as stream:
            writer=csv.writer(stream);writer.writerow(['timestamp','symbol','asset_class','open','high','low','close','volume'])
            for symbol,payload in conn.execute('SELECT symbol,payload FROM candles WHERE complete=1 ORDER BY end,symbol'):
                b=json.loads(payload);writer.writerow([b['timestamp'],symbol,'crypto',b['open'],b['high'],b['low'],b['close'],0])
        return path

    def backup(self, path):
        path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
        fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600);os.close(fd)
        with closing(self.connection()) as source,closing(sqlite3.connect(path)) as target:source.backup(target)
        return path
