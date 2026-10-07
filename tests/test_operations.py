from pathlib import Path
import tempfile
import json
import time
import unittest
from unittest.mock import patch
from scout.operations import DEFAULTS, validate_deployment, journal, scoreboard, readiness, recap
from scout.backups import backup, verify, stage_restore
from scout.account import Account
from scout.core import Settings
from scout.data import demo_bars
from scout.research import analyze
from scout.safety import Alerts
from server_manager import Manager, manager_lock, owned_identity
import app
import test_http

class OperationsTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        (self.root/'forward.example.json').write_text(json.dumps({'stock_weight':0,'crypto_weight':.9}))
        self.config=validate_deployment(self.root,{})
        self.account=Account.create(self.root/self.config['account_db'],['BTC-USD','ETH-USD'],Settings(stock_weight=0,crypto_weight=.9),'synthetic_live_demo','fixed:trend')
    def tearDown(self):self.tmp.cleanup()
    def test_reject_unsafe_deployment_and_commands(self):
        for raw in ({'account_db':'../outside.sqlite'},{'settings':'secrets/discord.json'},{'auto_start':['arbitrary']},{'model':'x;evil'},{'account_db':'runtime/alerts.sqlite'}):
            with self.assertRaises(ValueError):validate_deployment(self.root,raw)
        m=Manager(self.root,self.config)
        with self.assertRaises(ValueError):m.action('run','shell')
        command=m.command('worker');self.assertNotIn('shell',command);self.assertIn('--owner-token',command)
    def test_backup_integrity_stage_and_active_account_preserved(self):
        manifest=backup(self.root,self.config);source,_=verify(self.root,manifest['id'])
        restored=stage_restore(self.root,manifest['id'])
        self.assertFalse(restored['active_files_replaced'])
        self.assertFalse(self.account.snapshot()['state']['safety']['latched'])
        self.assertTrue(Account(self.root/restored['staged_path']/'account.sqlite').snapshot()['state']['safety']['latched'])
        with (source/'settings.json').open('a') as file:file.write('tampered')
        with self.assertRaises(ValueError):verify(self.root,manifest['id'])
        with self.assertRaises(ValueError):stage_restore(self.root,'../../secrets')
    def test_journal_pagination_and_scoreboard_same_report(self):
        self.account.trip();first=journal(self.account.path,0,1);second=journal(self.account.path,first['next_cursor'],1)
        self.assertGreater(second['events'][0]['id'],first['events'][0]['id'])
        report=app.stamp(analyze(demo_bars()));result=scoreboard(report)
        self.assertEqual(result['report_id'],report['report_id']);self.assertEqual(result['rows'][0]['final_equity'],report['settings']['capital'])
        self.assertEqual(result['rows'][1]['net_return_pct'],report['comparison']['combined']['net_return_pct'])
    def test_readiness_does_not_turn_profit_into_live_permission(self):
        r=readiness(self.root,self.config,{'configuration_ready':True})
        self.assertFalse(r['funded_trading_ready']);self.assertFalse(r['paper_observation_ready'])
        self.assertIn('lifetime net',recap(self.account.path,self.root/self.config['alerts_db']))
    def test_single_manager_lock(self):
        with manager_lock(self.root):
            with self.assertRaises(ValueError):
                with manager_lock(self.root):pass

class FakeProcess:
    def __init__(self):self.returncode=None
    def poll(self):return self.returncode
    def terminate(self):self.returncode=0
    def wait(self,timeout=None):return self.returncode
    def kill(self):self.returncode=-1

class SupervisorTests(unittest.TestCase):
    def test_restart_bounds_and_recap_dedup_across_manager_restart(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'forward.example.json').write_text(json.dumps({'stock_weight':0,'crypto_weight':.9}))
            config=validate_deployment(root,{'auto_start':['worker'],'backup_daily':False});created=[]
            def spawn(command,**kwargs):
                self.assertFalse(kwargs['shell']);p=FakeProcess();created.append(p);return p
            m=Manager(root,config,spawn)
            m.tick(100);created[-1].returncode=1;m.tick(101);m.tick(121)
            created[-1].returncode=1;m.tick(122);m.tick(162)
            created[-1].returncode=1;m.tick(163);m.tick(999)
            self.assertIn('worker',m.auto_disabled);self.assertEqual(len(created),3)
            m.action('start','worker');m.tick(1000);self.assertEqual(len(created),4);m.close()
            account=Account.create(root/config['account_db'],['BTC-USD','ETH-USD'],Settings(stock_weight=0,crypto_weight=.9),'synthetic_live_demo','fixed:trend')
            config['auto_start']=[];now=time.time()
            first=Manager(root,config,spawn);first.tick(now);first.tick(now+1)
            second=Manager(root,config,spawn);second.tick(now+2)
            recaps=[a for a in Alerts(root/config['alerts_db']).snapshot()['alerts'] if a['kind']=='daily_recap']
            self.assertEqual(len(recaps),1);self.assertTrue(account.snapshot()['state']['safety']['latched'])
    def test_manual_start_stop_never_resumes(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'forward.example.json').write_text('{}');config=validate_deployment(root,{})
            account=Account.create(root/config['account_db'],['BTC-USD'],Settings(),'synthetic_live_demo','fixed:trend')
            m=Manager(root,config,lambda *a,**k:FakeProcess());m.action('start','worker')
            self.assertTrue(account.snapshot()['state']['paused']);m.action('stop','worker')
            self.assertTrue(account.snapshot()['state']['safety']['latched'])

class RegistryBoundaryTests(unittest.TestCase):
    def test_identity_mismatch_never_terminates_a_process(self):
        from types import SimpleNamespace
        calls=[]
        class Gone(Exception):pass
        process=SimpleNamespace(create_time=lambda:100,cmdline=lambda:['python','owned'],children=lambda recursive:[],terminate=lambda:calls.append('terminate'),wait=lambda timeout:None)
        fake=SimpleNamespace(Process=lambda pid:process,NoSuchProcess=Gone,TimeoutExpired=TimeoutError,STATUS_ZOMBIE='zombie',wait_procs=lambda children,timeout:([],[]))
        with tempfile.TemporaryDirectory() as temp,patch.dict('sys.modules',{'psutil':fake}):
            root=Path(temp);(root/'runtime').mkdir();config=validate_deployment(root,{'auto_start':[],'backup_daily':False})
            for timestamp,command,expected in [(101,['python','owned'],0),(100,['python','different'],0),(100,['python','owned'],1)]:
                (root/'runtime/manager-state.json').write_text(json.dumps({'owned':{'worker':{'pid':10,'created':timestamp,'command':command}}}))
                Manager(root,config)
                self.assertEqual(len(calls),expected)
            child=SimpleNamespace(pid=10,poll=lambda:None)
            self.assertIsNone(owned_identity(child,['python','different']))
            self.assertEqual(owned_identity(child,['python','owned'])['created'],100)

class OwnedRecoveryTests(unittest.TestCase):
    def test_recorded_child_recovered_and_reused_identity_skipped(self):
        import subprocess,sys
        try:import psutil
        except ImportError:self.skipTest('Install requirements-control.txt for process recovery tests.')
        try:inspectable=Path(psutil.Process().exe()).resolve()==Path(sys.executable).resolve()
        except psutil.Error:inspectable=False
        if not inspectable:self.skipTest('This sandbox exposes a different /proc namespace; real process recovery needs the host drill.')
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'forward.example.json').write_text('{}');(root/'runtime').mkdir();config=validate_deployment(root,{'auto_start':[],'backup_daily':False})
            child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'])
            try:
                record={**owned_identity(child),'owner':None}
                actual_time=record['created'];record['created']=actual_time+1
                (root/'runtime/manager-state.json').write_text(json.dumps({'owned':{'worker':record}}))
                Manager(root,config);self.assertIsNone(child.poll())
                record['created']=actual_time
                (root/'runtime/manager-state.json').write_text(json.dumps({'owned':{'worker':record}}))
                Manager(root,config);child.wait(timeout=5)
                self.assertIsNotNone(child.returncode)
            finally:
                if child.poll() is None:child.terminate();child.wait(timeout=5)

class OperationsHTTPTests(unittest.TestCase):
    setUpClass=classmethod(test_http.HTTPTests.setUpClass.__func__)
    tearDownClass=classmethod(test_http.HTTPTests.tearDownClass.__func__)
    req=test_http.HTTPTests.req;headers=test_http.HTTPTests.headers
    def test_journal_scoreboard_and_setup_save_auth(self):
        self.assertEqual(self.req('/api/journal?after=-1')[0],400)
        self.assertEqual(self.req('/api/journal?after=0')[0],200)
        self.assertEqual(self.req('/api/scoreboard')[0],200)
        self.assertEqual(self.req('/api/setup/save',{'deployment':{}},{'Content-Type':'application/json'})[0],403)
        with tempfile.TemporaryDirectory() as temp,patch.object(app,'ROOT',Path(temp)):
            self.assertEqual(self.req('/api/setup/save',{'deployment':{'auto_start':['shell']}},self.headers())[0],400)
            self.assertEqual(self.req('/api/setup/save',{'deployment':{}},self.headers())[0],200)
            self.assertTrue((Path(temp)/'deployment.json').is_file())

if __name__=='__main__':unittest.main()
