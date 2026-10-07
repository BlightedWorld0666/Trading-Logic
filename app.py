"""Local research dashboard. Python 3.10+, standard library only."""
import argparse
import copy
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import threading
from urllib.parse import urlsplit

from scout.data import demo_bars, parse_csv
from scout.core import Settings
from scout.research import analyze
from scout.ai import summarize
from scout.account import Account
from scout.board import Board, evidence_snapshot, meeting, text_field

ROOT = Path(__file__).resolve().parent
TOKEN = secrets.token_urlsafe(32)
LOCK = threading.Lock()
REPORT = None
PAPER_PATH = ROOT / 'runtime' / 'demo.sqlite'
BOARD_PATH = ROOT / 'runtime' / 'board.sqlite'
MEETING_LOCK = threading.Lock()


def stamp(report):
    report['report_id'] = hashlib.sha256(json.dumps(report, sort_keys=True).encode()).hexdigest()[:20]
    return report


def settings_from(body):
    raw = body.get('settings', {})
    if not isinstance(raw, dict):
        raise ValueError('settings must be an object.')
    allowed = set(Settings.__dataclass_fields__)
    if set(raw) - allowed:
        raise ValueError('Unknown setting.')
    try:
        return Settings(**raw).validate()
    except (TypeError, AttributeError) as exc:
        raise ValueError('Invalid settings structure.') from exc


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        # Do not log uploaded data or model text.
        print('%s %s' % (self.command, self.path.split('?')[0]))

    def send(self, status, payload, content_type='application/json; charset=utf-8'):
        data = json.dumps(payload, allow_nan=False).encode() if not isinstance(payload, bytes) else payload
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        self.end_headers()
        self.wfile.write(data)

    def trusted_host(self):
        port = self.server.server_address[1]
        return self.headers.get('Host') in {f'127.0.0.1:{port}', f'localhost:{port}'}

    def do_GET(self):
        if not self.trusted_host():
            self.send(403, {'error': 'This dashboard is local-only.'})
            return
        path = urlsplit(self.path).path
        if path == '/api/board':
            try:
                self.send(200, Board(BOARD_PATH).snapshot())
            except Exception:
                self.send(503, {'error': 'Message board unavailable; its database has not been reset.'})
        elif path == '/api/paper':
            try:
                self.send(200, Account(PAPER_PATH).snapshot() if PAPER_PATH.is_file() else {'configured': False})
            except Exception:
                self.send(503, {'error': 'Paper account unavailable. Inspect its local database; it has not been reset.'})
        elif path == '/api/report':
            with LOCK:
                report = copy.deepcopy(REPORT)
            self.send(200, report)
        elif path in ('/', '/style.css', '/dashboard.js'):
            filename = 'index.html' if path == '/' else path[1:]
            data = (ROOT / 'web' / filename).read_bytes()
            if path == '/':
                data = data.replace(b'__API_TOKEN__', TOKEN.encode())
            mime = {'index.html': 'text/html', 'style.css': 'text/css', 'dashboard.js': 'text/javascript'}[filename]
            self.send(200, data, mime + '; charset=utf-8')
        else:
            self.send(404, {'error': 'Not found.'})

    def do_POST(self):
        global REPORT
        if not self.trusted_host() or not secrets.compare_digest(self.headers.get('X-Scout-Token', ''), TOKEN):
            self.send(403, {'error': 'Open the local dashboard before making requests.'})
            return
        if self.headers.get('Sec-Fetch-Site') == 'cross-site':
            self.send(403, {'error': 'Cross-site requests are not accepted.'})
            return
        if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
            self.send(415, {'error': 'Send JSON.'})
            return
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 1500000:
                raise ValueError('Request must be between 1 byte and 1.5 MB.')
            body = json.loads(self.rfile.read(length))
            if not isinstance(body, dict):
                raise ValueError('Send a JSON object.')
            path = urlsplit(self.path).path
            if path == '/api/board/post':
                board = Board(BOARD_PATH)
                thread_id = board.human_post(body.get('text'),body.get('thread_id'),body.get('reply_to'))
                self.send(200, {'thread_id':thread_id})
            elif path == '/api/board/review':
                title = text_field(body.get('question'),160)
                model = body.get('model') or None
                if model is not None and (not isinstance(model,str) or len(model)>96):
                    raise ValueError('Invalid local model name.')
                board = Board(BOARD_PATH)
                conversation = []
                if body.get('thread_id') is not None:
                    if type(body['thread_id']) is not int or body['thread_id']<=0:
                        raise ValueError('Choose a valid thread.')
                    previous = next((t for t in board.snapshot()['threads'] if t['id']==body['thread_id']),None)
                    if previous is None:
                        raise ValueError('Discussion thread not found.')
                    conversation = previous['messages'][-12:]
                with LOCK:
                    report = copy.deepcopy(REPORT)
                paper = Account(PAPER_PATH).snapshot() if PAPER_PATH.is_file() else {'configured':False}
                evidence = evidence_snapshot(report,paper)
                if not MEETING_LOCK.acquire(blocking=False):
                    self.send(409, {'error':'A research meeting is already running. Read its thread while it finishes.'})
                    return
                try:
                    thread_id = board.create(title,evidence,running=True)
                    message_id = board.post(thread_id,'Joseph',{'summary':title})
                    conversation.append({'id':message_id,'thread_id':thread_id,'author':'Joseph','content':{'summary':title}})
                    def worker():
                        try:
                            meeting(board,thread_id,evidence,conversation,model)
                        finally:
                            MEETING_LOCK.release()
                    threading.Thread(target=worker,daemon=True).start()
                except Exception:
                    MEETING_LOCK.release()
                    raise
                self.send(202, {'thread_id':thread_id})
            elif path == '/api/paper/control':
                Account(PAPER_PATH).control(body.get('paused'))
                self.send(200, Account(PAPER_PATH).snapshot())
            elif path == '/api/analyze':
                csv_text = body.get('csv_text')
                if csv_text is not None and not isinstance(csv_text, str):
                    raise ValueError('csv_text must be text.')
                if csv_text is not None and not csv_text.strip():
                    raise ValueError('Uploaded CSV is empty.')
                bars = parse_csv(csv_text) if csv_text is not None else demo_bars()
                result = stamp(analyze(bars, settings_from(body), 'uploaded_csv' if csv_text is not None else 'synthetic_demo'))
                with LOCK:
                    REPORT = result
                self.send(200, result)
            elif path == '/api/summary':
                with LOCK:
                    report = copy.deepcopy(REPORT)
                if body.get('report_id') != report['report_id']:
                    self.send(409, {'error': 'The report changed. Review the latest result first.'})
                    return
                notes = summarize(report, body.get('model', ''))
                self.send(200, {'report_id': report['report_id'], 'notes': notes})
            else:
                self.send(404, {'error': 'Not found.'})
        except (ValueError, KeyError, TypeError) as exc:
            self.send(400, {'error': str(exc)[:500]})
        except Exception as exc:
            if urlsplit(self.path).path == '/api/summary':
                self.send(503, {'error': 'Local AI unavailable. Start Ollama and enter an installed local model. ' + type(exc).__name__})
            else:
                self.send(500, {'error': 'Research run failed. Check the data and settings.'})


def main():
    global REPORT, PAPER_PATH, BOARD_PATH
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--csv', type=Path, help='Imported USD OHLCV dataset; otherwise run invented demo data.')
    parser.add_argument('--config', type=Path, help='JSON settings, such as config.example.json.')
    parser.add_argument('--report', type=Path, help='Write a JSON report and exit instead of serving the dashboard.')
    parser.add_argument('--paper-db', type=Path, default=PAPER_PATH, help='Existing forward account database to monitor/control.')
    parser.add_argument('--board-db', type=Path, default=BOARD_PATH, help='Persistent research board. Run one dashboard per board database.')
    parser.add_argument('--port', type=int, default=8002)
    args = parser.parse_args()
    PAPER_PATH = args.paper_db
    BOARD_PATH = args.board_db
    config = json.loads(args.config.read_text()) if args.config else {}
    settings = settings_from({'settings': config})
    bars = parse_csv(args.csv.read_text(encoding='utf-8-sig')) if args.csv else demo_bars()
    REPORT = stamp(analyze(bars, settings, 'uploaded_csv' if args.csv else 'synthetic_demo'))
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(REPORT, indent=2, allow_nan=False), encoding='utf-8')
        print('Research report written:', args.report)
        return
    if not 1024 <= args.port <= 65535:
        parser.error('Choose a port between 1024 and 65535.')
    Board(BOARD_PATH).interrupt_previous()
    server = ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
    print(f'Trading Logic research dashboard: http://127.0.0.1:{args.port}')
    print('Research simulations and optional forward VIRTUAL account. No real orders. Press Ctrl+C to stop.')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
