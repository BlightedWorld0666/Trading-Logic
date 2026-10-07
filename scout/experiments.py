"""Independent small-account stock and crypto research; never broker execution."""
from dataclasses import replace
import math
from .core import Settings
from .learning import LearningConfig, train


def goal_summary(initial, final, target):
    for value in (initial, final, target):
        if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
            raise ValueError('Balances and target must be positive finite numbers.')
    if target <= initial:
        raise ValueError('Research target must exceed starting capital.')
    checkpoints = sorted({initial, target, *[n for n in (25, 50, 100, 250, 500, 1000) if initial < n < target]})
    return {'starting_balance': initial, 'target_balance': target,
            'required_total_multiple': target / initial,
            'required_total_return_pct': (target / initial - 1) * 100,
            'heldout_ending_net_liquidation_equity': final,
            'heldout_net_profit': final - initial,
            'heldout_net_return_pct': (final / initial - 1) * 100,
            'target_met_at_test_end': final >= target,
            'additional_gain_needed': max(0, target - final),
            'checkpoints': [{'balance': n, 'ending_balance_at_or_above': final >= n} for n in checkpoints],
            'projected_days_to_target': None,
            'note': 'Ending balances only; no projected compounding path or promise of reaching the target.'}


def train_markets(bars, capital=20, target=2000, learning=None, settings=None, source='synthetic_demo', progress=None):
    """Each market gets its own virtual capital. Results must not be added together."""
    base = replace(settings or Settings(), capital=capital).validate()
    goal_summary(capital, capital, target)
    config = (learning or LearningConfig()).validate()
    subsets = {kind: [bar for bar in bars if bar.asset_class == kind] for kind in ('stock', 'crypto')}
    if not all(subsets.values()):
        raise ValueError('Provide stock AND crypto bars for the two-market experiment.')
    # Prevalidate both splits before training either market.
    from .learning import partition
    for subset in subsets.values():
        partition(subset)
    runs = {}
    for kind, subset in subsets.items():
        risk = replace(base, stock_weight=.9 if kind == 'stock' else 0,
                       crypto_weight=.9 if kind == 'crypto' else 0).validate()
        callback = (lambda row, k=kind: progress(k, row)) if progress else None
        policy, report, experience, candidate = train(subset, risk, config, source, callback)
        report['small_account_goal'] = goal_summary(capital, report['test']['final_equity'], target)
        runs[kind] = {'policy': policy, 'candidate': candidate, 'report': report, 'experience': experience}
    limitations = [
        'Separate hypothetical accounts, each starting with the stated capital. Do not add these balances as one funded account.',
        'No real orders and no additional deposits. There is no forecast of daily income or time to reach the target.',
        'Training episodes replay historical prices; they are not real calendar days or repeated profitable trades.',
        'Fractional quantities are unconstrained: broker minimum orders, quantity increments, liquidity and cash settlement are not modeled.',
        'Fees and adverse slippage are illustrative. Actual bid/ask spreads, broker costs and taxes can change results.',
        'The current proportional simulator is largely scale-invariant. A $20 run is not evidence a real $20 account can execute the trades.',
        'Stocks are historical research only; the current forward quote worker supports crypto.',
        'Imported CSV provenance is not automatically verified. Synthetic data cannot establish profitability.',
        'Neither a $2,000 target nor meeting it in a simulation establishes live readiness or brokerage eligibility.'
    ]
    summary = {'version': '0.3.1', 'mode': 'independent_small_account_research', 'source': source,
               'capital_per_hypothetical_account': capital, 'target_per_account': target,
               'live_readiness': 'not_established', 'limitations': limitations,
               'markets': {kind: {'status': run['report']['status'],
                                 'dataset_sha256': run['report']['dataset_sha256'],
                                 'split': run['report']['split'],
                                 'goal': run['report']['small_account_goal'],
                                 'test_baselines': run['report']['test_baselines'],
                                 'drawdown_pct': run['report']['test']['max_drawdown_pct'],
                                 'fills': run['report']['test']['fill_count']}
                           for kind, run in runs.items()}}
    return runs, summary
