"""Official Robinhood Crypto v2 quote reader. No order endpoints exist in this adapter."""
import base64
import json
import math
import re
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, build_opener
from .ai import NoRedirect


def signing_key(seed):
    try:
        from nacl.signing import SigningKey
    except ImportError as exc:
        raise ValueError('Install the optional dependency: python -m pip install -r requirements-robinhood.txt') from exc
    return SigningKey(base64.b64decode(seed, validate=True))


def quotes(credentials, symbols, opener=None, now=None):
    if not 1 <= len(symbols) <= 12 or len(set(symbols)) != len(symbols) or not all(re.fullmatch(r'[A-Z0-9]{1,16}-USD', s) for s in symbols):
        raise ValueError('Supply 1–12 unique uppercase USD crypto pairs.')
    key = credentials.get('api_key')
    if not isinstance(key, str) or not re.fullmatch(r'[A-Za-z0-9-]{1,200}', key):
        raise ValueError('Invalid API key. Keep credentials on your PC.')
    signer = signing_key(credentials['private_key_base64'])
    path = '/api/v2/crypto/marketdata/best_bid_ask/?' + urlencode([('symbol', s) for s in symbols])
    timestamp = str(int(time.time() if now is None else now))
    message = (key + timestamp + path + 'GET').encode()
    signature = base64.b64encode(signer.sign(message).signature).decode()
    request = Request('https://trading.robinhood.com' + path, method='GET', headers={
        'x-api-key': key, 'x-timestamp': timestamp, 'x-signature': signature,
        'Content-Type': 'application/json'})
    started=time.monotonic()
    try:
        with (opener or build_opener(NoRedirect())).open(request, timeout=20) as response:
            raw = response.read(262145)
    except HTTPError as exc:
        raise ValueError(f'Robinhood returned HTTP {exc.code}. Check key permissions and your PC clock.') from None
    except URLError:
        raise ValueError('Robinhood connection failed. No orders were sent.') from None
    if len(raw) > 262144:
        raise ValueError('Quote response was too large.')
    value = json.loads(raw)
    rows = value.get('results') if isinstance(value, dict) else None
    if not isinstance(rows, list) or len(rows) != len(symbols):
        raise ValueError('Missing quotes; no partial snapshot accepted.')
    result = []
    seen = set()
    for row in rows:
        symbol = row.get('symbol')
        if symbol not in symbols or symbol in seen:
            raise ValueError('Unexpected or duplicate quote symbol.')
        seen.add(symbol)
        try:
            bid, ask = float(row['bid']), float(row['ask'])
        except (KeyError, TypeError, ValueError):
            raise ValueError('Invalid quote price.') from None
        if not math.isfinite(bid) or not math.isfinite(ask) or not 0 < bid <= ask:
            raise ValueError('Invalid or crossed quote prices.')
        result.append({'symbol': symbol, 'bid': bid, 'ask': ask})
    return {'source': 'robinhood_crypto_v2', 'received_at_unix': time.time(), 'elapsed_seconds': time.monotonic()-started,
            'freshness': 'Receipt time only; endpoint has no exchange timestamp. Not an execution-price guarantee.',
            'quotes': result}
