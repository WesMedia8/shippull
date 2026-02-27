"""
api/order.py
GET /api/order?id=N — Return a single order's details, enriched with account info.
"""
import json
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs


def _cors(h):
    h.send_header("Access-Control-Allow-Origin", "*")
    h.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
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
            from api._store import orders, accounts
        except ImportError:
            from _store import orders, accounts

        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        id_vals = params.get("id", [])

        if not id_vals:
            _send_json(self, {"error": "Missing id parameter"}, 400)
            return

        try:
            oid = int(id_vals[0])
        except (ValueError, TypeError):
            _send_json(self, {"error": "Invalid id parameter"}, 400)
            return

        order = orders.get(oid)
        if not order:
            _send_json(self, {"error": "Order not found"}, 404)
            return

        acct = accounts.get(order["account_id"], {})
        result = {
            **{k: v for k, v in order.items() if k not in ("access_token", "refresh_token")},
            "account_email": acct.get("email", ""),
            "account_color": acct.get("avatar_color", "#3B82F6"),
            "account_display_name": acct.get("display_name", ""),
        }
        _send_json(self, result)

    def log_message(self, *args):
        pass
