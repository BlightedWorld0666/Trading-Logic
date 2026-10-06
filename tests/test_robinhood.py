import base64
import io
import json
import unittest
from unittest.mock import patch
from scout.robinhood import quotes

class Signer:
    def __init__(self):self.message=None
    def sign(self,message):
        self.message=message
        return type('Signature',(),{'signature':b'test-signature'})()
class Opener:
    def __init__(self,rows):self.rows=rows;self.request=None
    def open(self,request,timeout):
        self.request=request
        return io.BytesIO(json.dumps({'results':self.rows}).encode())

class RobinhoodTests(unittest.TestCase):
    def test_exact_signed_get(self):
        signer=Signer();o=Opener([{'symbol':'BTC-USD','bid':'99','ask':'101'}])
        with patch('scout.robinhood.signing_key',return_value=signer):
            result=quotes({'api_key':'rh-api-test','private_key_base64':'unused'},['BTC-USD'],o,123)
        self.assertEqual(o.request.get_method(),'GET')
        self.assertEqual(o.request.full_url,'https://trading.robinhood.com/api/v2/crypto/marketdata/best_bid_ask/?symbol=BTC-USD')
        self.assertEqual(signer.message,b'rh-api-test123/api/v2/crypto/marketdata/best_bid_ask/?symbol=BTC-USDGET')
        self.assertEqual(result['quotes'][0]['bid'],99)
    def test_bad_quotes_rejected(self):
        for rows in [[],[{'symbol':'ETH-USD','bid':1,'ask':2}],[{'symbol':'BTC-USD','bid':3,'ask':2}],[{'symbol':'BTC-USD','bid':float('nan'),'ask':2}]]:
            with self.subTest(rows=rows),patch('scout.robinhood.signing_key',return_value=Signer()),self.assertRaises(ValueError):
                quotes({'api_key':'test','private_key_base64':'unused'},['BTC-USD'],Opener(rows))
    def test_symbol_injection_rejected(self):
        with self.assertRaises(ValueError):quotes({},['BTC-USD&orders=buy'])

if __name__=='__main__':unittest.main()
