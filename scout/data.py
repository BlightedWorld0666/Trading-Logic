from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import csv
import io
import math
import random
import re

@dataclass(frozen=True)
class Bar:
    timestamp: datetime
    symbol: str
    asset_class: str
    open: float
    high: float
    low: float
    close: float
    volume: float


def parse_csv(text):
    reader = csv.DictReader(io.StringIO(text))
    required = {'timestamp', 'symbol', 'asset_class', 'open', 'high', 'low', 'close', 'volume'}
    if not reader.fieldnames or not required.issubset(reader.fieldnames):
        raise ValueError('CSV needs timestamp,symbol,asset_class,open,high,low,close,volume.')
    result, seen, classes = [], set(), {}
    for number, row in enumerate(reader, 2):
        if len(result) >= 20000:
            raise ValueError('Limit this research dataset to 20,000 bars.')
        try:
            timestamp = datetime.fromisoformat(row['timestamp'].replace('Z', '+00:00'))
            if timestamp.tzinfo is None:
                raise ValueError('Timestamp needs a timezone, such as Z or +00:00.')
            timestamp = timestamp.astimezone(timezone.utc)
            symbol = row['symbol'].strip().upper()
            if not re.fullmatch(r'[A-Z0-9][A-Z0-9._/-]{0,23}', symbol):
                raise ValueError('Invalid symbol.')
            kind = row['asset_class'].strip().lower()
            if kind not in {'stock', 'crypto'}:
                raise ValueError('asset_class must be stock or crypto.')
            if symbol in classes and classes[symbol] != kind:
                raise ValueError('A symbol cannot change asset class.')
            classes[symbol] = kind
            values = [float(row[k]) for k in ('open', 'high', 'low', 'close', 'volume')]
            o, h, l, c, v = values
            if not all(math.isfinite(x) for x in values) or min(o, h, l, c) <= 0 or v < 0:
                raise ValueError('Prices must be finite and positive; volume must be nonnegative.')
            if h < max(o, c) or l > min(o, c) or h < l:
                raise ValueError('Invalid OHLC price bounds.')
            if (symbol, timestamp) in seen:
                raise ValueError('Duplicate symbol and timestamp.')
            seen.add((symbol, timestamp))
            result.append(Bar(timestamp, symbol, kind, *values))
        except (ValueError, TypeError, KeyError) as exc:
            raise ValueError(f'CSV row {number}: {exc}') from exc
    if len(classes) > 12:
        raise ValueError('Use at most 12 symbols in this first version.')
    if not result:
        raise ValueError('CSV contains no bars.')
    return sorted(result, key=lambda b: (b.timestamp, b.symbol))


def demo_bars():
    """Invented daily prices. No symbol represents an actual security or coin."""
    rng = random.Random(666)
    start = datetime(2024, 1, 1, 21, tzinfo=timezone.utc)
    specs = [('STOCK-A', 'stock', 100), ('STOCK-B', 'stock', 65),
             ('CRYPTO-A', 'crypto', 1000), ('CRYPTO-B', 'crypto', 75)]
    prices = {symbol: price for symbol, _, price in specs}
    result = []
    for day in range(300):
        for index, (symbol, kind, _) in enumerate(specs):
            date = start + timedelta(days=day)
            if kind == 'stock' and date.weekday() >= 5:
                continue
            old = prices[symbol]
            phase = .003 * math.sin(day / 19 + index) + (.001 if day < 190 else -.0008)
            volatility = .011 if kind == 'stock' else .024
            opening = old * math.exp(rng.gauss(0, volatility / 3))
            closing = opening * math.exp(phase + rng.gauss(0, volatility))
            high = max(opening, closing) * (1 + rng.uniform(.001, volatility))
            low = min(opening, closing) * (1 - rng.uniform(.001, volatility))
            result.append(Bar(date, symbol, kind, opening, high, low, closing, rng.randint(5000, 50000)))
            prices[symbol] = closing
    return sorted(result, key=lambda b: (b.timestamp, b.symbol))
