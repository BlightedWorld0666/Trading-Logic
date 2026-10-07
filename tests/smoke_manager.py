"""Optional real-process manager smoke in an isolated copy (POSIX test host)."""
from pathlib import Path
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from urllib.request import urlopen
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import server_manager
from scout.account import Account


def main():
    if os.name=='nt':raise SystemExit('Use the documented Windows host drill; this smoke uses POSIX signals.')
    with tempfile.TemporaryDirectory() as temp:
        project=Path(temp)/'project'
        shutil.copytree(Path(__file__).resolve().parents[1],project,ignore=shutil.ignore_patterns('runtime','models','secrets','__pycache__','.git','data','reports','deployment.json','deployment.json.tmp'))
        config=json.loads((project/'deployment.example.json').read_text());config.update(interval=1,bar_seconds=60,backup_daily=False)
        (project/'deployment.json').write_text(json.dumps(config))
        proc=subprocess.Popen([sys.executable,str(project/'server_manager.py')],cwd=project,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL);pids=[]
        try:
            for attempt in range(100):
                try:
                    status=server_manager.rpc(project)
                    if all(next(s for s in status['services'] if s['name']==n)['running'] for n in ('watchdog','worker','dashboard')) and (project/'runtime/demo.sqlite').is_file():
                        with urlopen('http://127.0.0.1:8002/api/report',timeout=2) as response:
                            if response.status==200:break
                except Exception:pass
                time.sleep(.2)
            else:raise RuntimeError('Managed services did not become ready.')
            pids=[s['pid'] for s in status['services'] if s['running']]
            for path in ('/api/operations','/api/scoreboard','/api/journal?after=0'):
                with urlopen('http://127.0.0.1:8002'+path,timeout=10) as response:assert response.status==200
            result=server_manager.rpc(project,'backup');staged=server_manager.rpc(project,'stage_restore',backup_id=result['id'])
            assert not staged['active_files_replaced']
            server_manager.rpc(project,'stop','worker')
            assert Account(project/'runtime/demo.sqlite').snapshot()['state']['safety']['latched']
            assert server_manager.rpc(project,'logs','worker')['service']=='worker'
            print('Real supervisor smoke passed: services, dashboard APIs, backup/staging, worker stop and retained latch.')
        finally:
            proc.send_signal(signal.SIGINT)
            try:proc.wait(timeout=25)
            except subprocess.TimeoutExpired:proc.kill();proc.wait();raise RuntimeError('Manager shutdown timed out.')
        for pid in pids:
            try:os.kill(pid,0)
            except ProcessLookupError:continue
            raise RuntimeError('Managed child survived shutdown.')
        print('All managed child processes cleaned up on manager shutdown.')

if __name__=='__main__':main()
