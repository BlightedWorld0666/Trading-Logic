"""Setup diagnostics, bounded journal and honest research comparisons."""
from contextlib import closing
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import platform
import re
import shutil
import sys
import time
from urllib.request import Request, build_opener
from .account import Account
from .ai import NoRedirect
from .core import Settings
from .safety import Alerts

DEFAULTS={'account_db':'runtime/demo.sqlite','alerts_db':'runtime/alerts.sqlite','board_db':'runtime/board.sqlite','settings':'forward.example.json','source':'demo','strategy':'trend','model':'qwen3.5:4b-q4_K_M','use_model':False,'symbols':['BTC-USD','ETH-USD'],'interval':60,'bar_seconds':300,'discord_enabled':False,'remote_enabled':False,'auto_start':['watchdog','worker','dashboard'],'recap_hour_utc':0,'backup_daily':True}
SERVICES=('ollama','watchdog','worker','discord','dashboard')

def inside(root,value):
    if not isinstance(value,str) or Path(value).is_absolute():raise ValueError('Configuration paths must be relative to the project.')
    path=(Path(root)/value).resolve()
    if not path.is_relative_to(Path(root).resolve()):raise ValueError('Configuration path leaves the project.')
    return path

def load_deployment(root,path=None):
    root=Path(root).resolve();path=path or root/'deployment.json'
    raw=json.loads(Path(path).read_text()) if Path(path).is_file() else {}
    return validate_deployment(root,raw)

def validate_deployment(root,raw):
    if not isinstance(raw,dict) or set(raw)-set(DEFAULTS):raise ValueError('Unknown deployment settings.')
    config={**DEFAULTS,**raw}
    for key in ('account_db','alerts_db','board_db','settings'):inside(root,config[key])
    if len({str(inside(root,config[k])) for k in ('account_db','alerts_db','board_db')})!=3:raise ValueError('Use distinct database paths.')
    for key in ('account_db','alerts_db','board_db'):
        path=Path(config[key])
        if not path.parts or path.parts[0]!='runtime' or path.suffix!='.sqlite':raise ValueError('Account/board/alerts databases must be runtime .sqlite files.')
    if not re.fullmatch(r'[A-Za-z0-9._-]+\.json',config['settings']):raise ValueError('Risk settings must be a JSON file directly in the project folder.')
    if inside(root,config['settings']).is_file():Settings(**json.loads(inside(root,config['settings']).read_text())).validate()
    for key in ('use_model','discord_enabled','remote_enabled','backup_daily'):
        if type(config[key]) is not bool:raise ValueError('Deployment switches must be booleans.')
    if config['source'] not in ('demo','robinhood') or config['strategy'] not in ('cash','trend','reversion','breakout'):raise ValueError('Invalid source or strategy.')
    if not isinstance(config['model'],str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:/-]{0,95}',config['model']) or 'cloud' in config['model'].lower():raise ValueError('Use a local model name.')
    symbols=config['symbols']
    if not isinstance(symbols,list) or not 1<=len(symbols)<=4 or len(set(symbols))!=len(symbols) or not all(isinstance(s,str) and re.fullmatch(r'[A-Z0-9]{1,16}-USD',s) for s in symbols):raise ValueError('Use 1–4 unique crypto USD symbols.')
    if type(config['interval']) not in (int,float) or not 1<=config['interval']<=300 or (config['source']=='robinhood' and config['interval']<30):raise ValueError('Invalid poll interval.')
    if type(config['bar_seconds']) is not int or not 60<=config['bar_seconds']<=3600 or config['interval']>config['bar_seconds']/4:raise ValueError('Invalid candle/poll timing.')
    if type(config['recap_hour_utc']) is not int or not 0<=config['recap_hour_utc']<=23:raise ValueError('Recap hour must be 0–23 UTC.')
    if not isinstance(config['auto_start'],list) or len(config['auto_start'])!=len(set(config['auto_start'])) or set(config['auto_start'])-set(SERVICES):raise ValueError('Unknown startup service.')
    return config

def setup(root,config):
    root=Path(root);checks=[]
    def add(name,ready,detail,required=True):checks.append({'name':name,'ready':bool(ready),'detail':detail,'required':required})
    add('Manager dependency',importlib.util.find_spec('psutil') is not None,'Install requirements-control.txt for process identity and crash recovery.')
    try:
        import psutil
        inspectable=Path(psutil.Process().exe()).resolve()==Path(sys.executable).resolve()
    except Exception:inspectable=False
    add('Process identity inspection',inspectable,'Host process identity must be inspectable for forced manager-crash cleanup.')
    add('Python',sys.version_info>=(3,10),'Python '+platform.python_version())
    try:Settings(**json.loads(inside(root,config['settings']).read_text())).validate();add('Risk configuration',True,'Settings parsed and validated.')
    except Exception as exc:add('Risk configuration',False,'Inspect settings: '+type(exc).__name__)
    try:
        with build_opener(NoRedirect()).open(Request('http://127.0.0.1:11434/api/tags'),timeout=2) as response:
            data=json.loads(response.read(2000001))
        match=next((m for m in data.get('models',[]) if m.get('name')==config['model'] or m.get('model')==config['model']),None)
        local=match and match.get('size',0)>0 and not match.get('remote_host') and not match.get('remote_model')
        add('Ollama connection',True,'Local endpoint responded.',config['use_model'])
        add('Selected local model',local,config['model']+' must be downloaded locally. Actual inference still needs a host test.',config['use_model'])
    except Exception:add('Ollama connection',False,'Start Ollama and download the selected model.',config['use_model'])
    if config['source']=='robinhood':
        try:
            raw=json.loads((root/'secrets/robinhood.json').read_text());ready=bool(raw.get('api_key') and raw.get('private_key_base64'))
        except Exception:ready=False
        add('Quote credentials',ready,'Local credential file check only; request permissions are not verified.')
    add('Discord dependency',importlib.util.find_spec('discord') is not None,'Install requirements-control.txt.',config['discord_enabled'])
    if config['discord_enabled']:
        try:
            from discord_control import load_config
            load_config(root/'secrets/discord.json');ready=True
        except Exception:ready=False
        add('Discord configuration',ready,'Owner/server/channel IDs and token must be entered locally.')
    if config['remote_enabled']:
        try:
            from .access import Access
            Access(**json.loads((root/'secrets/access.json').read_text()));ready=True
        except Exception:ready=False
        add('Private remote access',ready,'Signed Access config and dependency check; real login still needs testing.')
    add('Account database',inside(root,config['account_db']).is_file(),'Worker creates it; existing account options must match.',False)
    return {'checks':checks,'configuration_ready':all(c['ready'] for c in checks if c['required']),'source':config['source'],'model':config['model']}

def journal(path,after=0,limit=200):
    if type(after) is not int or after<0:raise ValueError('Invalid journal cursor.')
    account=Account(path)
    with closing(account.connection()) as conn:
        rows=conn.execute('SELECT id,at,kind,payload FROM events WHERE id>? ORDER BY id LIMIT ?',(after,min(500,limit))).fetchall()
    events=[{'id':r[0],'at':r[1],'kind':r[2],**json.loads(r[3])} for r in rows]
    return {'events':events,'next_cursor':events[-1]['id'] if events else after,'note':'Chronological saved events, not model private reasoning. Hold proposals and discarded decisions explain skipped execution; fills retain decision IDs.'}

def scoreboard(report):
    def metric(result):return {k:result[k] for k in ('net_return_pct','max_drawdown_pct','fill_count','final_equity')}
    rows=[]
    # Cash is an explicit no-trade baseline on the same starting capital.
    rows.append({'name':'Cash','net_return_pct':0,'max_drawdown_pct':0,'fill_count':0,'final_equity':report['settings']['capital']})
    for name,result in report['comparison'].items():rows.append({'name':name,**metric(result)})
    candidates=[{'symbol':r['symbol'],'strategy':r['strategy'],'selected':r['selected'],**metric(r['holdout_diagnostic'])} for r in report['candidates']]
    return {'report_id':report['report_id'],'source':report['source'],'rows':rows,'candidates':candidates,'note':'Same historical study and costs. Unselected candidates are holdout diagnostics, not new untouched tests. Crypto/stock forward strategies are not synchronized comparisons. Win rate is omitted: fills are not completed trades.'}

def recap(account_path,alerts_path,now=None):
    now=time.time() if now is None else now;r=Account(account_path).snapshot(now);s=r['state']
    with closing(Account(account_path).connection()) as conn:
        counts=dict(conn.execute('SELECT kind,COUNT(*) FROM events WHERE at>=? AND at<=? GROUP BY kind',(now-86400,now)).fetchall())
    return f"Paper recap / {s['config']['source']}: lifetime net ${r['net_profit']:.2f}; equity ${s['equity']:.2f}; cumulative fees ${s['fees']:.2f}, extra slippage ${s['slippage']:.2f}; max drawdown {s['max_drawdown']*100:.2f}%; last 24h fills {counts.get('fill',0)}, proposals {counts.get('decision',0)}, discarded {counts.get('decision_discarded',0)}; paused {s['paused']}, safety latched {s['safety']['latched']}, risk halted {s['halted']}; worker active {r['worker_active']}, quote receipts fresh {r['receipt_fresh']}; queued alerts {Alerts(alerts_path).snapshot()['pending']}. Costs illustrative; no real orders."

def readiness(root,config,checks=None):
    checks=checks or setup(root,config)
    try:
        r=Account(inside(root,config['account_db'])).snapshot();s=r['state']
        operational=r['worker_active'] and r['receipt_fresh'] and s['health']=='observing'
        account={'worker_active':r['worker_active'],'receipt_fresh':r['receipt_fresh'],'safety_latched':s['safety']['latched'],'paused':s['paused'],'risk_halted':s['halted']}
    except Exception:operational=False;account={'configured':False}
    return {'configuration_ready':checks['configuration_ready'],'paper_observation_ready':checks['configuration_ready'] and operational,'account':account,'funded_trading_ready':False,'missing_live_evidence':['Real order adapter and order/position reconciliation','Broker costs, minimum quantities and realistic fills','New unseen evaluation and forward performance evidence','Host disconnect/reboot/restore drills','External host heartbeat monitoring'],'note':'Readiness is not an authorization or profitability claim. Safety stops still require manual acknowledgement/resume.'}
