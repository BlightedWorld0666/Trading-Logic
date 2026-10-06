import io
import json
import math
from datetime import datetime, timedelta, timezone
import unittest
from unittest.mock import patch
from scout.core import Settings, simulate
from scout.data import Bar, demo_bars, parse_csv
from scout.research import analyze
from scout.ai import paper_decision, summarize, validate_notes


def bars(prices=(100,100,100),symbol='A',kind='stock'):
    t = datetime(2024,1,1,tzinfo=timezone.utc)
    return [Bar(t+timedelta(days=i),symbol,kind,p,p,p,p,1) for i,p in enumerate(prices)]

class EngineTests(unittest.TestCase):
    def test_next_open(self):
        r=simulate(bars((100,200,300)),{'A':'hold'},Settings(slippage_bps={'stock':0,'crypto':0}))
        self.assertEqual(r['fills'][0]['reference_open'],200)
        self.assertEqual(r['fills'][0]['timestamp'],bars()[1].timestamp.isoformat())
    def test_costs_and_cash(self):
        r=simulate(bars(),{'A':'hold'},Settings(fees_bps={'stock':100,'crypto':100},slippage_bps={'stock':100,'crypto':100}))
        self.assertLess(r['net_profit'],0)
        self.assertGreater(r['estimated_exit_cost'],0)
        self.assertAlmostEqual(r['marked_equity']-r['estimated_exit_cost'],r['final_equity'])
        self.assertTrue(all(p['cash']>=-1e-8 for p in r['curve']))
    def test_shared_budget(self):
        data=bars(symbol='A')+bars(symbol='B',kind='crypto')
        r=simulate(data,{'A':'hold','B':'hold'},Settings(max_position=.9))
        self.assertLessEqual(r['curve'][1]['exposure']/r['curve'][1]['equity'],.9)
        self.assertAlmostEqual(r['weights']['A'],.45)
        self.assertAlmostEqual(r['weights']['B'],.45)
    def test_cash_no_fills(self):
        r=simulate(bars(),{'A':'cash'},Settings())
        self.assertEqual(r['net_profit'],0);self.assertEqual(r['fills'],[])
    def test_halt_overrides_ai(self):
        data=bars((100,100,10,10,10))
        def buy(e,n): return {'actions':{s:'buy' for s in n},'reason':'test'}
        r=simulate(data,{'A':'cash'},Settings(),decision_provider=buy)
        self.assertTrue(r['halted']);self.assertEqual([f['side'] for f in r['fills']],['buy','sell'])
        self.assertEqual(len(r['decisions']),2)
    def test_provider_sees_only_completed_history(self):
        seen=[]
        def buy(e,n):
            seen.append(e)
            self.assertTrue(all(b['timestamp']<=e['timestamp'] for hist in e['bars'].values() for b in hist))
            return {'actions':{s:'buy' for s in n},'reason':'test'}
        r=simulate(bars((100,150,200)),{'A':'cash'},Settings(),decision_provider=buy)
        self.assertEqual(len(seen[0]['bars']['A']),1)
        self.assertEqual(r['fills'][0]['reference_open'],150)
    def test_ai_error_holds(self):
        def fail(e,n): raise ValueError('bad')
        r=simulate(bars(),{'A':'cash'},Settings(),decision_provider=fail)
        self.assertEqual(r['fills'],[]);self.assertEqual(len(r['decisions']),3)
    def test_hold_keeps_position(self):
        calls=iter(['buy','hold','sell','hold'])
        def choose(e,n):return {'actions':{'A':next(calls)},'reason':'test'}
        r=simulate(bars((100,100,100,100)),{'A':'cash'},Settings(),decision_provider=choose)
        self.assertEqual([f['side'] for f in r['fills']],['buy','sell'])
        self.assertEqual(r['fills'][1]['timestamp'],bars((100,100,100,100))[3].timestamp.isoformat())
    def test_holdout_does_not_affect_selection(self):
        original=demo_bars();a=analyze(original);split=datetime.fromisoformat(a['split_at'])
        changed=[Bar(b.timestamp,b.symbol,b.asset_class,b.open*2,b.high*2,b.low*2,b.close*2,b.volume) if b.timestamp>=split else b for b in original]
        b=analyze(changed)
        self.assertEqual(a['symbols'],b['symbols'])
        self.assertEqual([c['training'] for c in a['candidates']],[c['training'] for c in b['candidates']])
    def test_settings_invalid(self):
        for kw in [{'capital':float('nan')},{'stock_weight':.9,'crypto_weight':.2},{'fees_bps':[]},{'capital':True}]:
            with self.subTest(kw=kw),self.assertRaises(ValueError): Settings(**kw).validate()

class DataTests(unittest.TestCase):
    def test_valid_csv(self):
        text='timestamp,symbol,asset_class,open,high,low,close,volume\n2024-01-01T00:00:00Z,A,stock,1,2,1,2,0\n'
        self.assertEqual(parse_csv(text)[0].symbol,'A')
    def test_reject_duplicates_and_bad_numbers(self):
        header='timestamp,symbol,asset_class,open,high,low,close,volume\n'
        row='2024-01-01T00:00:00Z,A,stock,1,2,1,2,0\n'
        for text in [header+row+row,header+row.replace(',2,0',',nan,0'),header+row.replace('Z',''),header+row.replace(',1,2,1,2',',3,2,1,2')]:
            with self.subTest(text=text),self.assertRaises(ValueError): parse_csv(text)

class FakeOpener:
    def __init__(self,decision,info=None):
        self.decision=decision;self.info=info or {'model_info':{'general.architecture':'test'}};self.requests=[]
    def open(self,request,timeout):
        self.requests.append(request)
        if request.full_url.endswith('/tags'):
            value={'models':[{'name':'local:test','size':1000}]}
        else:
            value=self.info if request.full_url.endswith('/show') else {'message':{'content':json.dumps(self.decision)}}
        return io.BytesIO(json.dumps(value).encode())

class AITests(unittest.TestCase):
    def test_paper_schema_and_local_endpoints(self):
        o=FakeOpener({'actions':{'A':'buy'},'reason':'test'})
        r=paper_decision('local:test',{'cash':100},['A'],o)
        self.assertEqual(r['actions']['A'],'buy')
        self.assertEqual([q.full_url for q in o.requests],['http://127.0.0.1:11434/api/tags','http://127.0.0.1:11434/api/show','http://127.0.0.1:11434/api/chat'])
    def test_remote_model_rejected_before_evidence(self):
        o=FakeOpener({}, {'remote_host':'https://remote','model_info':{'test':1}})
        with self.assertRaises(ValueError):paper_decision('local:test',{'secret':'evidence'},['A'],o)
        self.assertEqual(len(o.requests),2)
    def test_cloud_name_rejected(self):
        o=FakeOpener({})
        with self.assertRaises(ValueError):paper_decision('model:cloud',{},['A'],o)
        self.assertEqual(o.requests,[])
    def test_invalid_action_rejected(self):
        for decision in [{'actions':{'A':'leverage'},'reason':'x'},{'actions':{'B':'buy'},'reason':'x'},{'actions':{'A':'buy'},'reason':'x','command':'run'}]:
            with self.subTest(decision=decision),self.assertRaises(ValueError):paper_decision('local:test',{},['A'],FakeOpener(decision))
    def test_notes_validation(self):
        with self.assertRaises(ValueError):validate_notes({'summary':'x','risks':['x'],'next_checks':[],'orders':[]})
    def test_summary(self):
        r=analyze(demo_bars());o=FakeOpener({'summary':'Synthetic data.','risks':['Not profitability evidence.'],'next_checks':['Import data.']})
        self.assertTrue(summarize(r,'local:test',o)['unverified'])

if __name__=='__main__':unittest.main()
