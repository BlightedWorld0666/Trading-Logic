"""Forward virtual crypto worker. Optional Robinhood reads; never submits real orders."""
import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import random
import secrets
import threading
import time
from types import SimpleNamespace
from scout.account import Account
from scout.safety import Alerts, monitor
from scout.ai import paper_decision
from scout.core import Settings, signal
from scout.learning import load_policy
from scout.robinhood import quotes


def provider_from(args, symbols, settings):
    if args.policy:
        if args.policy.stat().st_size>20000000:raise ValueError('Policy file is too large.')
        raw=args.policy.read_bytes()
        provider=load_policy(json.loads(raw),symbols,{s:'crypto' for s in symbols},settings)
        return provider,'policy:'+hashlib.sha256(raw).hexdigest()
    if args.model:
        def provider(evidence,names):return paper_decision(args.model,evidence,names)
        return provider,'ollama:'+args.model
    strategy=args.strategy or 'trend'
    def provider(evidence,names):
        actions={}
        for s in names:
            bars=[SimpleNamespace(**b) for b in evidence['bars'][s]]
            want=signal(strategy,bars,evidence['positions'][s]>0)
            actions[s]='buy' if want else 'sell'
        return {'actions':actions,'reason':'Fixed '+strategy+' rule on completed sampled midpoint candles.'}
    return provider,'fixed:'+strategy


class DemoFeed:
    def __init__(self,account):
        state=account.snapshot()['state'];self.symbols=state['config']['symbols'];self.tick=state['seq']
        self.prices={s:(state['quotes'][s]['bid']+state['quotes'][s]['ask'])/2 if s in state['quotes'] else (100+50*i) for i,s in enumerate(self.symbols)}
    def __call__(self):
        self.tick+=1;rng=random.Random(666+self.tick)
        for s in self.symbols:self.prices[s]*=max(.9,1+rng.gauss(.0001,.002))
        return {'source':'synthetic_live_demo','received_at_unix':time.time(),'elapsed_seconds':0,
                'freshness':'Invented prices generated locally; no market information.',
                'quotes':[{'symbol':s,'bid':p*.999,'ask':p*1.001} for s,p in self.prices.items()]}


def process_tick(account,feed,provider,owner,now=None):
    snapshot=feed()
    result=account.ingest(snapshot,owner,now)
    if result['accepted'] and result['completed']:
        state=account.snapshot(now)['state']
        if not state['paused'] and not state['halted']:
            if all(len(state['history'][s])>=30 for s in state['positions']):
                evidence=account.evidence()
                proposal=provider(evidence,sorted(state['positions']))
                account.queue(proposal,result['seq'],result['control_revision'],result['bar_end'],owner,now)
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db',type=Path,default=Path('runtime/demo.sqlite'))
    parser.add_argument('--alerts-db',type=Path,default=Path('runtime/alerts.sqlite'))
    parser.add_argument('--source',choices=['demo','robinhood'],default='demo')
    parser.add_argument('--symbols',nargs='+',default=['BTC-USD','ETH-USD'])
    parser.add_argument('--credentials',type=Path,default=Path('secrets/robinhood.json'))
    parser.add_argument('--config',type=Path,default=Path('forward.example.json'))
    parser.add_argument('--interval',type=float,default=60,help='Poll interval seconds; Robinhood minimum 30.')
    parser.add_argument('--bar-seconds',type=int,default=300)
    parser.add_argument('--ticks',type=int,help='Stop after this many polls; otherwise run until Ctrl+C.')
    mode=parser.add_mutually_exclusive_group()
    mode.add_argument('--model')
    mode.add_argument('--policy',type=Path)
    mode.add_argument('--strategy',choices=['cash','trend','reversion','breakout'])
    args=parser.parse_args()
    if not 1<=args.interval<=300 or (args.source=='robinhood' and args.interval<30):parser.error('Use 1–300 seconds; Robinhood polls must be at least 30 seconds apart.')
    if not 60<=args.bar_seconds<=3600 or args.interval>args.bar_seconds/4:parser.error('Use 60–3,600 second candles and a polling interval at most one quarter of the candle size.')
    if args.ticks is not None and args.ticks<1:parser.error('--ticks must be positive.')
    owner=secrets.token_hex(16);account=None;claimed=False
    try:
        settings=Settings(**json.loads(args.config.read_text())).validate()
        symbols=sorted(args.symbols)
        provider,identity=provider_from(args,symbols,settings)
        source='robinhood_crypto_v2' if args.source=='robinhood' else 'synthetic_live_demo'
        if args.db.exists():
            account=Account(args.db);config=account.snapshot()['state']['config']
            expected={'symbols':symbols,'settings':asdict(settings),'source':source,'provider':identity,'bar_seconds':args.bar_seconds}
            if any(config[k]!=v for k,v in expected.items()):
                raise ValueError('Existing account configuration differs. Resume with the same options or choose a new --db.')
        else:
            account=Account.create(args.db,symbols,settings,source,identity,args.bar_seconds,
                                   max_receipt_age=max(90,args.interval*2),max_gap=max(180,args.interval*3))
        account.claim(owner,max(180,args.interval+120));claimed=True
        credentials=None
        if args.source=='robinhood':
            credentials=json.loads(args.credentials.read_text())
            def feed():return quotes(credentials,symbols)
        else:feed=DemoFeed(account)
        print('Forward VIRTUAL account:',args.db,'/ source:',source,'/ provider:',identity,flush=True)
        print('No real orders. Wait for 30 completed sampled candles before decisions. Ctrl+C stops the worker.',flush=True)
        polls=0;stop=threading.Event()
        while args.ticks is None or polls<args.ticks:
            account.claim(owner,max(180,args.interval+120))
            started=time.monotonic()
            try:
                monitor(args.db,args.alerts_db)
                result=process_tick(account,feed,provider,owner)
                state=account.snapshot()['state']
                print(f"Poll {polls+1} | seq {state['seq']} | equity ${state['equity']:.2f} | paused {state['paused']} | halted {state['halted']}",flush=True)
            except Exception as exc:
                # Persist only error type; never credentials, request headers or arbitrary model text.
                account.error(type(exc).__name__,owner)
                Alerts(args.alerts_db).collect(account)
                print('Poll/decision failed:',type(exc).__name__,'/ pending intents cancelled; balances retained.',flush=True)
            polls+=1
            if args.ticks is not None and polls>=args.ticks:break
            stop.wait(max(0,args.interval-(time.monotonic()-started)))
    except KeyboardInterrupt:
        print('Worker stopped. Account and observation journal saved.')
    except (ValueError,OSError,KeyError,TypeError) as exc:
        parser.exit(1,'Could not start/resume forward account: '+(str(exc)[:300] if isinstance(exc,ValueError) else type(exc).__name__)+'. Check options and local files.\n')
    finally:
        if account is not None and claimed:account.release(owner)

if __name__=='__main__':main()
