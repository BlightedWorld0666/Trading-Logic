from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from scout.account import Account
from scout.core import Settings

T=1800000000.0

def snap(t=T,bid=99,ask=101,source='synthetic_live_demo'):
    return {'source':source,'received_at_unix':t,'elapsed_seconds':0,
            'quotes':[{'symbol':'BTC-USD','bid':bid,'ask':ask}]}

class AccountTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'paper.sqlite'
        self.settings=Settings(stock_weight=0,crypto_weight=.9,max_position=.25)
        self.a=Account.create(self.path,['BTC-USD'],self.settings,'synthetic_live_demo','fixed:trend',60)
    def tearDown(self):self.tmp.cleanup()
    def ingest(self,t=T,bid=99,ask=101):return self.a.ingest(snap(t,bid,ask),now=t)
    def ready(self):
        for offset in (0,10,20,30,40,50,60):self.ingest(T+offset)
        return self.a.snapshot(T+60)['state']
    def queue_buy(self):
        state=self.ready()
        self.assertTrue(self.a.queue({'actions':{'BTC-USD':'buy'},'reason':'test'},state['seq'],state['control_revision'],state['last_completed_bar'],now=T+60))
    def test_next_observation_and_restart_recovery(self):
        self.queue_buy();state=self.a.snapshot(T+60)['state'];self.assertEqual(state['positions']['BTC-USD'],0)
        self.a=Account(self.path);self.ingest(T+70)
        r=self.a.snapshot(T+70);self.assertGreater(r['state']['positions']['BTC-USD'],0)
        self.assertEqual(len(r['fills']),1);self.assertEqual(r['fills'][0]['seq'],8)
        self.assertLess(r['net_profit'],0)
        self.assertEqual(Account(self.path).snapshot(T+70)['state'],r['state'])
    def test_duplicate_observation_cannot_fill_twice(self):
        self.queue_buy();self.ingest(T+70);self.assertFalse(self.ingest(T+70)['accepted'])
        self.assertEqual(len(self.a.snapshot(T+70)['fills']),1)
    def test_stale_and_incomplete_rejected_atomically(self):
        self.queue_buy();before=self.a.snapshot(T+60)['state']
        for snapshot,now in [(snap(T+70),T+300),(snap(T+70),T-100),({**snap(T+70),'elapsed_seconds':100},T+70),({**snap(T+70),'quotes':[]},T+70),({**snap(T+70),'source':'robinhood_crypto_v2'},T+70)]:
            with self.subTest(snapshot=snapshot),self.assertRaises(ValueError):self.a.ingest(snapshot,now=now)
            self.assertEqual(self.a.snapshot(T+60)['state'],before)
    def test_pause_cancels_pending_and_retains_positions(self):
        self.queue_buy();self.a.control(True,now=T+65);self.ingest(T+70)
        self.assertEqual(self.a.snapshot(T+70)['fills'],[])
        self.a.control(False,now=T+75);self.ingest(T+80)
        self.assertEqual(self.a.snapshot(T+80)['fills'],[])
    def test_pause_resume_during_inference_discards_old_plan(self):
        state=self.ready();self.a.control(True,now=T+61);self.a.control(False,now=T+62)
        self.assertFalse(self.a.queue({'actions':{'BTC-USD':'buy'},'reason':'old'},state['seq'],state['control_revision'],state['last_completed_bar'],now=T+63))
    def test_gap_cancels_old_pending(self):
        self.queue_buy();self.ingest(T+400)
        r=self.a.snapshot(T+400);self.assertEqual(r['fills'],[]);self.assertTrue(any(e['kind']=='observation_gap' for e in r['events']))
    def test_risk_halt_delays_exit_and_is_sticky(self):
        self.queue_buy();self.ingest(T+70);self.ingest(T+80,bid=40,ask=41)
        r=self.a.snapshot(T+80);self.assertTrue(r['state']['halted']);self.assertEqual(len(r['fills']),1)
        self.a=Account(self.path);self.ingest(T+90,bid=39,ask=40)
        r=self.a.snapshot(T+90);self.assertEqual([f['side'] for f in r['fills']],['sell','buy'])
        self.assertEqual(r['state']['positions']['BTC-USD'],0);self.assertTrue(r['state']['halted'])
    def test_provider_error_cancels_orders_without_reset(self):
        self.queue_buy();self.a.error('ConnectionError',now=T+65);self.ingest(T+70)
        self.assertEqual(self.a.snapshot(T+70)['fills'],[])
    def test_single_worker_lease_and_fencing(self):
        self.a.claim('one',10,now=T)
        with self.assertRaises(ValueError):self.a.claim('two',10,now=T+1)
        with self.assertRaises(ValueError):self.a.ingest(snap(T+1),owner='two',now=T+1)
        self.a.claim('two',10,now=T+11)
        with self.assertRaises(ValueError):self.a.ingest(snap(T+12),owner='one',now=T+12)
        self.assertTrue(self.a.ingest(snap(T+12),owner='two',now=T+12)['accepted'])
    def test_same_bar_decision_cannot_repeat(self):
        self.queue_buy();state=self.a.snapshot(T+60)['state']
        self.assertFalse(self.a.queue({'actions':{'BTC-USD':'buy'},'reason':'repeat'},state['seq'],state['control_revision'],state['last_completed_bar'],now=T+61))
    def test_partial_startup_candle_excluded(self):
        self.ingest(T+40);self.ingest(T+50);self.ingest(T+60)
        self.assertEqual(self.a.snapshot(T+60)['completed_candles'],{})
    def test_export_backup_and_existing_file_preserved(self):
        self.queue_buy();self.ingest(T+70)
        target=Path(self.tmp.name)/'backup.sqlite';self.a.backup(target)
        self.assertEqual(Account(target).snapshot(T+70)['state'],self.a.snapshot(T+70)['state'])
        csv=Path(self.tmp.name)/'history.csv';self.a.export_csv(csv)
        self.assertIn('BTC-USD,crypto',csv.read_text())
        with self.assertRaises(FileExistsError):self.a.backup(target)
        with self.assertRaises(FileExistsError):Account.create(self.path,['BTC-USD'],self.settings,'synthetic_live_demo','fixed:trend')
    def test_pending_expiry_even_without_observation_gap(self):
        self.queue_buy()
        with self.a.transaction() as conn:
            state=self.a._state(conn);state['config']['max_order_age']=5;self.a._save(conn,state)
        self.ingest(T+70);self.assertEqual(self.a.snapshot(T+70)['fills'],[])
    def test_failed_transaction_rolls_back_fills_and_balances(self):
        self.queue_buy();before=self.a.snapshot(T+60)
        with patch.object(self.a,'_candles',side_effect=RuntimeError('simulated interruption')),self.assertRaises(RuntimeError):self.ingest(T+70)
        after=Account(self.path).snapshot(T+60)
        self.assertEqual(after['state'],before['state']);self.assertEqual(after['fills'],before['fills'])
        self.ingest(T+70);self.assertEqual(len(self.a.snapshot(T+70)['fills']),1)
    def test_multi_asset_budget_and_cost_inclusive_cash(self):
        settings=Settings(stock_weight=0,crypto_weight=.9,max_position=.9,fees_bps={'stock':0,'crypto':1000})
        a=Account.create(Path(self.tmp.name)/'multi.sqlite',['BTC-USD','ETH-USD'],settings,'synthetic_live_demo','fixed:trend',60)
        def multi(t):return {'source':'synthetic_live_demo','received_at_unix':t,'elapsed_seconds':0,'quotes':[{'symbol':s,'bid':100,'ask':100} for s in ['BTC-USD','ETH-USD']]}
        for offset in (0,10,20,30,40,50,60):a.ingest(multi(T+offset),now=T+offset)
        s=a.snapshot(T+60)['state'];a.queue({'actions':{'BTC-USD':'buy','ETH-USD':'buy'},'reason':'test'},s['seq'],s['control_revision'],s['last_completed_bar'],now=T+60)
        a.ingest(multi(T+70),now=T+70);s=a.snapshot(T+70)['state']
        self.assertGreaterEqual(s['cash'],0)
        self.assertLessEqual(sum(q*100 for q in s['positions'].values())/s['equity'],.9)
    def test_pause_keeps_halted_positions_until_resume(self):
        self.queue_buy();self.ingest(T+70);self.a.control(True,now=T+75)
        self.ingest(T+80,bid=40,ask=41);self.ingest(T+90,bid=39,ask=40)
        s=self.a.snapshot(T+90)['state'];self.assertTrue(s['halted']);self.assertGreater(s['positions']['BTC-USD'],0)
        self.a.control(False,now=T+95);self.ingest(T+100,bid=39,ask=40);self.ingest(T+110,bid=39,ask=40)
        self.assertEqual(self.a.snapshot(T+110)['state']['positions']['BTC-USD'],0)
    def test_deleted_database_is_not_recreated(self):
        self.path.unlink()
        with self.assertRaises(Exception):self.a.snapshot(T)
        self.assertFalse(self.path.exists())

if __name__=='__main__':unittest.main()
