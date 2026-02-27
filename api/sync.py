"""
api/sync.py
POST /api/sync — Fetch emails from Gmail for all connected accounts, parse shipping info,
and store unique orders in the in-memory store. Uses only stdlib (urllib, json, re, base64).
"""
import base64
import json
import re
from datetime import datetime
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError


# ---------------------------------------------------------------------------
# CORS helpers
# ---------------------------------------------------------------------------
def _cors(h):
    h.send_header("Access-Control-Allow-Origin", "*")
    h.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
    h.send_header("Access-Control-Allow-Headers", "Content-Type")


def _send_json(h, data, status=200):
    body = json.dumps(data).encode("utf-8")
    h.send_response(status)
    h.send_header("Content-Type", "application/json")
    h.send_header("Content-Length", str(len(body)))
    _cors(h)
    h.end_headers()
    h.wfile.write(body)


# ---------------------------------------------------------------------------
# Retailer detection from sender domain
# ---------------------------------------------------------------------------
RETAILER_MAP = {
    "nike.com": "Nike",
    "apple.com": "Apple",
    "amazon.com": "Amazon",
    "amazon.co.uk": "Amazon",
    "stockx.com": "StockX",
    "bestbuy.com": "Best Buy",
    "target.com": "Target",
    "walmart.com": "Walmart",
    "ssense.com": "SSENSE",
    "lululemon.com": "Lululemon",
    "footlocker.com": "Foot Locker",
    "goat.com": "GOAT",
    "ebay.com": "eBay",
    "etsy.com": "Etsy",
    "nordstrom.com": "Nordstrom",
    "adidas.com": "Adidas",
    "newbalance.com": "New Balance",
    "zappos.com": "Zappos",
    "shopify.com": "Shopify Store",
    "gap.com": "Gap",
    "zara.com": "Zara",
    "hm.com": "H&M",
    "uniqlo.com": "Uniqlo",
    "patagonia.com": "Patagonia",
    "rei.com": "REI",
    "dickssportinggoods.com": "Dick's Sporting Goods",
    "costco.com": "Costco",
    "saks.com": "Saks Fifth Avenue",
    "bloomingdales.com": "Bloomingdale's",
    "macys.com": "Macy's",
    "neiman-marcus.com": "Neiman Marcus",
    "ups.com": "UPS",
    "fedex.com": "FedEx",
    "usps.com": "USPS",
    "dhl.com": "DHL",
}

CARRIER_MAP = {
    "ups.com": "UPS",
    "fedex.com": "FedEx",
    "usps.com": "USPS",
    "dhl.com": "DHL",
}

CARRIER_TRACKING_URLS = {
    "UPS": "https://www.ups.com/track?tracknum=",
    "FedEx": "https://www.fedex.com/fedextrack/?trknbr=",
    "USPS": "https://tools.usps.com/go/TrackConfirmAction?tLabels=",
    "DHL": "https://www.dhl.com/us-en/home/tracking.html?tracking-id=",
}

# ---------------------------------------------------------------------------
# Tracking number patterns
# ---------------------------------------------------------------------------
TRACKING_PATTERNS = [
    # UPS: 1Z + 16 alphanumeric
    ("UPS",   re.compile(r'\b(1Z[A-Z0-9]{16})\b')),
    # USPS: starts with 94/92/93 + 18-22 digits
    ("USPS",  re.compile(r'\b(9[234]\d{18,22})\b')),
    # USPS intelligent mail: ~20 digit numbers beginning with common prefixes
    ("USPS",  re.compile(r'\b(420\d{17,22})\b')),
    # FedEx: 12 or 15 digit all-numeric
    ("FedEx", re.compile(r'\b(\d{15})\b')),
    ("FedEx", re.compile(r'\b(\d{12})\b')),
    # DHL: 10 digit
    ("DHL",   re.compile(r'\b(\d{10})\b')),
]

# ---------------------------------------------------------------------------
# Delivery date patterns
# ---------------------------------------------------------------------------
DATE_PATTERNS = [
    re.compile(r'(?:estimated delivery|est\.?\s+delivery|arriving|arrives|deliver(?:ed)?\s+by|expected\s+delivery|delivery\s+date)[:\s]+([A-Za-z]+\.?\s+\d{1,2}(?:,\s+\d{4})?|\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4})', re.IGNORECASE),
    re.compile(r'\b((?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),\s+(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2})\b', re.IGNORECASE),
    re.compile(r'\b((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\.?\s+\d{1,2}(?:,\s+\d{4})?)\b', re.IGNORECASE),
]

MONTH_MAP = {
    'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'may': 5, 'jun': 6,
    'jul': 7, 'aug': 8, 'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12,
    'january': 1, 'february': 2, 'march': 3, 'april': 4,
    'june': 6, 'july': 7, 'august': 8, 'september': 9,
    'october': 10, 'november': 11, 'december': 12,
}

# ---------------------------------------------------------------------------
# Gmail search query
# ---------------------------------------------------------------------------
GMAIL_QUERY = (
    'subject:(shipped OR tracking OR delivery OR "order confirmed" OR '
    '"out for delivery" OR "has shipped" OR "is on its way" OR '
    '"order confirmation" OR "shipping confirmation" OR "your order")'
)

MAX_RESULTS = 50


# ---------------------------------------------------------------------------
# Token refresh
# ---------------------------------------------------------------------------
def refresh_access_token(refresh_token, client_id, client_secret):
    """Use a refresh token to get a new access token. Returns new access_token or None."""
    import os
    if not refresh_token:
        return None
    body = urlencode({
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    }).encode("utf-8")
    req = Request("https://oauth2.googleapis.com/token", data=body, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        resp = urlopen(req, timeout=10)
        data = json.loads(resp.read())
        return data.get("access_token")
    except Exception:
        return None


def gmail_get(path, access_token, params=None):
    """Make a GET request to the Gmail API. Returns (status_code, data)."""
    url = f"https://gmail.googleapis.com/gmail/v1{path}"
    if params:
        url += "?" + urlencode(params)
    req = Request(url)
    req.add_header("Authorization", f"Bearer {access_token}")
    try:
        resp = urlopen(req, timeout=15)
        return 200, json.loads(resp.read())
    except HTTPError as e:
        return e.code, {}
    except URLError:
        return 503, {}


# ---------------------------------------------------------------------------
# Email parsing helpers
# ---------------------------------------------------------------------------
def decode_body_part(part):
    """Decode a Gmail message part body to text."""
    data = part.get("body", {}).get("data", "")
    if not data:
        return ""
    try:
        decoded = base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="replace")
        return decoded
    except Exception:
        return ""


def extract_text_from_message(msg_payload):
    """Recursively extract plain-text and HTML body from a Gmail message payload."""
    text_plain = ""
    text_html = ""
    mime = msg_payload.get("mimeType", "")

    if mime == "text/plain":
        text_plain = decode_body_part(msg_payload)
    elif mime == "text/html":
        text_html = decode_body_part(msg_payload)
    elif "multipart" in mime:
        for part in msg_payload.get("parts", []):
            p, h = extract_text_from_message(part)
            text_plain += p
            text_html += h

    return text_plain, text_html


def strip_html(html):
    """Very simple HTML tag stripper."""
    return re.sub(r'<[^>]+>', ' ', html)


def detect_retailer(sender_email, sender_name=""):
    """Try to detect retailer from the sender's email domain."""
    if sender_email:
        domain = sender_email.lower().split("@")[-1] if "@" in sender_email else sender_email.lower()
        # Exact domain match
        if domain in RETAILER_MAP:
            return RETAILER_MAP[domain]
        # Partial domain match (subdomain support)
        for key, name in RETAILER_MAP.items():
            if domain.endswith("." + key) or domain == key:
                return name
    # Fall back to sender name
    if sender_name:
        cleaned = re.sub(r'["\']', '', sender_name).strip()
        if cleaned:
            return cleaned[:40]
    return "Unknown"


def detect_carrier_from_sender(sender_email):
    """Detect carrier if the email is from a carrier directly."""
    if sender_email:
        domain = sender_email.lower().split("@")[-1] if "@" in sender_email else ""
        for key, carrier in CARRIER_MAP.items():
            if domain.endswith(key) or domain == key:
                return carrier
    return None


def extract_tracking_number(text):
    """Find the first tracking number in text. Returns (carrier, number) or (None, None)."""
    for carrier, pattern in TRACKING_PATTERNS:
        m = pattern.search(text)
        if m:
            return carrier, m.group(1)
    return None, None


def extract_cost(text):
    """Find the first dollar amount that looks like an order total."""
    # Prefer "total: $X" or "order total $X" patterns
    total_pattern = re.compile(r'(?:order\s+total|subtotal|total)[:\s]+\$?([\d,]+\.?\d{0,2})', re.IGNORECASE)
    m = total_pattern.search(text)
    if m:
        try:
            return float(m.group(1).replace(",", ""))
        except ValueError:
            pass
    # Fallback: any dollar amount >= 1
    amounts = re.findall(r'\$([\d,]+\.\d{2})', text)
    valid = []
    for a in amounts:
        try:
            val = float(a.replace(",", ""))
            if 1.0 <= val <= 100000.0:
                valid.append(val)
        except ValueError:
            pass
    # Heuristic: use the largest amount up to $10k (likely order total, not shipping cost)
    if valid:
        candidates = [v for v in valid if v <= 10000.0]
        if candidates:
            return max(candidates)
        return max(valid)
    return 0.0


def extract_delivery_date(text):
    """Try to extract an estimated delivery date from text. Returns YYYY-MM-DD or None."""
    for pattern in DATE_PATTERNS:
        m = pattern.search(text)
        if m:
            raw = m.group(1).strip()
            # Try to parse various formats
            parsed = _parse_date_string(raw)
            if parsed:
                return parsed
    return None


def _parse_date_string(s):
    """Attempt to parse a loose date string to YYYY-MM-DD."""
    now = datetime.now()
    s = s.strip().rstrip(",")
    # Try common formats
    for fmt in ("%B %d, %Y", "%b %d, %Y", "%B %d", "%b %d", "%m/%d/%Y", "%m/%d/%y", "%m-%d-%Y"):
        try:
            d = datetime.strptime(s, fmt)
            if d.year == 1900:  # strptime default when year not in string
                d = d.replace(year=now.year)
                if d < now:
                    d = d.replace(year=now.year + 1)
            return d.strftime("%Y-%m-%d")
        except ValueError:
            pass
    # Try "Monday, January 15" style
    try:
        # strip day-of-week
        s2 = re.sub(r'^(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),?\s+', '', s, flags=re.IGNORECASE)
        d = datetime.strptime(s2.strip(), "%B %d")
        d = d.replace(year=now.year)
        if d.date() < now.date():
            d = d.replace(year=now.year + 1)
        return d.strftime("%Y-%m-%d")
    except ValueError:
        pass
    return None


def infer_status(subject, body_text, carrier, tracking_number):
    """Infer shipment status from email content."""
    combined = (subject + " " + body_text).lower()
    if any(k in combined for k in ("delivered", "has been delivered", "was delivered")):
        return "delivered"
    if any(k in combined for k in ("out for delivery", "out for del")):
        return "out_for_delivery"
    if any(k in combined for k in ("in transit", "on its way", "has shipped", "has been shipped", "tracking")):
        if tracking_number:
            return "in_transit"
        return "shipped"
    if any(k in combined for k in ("shipped", "dispatched", "on the way")):
        return "shipped"
    if any(k in combined for k in ("order confirmed", "order confirmation", "thank you for your order", "we've received your order")):
        return "processing"
    # If we have a tracking number but no other clues, assume in_transit
    if tracking_number:
        return "in_transit"
    return "processing"


def build_item_name(subject, retailer):
    """Extract a human-readable item name from the email subject."""
    # Remove common boilerplate prefixes
    cleaners = [
        r'^(?:your|re:|fw:|fwd:)\s+', r'^(?:from\s+)?[\w\s]+:\s+',
        r'order\s+(?:has\s+)?(?:shipped|confirmed|confirmation|update|status)',
        r'shipment\s+(?:update|notification|confirmation)',
        r'tracking\s+(?:information|update|number)',
        r'has\s+shipped', r'is\s+on\s+its\s+way',
        r'your\s+(?:order|package|shipment)',
        r'^re:\s+', r'^fwd?:\s+',
    ]
    name = subject
    for c in cleaners:
        name = re.sub(c, '', name, flags=re.IGNORECASE).strip()
    name = name.strip(" -:,.")
    if len(name) < 4:
        name = f"{retailer} Order"
    return name[:120]


def get_header(headers, name):
    """Get a specific header value from Gmail message headers list."""
    for h in headers:
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""


def parse_sender(from_header):
    """Parse 'Display Name <email@domain.com>' into (name, email)."""
    m = re.match(r'^(.+?)\s*<([^>]+)>', from_header.strip())
    if m:
        return m.group(1).strip().strip('"'), m.group(2).strip().lower()
    if "@" in from_header:
        return "", from_header.strip().lower()
    return from_header.strip(), ""


# ---------------------------------------------------------------------------
# Core sync logic per account
# ---------------------------------------------------------------------------
def sync_account(account):
    """Fetch and parse emails for one account. Returns list of new order dicts."""
    import os
    try:
        from api._store import orders as store_orders
    except ImportError:
        from _store import orders as store_orders

    client_id = os.environ.get("GOOGLE_CLIENT_ID", "")
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET", "")

    access_token = account["access_token"]
    new_orders = []

    # Existing tracking numbers for this account (deduplicate)
    existing_tracking = {
        o.get("tracking_number", "").lower()
        for o in store_orders.values()
        if o["account_id"] == account["id"] and o.get("tracking_number")
    }

    # 1. List messages
    status, data = gmail_get(
        "/users/me/messages",
        access_token,
        params={"q": GMAIL_QUERY, "maxResults": str(MAX_RESULTS)},
    )

    # Handle 401: try token refresh
    if status == 401:
        new_token = refresh_access_token(account.get("refresh_token"), client_id, client_secret)
        if new_token:
            account["access_token"] = new_token
            access_token = new_token
            status, data = gmail_get(
                "/users/me/messages",
                access_token,
                params={"q": GMAIL_QUERY, "maxResults": str(MAX_RESULTS)},
            )
        else:
            return new_orders  # Can't authenticate

    if status != 200:
        return new_orders

    messages = data.get("messages", [])

    for msg_ref in messages:
        msg_id = msg_ref.get("id")
        if not msg_id:
            continue

        # 2. Fetch full message
        msg_status, msg = gmail_get(
            f"/users/me/messages/{msg_id}",
            access_token,
            params={"format": "full"},
        )
        if msg_status == 401:
            new_token = refresh_access_token(account.get("refresh_token"), client_id, client_secret)
            if new_token:
                account["access_token"] = new_token
                access_token = new_token
                msg_status, msg = gmail_get(
                    f"/users/me/messages/{msg_id}",
                    access_token,
                    params={"format": "full"},
                )
        if msg_status != 200 or not msg:
            continue

        # 3. Extract headers
        headers = msg.get("payload", {}).get("headers", [])
        subject = get_header(headers, "subject")
        from_header = get_header(headers, "from")
        date_header = get_header(headers, "date")

        # 4. Parse sender
        sender_name, sender_email = parse_sender(from_header)
        retailer = detect_retailer(sender_email, sender_name)
        carrier_from_sender = detect_carrier_from_sender(sender_email)

        # 5. Extract body text
        payload = msg.get("payload", {})
        text_plain, text_html = extract_text_from_message(payload)
        body_text = text_plain if text_plain else strip_html(text_html)

        combined_text = subject + "\n" + body_text

        # 6. Find tracking number
        carrier, tracking_number = extract_tracking_number(combined_text)
        if not carrier and carrier_from_sender:
            carrier = carrier_from_sender

        # 7. Deduplicate by tracking number
        if tracking_number and tracking_number.lower() in existing_tracking:
            continue

        # 8. Extract cost
        cost = extract_cost(combined_text)

        # 9. Extract estimated delivery
        est_delivery = extract_delivery_date(combined_text)

        # 10. Parse order date from email date header
        order_date = _parse_email_date(date_header)

        # 11. Infer status
        status_val = infer_status(subject, body_text, carrier, tracking_number)

        # 12. Build item name
        item_name = build_item_name(subject, retailer)

        # 13. Build tracking URL
        if tracking_number and carrier:
            base_url = CARRIER_TRACKING_URLS.get(carrier, "")
            tracking_url = base_url + tracking_number if base_url else ""
        else:
            tracking_url = ""
            tracking_number = tracking_number or ""
            carrier = carrier or "Unknown"

        order_data = {
            "account_id": account["id"],
            "retailer": retailer,
            "item_name": item_name,
            "item_description": "",
            "item_image_url": "",
            "order_cost": cost,
            "order_date": order_date or datetime.now().strftime("%Y-%m-%d"),
            "shipping_carrier": carrier,
            "tracking_number": tracking_number,
            "tracking_url": tracking_url,
            "estimated_delivery": est_delivery or "",
            "status": status_val,
            "raw_email_subject": subject,
            "raw_email_date": date_header,
            "gmail_message_id": msg_id,
        }

        if tracking_number:
            existing_tracking.add(tracking_number.lower())

        new_orders.append(order_data)

    return new_orders


def _parse_email_date(date_str):
    """Parse RFC 2822 email date to YYYY-MM-DD."""
    if not date_str:
        return None
    # Strip timezone name in parens
    date_str = re.sub(r'\s+\([A-Z]+\)\s*$', '', date_str.strip())
    for fmt in (
        "%a, %d %b %Y %H:%M:%S %z",
        "%d %b %Y %H:%M:%S %z",
        "%a, %d %b %Y %H:%M:%S",
        "%d %b %Y %H:%M:%S",
    ):
        try:
            d = datetime.strptime(date_str, fmt)
            return d.strftime("%Y-%m-%d")
        except ValueError:
            pass
    return None


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------
class handler(BaseHTTPRequestHandler):

    def do_OPTIONS(self):
        self.send_response(204)
        _cors(self)
        self.end_headers()

    def do_POST(self):
        try:
            from api._store import accounts, add_order
        except ImportError:
            from _store import accounts, add_order

        if not accounts:
            _send_json(self, {"success": True, "synced": 0, "new_orders": 0, "message": "No accounts connected"})
            return

        now_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        total_new = 0

        for account in accounts.values():
            new_orders = []
            try:
                new_orders = sync_account(account)
            except Exception as e:
                pass  # Don't let one account failure block others

            for order_data in new_orders:
                add_order(**order_data)
                total_new += 1

            account["last_synced"] = now_ts

        _send_json(self, {
            "success": True,
            "synced": len(accounts),
            "new_orders": total_new,
            "synced_at": now_ts,
        })

    def log_message(self, *args):
        pass
