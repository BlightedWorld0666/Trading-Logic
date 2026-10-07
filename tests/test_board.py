import tempfile
from pathlib import Path
import sqlite3
import json
import unittest
from scout.board import Board, evidence_snapshot, meeting, review
from scout.data import demo_bars
from scout.research import analyze
import app
import test_http

class BoardTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.board=Board(Path(self.tmp.name)/'board.sqlite')
        self.evidence=evidence_snapshot(app.stamp(analyze(demo_bars())), {'configured':False})
    def tearDown(self): self.tmp.cleanup()
    def test_persistence_and_cross_thread_reply_rejected(self):
        first=self.board.human_post('<script>alert(1)</script>')
        second=self.board.human_post('Another discussion')
        message=self.board.snapshot()['threads'][1]['messages'][0]['id']
        with self.assertRaises(ValueError):self.board.human_post('Invalid reply',second,message)
        self.board.human_post('Valid reply',first,message)
        threads=Board(self.board.path).snapshot()['threads']
        self.assertEqual(threads[1]['messages'][-1]['reply_to'],message)
        self.assertEqual(threads[1]['messages'][0]['content']['summary'],'<script>alert(1)</script>')
    def test_sequential_exchange_and_failure_retention(self):
        thread=self.board.create('Review',self.evidence,True)
        received=[]
        def reviewer(role,evidence,conversation,model):
            received.append((role,[m['author'] for m in conversation]))
            if role=='coordinator': raise RuntimeError('private information')
            return {'summary':role,'risks':[],'next_checks':[]}
        meeting(self.board,thread,self.evidence,[],reviewer=reviewer)
        self.assertEqual(received[2][1],['steady','momentum'])
        result=self.board.snapshot()['threads'][0]
        self.assertEqual(result['status'],'failed')
        self.assertEqual([m['author'] for m in result['messages']],['steady','momentum','risk','system'])
        self.assertNotIn('private information',str(result))
        self.assertEqual(result['context']['source'],'synthetic_demo')
    def test_local_prompt_contains_peer_messages_and_constraints(self):
        def chat(model,body):
            self.assertIn('no tools or execution authority',body['messages'][0]['content'])
            self.assertIn('peer disagreement',body['messages'][1]['content'])
            return {'message':{'content':'{"summary":"Review","risks":[],"next_checks":[]}'}}
        self.assertEqual(review('risk',self.evidence,[{'author':'steady','content':'peer disagreement'}],'local',chat)['summary'],'Review')
    def test_unknown_database_is_not_modified(self):
        with sqlite3.connect(self.board.path) as db:db.execute('CREATE TABLE valuable(data TEXT)')
        with self.assertRaises(ValueError):self.board.snapshot()
        with sqlite3.connect(self.board.path) as db:self.assertEqual(db.execute('PRAGMA application_id').fetchone()[0],0)
    def test_template_meeting_and_restart_status(self):
        thread=self.board.create('Templates',self.evidence,True)
        meeting(self.board,thread,self.evidence,[])
        result=self.board.snapshot()['threads'][0]
        self.assertEqual(result['status'],'complete')
        self.assertEqual(len(result['messages']),4)
        self.assertTrue(all(m['mode']=='template' for m in result['messages']))
        self.board.create('Old work',running=True);self.board.interrupt_previous()
        self.assertEqual(self.board.snapshot()['threads'][0]['status'],'interrupted')

class BoardHTTPTests(unittest.TestCase):
    setUpClass=classmethod(test_http.HTTPTests.setUpClass.__func__)
    tearDownClass=classmethod(test_http.HTTPTests.tearDownClass.__func__)
    req=test_http.HTTPTests.req
    headers=test_http.HTTPTests.headers
    def test_board_routes(self):
        with tempfile.TemporaryDirectory() as temp:
            old=app.BOARD_PATH;app.BOARD_PATH=Path(temp)/'board.sqlite'
            try:
                self.assertEqual(self.req('/api/board/post',{'text':'test'},{'Content-Type':'application/json'})[0],403)
                status,data=self.req('/api/board/post',{'text':'What should we test?'},self.headers())
                self.assertEqual(status,200);thread_id=json.loads(data)['thread_id']
                self.assertEqual(self.req('/api/board/review',{'question':'Review','thread_id':True},self.headers())[0],400)
                app.MEETING_LOCK.acquire()
                try:self.assertEqual(self.req('/api/board/review',{'question':'Review','thread_id':thread_id},self.headers())[0],409)
                finally:app.MEETING_LOCK.release()
                status,data=self.req('/api/board/review',{'question':'Review','thread_id':thread_id},self.headers())
                self.assertEqual(status,202)
                self.assertTrue(app.MEETING_LOCK.acquire(timeout=5));app.MEETING_LOCK.release()
                status,data=self.req('/api/board');self.assertEqual(status,200)
                self.assertEqual(json.loads(data)['threads'][0]['status'],'complete')
            finally:app.BOARD_PATH=old

if __name__=='__main__':unittest.main()
