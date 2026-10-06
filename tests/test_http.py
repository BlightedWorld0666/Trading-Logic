import http.client
from http.server import ThreadingHTTPServer
import json
import threading
import tempfile
from pathlib import Path
from scout.account import Account
from scout.core import Settings
import unittest
from unittest.mock import patch
import app
from scout.data import demo_bars
from scout.research import analyze

class HTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory();cls.old_path=app.PAPER_PATH
        app.PAPER_PATH=Path(cls.tmp.name)/'paper.sqlite'
        Account.create(app.PAPER_PATH,['BTC-USD'],Settings(),'synthetic_live_demo','fixed:cash')
        app.REPORT=app.stamp(analyze(demo_bars()))
        cls.server=ThreadingHTTPServer(('127.0.0.1',0),app.Handler)
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True);cls.thread.start()
        cls.port=cls.server.server_address[1]
    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown();cls.server.server_close();cls.thread.join();app.PAPER_PATH=cls.old_path;cls.tmp.cleanup()
    def req(self,path='/',body=None,headers=None):
        conn=http.client.HTTPConnection('127.0.0.1',self.port,timeout=5)
        conn.request('GET' if body is None else 'POST',path,json.dumps(body) if body is not None else None,headers or {})
        res=conn.getresponse();status=res.status;data=res.read();conn.close();return status,data
    def headers(self):return {'Content-Type':'application/json','X-Scout-Token':app.TOKEN}
    def test_paper_read_and_control(self):
        status,data=self.req('/api/paper');self.assertEqual(status,200)
        self.assertEqual(json.loads(data)['mode'],'forward_virtual_crypto_account')
        status,data=self.req('/api/paper/control',{'paused':True},self.headers());self.assertEqual(status,200)
        self.assertTrue(json.loads(data)['state']['paused'])
        self.assertEqual(self.req('/api/paper/control',{'paused':False},{'Content-Type':'application/json'})[0],403)
        self.assertEqual(self.req('/api/paper/control',{'paused':'yes'},self.headers())[0],400)
    def test_html_injects_token(self):
        status,data=self.req();self.assertEqual(status,200);self.assertIn(app.TOKEN.encode(),data);self.assertNotIn(b'__API_TOKEN__',data)
    def test_host_rejected(self):self.assertEqual(self.req(headers={'Host':'evil.test'})[0],403)
    def test_token_required(self):self.assertEqual(self.req('/api/analyze',{}, {'Content-Type':'application/json'})[0],403)
    def test_cross_site_rejected(self):
        h=self.headers();h['Sec-Fetch-Site']='cross-site';self.assertEqual(self.req('/api/analyze',{},h)[0],403)
    def test_bad_input_preserves_report(self):
        previous=app.REPORT['report_id'];self.assertEqual(self.req('/api/analyze',{'csv_text':'bad'},self.headers())[0],400)
        self.assertEqual(app.REPORT['report_id'],previous)
    def test_stale_ai_rejected(self):self.assertEqual(self.req('/api/summary',{'report_id':'old','model':'local'},self.headers())[0],409)
    def test_static_allowlist(self):self.assertEqual(self.req('/scout/core.py')[0],404)
    def test_analyze_and_report(self):
        status,data=self.req('/api/analyze',{'settings':{'capital':2000}},self.headers());self.assertEqual(status,200)
        r=json.loads(data);self.assertEqual(r['settings']['capital'],2000);self.assertEqual(r['source'],'synthetic_demo')
        self.assertEqual(json.loads(self.req('/api/report')[1])['report_id'],r['report_id'])

if __name__=='__main__':unittest.main()
