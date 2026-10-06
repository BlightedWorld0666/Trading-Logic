from argparse import Namespace
from pathlib import Path
import tempfile
import unittest
from forward import provider_from, process_tick
from scout.account import Account
from scout.core import Settings

T=1800000000

class ForwardTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.settings=Settings(stock_weight=0,crypto_weight=.9)
        self.account=Account.create(Path(self.tmp.name)/'account.sqlite',['BTC-USD'],self.settings,'synthetic_live_demo','fixed:trend',60)
        self.provider,_=provider_from(Namespace(policy=None,model=None,strategy='trend'),['BTC-USD'],self.settings)
    def tearDown(self):self.tmp.cleanup()
    def feed(self,t):
        price=100+(t-T)/60
        return lambda:{'source':'synthetic_live_demo','received_at_unix':t,'elapsed_seconds':0,
                       'quotes':[{'symbol':'BTC-USD','bid':price-.1,'ask':price+.1}]}
    def test_completed_candle_warmup_and_next_tick_fill(self):
        for offset in range(0,1801,10):process_tick(self.account,self.feed(T+offset),self.provider,None,now=T+offset)
        state=self.account.snapshot(T+1800)['state']
        self.assertEqual(len(state['history']['BTC-USD']),30)
        self.assertEqual(state['positions']['BTC-USD'],0)
        self.assertEqual(len(state['pending']),1)
        process_tick(self.account,self.feed(T+1810),self.provider,None,now=T+1810)
        r=self.account.snapshot(T+1810);self.assertEqual(len(r['fills']),1)
        self.assertGreater(r['state']['positions']['BTC-USD'],0)
        self.assertGreaterEqual(r['state']['cash'],0)
    def test_pause_while_provider_running_blocks_its_plan(self):
        def pause_provider(evidence,symbols):
            self.account.control(True,now=T+1800)
            return {'actions':{'BTC-USD':'buy'},'reason':'inference completed after pause'}
        for offset in range(0,1800,10):process_tick(self.account,self.feed(T+offset),self.provider,None,now=T+offset)
        process_tick(self.account,self.feed(T+1800),pause_provider,None,now=T+1800)
        state=self.account.snapshot(T+1800)['state']
        self.assertTrue(state['paused']);self.assertEqual(state['pending'],[])
    def test_callback_never_gets_building_candle(self):
        seen=[]
        def inspect(e,n):
            seen.append(e)
            self.assertEqual(len(e['bars']['BTC-USD']),30)
            self.assertAlmostEqual(e['bars']['BTC-USD'][-1]['close'],100+1790/60)
            return {'actions':{'BTC-USD':'hold'},'reason':'test'}
        for offset in range(0,1801,10):process_tick(self.account,self.feed(T+offset),inspect,None,now=T+offset)
        self.assertEqual(len(seen),1)

if __name__=='__main__':unittest.main()
