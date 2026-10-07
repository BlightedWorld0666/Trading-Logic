import unittest
from dataclasses import replace
from scout.data import demo_bars
from scout.experiments import goal_summary, train_markets
from scout.learning import LearningConfig, load_policy
from scout.core import Settings


class SmallAccountTests(unittest.TestCase):
    def test_goal_uses_net_ending_balance_and_never_forecasts_a_time(self):
        result = goal_summary(20, 19, 2000)
        self.assertEqual(result['required_total_multiple'], 100)
        self.assertEqual(result['required_total_return_pct'], 9900)
        self.assertEqual(result['heldout_net_profit'], -1)
        self.assertFalse(result['target_met_at_test_end'])
        self.assertFalse(result['checkpoints'][0]['ending_balance_at_or_above'])
        self.assertIsNone(result['projected_days_to_target'])
        self.assertTrue(goal_summary(20, 2000, 2000)['target_met_at_test_end'])

    def test_two_markets_have_independent_budgets_and_frozen_loadable_policies(self):
        runs, summary = train_markets(demo_bars(), learning=LearningConfig(episodes=2))
        self.assertEqual(set(runs), {'stock', 'crypto'})
        self.assertEqual(summary['live_readiness'], 'not_established')
        for kind, run in runs.items():
            self.assertEqual(run['report']['settings']['capital'], 20)
            self.assertEqual(run['report']['settings'][kind+'_weight'], .9)
            other = 'crypto' if kind == 'stock' else 'stock'
            self.assertEqual(run['report']['settings'][other+'_weight'], 0)
            self.assertEqual(set(run['policy']['asset_classes'].values()), {kind})
            risk = Settings(**run['report']['settings'])
            load_policy(run['policy'], run['policy']['symbols'], run['policy']['asset_classes'], risk)
            self.assertEqual(summary['markets'][kind]['goal']['heldout_ending_net_liquidation_equity'],
                             run['report']['test']['final_equity'])

    def test_goal_does_not_influence_selection_or_learning(self):
        a, _ = train_markets(demo_bars(), target=100, learning=LearningConfig(episodes=2))
        b, _ = train_markets(demo_bars(), target=2000, learning=LearningConfig(episodes=2))
        for kind in a:
            self.assertEqual(a[kind]['policy'], b[kind]['policy'])
            self.assertEqual(a[kind]['report']['test'], b[kind]['report']['test'])

    def test_missing_market_and_invalid_capital_or_goal_are_rejected(self):
        bars = demo_bars()
        with self.assertRaises(ValueError):
            train_markets([b for b in bars if b.asset_class == 'crypto'])
        for capital, target in [(0, 2000), (20, 20), (20, float('nan')), (20, True)]:
            with self.assertRaises(ValueError):
                train_markets(bars, capital, target)


if __name__ == '__main__':
    unittest.main()
