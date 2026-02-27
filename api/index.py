#!/usr/bin/env python3
"""
ShipPull — Vercel Serverless API
In-memory store (resets on cold starts). For demo/MVP use.
"""

import json
import random
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

# ─────────────────────────────────────────────
# Module-level in-memory state
# Persists across warm invocations within the same container instance.
# Resets on cold starts / new deployments.
# ─────────────────────────────────────────────
_accounts = []
_orders = []
_next_account_id = 1
_next_order_id = 1


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

def generate_tracking(carrier):
    carriers = {
        "UPS": (
            "1Z" + "".join(random.choices("0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ", k=16)),
            "https://www.ups.com/track?tracknum=",
        ),
        "FedEx": (
            "".join(random.choices("0123456789", k=15)),
            "https://www.fedex.com/fedextrack/?trknbr=",
        ),
        "USPS": (
            "94" + "".join(random.choices("0123456789", k=20)),
            "https://tools.usps.com/go/TrackConfirmAction?tLabels=",
        ),
        "DHL": (
            "".join(random.choices("0123456789", k=10)),
            "https://www.dhl.com/us-en/home/tracking.html?tracking-id=",
        ),
    }
    tracking_num, base_url = carriers.get(carrier, carriers["USPS"])
    return tracking_num, base_url + tracking_num


def build_sample_orders(account_id):
    now = datetime.now()
    templates = [
        {
            "retailer": "Nike",
            "item_name": "Air Jordan 1 Retro High OG 'Chicago'",
            "item_description": "Men's Shoes - Size 10.5 - White/Black/Varsity Red",
            "item_image_url": "https://static.nike.com/a/images/t_PDP_1728_v1/f_auto,q_auto:eco/0c8e9400-600d-4623-a6eb-7a9038f6e882/WMNS+AIR+JORDAN+1+RETRO+HIGH+OG.png",
            "order_cost": 180.00,
            "order_date": (now - timedelta(days=2)).strftime("%Y-%m-%d"),
            "shipping_carrier": "UPS",
            "status": "in_transit",
            "estimated_delivery": (now + timedelta(days=2)).strftime("%Y-%m-%d"),
            "raw_email_subject": "Your Nike Order Has Shipped!",
        },
        {
            "retailer": "Apple",
            "item_name": "AirPods Pro (2nd Gen) with USB-C",
            "item_description": "Active Noise Cancellation, Adaptive Audio, Personalized Spatial Audio",
            "item_image_url": "https://store.storeimages.cdn-apple.com/4982/as-images.apple.com/is/airpods-pro-2-hero-select-202409?wid=400&hei=400&fmt=png-alpha",
            "order_cost": 249.00,
            "order_date": (now - timedelta(days=5)).strftime("%Y-%m-%d"),
            "shipping_carrier": "FedEx",
            "status": "delivered",
            "estimated_delivery": (now - timedelta(days=1)).strftime("%Y-%m-%d"),
            "raw_email_subject": "Your Apple Store order has shipped",
        },
        {
            "retailer": "Amazon",
            "item_name": "Sony WH-1000XM5 Headphones",
            "item_description": "Wireless Noise Canceling Overhead Headphones - Black",
            "item_image_url": "https://m.media-amazon.com/images/I/51aXvjzcukL._AC_SL1500_.jpg",
            "order_cost": 328.00,
            "order_date": (now - timedelta(days=1)).strftime("%Y-%m-%d"),
            "shipping_carrier": "USPS",
            "status": "processing",
            "estimated_delivery": (now + timedelta(days=5)).strftime("%Y-%m-%d"),
            "raw_email_subject": "Your Amazon.com order confirmation",
        },
        {
            "retailer": "StockX",
            "item_name": "adidas Yeezy Boost 350 V2 'Onyx'",
            "item_description": "Men's Size 11 - Deadstock - Verified Authentic",
            "item_image_url": "https://images.stockx.com/images/adidas-Yeezy-Boost-350-V2-Onyx-Product.jpg?fit=fill&bg=FFFFFF&w=700",
            "order_cost": 320.00,
            "order_date": (now - timedelta(days=4)).strftime("%Y-%m-%d"),
            "shipping_carrier": "UPS",
            "status": "in_transit",
            "estimated_delivery": (now + timedelta(days=1)).strftime("%Y-%m-%d"),
            "raw_email_subject": "StockX: Your item has shipped",
        },
        {
            "retailer": "Best Buy",
            "item_name": "PS5 DualSense Wireless Controller",
            "item_description": "Midnight Black - Haptic Feedback & Adaptive Triggers",
            "item_image_url": "https://pisces.bbystatic.com/image2/BestBuy_US/images/products/6430/6430163_sd.jpg",
            "order_cost": 69.99,
            "order_date": (now - timedelta(days=7)).strftime("%Y-%m-%d"),
            "shipping_carrier": "FedEx",
            "status": "delivered",
            "estimated_delivery": (now - timedelta(days=3)).strftime("%Y-%m-%d"),
            "raw_email_subject": "Your Best Buy order has been delivered",
        },
        {
            "retailer": "Target",
            "item_name": "Pokemon TCG Scarlet & Violet Elite Trainer Box",
            "item_description": "9 Booster Packs, 1 Full-Art Promo Card, Premium Accessories",
            "item_image_url": "https://target.scene7.com/is/image/Target/GUEST_d5fb7a81-e2f1-4b7f-a5a5-5d4cf37a6b35?wid=400",
            "order_cost": 44.99,
            "order_date": (now - timedelta(days=3)).strftime("%Y-%m-%d"),
            "shipping_carrier": "USPS",
            "status": "out_for_delivery",
            "estimated_delivery": now.strftime("%Y-%m-%d"),
            "raw_email_subject": "Your Target order is out for delivery!",
        },
        {
            "retailer": "Walmart",
            "item_name": "Nintendo Switch OLED Model",
            "item_description": "White Joy-Con - 7-inch OLED Screen - 64GB Storage",
            "item_image_url": "https://i5.walmartimages.com/seo/Nintendo-Switch-OLED-Model-w-White-Joy-Con_0618a22f-3e03-41c4-8fb0-fc1e3da1e97e.e9c11d01ebde2032942ada0e4a7a4e57.jpeg?odnHeight=640&odnWidth=640",
            "order_cost": 349.99,
            "order_date": (now - timedelta(days=6)).strftime("%Y-%m-%d"),
            "shipping_carrier": "FedEx",
            "status": "delivered",
            "estimated_delivery": (now - timedelta(days=2)).strftime("%Y-%m-%d"),
            "raw_email_subject": "Walmart: Your order has been delivered",
        },
        {
            "retailer": "SSENSE",
            "item_name": "Acne Studios Canada Narrow Scarf",
            "item_description": "Black Wool Scarf - 200cm x 45cm - Made in Italy",
            "item_image_url": "https://img.ssensemedia.com/images/242129M150009_1/acne-studios-black-canada-narrow-scarf.jpg",
            "order_cost": 220.00,
            "order_date": (now - timedelta(days=3)).strftime("%Y-%m-%d"),
            "shipping_carrier": "DHL",
            "status": "shipped",
            "estimated_delivery": (now + timedelta(days=4)).strftime("%Y-%m-%d"),
            "raw_email_subject": "SSENSE: Your order has been shipped",
        },
        {
            "retailer": "Lululemon",
            "item_name": 'ABC Jogger 30" *Warpstreme',
            "item_description": "Men's Joggers - True Navy - Size M - Anti-Ball Crushing",
            "item_image_url": "https://images.lululemon.com/is/image/lululemon/LM5ATAS_031382_1?wid=400",
            "order_cost": 128.00,
            "order_date": (now - timedelta(days=1)).strftime("%Y-%m-%d"),
            "shipping_carrier": "UPS",
            "status": "processing",
            "estimated_delivery": (now + timedelta(days=6)).strftime("%Y-%m-%d"),
            "raw_email_subject": "Lululemon: Order Confirmation",
        },
        {
            "retailer": "Foot Locker",
            "item_name": "New Balance 550 White Green",
            "item_description": "Men's Size 10 - Leather Upper - White/Nori Green",
            "item_image_url": "https://images.footlocker.com/is/image/EBFL2/BC550WT1_a1?wid=400",
            "order_cost": 110.00,
            "order_date": (now - timedelta(days=8)).strftime("%Y-%m-%d"),
            "shipping_carrier": "USPS",
            "status": "delivered",
            "estimated_delivery": (now - timedelta(days=4)).strftime("%Y-%m-%d"),
            "raw_email_subject": "Foot Locker: Your order has arrived!",
        },
        {
            "retailer": "GOAT",
            "item_name": "Travis Scott x Nike Air Force 1 Low 'Cactus Jack'",
            "item_description": "Men's Size 10.5 - Verified Authentic - New/Deadstock",
            "item_image_url": "https://image.goat.com/transform/v1/attachments/product_template_pictures/images/092/606/006/original/1286855_00.png.png?width=400",
            "order_cost": 450.00,
            "order_date": (now - timedelta(days=2)).strftime("%Y-%m-%d"),
            "shipping_carrier": "UPS",
            "status": "in_transit",
            "estimated_delivery": (now + timedelta(days=3)).strftime("%Y-%m-%d"),
            "raw_email_subject": "GOAT: Your order is on its way",
        },
        {
            "retailer": "eBay",
            "item_name": "Vintage 1997 Pokemon Base Set Booster Pack",
            "item_description": "Sealed - Charizard Art - WOTC Original - PSA Ready",
            "item_image_url": "https://i.ebayimg.com/images/g/VR4AAOSwwbFk2uBN/s-l400.jpg",
            "order_cost": 289.99,
            "order_date": (now - timedelta(days=5)).strftime("%Y-%m-%d"),
            "shipping_carrier": "USPS",
            "status": "shipped",
            "estimated_delivery": (now + timedelta(days=2)).strftime("%Y-%m-%d"),
            "raw_email_subject": "eBay: Your item has shipped!",
        },
        {
            "retailer": "Amazon",
            "item_name": "Anker 737 Power Bank (PowerCore 24K)",
            "item_description": "24,000mAh - 140W Output - USB-C Fast Charging",
            "item_image_url": "https://m.media-amazon.com/images/I/61Gxu4gEiIL._AC_SL1500_.jpg",
            "order_cost": 109.99,
            "order_date": (now - timedelta(days=2)).strftime("%Y-%m-%d"),
            "shipping_carrier": "USPS",
            "status": "in_transit",
            "estimated_delivery": (now + timedelta(days=1)).strftime("%Y-%m-%d"),
            "raw_email_subject": "Your Amazon.com order has shipped",
        },
        {
            "retailer": "Nike",
            "item_name": "Nike Dunk Low 'Panda' 2.0",
            "item_description": "Men's Shoes - Size 10 - White/Black",
            "item_image_url": "https://static.nike.com/a/images/t_PDP_1728_v1/f_auto,q_auto:eco/d4b1b1b1-4b3b-4b3b-8b3b-4b3b4b3b4b3b/NIKE+DUNK+LOW+RETRO.png",
            "order_cost": 115.00,
            "order_date": now.strftime("%Y-%m-%d"),
            "shipping_carrier": "FedEx",
            "status": "processing",
            "estimated_delivery": (now + timedelta(days=7)).strftime("%Y-%m-%d"),
            "raw_email_subject": "Nike: Order Confirmed",
        },
    ]

    orders = []
    for tmpl in templates:
        tracking_num, tracking_url = generate_tracking(tmpl["shipping_carrier"])
        orders.append({
            "account_id": account_id,
            "retailer": tmpl["retailer"],
            "item_name": tmpl["item_name"],
            "item_description": tmpl["item_description"],
            "item_image_url": tmpl["item_image_url"],
            "order_cost": tmpl["order_cost"],
            "order_date": tmpl["order_date"],
            "shipping_carrier": tmpl["shipping_carrier"],
            "tracking_number": tracking_num,
            "tracking_url": tracking_url,
            "estimated_delivery": tmpl["estimated_delivery"],
            "status": tmpl["status"],
            "raw_email_subject": tmpl["raw_email_subject"],
            "raw_email_date": tmpl["order_date"],
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        })
    return orders


def cors_headers(h):
    h.send_header("Access-Control-Allow-Origin", "*")
    h.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
    h.send_header("Access-Control-Allow-Headers", "Content-Type")


def send_json(h, data, status=200):
    body = json.dumps(data).encode("utf-8")
    h.send_response(status)
    h.send_header("Content-Type", "application/json")
    h.send_header("Content-Length", str(len(body)))
    cors_headers(h)
    h.end_headers()
    h.wfile.write(body)


# ─────────────────────────────────────────────
# Vercel serverless handler
# ─────────────────────────────────────────────

class handler(BaseHTTPRequestHandler):

    def log_message(self, format, *args):
        pass  # Suppress default access log noise in Vercel logs

    def do_OPTIONS(self):
        self.send_response(204)
        cors_headers(self)
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)

        def p(key, default=""):
            vals = params.get(key, [default])
            return vals[0] if vals else default

        action = p("action")

        # ── GET /api?action=accounts ──────────────────
        if action == "accounts":
            send_json(self, _accounts)

        # ── GET /api?action=orders ────────────────────
        elif action == "orders":
            results = list(_orders)

            status_filter = p("status")
            if status_filter:
                results = [o for o in results if o["status"] == status_filter]

            retailer_filter = p("retailer")
            if retailer_filter:
                results = [o for o in results if o["retailer"] == retailer_filter]

            account_id_filter = p("account_id")
            if account_id_filter:
                try:
                    aid = int(account_id_filter)
                    results = [o for o in results if o["account_id"] == aid]
                except ValueError:
                    pass

            search = p("search").lower()
            if search:
                results = [
                    o for o in results
                    if search in o["item_name"].lower()
                    or search in o["retailer"].lower()
                    or search in o["tracking_number"].lower()
                ]

            # Enrich with account info
            account_map = {a["id"]: a for a in _accounts}
            enriched = []
            for o in results:
                acct = account_map.get(o["account_id"], {})
                enriched.append({
                    **o,
                    "account_email": acct.get("email", ""),
                    "account_color": acct.get("avatar_color", "#3B82F6"),
                })

            sort = p("sort", "newest")
            status_order = ["processing", "shipped", "in_transit", "out_for_delivery", "delivered"]
            if sort == "newest":
                enriched.sort(key=lambda o: (o["order_date"], o["id"]), reverse=True)
            elif sort == "status":
                enriched.sort(key=lambda o: (
                    status_order.index(o["status"]) if o["status"] in status_order else 99,
                    o["order_date"],
                ))
            elif sort == "eta":
                enriched.sort(key=lambda o: o["estimated_delivery"])
            elif sort == "cost_desc":
                enriched.sort(key=lambda o: o["order_cost"], reverse=True)
            else:
                enriched.sort(key=lambda o: o["order_date"], reverse=True)

            send_json(self, enriched)

        # ── GET /api?action=order&id=N ────────────────
        elif action == "order":
            try:
                oid = int(p("id"))
            except (ValueError, TypeError):
                send_json(self, {"error": "Invalid order id"}, 400)
                return

            order = next((o for o in _orders if o["id"] == oid), None)
            if not order:
                send_json(self, {"error": "Order not found"}, 404)
                return

            account_map = {a["id"]: a for a in _accounts}
            acct = account_map.get(order["account_id"], {})
            send_json(self, {
                **order,
                "account_email": acct.get("email", ""),
                "account_color": acct.get("avatar_color", "#3B82F6"),
                "account_display_name": acct.get("display_name", ""),
            })

        # ── GET /api?action=stats ─────────────────────
        elif action == "stats":
            total = len(_orders)
            in_transit = sum(
                1 for o in _orders
                if o["status"] in ("in_transit", "shipped", "out_for_delivery")
            )
            delivered = sum(1 for o in _orders if o["status"] == "delivered")
            processing = sum(1 for o in _orders if o["status"] == "processing")
            total_spent = sum(o["order_cost"] for o in _orders)
            retailers = sorted(set(o["retailer"] for o in _orders))

            send_json(self, {
                "total": total,
                "in_transit": in_transit,
                "delivered": delivered,
                "processing": processing,
                "total_spent": round(total_spent, 2),
                "retailers": retailers,
            })

        else:
            send_json(self, {"error": "Unknown action", "action": action, "method": "GET"}, 404)

    def do_POST(self):
        global _next_account_id, _next_order_id

        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)

        def p(key, default=""):
            vals = params.get(key, [default])
            return vals[0] if vals else default

        action = p("action")

        content_length = int(self.headers.get("Content-Length", 0))
        body_bytes = self.rfile.read(content_length) if content_length else b"{}"
        try:
            body = json.loads(body_bytes)
        except json.JSONDecodeError:
            body = {}

        # ── POST /api?action=add_account ──────────────
        if action == "add_account":
            email = body.get("email", "").strip().lower()
            if not email:
                send_json(self, {"error": "Email is required"}, 400)
                return

            if any(a["email"] == email for a in _accounts):
                send_json(self, {"error": "Account already connected"}, 409)
                return

            colors = [
                "#3B82F6", "#10B981", "#F59E0B", "#EF4444",
                "#8B5CF6", "#EC4899", "#06B6D4", "#F97316",
            ]
            avatar_color = random.choice(colors)
            display_name = email.split("@")[0].replace(".", " ").title()
            now_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            account = {
                "id": _next_account_id,
                "email": email,
                "display_name": display_name,
                "avatar_color": avatar_color,
                "connected_at": now_ts,
                "last_synced": now_ts,
            }
            _accounts.append(account)
            _next_account_id += 1

            # Seed orders for this account
            for order_tmpl in build_sample_orders(account["id"]):
                order = {**order_tmpl, "id": _next_order_id}
                _orders.append(order)
                _next_order_id += 1

            send_json(self, account, 201)

        # ── POST /api?action=sync ─────────────────────
        elif action == "sync":
            now_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            for a in _accounts:
                a["last_synced"] = now_ts
            send_json(self, {"success": True, "synced_at": now_ts})

        else:
            send_json(self, {"error": "Unknown action", "action": action, "method": "POST"}, 404)

    def do_DELETE(self):
        global _accounts, _orders

        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)

        def p(key, default=""):
            vals = params.get(key, [default])
            return vals[0] if vals else default

        action = p("action")

        # ── DELETE /api?action=remove_account&id=N ────
        if action == "remove_account":
            try:
                account_id = int(p("id"))
            except (ValueError, TypeError):
                send_json(self, {"error": "Invalid account id"}, 400)
                return

            _accounts[:] = [a for a in _accounts if a["id"] != account_id]
            _orders[:] = [o for o in _orders if o["account_id"] != account_id]
            send_json(self, {"success": True})

        else:
            send_json(self, {"error": "Unknown action", "action": action, "method": "DELETE"}, 404)
