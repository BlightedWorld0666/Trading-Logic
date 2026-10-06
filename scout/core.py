from collections import defaultdict
from dataclasses import dataclass, field
import math
from statistics import mean, pstdev

STRATEGIES = ('trend', 'reversion', 'breakout')
LABELS = {'trend': 'Trend / 10–30', 'reversion': 'Mean reversion / 20',
          'breakout': 'Breakout / 20', 'hold': 'Buy and hold', 'cash': 'Stay in cash'}

@dataclass(frozen=True)
class Settings:
    capital: float = 1000.0
    stock_weight: float = .45
    crypto_weight: float = .45
    max_position: float = .25
    max_drawdown: float = .10
    # Example assumptions, not current brokerage or exchange fee schedules.
    fees_bps: dict = field(default_factory=lambda: {'stock': 0.0, 'crypto': 25.0})
    slippage_bps: dict = field(default_factory=lambda: {'stock': 2.0, 'crypto': 10.0})

    def validate(self):
        if not all(isinstance(c, dict) for c in (self.fees_bps, self.slippage_bps)):
            raise ValueError('Cost settings must be objects.')
        numbers = [self.capital, self.stock_weight, self.crypto_weight, self.max_position,
                   self.max_drawdown, *self.fees_bps.values(), *self.slippage_bps.values()]
        if not all(isinstance(n, (int, float)) and not isinstance(n, bool) and math.isfinite(n) for n in numbers):
            raise ValueError('All settings must be finite numbers.')
        if not 1 <= self.capital <= 10000000:
            raise ValueError('Simulation capital must be between 1 and 10,000,000.')
        if min(self.stock_weight, self.crypto_weight) < 0 or self.stock_weight + self.crypto_weight > .90000001:
            raise ValueError('Stock and crypto allocations must total at most 90%; remaining capital stays in cash.')
        if not 0 < self.max_position <= .90 or not 0 < self.max_drawdown < 1:
            raise ValueError('Invalid position or drawdown limit.')
        for costs in (self.fees_bps, self.slippage_bps):
            if set(costs) != {'stock', 'crypto'} or not all(0 <= n <= 1000 for n in costs.values()):
                raise ValueError('Specify stock and crypto costs between 0 and 1,000 basis points.')
        return self


def signal(strategy, history, held):
    closes = [bar.close for bar in history]
    if strategy == 'cash':
        return False
    if strategy == 'hold':
        return True
    if strategy == 'trend':
        return len(closes) >= 30 and mean(closes[-10:]) > mean(closes[-30:])
    if strategy == 'reversion':
        if len(closes) < 20:
            return False
        average, sigma = mean(closes[-20:]), pstdev(closes[-20:])
        return closes[-1] < average if held else closes[-1] < average - 1.2 * sigma
    if strategy == 'breakout':
        if len(closes) < 21:
            return False
        return closes[-1] >= mean(closes[-10:]) if held else closes[-1] > max(b.high for b in history[-21:-1])
    raise ValueError('Unknown strategy: ' + strategy)


def simulate(bars, choices, settings, start=None, decision_provider=None):
    """Close-based signals fill on the next available bar's open, never that close."""
    settings.validate()
    selected = [b for b in bars if b.symbol in choices]
    kinds = {b.symbol: b.asset_class for b in selected}
    counts = {k: sum(v == k for v in kinds.values()) for k in ('stock', 'crypto')}
    class_caps = {'stock': settings.stock_weight, 'crypto': settings.crypto_weight}
    weights = {s: min(settings.max_position, class_caps[k] / counts[k]) for s, k in kinds.items()}
    grouped = defaultdict(list)
    for bar in selected:
        grouped[bar.timestamp].append(bar)
    cash, peak = settings.capital, settings.capital
    quantities = {s: 0.0 for s in kinds}
    marks, history, pending = {}, defaultdict(list), {}
    fills, curve, decisions = [], [], []
    fees = slippage = max_dd = turnover = 0.0
    halted, halted_at = False, None

    def equity():
        return cash + sum(q * marks.get(s, 0) for s, q in quantities.items())

    for timestamp in sorted(grouped):
        current = sorted(grouped[timestamp], key=lambda b: b.symbol)
        active = start is None or timestamp >= start
        if not active:
            for bar in current:
                history[bar.symbol].append(bar)
                history[bar.symbol] = history[bar.symbol][-60:]
            continue
        # All current opens become available together. Exits run before entries.
        for bar in current:
            marks[bar.symbol] = bar.open
        for want in (False, True):
            for bar in current:
                symbol, kind = bar.symbol, bar.asset_class
                desired = False if halted else pending.get(symbol)
                if desired is None or desired != want:
                    continue
                fee_rate, slip_rate = settings.fees_bps[kind] / 10000, settings.slippage_bps[kind] / 10000
                if not want and quantities[symbol] > 0:
                    qty = quantities[symbol]
                    price = bar.open * (1 - slip_rate)
                    fee = qty * price * fee_rate
                    cash += qty * price - fee
                    quantities[symbol] = 0
                    side = 'sell'
                elif want and not halted and quantities[symbol] == 0 and weights[symbol] > 0:
                    price = bar.open * (1 + slip_rate)
                    total = equity()
                    exposure = total - cash
                    target_value = min(total * weights[symbol], max(0, total * .90 - exposure), cash)
                    # Cost-inclusive sizing prevents borrowing for entry fees.
                    qty = target_value / (price * (1 + fee_rate))
                    if qty <= 1e-12:
                        continue
                    fee = qty * price * fee_rate
                    cash -= qty * price + fee
                    quantities[symbol] = qty
                    side = 'buy'
                else:
                    continue
                fees += fee
                slip_cost = qty * abs(price - bar.open)
                slippage += slip_cost
                turnover += qty * price
                fills.append({'timestamp': timestamp.isoformat(), 'symbol': symbol,
                              'asset_class': kind, 'side': side, 'quantity': qty,
                              'reference_open': bar.open, 'fill_price': price,
                              'fee': fee, 'slippage_cost': slip_cost})
        for bar in current:
            marks[bar.symbol] = bar.close
            history[bar.symbol].append(bar)
            history[bar.symbol] = history[bar.symbol][-60:]
        total = equity()
        peak = max(peak, total)
        dd = (peak - total) / peak
        max_dd = max(max_dd, dd)
        if dd >= settings.max_drawdown and not halted:
            halted, halted_at = True, timestamp.isoformat()
        curve.append({'timestamp': timestamp.isoformat(), 'equity': total, 'cash': cash,
                      'exposure': total - cash, 'drawdown': dd})
        # A halt queues exits at each asset's next available bar. It cannot guarantee a loss ceiling.
        actions = None
        if decision_provider is not None and not halted:
            evidence = {'timestamp': timestamp.isoformat(), 'cash': cash, 'equity': total,
                        'positions': dict(quantities), 'drawdown': dd,
                        'bars': {s: [{'timestamp': b.timestamp.isoformat(), 'close': b.close,
                                     'high': b.high, 'low': b.low, 'volume': b.volume}
                                    for b in series[-30:]] for s, series in history.items()}}
            try:
                proposal = decision_provider(evidence, sorted(kinds))
                actions = proposal['actions']
                if set(actions) != set(kinds) or any(a not in ('buy', 'sell', 'hold') for a in actions.values()):
                    raise ValueError('Invalid paper actions.')
                decisions.append({'timestamp': timestamp.isoformat(), **proposal})
            except Exception as exc:
                actions = {s: 'hold' for s in kinds}
                decisions.append({'timestamp': timestamp.isoformat(), 'actions': actions,
                                  'reason': 'AI unavailable or invalid; hold.', 'error_type': type(exc).__name__})
        if actions is not None:
            for symbol, action in actions.items():
                pending[symbol] = (quantities[symbol] > 0) if action == 'hold' else action == 'buy'
        for bar in current:
            if actions is not None:
                action = actions[bar.symbol]
                pending[bar.symbol] = (quantities[bar.symbol] > 0) if action == 'hold' else action == 'buy'
                continue
            pending[bar.symbol] = False if halted else signal(choices[bar.symbol], history[bar.symbol], quantities[bar.symbol] > 0)
    marked = equity()
    exit_cost = sum(q * marks[s] * (1 - (1 - settings.slippage_bps[kinds[s]] / 10000)
                         * (1 - settings.fees_bps[kinds[s]] / 10000)) for s, q in quantities.items() if q)
    final = marked - exit_cost
    net_return = (final / settings.capital - 1) * 100
    return {'net_return_pct': net_return, 'net_profit': final - settings.capital,
            'final_equity': final, 'marked_equity': marked,
            'max_drawdown_pct': max_dd * 100, 'fees_paid': fees,
            'slippage_cost': slippage, 'estimated_exit_cost': exit_cost,
            'turnover': turnover, 'fill_count': len(fills), 'halted': halted,
            'halted_at': halted_at, 'open_positions': {s: q for s, q in quantities.items() if q},
            'curve': curve, 'fills': fills, 'weights': weights, 'decisions': decisions,
            'score': net_return - 1.5 * max_dd * 100}
