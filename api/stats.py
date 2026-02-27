"""
api/stats.py
GET /api/stats — Return aggregate statistics for the dashboard.
"""
import json
from http.server import BaseHTTPRequestHandler


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
            from api._store import orders
        except ImportError:
            from _store import orders

        order_list = list(orders.values())
        total = len(order_list)
        in_transit = sum(
            1 for o in order_list
            if o.get("status") in ("in_transit", "shipped", "out_for_delivery")
        )
        delivered = sum(1 for o in order_list if o.get("status") == "delivered")
        processing = sum(1 for o in order_list if o.get("status") == "processing")
        total_spent = sum((o.get("order_cost") or 0.0) for o in order_list)
        retailers = sorted(set(o.get("retailer", "") for o in order_list if o.get("retailer")))
        carriers = sorted(set(o.get("shipping_carrier", "") for o in order_list if o.get("shipping_carrier")))

        _send_json(self, {
            "total": total,
            "in_transit": in_transit,
            "delivered": delivered,
            "processing": processing,
            "total_spent": round(total_spent, 2),
            "retailers": retailers,
            "carriers": carriers,
        })

    def log_message(self, *args):
        pass
