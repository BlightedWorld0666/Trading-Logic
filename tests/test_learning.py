import copy
from dataclasses import replace
from datetime import datetime
import json
import math
import random
import unittest
from scout.core import Settings, simulate
from scout.data import Bar, demo_bars
from scout.learning import (LearningConfig, Learner, Policy, actions_from_mask, evaluate,
                            greedy, load_policy, partition, state_key, train)


def evidence(equity=1000,dd=0,turnover=0,stamp='2024-01-01T00:00:00+00:00'):
    return {'timestamp':stamp,'equity':equity,'net_equity':equity,'cash':equity,
            'positions':{'A':0},'drawdown':dd,'max_drawdown':dd,'turnover':turnover,
            'bars':{'A':[{'close':100} for _ in range(30)]}}

class LearningTests(unittest.TestCase):
    def test_bellman_reward_and_terminal(self):
        config=LearningConfig(alpha=.5,gamma=.9,drawdown_penalty=2,turnover_penalty=.001)
        table={'future':[100,200]};learner=Learner(['A'],table,config,random.Random(1),0,1000,'end')
        learner.previous=(evidence(),'old',1)
        learner.update(evidence(990,.02,500),'future',True)
        reward=math.log(.99)-2*.02-.001*.5
        self.assertAlmostEqual(table['old'][1],.5*reward)
        self.assertEqual(table['old'][0],0)
        self.assertTrue(learner.experiences[0]['terminal'])
    def test_nonterminal_bootstraps_future(self):
        config=LearningConfig(alpha=1,gamma=.5,drawdown_penalty=0,turnover_penalty=0)
        table={'next':[2,4]};learner=Learner(['A'],table,config,random.Random(1),0,1000,'end')
        learner.previous=(evidence(),'old',0);learner.update(evidence(),'next',False)
        self.assertEqual(table['old'][0],2)
    def test_halt_terminal_accounts_delayed_exit(self):
        learner=Learner(['A'],{},LearningConfig(alpha=1),random.Random(1),0,1000,'end')
        learner.previous=(evidence(),'old',1)
        learner.finish({'final_equity':800,'max_drawdown_pct':20,'turnover':1000},'end')
        self.assertAlmostEqual(learner.table['old'][1],math.log(.8)-.4-.0005)
        self.assertIsNone(learner.previous)
    def test_joint_action_and_cash_tie(self):
        self.assertEqual(actions_from_mask(2,['A','B']),{'A':'sell','B':'buy'})
        self.assertEqual(greedy({'x':[0,0,0,0]},'x',4),0)
        self.assertEqual(greedy({},'new',4),0)
    def test_unseen_policy_falls_back_to_cash(self):
        p=Policy(['A']);before=copy.deepcopy(p.table)
        self.assertEqual(p(evidence(),['A'])['actions'],{'A':'sell'})
        self.assertEqual(p.table,before)
    def test_evaluation_never_updates_q_table(self):
        data=demo_bars();symbols,kinds,val,test=partition(data);p=Policy(symbols,{'x':[1]*16})
        before=copy.deepcopy(p.table);evaluate(data,p,Settings(),test)
        self.assertEqual(p.table,before)
    def test_state_scale_invariant_and_readiness(self):
        a=evidence();b=copy.deepcopy(a)
        for bar in b['bars']['A']:bar['close']*=10
        self.assertEqual(state_key(a,['A']),state_key(b,['A']))
        b['bars']['A']=b['bars']['A'][:10]
        self.assertNotEqual(state_key(a,['A']),state_key(b,['A']))
    def test_config_rejects_nan_and_bad_schedule(self):
        for c in [LearningConfig(episodes=1),LearningConfig(gamma=1),LearningConfig(alpha=float('nan')),LearningConfig(epsilon_start=.1,epsilon_end=.9)]:
            with self.subTest(config=c),self.assertRaises(ValueError):c.validate()
    def test_policy_validation_and_risk_matching(self):
        p=Policy(['A'],{'x':[0,1]});settings=Settings();kinds={'A':'stock'};v=p.artifact(kinds,settings)
        self.assertEqual(load_policy(v,['A'],kinds,settings).table,p.table)
        with self.assertRaises(ValueError):load_policy(v,['A'],kinds,replace(settings,max_drawdown=.2))
        v['q_table']['x'][0]=float('nan')
        with self.assertRaises(ValueError):load_policy(v,['A'],kinds,settings)
    def test_dataset_tail_cannot_change_training_or_selection(self):
        data=demo_bars();config=LearningConfig(episodes=4,seed=9)
        policy,a,experience,candidate=train(data,config=config)
        test_start=datetime.fromisoformat(a['split']['validation_end_exclusive'])
        changed=[replace(b,open=b.open*1.5,high=b.high*1.5,low=b.low*1.5,close=b.close*1.5) if b.timestamp>=test_start else b for b in data]
        other,b,other_exp,other_candidate=train(changed,config=config)
        self.assertEqual(a['episodes'],b['episodes'])
        self.assertEqual(a['validation_candidates'],b['validation_candidates'])
        self.assertEqual(a['selected_episode'],b['selected_episode'])
        self.assertEqual(policy['q_table'],other['q_table'])
        self.assertEqual(candidate['q_table'],other_candidate['q_table'])
        self.assertTrue(candidate['q_table'])
        self.assertEqual(experience,other_exp)
        self.assertNotEqual(a['dataset_sha256'],b['dataset_sha256'])
        self.assertTrue(all(datetime.fromisoformat(row['outcome_at'])<datetime.fromisoformat(a['split']['training_end_exclusive']) for row in experience))
    def test_seed_reproducibility(self):
        data=demo_bars();config=LearningConfig(episodes=2,seed=10)
        self.assertEqual(train(data,config=config),train(data,config=config))
    def test_cash_competes_in_validation(self):
        p,r,e,c=train(demo_bars(),config=LearningConfig(episodes=2))
        self.assertIn(0,[c['episode'] for c in r['validation_candidates']])
        self.assertGreaterEqual(max(c['metrics']['score'] for c in r['validation_candidates']),0)
        self.assertEqual(len(r['episodes']),2)

if __name__=='__main__':unittest.main()
