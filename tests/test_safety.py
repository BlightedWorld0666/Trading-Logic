import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from scout.account import Account
from scout.core import Settings
from scout.safety import Alerts, authorized, control, monitor
from scout.access import Access
import app
import test_http
from test_account import snap, T

class SafetyTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'account.sqlite';self.out=Path(self.tmp.name)/'alerts.sqlite'
        self.a=Account.create(self.path,['BTC-USD'],Settings(stock_weight=0,crypto_weight=.9),'synthetic_live_demo','fixed:trend',60)
        self.a.claim('worker',300,now=T)
        for offset in (0,10,20,30,40,50,60):self.a.ingest(snap(T+offset),owner='worker',now=T+offset)
        self.s=self.a.snapshot(T+60)['state']
        self.a.queue({'actions':{'BTC-USD':'buy'},'reason':'queued before fault'},self.s['seq'],self.s['control_revision'],self.s['last_completed_bar'],owner='worker',now=T+60)
    def tearDown(self):self.tmp.cleanup()
    def test_error_latches_and_recovery_does_not_resume(self):
        self.a.error('ConnectionError','worker',now=T+65)
        self.a.ingest(snap(T+70),owner='worker',now=T+70)
        state=Account(self.path).snapshot(T+70)['state']
        self.assertTrue(state['safety']['latched']);self.assertTrue(state['paused']);self.assertEqual(state['pending'],[])
        self.assertEqual(self.a.snapshot(T+70)['fills'],[])
        with self.assertRaises(ValueError):self.a.control(False,now=T+71)
        self.a.acknowledge_safety(now=T+71)
        self.assertTrue(self.a.snapshot(T+71)['state']['paused'])
        self.a.control(False,now=T+72)
        self.assertFalse(self.a.snapshot(T+72)['state']['safety']['latched'])
    def test_unhealthy_ack_and_old_inference_rejected(self):
        self.a.trip(now=T+61)
        with self.assertRaises(ValueError):self.a.acknowledge_safety(now=T+400)
        self.assertFalse(self.a.queue({'actions':{'BTC-USD':'buy'},'reason':'late AI'},self.s['seq'],self.s['control_revision'],self.s['last_completed_bar'],owner='worker',now=T+62))
    def test_stale_feed_stops_before_fill_without_watchdog(self):
        self.a.ingest(snap(T+155),owner='worker',now=T+155)
        r=self.a.snapshot(T+155);self.assertTrue(r['state']['safety']['latched']);self.assertEqual(r['fills'],[])
    def test_independent_watchdog_dedup_and_retry_queue(self):
        monitor(self.path,self.out,now=T+155);monitor(self.path,self.out,now=T+156)
        alerts=Alerts(self.out);r=alerts.snapshot();self.assertEqual(r['pending'],1)
        event=r['alerts'][0];alerts.outcome(event['id'],'ConnectionError')
        self.assertEqual(Alerts(self.out).snapshot()['pending'],1)
        alerts.outcome(event['id']);self.assertEqual(alerts.snapshot()['pending'],0)
        self.assertEqual(alerts.snapshot()['alerts'][0]['attempts'],2)
    def test_worker_loss_and_required_discord_loss(self):
        self.a.release('worker');monitor(self.path,self.out,now=T+61)
        self.assertEqual(self.a.snapshot(T+61)['state']['safety']['reason'],'worker_offline')
        self.a.claim('worker',300,now=T+62);self.a.acknowledge_safety(now=T+62)
        Alerts(self.out).heartbeat(True,now=T+62)
        monitor(self.path,self.out,now=T+94)
        self.assertEqual(self.a.snapshot(T+94)['state']['safety']['reason'],'discord_disconnected')
    def test_ack_requires_required_discord_and_owner_guild(self):
        self.a.trip(now=T+61);Alerts(self.out).heartbeat(False)
        with self.assertRaises(ValueError):control(self.path,'acknowledge',self.out)
        config={'owner_id':'123','guild_id':'456'}
        self.assertTrue(authorized(123,456,config))
        for u,g in ((124,456),(123,457),(123,None)):
            self.assertFalse(authorized(u,g,config))
    def test_broken_alert_storage_fails_closed(self):
        import sqlite3
        with sqlite3.connect(self.out) as db:db.execute('CREATE TABLE valuable(payload TEXT)')
        with self.assertRaises(ValueError):monitor(self.path,self.out,now=T+61)
        self.assertTrue(self.a.snapshot(T+61)['state']['safety']['latched'])
    def test_missing_account_not_created(self):
        missing=Path(self.tmp.name)/'missing.sqlite'
        self.assertFalse(monitor(missing,self.out)['configured'])
        self.assertFalse(missing.exists());self.assertEqual(Alerts(self.out).snapshot()['pending'],1)

class SafetyHTTPTests(unittest.TestCase):
    setUpClass=classmethod(test_http.HTTPTests.setUpClass.__func__)
    tearDownClass=classmethod(test_http.HTTPTests.tearDownClass.__func__)
    req=test_http.HTTPTests.req;headers=test_http.HTTPTests.headers
    def test_authenticated_kill_resume_and_access_boundary(self):
        with tempfile.TemporaryDirectory() as temp:
            old=app.ALERTS_PATH;app.ALERTS_PATH=Path(temp)/'alerts.sqlite'
            try:
                self.assertEqual(self.req('/api/safety/control',{'action':'kill'},{'Content-Type':'application/json'})[0],403)
                status,data=self.req('/api/safety/control',{'action':'kill'},self.headers());self.assertEqual(status,200)
                self.assertTrue(json.loads(data)['account']['state']['safety']['latched'])
                self.assertEqual(self.req('/api/safety/control',{'action':'resume'},self.headers())[0],400)
                self.assertEqual(self.req('/api/safety/control',{'action':'acknowledge'},self.headers())[0],400)
                self.assertEqual(self.req('/api/safety')[0],200)
                # Enabling remote mode also requires signed assertions on localhost: no host-based bypass.
                fake=SimpleNamespace(host='trading.blighted.world',verify=lambda token:token=='verified-owner')
                with patch.object(app,'ACCESS',fake):
                    self.assertEqual(self.req('/api/report')[0],403)
                    self.assertEqual(self.req('/api/report',headers={'Host':'trading.blighted.world','Cf-Access-Jwt-Assertion':'fake'})[0],403)
                    self.assertEqual(self.req('/api/report',headers={'Host':'trading.blighted.world','Cf-Access-Jwt-Assertion':'verified-owner'})[0],200)
            finally:app.ALERTS_PATH=old

class AccessTests(unittest.TestCase):
    def test_validation_constraints_and_owner_check(self):
        calls=[]
        def decode(token,key,**kwargs):
            calls.append(kwargs)
            if token=='bad':raise ValueError('bad signature')
            return {'email':'JOSEPH@BLIGHTED.WORLD' if token=='owner' else 'other@example.com','type':'app'}
        fake=SimpleNamespace(PyJWKClient=lambda *a,**k:SimpleNamespace(get_signing_key_from_jwt=lambda token:SimpleNamespace(key='verified')),decode=decode)
        with patch.dict('sys.modules',{'jwt':fake}):
            access=Access('trading.blighted.world','team.cloudflareaccess.com','aud','Joseph@Blighted.World')
            self.assertTrue(access.verify('owner'));self.assertFalse(access.verify('other'));self.assertFalse(access.verify('bad'));self.assertFalse(access.verify(None))
            self.assertEqual(calls[0]['algorithms'],['RS256']);self.assertEqual(calls[0]['audience'],'aud')
            self.assertEqual(calls[0]['issuer'],'https://team.cloudflareaccess.com')
            self.assertIn('exp',calls[0]['options']['require'])
            with self.assertRaises(ValueError):Access('trading.blighted.world','evil.example.com','aud','Joseph@Blighted.World')


class OptionalIntegrationTests(unittest.TestCase):
    def test_real_signed_access_tokens(self):
        try:
            import jwt
            from cryptography.hazmat.primitives.asymmetric import rsa
        except ImportError:self.skipTest('Install requirements-control.txt for actual JWT tests.')
        import time
        key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
        access=Access('trading.blighted.world','team.cloudflareaccess.com','aud','Joseph@Blighted.World')
        access.keys=SimpleNamespace(get_signing_key_from_jwt=lambda token:SimpleNamespace(key=key.public_key()))
        current=int(time.time())
        claims={'iss':'https://team.cloudflareaccess.com','aud':['aud'],'sub':'owner','email':'Joseph@Blighted.World','type':'app','iat':current,'exp':current+60}
        sign=lambda data:jwt.encode(data,key,algorithm='RS256')
        self.assertTrue(access.verify(sign(claims)))
        for changed in ({'aud':['wrong']},{'iss':'https://evil.example.com'},{'exp':current-1},{'email':'other@example.com'},{'type':'service'}):
            self.assertFalse(access.verify(sign({**claims,**changed})))
        different=rsa.generate_private_key(public_exponent=65537,key_size=2048)
        self.assertFalse(access.verify(jwt.encode(claims,different,algorithm='RS256')))
        self.assertFalse(access.verify(jwt.encode(claims,'invalid key that is longer than thirty two characters',algorithm='HS256')))

class DiscordBoundaryTests(unittest.IsolatedAsyncioTestCase):
    async def test_actual_command_tree_owner_check_without_network(self):
        try:import discord
        except ImportError:self.skipTest('Install requirements-control.txt for Discord API registration tests.')
        from unittest.mock import AsyncMock
        from discord_control import build_client
        client=build_client({'owner_id':'123','guild_id':'456','alerts_channel_id':'789'},Path('unused-account'),Path('unused-alerts'),Path('unused-board'))
        self.assertEqual({c.name for c in client.tree.get_commands()},{'trading_status','trading_control','agent_board','agent_note','server_status','server_control','paper_recap','backup_now'})
        def interaction(user,guild):return SimpleNamespace(user=SimpleNamespace(id=user),guild_id=guild,response=SimpleNamespace(send_message=AsyncMock()))
        denied=interaction(124,456);self.assertFalse(await client.tree.interaction_check(denied));denied.response.send_message.assert_awaited_once()
        self.assertFalse(await client.tree.interaction_check(interaction(123,457)))
        self.assertFalse(await client.tree.interaction_check(interaction(123,None)))
        self.assertTrue(await client.tree.interaction_check(interaction(123,456)))
        await client.close()

if __name__=='__main__':unittest.main()
