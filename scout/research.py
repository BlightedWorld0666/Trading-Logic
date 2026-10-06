from collections import defaultdict
from dataclasses import asdict
from datetime import datetime, timezone
from .core import Settings, STRATEGIES, LABELS, simulate


def brief(result):
    return {key: value for key, value in result.items() if key not in ('curve', 'fills', 'decisions')}


def analyze(bars, settings=None, source='synthetic_demo'):
    settings = (settings or Settings()).validate()
    times = sorted({b.timestamp for b in bars})
    if len(times) < 100:
        raise ValueError('Use at least 100 distinct bar timestamps for training and holdout.')
    split = times[int(len(times) * .70)]
    groups = defaultdict(list)
    for bar in bars:
        groups[bar.symbol].append(bar)
    if not any(b.asset_class == 'stock' for b in bars) or not any(b.asset_class == 'crypto' for b in bars):
        raise ValueError('Include at least one stock and one crypto symbol for a combined study.')
    selected, candidates = {}, []
    for symbol in sorted(groups):
        history = groups[symbol]
        training = [b for b in history if b.timestamp < split]
        testing = [b for b in history if b.timestamp >= split]
        if len(training) < 40 or len(testing) < 20:
            raise ValueError(f'{symbol} needs at least 40 training bars and 20 holdout bars.')
        scored = []
        # Cash is a valid winner: the agent is not required to find a reason to trade.
        for name in (*STRATEGIES, 'cash'):
            train = simulate(training, {symbol: name}, settings)
            scored.append((train['score'], name, train))
        _, picked, _ = max(scored, key=lambda row: (row[0], row[1] == 'cash'))
        selected[symbol] = picked
        for _, name, train in scored:
            test = simulate(history, {symbol: name}, settings, split)
            candidates.append({'symbol': symbol, 'asset_class': history[0].asset_class,
                               'strategy': name, 'label': LABELS[name], 'selected': name == picked,
                               'training': brief(train), 'holdout_diagnostic': brief(test)})
    combined = simulate(bars, selected, settings, split)
    stocks = simulate(bars, {s: n for s, n in selected.items() if groups[s][0].asset_class == 'stock'}, settings, split)
    crypto = simulate(bars, {s: n for s, n in selected.items() if groups[s][0].asset_class == 'crypto'}, settings, split)
    benchmark = simulate(bars, {s: 'hold' for s in groups}, settings, split)
    notices = [
        'Historical simulation only. No broker connection, live quotes, or real orders.',
        'Strategies are selected using the first 70% of timestamps only; the final 30% is held out.',
        'Holdout results for unselected candidates are diagnostic. Do not keep tuning against this holdout.',
        'Costs are configurable example assumptions, not verified current fees. All prices must be in USD.',
        'Open positions are marked at the last observed close. Final equity deducts estimated exit costs; that closeout is not an executed trade.',
        'Missing asset bars do not fill orders. Marks stay stale until that asset has another bar.',
        'Position/allocation caps apply to new entries. Price changes may increase exposure after entry.',
        'The drawdown halt blocks further entries and queues exits; gaps or closed markets can exceed the limit.',
        'Taxes, dividends, borrow costs, split adjustments, order-book liquidity and market impact are not modeled.',
    ]
    if source == 'synthetic_demo':
        notices.insert(0, 'DEMO: invented assets and prices. These numbers provide no evidence of a profitable strategy.')
    else:
        notices.insert(0, 'Imported CSV: provenance and adjustments are supplied by you and have not been verified.')
    audit = []
    if all(value == 'cash' for value in selected.values()):
        audit.append('Training favored cash for every symbol. There is no selected trading strategy in this study.')
    if combined['net_profit'] <= 0:
        audit.append('The combined holdout did not produce a positive net result under these assumptions.')
    if combined['halted']:
        audit.append('Shared drawdown protection triggered. Inspect the halt date and delayed exits.')
    if combined['fill_count'] < 20:
        audit.append('Fewer than 20 combined fills: this sample is too small for a strong performance conclusion.')
    if combined['net_return_pct'] < benchmark['net_return_pct']:
        audit.append('The selected combination lagged the same-allocation buy-and-hold comparison.')
    audit.append('Repeat on genuinely new, verified data and stress fees/slippage before considering execution.')
    return {'version': '0.3.0', 'created_at': datetime.now(timezone.utc).isoformat(),
            'source': source, 'currency': 'USD', 'settings': asdict(settings),
            'selection_rule': 'Training net return percentage minus 1.5 × training maximum drawdown percentage; cash is eligible.',
            'split_at': split.isoformat(), 'start': times[0].isoformat(), 'end': times[-1].isoformat(),
            'symbols': [{'symbol': s, 'asset_class': groups[s][0].asset_class,
                         'bars': len(groups[s]), 'selected_strategy': selected[s]} for s in sorted(groups)],
            'candidates': candidates, 'combined': combined,
            'comparison': {'combined': brief(combined), 'stocks_only': brief(stocks),
                           'crypto_only': brief(crypto), 'buy_and_hold': brief(benchmark)},
            'benchmark_curve': benchmark['curve'], 'audit': audit, 'limitations': notices}
