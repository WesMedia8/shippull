"""
api/accounts.py
GET  /api/accounts — List all connected accounts (no tokens returned).
DELETE /api/accounts?id=N — Remove an account and its orders.
"""
import json
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs


def _cors(h):
    h.send_header("Access-Control-Allow-Origin", "*")
    h.send_header("Access-Control-Allow-Methods", "GET, DELETE, OPTIONS")
    h.send_header("Access-Control-Allow-Headers", "Content-Type")


def _send_json(h, data, status=200):
    body = json.dumps(data).encode("utf-8")
    h.send_response(status)
    h.send_header("Content-Type", "application/json")
    h.send_header("Content-Length", str(len(body)))
    _cors(h)
    h.end_headers()
    h.wfile.write(body)


class handler(BaseHTTPRequestHandler):

    def do_OPTIONS(self):
        self.send_response(204)
        _cors(self)
        self.end_headers()

    def do_GET(self):
        try:
            from api._store import get_accounts_public
        except ImportError:
            from _store import get_accounts_public

        _send_json(self, get_accounts_public())

    def do_DELETE(self):
        try:
            from api._store import remove_account
        except ImportError:
            from _store import remove_account

        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        id_vals = params.get("id", [])
        if not id_vals:
            _send_json(self, {"error": "Missing id parameter"}, 400)
            return

        try:
            account_id = int(id_vals[0])
        except (ValueError, TypeError):
            _send_json(self, {"error": "Invalid id parameter"}, 400)
            return

        remove_account(account_id)
        _send_json(self, {"success": True})

    def log_message(self, *args):
        pass
