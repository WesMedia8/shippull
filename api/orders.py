"""
api/orders.py
GET /api/orders — List orders with optional filtering and sorting.

Query params:
  status      — filter by status value
  retailer    — filter by retailer name
  search      — text search across item_name, retailer, tracking_number
  sort        — newest | status | eta | cost_desc
  account_id  — filter by account id
"""
import json
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs


STATUS_ORDER = ["processing", "shipped", "in_transit", "out_for_delivery", "delivered"]


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


def _p(params, key, default=""):
    vals = params.get(key, [default])
    return vals[0] if vals else default


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

        results = list(orders.values())

        # -- Filters --
        status_filter = _p(params, "status")
        if status_filter:
            results = [o for o in results if o.get("status") == status_filter]

        retailer_filter = _p(params, "retailer")
        if retailer_filter:
            results = [o for o in results if o.get("retailer") == retailer_filter]

        account_id_filter = _p(params, "account_id")
        if account_id_filter:
            try:
                aid = int(account_id_filter)
                results = [o for o in results if o.get("account_id") == aid]
            except ValueError:
                pass

        search = _p(params, "search").strip().lower()
        if search:
            results = [
                o for o in results
                if search in (o.get("item_name") or "").lower()
                or search in (o.get("retailer") or "").lower()
                or search in (o.get("tracking_number") or "").lower()
                or search in (o.get("raw_email_subject") or "").lower()
            ]

        # -- Enrich with account info --
        enriched = []
        for o in results:
            acct = accounts.get(o["account_id"], {})
            enriched.append({
                **{k: v for k, v in o.items() if k not in ("access_token", "refresh_token")},
                "account_email": acct.get("email", ""),
                "account_color": acct.get("avatar_color", "#3B82F6"),
                "account_display_name": acct.get("display_name", ""),
            })

        # -- Sort --
        sort = _p(params, "sort", "newest")
        if sort == "newest":
            enriched.sort(key=lambda o: (o.get("order_date", ""), o.get("id", 0)), reverse=True)
        elif sort == "status":
            enriched.sort(key=lambda o: (
                STATUS_ORDER.index(o.get("status")) if o.get("status") in STATUS_ORDER else 99,
                o.get("order_date", ""),
            ))
        elif sort == "eta":
            enriched.sort(key=lambda o: (o.get("estimated_delivery") or "9999-99-99"))
        elif sort == "cost_desc":
            enriched.sort(key=lambda o: (o.get("order_cost") or 0.0), reverse=True)
        else:
            enriched.sort(key=lambda o: (o.get("order_date", ""), o.get("id", 0)), reverse=True)

        _send_json(self, enriched)

    def log_message(self, *args):
        pass
