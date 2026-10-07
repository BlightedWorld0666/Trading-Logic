"""Independent fixed-service supervisor. Local token-protected RPC; no arbitrary commands."""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import re
import shutil
import subprocess
import sys
import threading
import time
from urllib.request import Request, build_opener
from urllib.error import HTTPError
from scout.ai import NoRedirect
from scout.account import Account
from scout.safety import Alerts
from scout.operations import SERVICES, inside, load_deployment, setup, recap
from scout.backups import backup, listing, stage_restore

ROOT=Path(__file__).resolve().parent
PORT=8004

@contextmanager
def manager_lock(root):
    path=Path(root)/'runtime/manager.lock';path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('a+b') as handle:
        handle.seek(0);handle.write(b'0');handle.flush();handle.seek(0)
        try:
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError:raise ValueError('Another manager is already running.')
        try:yield
        finally:
            handle.seek(0)
            if os.name=='nt':msvcrt.locking(handle.fileno(),msvcrt.LK_UNLCK,1)
            else:fcntl.flock(handle.fileno(),fcntl.LOCK_UN)


def manager_token(root,create=False):
    path=Path(root)/'secrets/manager.token'
    if not path.is_file() and create:
        path.parent.mkdir(parents=True,exist_ok=True)
        with path.open('x') as file:file.write(secrets.token_urlsafe(32))
        if os.name!='nt':path.chmod(0o600)
    token=path.read_text().strip()
    if not 32<=len(token)<=100:raise ValueError('Invalid manager token.')
    return token


def rpc(root,action=None,service=None,backup_id=None):
    body=None if action is None else json.dumps({'action':action,'service':service,'backup_id':backup_id}).encode()
    request=Request('http://127.0.0.1:8004/api/manager',body,{'Authorization':'Bearer '+manager_token(root),'Content-Type':'application/json'},method='GET' if body is None else 'POST')
    try:
        with build_opener(NoRedirect()).open(request,timeout=20) as response:return json.loads(response.read(2000001))
    except HTTPError as exc:
        try:message=json.loads(exc.read(2000)).get('error','Manager rejected the action.')
        except Exception:message='Manager rejected the action.'
        raise ValueError(str(message)[:300]) from None

def owned_identity(process,command=None):
    import psutil
    for attempt in range(20):
        try:
            identity=psutil.Process(process.pid)
            actual=identity.cmdline()
            if command is not None and actual!=command:return None
            return {'pid':process.pid,'created':identity.create_time(),'command':actual}
        except psutil.NoSuchProcess:
            if process.poll() is not None:return None
            time.sleep(.02)
    return None  # Keep controlling the actual Popen handle; do not persist an unverified PID.

class Manager:
    def __init__(self,root,config,spawn=subprocess.Popen):
        self.root=Path(root);self.config=config;self.spawn=spawn;self.lock=threading.RLock();self.processes={};self.log_handles={};self.owner_tokens={};self.account_seen=False;self.desired=set(config['auto_start']);self.restart_times={};self.next_start={};self.errors={};self.auto_disabled=set();self.started=time.time()
        self.ledger=self.root/'runtime/manager-state.json'
        self.state=json.loads(self.ledger.read_text()) if self.ledger.is_file() else {'last_recap':None,'last_backup':None}
        self.latch()
        self.recover_owned()
    def recover_owned(self):
        records=self.state.get('owned',{})
        if not records:return
        import psutil
        for service,record in records.items():
            if service not in SERVICES:raise ValueError('Invalid owned service record.')
            try:
                process=psutil.Process(record['pid'])
                if process.create_time()!=record['created'] or process.cmdline()!=record['command']:continue
                # These exact process identities were recorded at spawn, not supplied by an RPC caller.
                descendants=process.children(recursive=True)
                process.terminate()
                try:process.wait(timeout=8)
                except psutil.TimeoutExpired:
                    if process.status()!=psutil.STATUS_ZOMBIE:process.kill();process.wait(timeout=3)
                for child in descendants:
                    try:child.terminate()
                    except psutil.NoSuchProcess:pass
                _,alive=psutil.wait_procs(descendants,timeout=3)
                for child in alive:child.kill()
                if service=='worker' and record.get('owner'):
                    path=inside(self.root,self.config['account_db'])
                    if path.is_file():Account(path).release(record['owner'])
            except psutil.NoSuchProcess:continue
        self.state['owned']={};self.save()

    def save(self):
        self.ledger.parent.mkdir(parents=True,exist_ok=True);temporary=self.ledger.with_suffix('.tmp');temporary.write_text(json.dumps(self.state));temporary.replace(self.ledger)
    def command(self,service):
        c=self.config;py=sys.executable;root=self.root
        db=str(inside(root,c['account_db']));alerts=str(inside(root,c['alerts_db']));board=str(inside(root,c['board_db']))
        if service=='ollama':
            executable=shutil.which('ollama')
            if not executable:raise ValueError('Install Ollama first.')
            return [executable,'serve']
        if service=='watchdog':return [py,str(root/'safety_watch.py'),'--db',db,'--alerts-db',alerts]
        if service=='worker':return [py,str(root/'forward.py'),'--db',db,'--alerts-db',alerts,'--config',str(inside(root,c['settings'])),'--source',c['source'],'--symbols',*c['symbols'],'--interval',str(c['interval']),'--bar-seconds',str(c['bar_seconds']),'--owner-token',self.owner_tokens.setdefault('worker',secrets.token_hex(16)),*(['--model',c['model']] if c['use_model'] else ['--strategy',c['strategy']])]
        if service=='discord':
            if not c['discord_enabled']:raise ValueError('Enable Discord in deployment.json after configuring secrets/discord.json.')
            return [py,str(root/'discord_control.py'),'--db',db,'--alerts-db',alerts,'--board-db',board]
        if service=='dashboard':return [py,str(root/'app.py'),'--paper-db',db,'--alerts-db',alerts,'--board-db',board,*(['--access-config',str(root/'secrets/access.json')] if c['remote_enabled'] else [])]
        raise ValueError('Unknown service.')
    def stop_process(self,service):
        process=self.processes.pop(service,None)
        descendants=[]
        if process and getattr(process,'pid',None) and process.poll() is None:
            import psutil
            try:
                record=self.state.get('owned',{}).get(service)
                identity=psutil.Process(process.pid)
                if record and identity.create_time()==record['created'] and identity.cmdline()==record['command']:descendants=identity.children(recursive=True)
            except psutil.NoSuchProcess:pass
        if process and process.poll() is None:
            process.terminate()
            try:process.wait(timeout=8)
            except subprocess.TimeoutExpired:process.kill();process.wait(timeout=3)
        if descendants:
            import psutil
            for child in descendants:
                try:child.terminate()
                except psutil.NoSuchProcess:pass
            _,alive=psutil.wait_procs(descendants,timeout=3)
            for child in alive:child.kill()
        self.state.setdefault('owned',{}).pop(service,None);self.save()
        if service=='worker':
            owner=self.owner_tokens.pop(service,None)
            account=inside(self.root,self.config['account_db'])
            if owner and account.is_file():Account(account).release(owner)
        handle=self.log_handles.pop(service,None)
        if handle:handle.close()
    def latch(self):
        path=inside(self.root,self.config['account_db'])
        if path.is_file():Account(path).trip()
    def action(self,action,service=None,backup_id=None):
        with self.lock:
            if action=='logs':
                if service not in SERVICES:raise ValueError('Unknown service.')
                path=self.root/'runtime/logs'/f'{service}.log'
                text='No manager-owned log yet.'
                if path.is_file():
                    with path.open('rb') as file:
                        file.seek(max(0,path.stat().st_size-12000));text=file.read(12000).decode('utf-8',errors='replace')
                return {'service':service,'text':text}
            if action=='backup':return backup(self.root,self.config)
            if action=='stage_restore':return stage_restore(self.root,backup_id)
            if service not in SERVICES or action not in ('start','stop','restart'):raise ValueError('Choose a fixed service and start, stop or restart.')
            if action=='start' and service in self.processes and self.processes[service].poll() is None:return self.status()
            if action in ('stop','restart') or service=='worker':self.latch()
            if action in ('stop','restart'):self.stop_process(service)
            if action=='stop':self.desired.discard(service)
            else:
                self.command(service)  # Validate before scheduling; never execute supplied shell text.
                self.desired.add(service);self.auto_disabled.discard(service);self.restart_times[service]=[];self.next_start[service]=0
            return self.status()
    def status(self):
        return {'uptime_seconds':time.time()-self.started,'services':[{'name':s,'running':s in self.processes and self.processes[s].poll() is None,'pid':getattr(self.processes.get(s),'pid',None),'desired':s in self.desired,'restart_count':len(self.restart_times.get(s,[])),'automatic_restart_blocked':s in self.auto_disabled,'last_error':self.errors.get(s)} for s in SERVICES],'last_recap':self.state.get('last_recap'),'last_backup':self.state.get('last_backup'),'backups':listing(self.root),'note':'Only manager-owned processes are controlled. Restart never resumes paper trading. Configuration changes require manager restart.'}
    def tick(self,now=None):
        now=time.time() if now is None else now
        with self.lock:
            for service in SERVICES:
                if service in self.processes and self.processes[service].poll() is not None:
                    self.stop_process(service);self.latch()
                    self.errors[service]='Process exited; paper account stopped.'
                    times=[t for t in self.restart_times.get(service,[]) if now-t<600];times.append(now);self.restart_times[service]=times
                    if len(times)>=3:self.auto_disabled.add(service)
                    self.next_start[service]=now+min(60,5*2**len(times))
                    Alerts(inside(self.root,self.config['alerts_db'])).record('service_exit:'+service+':'+str(now),'service_fault',service+' exited. Automatic restarts are bounded; review the manager.')
                if service not in self.desired or service in self.processes or service in self.auto_disabled or now<self.next_start.get(service,0):continue
                try:
                    if service=='worker':
                        account_path=inside(self.root,self.config['account_db'])
                        if account_path.is_file() and Account(account_path).snapshot()['worker_active']:
                            self.errors[service]='An existing worker lease is active; waiting rather than starting a duplicate.';continue
                    command=self.command(service)
                    if service=='ollama':
                        try:
                            with build_opener(NoRedirect()).open('http://127.0.0.1:11434/api/tags',timeout=1):pass
                            self.errors[service]='An external Ollama server is already running; this manager will not stop it.';self.auto_disabled.add(service);continue
                        except Exception:pass
                    path=self.root/'runtime/logs'/f'{service}.log';path.parent.mkdir(parents=True,exist_ok=True)
                    if path.is_file() and path.stat().st_size>2000000:path.replace(path.with_suffix('.previous.log'))
                    handle=path.open('ab');self.log_handles[service]=handle
                    env={**os.environ,'PYTHONUNBUFFERED':'1','OLLAMA_NO_CLOUD':'1'}
                    if self.spawn is subprocess.Popen:
                        import psutil  # Fail before spawning if the process identity dependency is missing.
                    self.processes[service]=self.spawn(command,cwd=self.root,stdout=handle,stderr=handle,env=env,shell=False)
                    process=self.processes[service]
                    if getattr(process,'pid',None):
                        import psutil
                        record=owned_identity(process,command)
                        if record is not None:
                            self.state.setdefault('owned',{})[service]={**record,'owner':self.owner_tokens.get(service)};self.save()
                        else:self.errors[service]='Process identity registry unavailable; forced manager-crash recovery needs a host drill.'
                    if not getattr(process,'pid',None) or self.state.get('owned',{}).get(service):self.errors.pop(service,None)
                except Exception as exc:
                    if service in self.processes:self.stop_process(service)
                    handle=self.log_handles.pop(service,None)
                    if handle:handle.close()
                    self.errors[service]=type(exc).__name__+'; inspect setup checks.';self.auto_disabled.add(service)
            dt=datetime.fromtimestamp(now,timezone.utc);day=dt.date().isoformat()
            account=inside(self.root,self.config['account_db']);alerts=inside(self.root,self.config['alerts_db'])
            if account.is_file() and not self.account_seen:
                self.latch();self.account_seen=True
            if account.is_file() and dt.hour>=self.config['recap_hour_utc'] and self.state.get('last_recap')!=day:
                Alerts(alerts).record('daily_recap:'+day,'daily_recap',recap(account,alerts,now),now);self.state['last_recap']=day;self.save()
            if self.config['backup_daily'] and account.is_file() and self.state.get('last_backup')!=day:
                backup(self.root,self.config);self.state['last_backup']=day;self.save()
    def close(self):
        with self.lock:
            self.latch()
            for s in reversed(SERVICES):self.stop_process(s)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--config',type=Path,default=ROOT/'deployment.json');args=p.parse_args()
    try:
        config=load_deployment(ROOT,args.config)
        with manager_lock(ROOT):
            manager=Manager(ROOT,config);token=manager_token(ROOT,True);manager.latch()
            class Handler(BaseHTTPRequestHandler):
                def log_message(self,*args):pass
                def serve(self,post=False):
                    if self.headers.get('Host') not in ('127.0.0.1:8004','localhost:8004') or not secrets.compare_digest(self.headers.get('Authorization',''),'Bearer '+token) or self.path!='/api/manager':self.respond(403,{'error':'Manager access denied.'});return
                    try:
                        if post:
                            length=int(self.headers.get('Content-Length','0'))
                            if not 0<length<=2000 or self.headers.get('Content-Type')!='application/json':raise ValueError('Invalid request.')
                            body=json.loads(self.rfile.read(length));result=manager.action(body.get('action'),body.get('service'),body.get('backup_id'))
                        else:
                            with manager.lock:result=manager.status()
                        self.respond(200,result)
                    except Exception as exc:self.respond(400,{'error':str(exc)[:300] if isinstance(exc,ValueError) else type(exc).__name__})
                def respond(self,status,payload):
                    data=json.dumps(payload).encode();self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(data)));self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(data)
                def do_GET(self):self.serve()
                def do_POST(self):self.serve(True)
            server=ThreadingHTTPServer(('127.0.0.1',PORT),Handler);stop=threading.Event()
            def supervise():
                while not stop.is_set():
                    try:manager.tick()
                    except Exception as exc:
                        try:manager.latch()
                        except Exception:pass
                        print('Manager check failed:',type(exc).__name__,flush=True)
                    stop.wait(3)
            thread=threading.Thread(target=supervise,daemon=True);thread.start()
            print('Manager running independently on loopback port 8004. Use the dashboard or owner-only Discord controls.',flush=True)
            try:server.serve_forever()
            except KeyboardInterrupt:pass
            finally:stop.set();thread.join(timeout=15);manager.close();server.server_close()
    except Exception as exc:p.exit(1,'Manager stopped: '+type(exc).__name__+'. Inspect deployment configuration and local logs.\n')

if __name__=='__main__':main()
