"""Independent account watchdog and durable, minimal operational alert queue."""
from contextlib import closing, contextmanager
import hashlib
import json
from pathlib import Path
import sqlite3
import time
from .account import Account

ALERT_KINDS=('safety_stop','safety_acknowledged','drawdown_halt','paused','resumed')
APP_ID=0x42574131

class Alerts:
    def __init__(self,path):self.path=Path(path)
    @contextmanager
    def connection(self):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        with sqlite3.connect(self.path,timeout=10) as db:
            db.row_factory=sqlite3.Row
            identity=db.execute('PRAGMA application_id').fetchone()[0]
            tables=db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            if identity!=APP_ID and (identity or tables):raise ValueError('Unsupported alerts database; it has not been reset.')
            db.execute(f'PRAGMA application_id={APP_ID}')
            db.execute('CREATE TABLE IF NOT EXISTS alerts(id INTEGER PRIMARY KEY, key TEXT UNIQUE NOT NULL, at REAL NOT NULL, kind TEXT NOT NULL, message TEXT NOT NULL, delivered REAL, attempts INTEGER NOT NULL DEFAULT 0, last_error TEXT)')
            db.execute('CREATE TABLE IF NOT EXISTS notification_health(key TEXT PRIMARY KEY, payload TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS cursors(scope TEXT PRIMARY KEY, event_id INTEGER NOT NULL)')
            yield db
    def record(self,key,kind,message,now=None):
        with self.connection() as db:db.execute('INSERT OR IGNORE INTO alerts(key,at,kind,message) VALUES(?,?,?,?)',(key,time.time() if now is None else now,kind,message))
    def collect(self,account):
        with closing(account.connection()) as source:
            source.execute('BEGIN')
            created=source.execute("SELECT at FROM events WHERE kind='created' ORDER BY id LIMIT 1").fetchone()[0]
            scope=hashlib.sha256((str(account.path.resolve())+':'+str(created)).encode()).hexdigest()
            with self.connection() as db:
                cursor=db.execute('SELECT event_id FROM cursors WHERE scope=?',(scope,)).fetchone()
                last=cursor[0] if cursor else 0
                marks=','.join('?' for _ in ALERT_KINDS)
                rows=source.execute(f'SELECT id,at,kind,payload FROM events WHERE id>? AND kind IN ({marks}) ORDER BY id LIMIT 1000',(last,*ALERT_KINDS)).fetchall()
                maximum=source.execute('SELECT COALESCE(MAX(id),0) FROM events').fetchone()[0]
                for event_id,at,kind,raw in rows:
                    payload=json.loads(raw)
                    reason=payload.get('reason','')
                    message=f'{kind}: {reason}. Paper account only; positions may remain open.'
                    db.execute('INSERT OR IGNORE INTO alerts(key,at,kind,message) VALUES(?,?,?,?)',(scope+':'+str(event_id),at,kind,message))
                db.execute('INSERT OR REPLACE INTO cursors VALUES(?,?)',(scope,rows[-1][0] if len(rows)==1000 else maximum))
            source.commit()
    def snapshot(self):
        with self.connection() as db:
            rows=[dict(r) for r in db.execute('SELECT * FROM alerts ORDER BY id DESC LIMIT 100')]
            pending=db.execute('SELECT COUNT(*) FROM alerts WHERE delivered IS NULL').fetchone()[0]
        return {'pending':pending,'alerts':rows,'discord':self.delivery_health()}
    def heartbeat(self,ready,now=None):
        with self.connection() as db:
            db.execute('INSERT OR REPLACE INTO notification_health VALUES(?,?)',('discord',json.dumps({'required':True,'ready':bool(ready),'at':time.time() if now is None else now})))
    def delivery_health(self,now=None):
        now=time.time() if now is None else now
        with self.connection() as db:row=db.execute('SELECT payload FROM notification_health WHERE key=?',('discord',)).fetchone()
        if row is None:return {'required':False,'ready':False,'reason':'Discord is not configured.'}
        health=json.loads(row[0]);health['fresh']=0<=now-health['at']<=30
        health['available']=health['ready'] and health['fresh']
        return health

    def pending(self):
        with self.connection() as db:return [dict(r) for r in db.execute('SELECT * FROM alerts WHERE delivered IS NULL ORDER BY id LIMIT 20')]
    def outcome(self,alert_id,error=None):
        with self.connection() as db:
            db.execute('UPDATE alerts SET attempts=attempts+1,last_error=?,delivered=? WHERE id=?',(error,time.time() if error is None else None,alert_id))


def monitor(account_path,alerts_path,now=None):
    alerts=Alerts(alerts_path)
    if not Path(account_path).is_file():
        # No money is created, no account is silently reset.
        alerts.record('account_missing:'+str(Path(account_path).resolve()),'setup_needed','Paper account database is missing. Start the worker with the configured database path.',now)
        return {'configured':False}
    try:
        account=Account(account_path)
        if alerts.delivery_health(now).get('required') and not alerts.delivery_health(now).get('available'):
            account.trip('discord_disconnected',now)
        account.watch_safety(now)
        alerts.collect(account)
        return account.snapshot(now)
    except Exception as exc:
        try:
            if Path(account_path).is_file():Account(account_path).trip('monitor_unavailable',now)
        except Exception:pass
        alerts.record('account_unavailable:'+str(Path(account_path).resolve()),'account_unavailable','Paper account unavailable: '+type(exc).__name__+'. Inspect local storage; no reset was attempted.',now)
        raise


def authorized(user_id,guild_id,config):
    return str(user_id)==config['owner_id'] and str(guild_id)==config['guild_id']


def control(account_path,action,alerts_path=None):
    account=Account(account_path)
    if alerts_path is not None and action in ('acknowledge','resume'):
        health=Alerts(alerts_path).delivery_health()
        if health.get('required') and not health.get('available'):
            account.trip('discord_disconnected')
            raise ValueError('Discord is configured as required, but its delivery heartbeat is unavailable. Restore the Discord control service first.')
    if action=='kill':account.trip()
    elif action=='acknowledge':account.acknowledge_safety()
    elif action=='pause':account.control(True)
    elif action=='resume':
        account.watch_safety()
        account.control(False)
    else:raise ValueError('Unknown safety action.')
    return account.snapshot()
