"""
api/sync.py
POST /api/sync — Stateless Gmail sync endpoint.

Accepts a JSON body: {"accounts": [{"email", "access_token", "refresh_token"}]}
Optionally: {"page_token": "..."} for pagination.

For each account, fetches Gmail emails matching the shipping query,
parses them, and returns all parsed orders as JSON.

NO server-side storage. All state lives in the browser (localStorage).
Token refreshes are returned in the response so the frontend can update
its stored tokens.
"""
import base64
import json
import os
import re
import sys
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
# Blocklisted senders — these are NOT real orders/shipments
# Subscriptions, streaming, newsletters, marketing, digital-only services
# ---------------------------------------------------------------------------
BLOCKED_DOMAINS = {
    # Digital/streaming services
    "audible.com", "audible.co.uk", "audible.de",
    "netflix.com", "spotify.com", "hulu.com",
    "disneyplus.com", "hbomax.com", "max.com",
    "youtube.com", "google.com", "play.google.com",
    "twitch.tv", "crunchyroll.com",
    # Social media
    "facebook.com", "facebookmail.com", "meta.com",
    "instagram.com", "twitter.com", "x.com",
    "linkedin.com", "tiktok.com", "pinterest.com",
    # Email/productivity
    "gmail.com", "outlook.com", "yahoo.com",
    "slack.com", "zoom.us", "notion.so",
    # Food delivery (not reseller items)
    "doordash.com", "ubereats.com", "grubhub.com",
    "postmates.com", "instacart.com",
    # Ride services
    "uber.com", "lyft.com",
    # Banking/payments
    "paypal.com", "venmo.com", "cashapp.com",
    "chase.com", "bankofamerica.com", "wellsfargo.com",
    # Software/SaaS
    "github.com", "vercel.com", "heroku.com",
    "amazonaws.com", "digitalocean.com",
    # Gaming
    "steampowered.com", "epicgames.com", "playstation.com",
    "xbox.com", "ea.com",
    # News/media
    "medium.com", "substack.com", "nytimes.com",
    "washingtonpost.com",
}

# Blocked sender keywords — if sender email or name contains these
BLOCKED_SENDER_KEYWORDS = {
    "newsletter", "noreply-marketing", "promo", "marketing",
    "campaign", "digest", "weekly", "daily-digest",
}

# Brands that send marketing emails disguised as shipping/delivery notifications
# These get caught by the is_real_order scoring too, but blocking outright is safer
MARKETING_BRAND_DOMAINS = {
    "fearofgod.com", "essentials.com",
    "jfrnd.com", "jiberish.com",
    "gruns.com", "getgruns.com",
}

# ---------------------------------------------------------------------------
# Marketing / promo detection — subjects that look like orders but aren't
# ---------------------------------------------------------------------------
MARKETING_SUBJECT_PATTERNS = [
    # "Last call" / urgency marketing
    re.compile(r'last\s+call', re.IGNORECASE),
    # "New" collection/arrivals/playlist
    re.compile(r'new\s+(?:arrivals?|collection|season|drop|release|playlist|episode)', re.IGNORECASE),
    # Sales/discounts
    re.compile(r'\b(?:sale|% off|discount|coupon|promo code|free shipping|flash sale|clearance)\b', re.IGNORECASE),
    # Newsletters
    re.compile(r'\b(?:newsletter|weekly|digest|roundup|picks for you|recommended)\b', re.IGNORECASE),
    # "Shop now" / "Buy now"
    re.compile(r'\b(?:shop now|buy now|limited edition|exclusive access|early access|just dropped)\b', re.IGNORECASE),
    # Fear of God / brand "delivery" marketing (new product line)
    re.compile(r'\b(?:introducing|launching|collection|lookbook|editorial|campaign)\b', re.IGNORECASE),
    # Restock alerts
    re.compile(r'\b(?:back in stock|restock|coming soon|waitlist|notify me)\b', re.IGNORECASE),
    # Review requests
    re.compile(r'\b(?:review your|rate your|how was your|feedback|survey)\b', re.IGNORECASE),
    # Rewards / loyalty
    re.compile(r'\b(?:rewards?|loyalty|points|member|earn|redeem)\b', re.IGNORECASE),
]

# Strong positive signals — these indicate a REAL transactional email
ORDER_SIGNAL_PATTERNS = [
    re.compile(r'order\s*#\s*\d', re.IGNORECASE),                          # order #12345
    re.compile(r'order\s+(?:number|id|no\.?)\s*:?\s*\d', re.IGNORECASE),   # order number: 123
    re.compile(r'\btracking\s*(?:#|number|:)\s*\S', re.IGNORECASE),        # tracking #...
    re.compile(r'\b1Z[A-Z0-9]{16}\b'),                                     # UPS tracking
    re.compile(r'\b9[234]\d{18,22}\b'),                                    # USPS tracking
    re.compile(r'\bTBA\d{10,}\b'),                                         # Amazon tracking
    re.compile(r'\bitem(?:s)?\s+shipped\b', re.IGNORECASE),                 # items shipped
    re.compile(r'\byour\s+(?:order|package|shipment)\s+(?:has|is|was)\b', re.IGNORECASE),
    re.compile(r'\bshipping\s+(?:label|confirmation)\b', re.IGNORECASE),
    re.compile(r'\best(?:imated)?\s+delivery\b', re.IGNORECASE),           # estimated delivery
    re.compile(r'\b(?:out for|scheduled for)\s+delivery\b', re.IGNORECASE),
    re.compile(r'\bdelivered\s+(?:to|at|on)\b', re.IGNORECASE),            # delivered to your door
    re.compile(r'\b(?:ups|fedex|usps|dhl|ontrac)\b', re.IGNORECASE),       # carrier name
    re.compile(r'\$\d+\.\d{2}', re.IGNORECASE),                            # dollar amount
]

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
    # Amazon TBA tracking
    ("Amazon", re.compile(r'\b(TBA\d{10,})\b')),
    # OnTrac tracking
    ("OnTrac", re.compile(r'\b([CD]\d{14})\b')),
    # FedEx: 15 digit all-numeric — require nearby tracking keywords
    ("FedEx", re.compile(r'(?i)(?:tracking|track|fedex|shipment|ship).{0,200}\b(\d{15})\b')),
    # FedEx: 12 digit all-numeric — require nearby tracking keywords
    ("FedEx", re.compile(r'(?i)(?:tracking|track|fedex|shipment|ship).{0,200}\b(\d{12})\b')),
    # DHL: full express format JD + digits, or 10 digit only when DHL keyword is nearby
    ("DHL",   re.compile(r'\b(JD\d{18})\b')),
]

# ---------------------------------------------------------------------------
# Delivery date patterns
# ---------------------------------------------------------------------------
DATE_PATTERNS = [
    re.compile(
        r'(?:estimated delivery|est\.?\s+delivery|arriving|arrives|deliver(?:ed)?\s+by|'
        r'expected\s+delivery|delivery\s+date)[:\s]+'
        r'([A-Za-z]+\.?\s+\d{1,2}(?:,\s+\d{4})?|\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4})',
        re.IGNORECASE
    ),
    re.compile(
        r'\b((?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),\s+'
        r'(?:January|February|March|April|May|June|July|August|September|October|November|December)'
        r'\s+\d{1,2})\b',
        re.IGNORECASE
    ),
    re.compile(
        r'\b((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\.?\s+\d{1,2}(?:,\s+\d{4})?)\b',
        re.IGNORECASE
    ),
]

# ---------------------------------------------------------------------------
# Gmail search query — focused on transactional shipping emails
# Using category:updates to prefer transactional over promotional
# ---------------------------------------------------------------------------
GMAIL_QUERY = (
    '(subject:("has shipped" OR "is on its way" OR "out for delivery" '
    'OR "shipping confirmation" OR "shipment notification" OR "track your" '
    'OR "tracking number" OR "order confirmed" OR "order shipped") '
    'OR from:(ups.com OR fedex.com OR usps.com OR dhl.com)) '
    '-category:promotions -category:social '
    '-subject:("sale" OR "% off" OR "newsletter" OR "new arrivals" OR "shop now")'
)

MAX_RESULTS = 100


# ---------------------------------------------------------------------------
# Token refresh
# ---------------------------------------------------------------------------
def refresh_access_token(refresh_token, client_id, client_secret):
    """Use a refresh token to get a new access token. Returns new access_token or None."""
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
        cleaned = re.sub(r'["\u2018\u2019\u201c\u201d\'`]', '', sender_name).strip()
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


def _extract_url_param(url, param_names):
    """Extract a query parameter value from a URL string."""
    for param in param_names:
        m = re.search(r'(?:[?&])' + re.escape(param) + r'=([^&\s"]+)', url, re.IGNORECASE)
        if m:
            return m.group(1)
    return None


def _clean_tracking_number(raw):
    """Strip URL-encoding and whitespace from a candidate tracking number."""
    if not raw:
        return ""
    raw = raw.replace("%20", " ").replace("+", " ").strip()
    return raw


def extract_tracking_from_html(html):
    """
    Parse <a href> tags from raw HTML email to extract carrier tracking URLs.
    Returns (carrier, tracking_number, tracking_url) or (None, None, None).
    """
    if not html:
        return None, None, None

    anchor_pattern = re.compile(
        r'<a[^>]+href=["\']([^"\'\s>]+)["\'][^>]*>(.*?)</a>',
        re.IGNORECASE | re.DOTALL
    )
    anchor_pattern2 = re.compile(
        r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
        re.IGNORECASE | re.DOTALL
    )

    anchors = []
    for m in anchor_pattern.finditer(html):
        href = m.group(1).strip()
        text = re.sub(r'<[^>]+>', '', m.group(2)).strip()
        anchors.append((href, text))

    if not anchors:
        for m in anchor_pattern2.finditer(html):
            href = m.group(1).strip()
            text = re.sub(r'<[^>]+>', '', m.group(2)).strip()
            anchors.append((href, text))

    for href, link_text in anchors:
        href_lower = href.lower()

        # UPS
        if 'ups.com/track' in href_lower or 'ups.com/webtracking' in href_lower:
            num = _extract_url_param(href, ['trackNums', 'tracknum', 'InquiryNumber', 'track'])
            if not num:
                m2 = re.search(r'(1Z[A-Z0-9]{16})', href, re.IGNORECASE)
                num = m2.group(1) if m2 else None
            if not num:
                m2 = re.search(r'\b(1Z[A-Z0-9]{16})\b', link_text, re.IGNORECASE)
                num = m2.group(1) if m2 else None
            if num:
                return "UPS", _clean_tracking_number(num), href

        # FedEx
        elif 'fedex.com/fedextrack' in href_lower or 'fedex.com/apps/fedextrack' in href_lower:
            num = _extract_url_param(href, ['trknbr', 'trackingnumber', 'tracknum', 'data'])
            if not num:
                m2 = re.search(r'\b(\d{12}|\d{15})\b', href)
                num = m2.group(1) if m2 else None
            if not num:
                m2 = re.search(r'\b(\d{12}|\d{15})\b', link_text)
                num = m2.group(1) if m2 else None
            if num:
                return "FedEx", _clean_tracking_number(num), href

        # USPS
        elif 'tools.usps.com' in href_lower or 'usps.com/go/track' in href_lower or \
             'usps.com/go/TrackConfirm' in href:
            num = _extract_url_param(href, ['tLabels', 'label', 'trackId', 'labelNumber'])
            if not num:
                m2 = re.search(r'\b(9[234]\d{18,22}|420\d{17,22})\b', href)
                num = m2.group(1) if m2 else None
            if not num:
                m2 = re.search(r'\b(9[234]\d{18,22}|420\d{17,22})\b', link_text)
                num = m2.group(1) if m2 else None
            if num:
                return "USPS", _clean_tracking_number(num), href

        # DHL
        elif 'dhl.com/tracking' in href_lower or 'dhl.com/home/tracking' in href_lower or \
             'dhl.com/en/express/tracking' in href_lower:
            num = _extract_url_param(href, ['tracking-id', 'AWB', 'trackingNumber', 'id'])
            if not num:
                m2 = re.search(r'\b(JD\d{18}|\d{10,11})\b', href)
                num = m2.group(1) if m2 else None
            if not num:
                m2 = re.search(r'\b(JD\d{18}|[0-9]{10,11})\b', link_text)
                num = m2.group(1) if m2 else None
            if num:
                return "DHL", _clean_tracking_number(num), href

        # Narvar
        elif 'narvar.com/tracking' in href_lower or '.narvar.com/track' in href_lower:
            num = _extract_url_param(href, ['tracking_number', 'id', 'track'])
            if not num:
                m2 = re.search(r'\b(1Z[A-Z0-9]{16}|9[234]\d{18,22}|\d{12}|\d{15}|TBA\d{10,})\b', link_text)
                num = m2.group(1) if m2 else None
            if num:
                carrier = _guess_carrier_from_number(num)
                return carrier, _clean_tracking_number(num), href

        # AfterShip
        elif 'aftership.com' in href_lower or 'track.aftership.com' in href_lower:
            num = _extract_url_param(href, ['number', 'tracking_number', 'id'])
            if not num:
                m2 = re.search(r'/trackings/[^/]+/([A-Z0-9-]{8,})', href, re.IGNORECASE)
                num = m2.group(1) if m2 else None
            if not num:
                m2 = re.search(r'\b(1Z[A-Z0-9]{16}|9[234]\d{18,22}|\d{12}|\d{15}|TBA\d{10,})\b', link_text)
                num = m2.group(1) if m2 else None
            if num:
                carrier = _guess_carrier_from_number(num)
                return carrier, _clean_tracking_number(num), href

        # EasyPost
        elif 'track.easypost.com' in href_lower:
            num = _extract_url_param(href, ['tracking_code', 'id', 'number'])
            if not num:
                m2 = re.search(r'\b(1Z[A-Z0-9]{16}|9[234]\d{18,22}|\d{12}|\d{15})\b', link_text)
                num = m2.group(1) if m2 else None
            if num:
                carrier = _guess_carrier_from_number(num)
                return carrier, _clean_tracking_number(num), href

        # PackageTrackr
        elif 'packagetrackr.com' in href_lower:
            m2 = re.search(r'/track/([A-Z0-9]{8,})', href, re.IGNORECASE)
            num = m2.group(1) if m2 else None
            if num:
                carrier = _guess_carrier_from_number(num)
                return carrier, _clean_tracking_number(num), href

        # Generic: link text looks like a tracking number
        if not any(skip in href_lower for skip in ('unsubscribe', 'mailto', 'javascript')):
            for carrier_name, pat in TRACKING_PATTERNS[:5]:
                m2 = pat.search(link_text)
                if m2:
                    return carrier_name, m2.group(1), href

    return None, None, None


def _guess_carrier_from_number(num):
    """Guess carrier from tracking number format."""
    if re.match(r'^1Z[A-Z0-9]{16}$', num, re.IGNORECASE):
        return "UPS"
    if re.match(r'^9[234]\d{18,22}$', num) or re.match(r'^420\d{17,22}$', num):
        return "USPS"
    if re.match(r'^TBA\d{10,}$', num, re.IGNORECASE):
        return "Amazon"
    if re.match(r'^JD\d{18}$', num):
        return "DHL"
    if re.match(r'^\d{15}$', num) or re.match(r'^\d{12}$', num):
        return "FedEx"
    return "Unknown"


# Image URL blocklist patterns (compiled once)
_IMG_SKIP_URL = re.compile(
    r'pixel|beacon|spacer|transparent|blank|1x1|track|open|email-open|'
    r'logo|icon|favicon|header|footer|social|facebook|twitter|instagram|'
    r'linkedin|pinterest|youtube|badge|button|banner|sprite|arrow|'
    r'unsubscribe|powered-by|email-template|separator|divider|line|'
    r'background|bg[-_]|corner|bullet|star|check|rating',
    re.IGNORECASE
)
_IMG_SKIP_DIMS = re.compile(r'width=["\']?1["\']?|height=["\']?1["\']?', re.IGNORECASE)


def extract_product_images(html):
    """
    Extract the best candidate product image URL from HTML email.
    Returns a URL string or empty string.
    """
    if not html:
        return ""

    img_pattern = re.compile(r'<img\b[^>]+>', re.IGNORECASE | re.DOTALL)
    src_pattern  = re.compile(r'\bsrc=["\']([^"\'\s>]+)["\']', re.IGNORECASE)
    alt_pattern  = re.compile(r'\balt=["\']([^"\']*)["\']', re.IGNORECASE)
    width_pattern  = re.compile(r'\bwidth=["\']?(\d+)["\']?', re.IGNORECASE)
    height_pattern = re.compile(r'\bheight=["\']?(\d+)["\']?', re.IGNORECASE)

    candidates = []

    for img_tag in img_pattern.finditer(html):
        tag = img_tag.group(0)

        src_m = src_pattern.search(tag)
        if not src_m:
            continue
        src = src_m.group(1).strip()

        if not src.startswith('https://'):
            continue

        w_m = width_pattern.search(tag)
        h_m = height_pattern.search(tag)
        w = int(w_m.group(1)) if w_m else None
        h = int(h_m.group(1)) if h_m else None
        if (w is not None and w <= 1) or (h is not None and h <= 1):
            continue
        if (w is not None and w < 30) or (h is not None and h < 30):
            continue

        if _IMG_SKIP_URL.search(src):
            continue

        score = 0

        if 'm.media-amazon.com' in src or 'images-na.ssl-images-amazon.com' in src or \
           'images-amazon.com' in src:
            score += 50

        if w is not None and h is not None:
            area = w * h
            if area >= 40000:
                score += 30
            elif area >= 10000:
                score += 15
            elif area >= 2500:
                score += 5

        alt_m = alt_pattern.search(tag)
        alt = alt_m.group(1).strip() if alt_m else ""
        if alt and len(alt) > 3:
            score += 10

        if any(cdn in src for cdn in ('cdn.shopify', 'cdn.shopifycdn', 'cloudinary',
                                       'fastly.net', 'akamaihd', 'scene7.com',
                                       'res.cloudinary', 'images.ctfassets')):
            score += 20

        if score < 0:
            continue

        candidates.append((score, src))

    if not candidates:
        return ""

    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0][1]


def extract_cost(text):
    """Find the first dollar amount that looks like an order total."""
    total_pattern = re.compile(
        r'(?:order\s+total|subtotal|total)[:\s]+\$?([\d,]+\.?\d{0,2})',
        re.IGNORECASE
    )
    m = total_pattern.search(text)
    if m:
        try:
            return float(m.group(1).replace(",", ""))
        except ValueError:
            pass
    amounts = re.findall(r'\$([\d,]+\.\d{2})', text)
    valid = []
    for a in amounts:
        try:
            val = float(a.replace(",", ""))
            if 1.0 <= val <= 100000.0:
                valid.append(val)
        except ValueError:
            pass
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
            parsed = _parse_date_string(raw)
            if parsed:
                return parsed
    return None


def _parse_date_string(s):
    """Attempt to parse a loose date string to YYYY-MM-DD."""
    now = datetime.now()
    s = s.strip().rstrip(",")
    for fmt in ("%B %d, %Y", "%b %d, %Y", "%B %d", "%b %d", "%m/%d/%Y", "%m/%d/%y", "%m-%d-%Y"):
        try:
            d = datetime.strptime(s, fmt)
            if d.year == 1900:
                d = d.replace(year=now.year)
                if d < now:
                    d = d.replace(year=now.year + 1)
            return d.strftime("%Y-%m-%d")
        except ValueError:
            pass
    try:
        s2 = re.sub(
            r'^(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),?\s+',
            '', s, flags=re.IGNORECASE
        )
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
    if any(k in combined for k in (
        "order confirmed", "order confirmation",
        "thank you for your order", "we've received your order"
    )):
        return "processing"
    if tracking_number:
        return "in_transit"
    return "processing"


def build_item_name(subject, retailer):
    """Extract a human-readable item name from the email subject."""
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


def _parse_email_date(date_str):
    """Parse RFC 2822 email date to YYYY-MM-DD."""
    if not date_str:
        return None
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
# Email classification — filter marketing from real orders
# ---------------------------------------------------------------------------
def is_blocked_sender(sender_email, sender_name=""):
    """Return True if the sender is known to NOT send real shipping emails."""
    if not sender_email:
        return False
    domain = sender_email.lower().split("@")[-1] if "@" in sender_email else sender_email.lower()
    # Check exact domain
    if domain in BLOCKED_DOMAINS:
        return True
    # Check marketing brand domains
    if domain in MARKETING_BRAND_DOMAINS:
        return True
    # Check subdomain (e.g., email.audible.com)
    for blocked in BLOCKED_DOMAINS | MARKETING_BRAND_DOMAINS:
        if domain.endswith("." + blocked):
            return True
    # Check keyword patterns in email address
    email_lower = sender_email.lower()
    for kw in BLOCKED_SENDER_KEYWORDS:
        if kw in email_lower:
            return True
    return False


def is_real_order(subject, body_text, sender_email, tracking_number):
    """
    Score an email to determine if it's a real order/shipment notification
    vs marketing/promotional noise. Returns True if it looks like a real order.

    Scoring:
      +3  tracking number found
      +2  each strong order signal in subject
      +1  each strong order signal in body (up to +5)
      -3  each marketing pattern in subject
      -1  each marketing pattern in body (up to -3)
      +2  sent from a carrier (UPS, FedEx, etc.)
      +1  contains dollar amount

    Threshold: score >= 2 is a real order
    """
    score = 0
    subject_lower = (subject or "").lower()
    body_lower = (body_text or "")[:3000].lower()
    combined = subject_lower + " " + body_lower

    # Tracking number is a very strong signal
    if tracking_number:
        score += 3

    # Check for carrier sender
    if sender_email:
        sender_domain = sender_email.lower().split("@")[-1] if "@" in sender_email else ""
        for carrier_domain in CARRIER_MAP:
            if sender_domain.endswith(carrier_domain):
                score += 3
                break

    # Check strong order signals in subject (high weight)
    for pattern in ORDER_SIGNAL_PATTERNS:
        if pattern.search(subject):
            score += 2

    # Check strong order signals in body (lower weight, capped)
    body_signal_count = 0
    for pattern in ORDER_SIGNAL_PATTERNS:
        if pattern.search(body_lower):
            body_signal_count += 1
            if body_signal_count >= 5:
                break
    score += body_signal_count

    # Check marketing patterns in subject (heavy penalty)
    for pattern in MARKETING_SUBJECT_PATTERNS:
        if pattern.search(subject):
            score -= 3

    # Check marketing patterns in body (lighter penalty, capped)
    body_marketing_count = 0
    for pattern in MARKETING_SUBJECT_PATTERNS:
        if pattern.search(body_lower):
            body_marketing_count += 1
            if body_marketing_count >= 3:
                break
    score -= body_marketing_count

    return score >= 2


# ---------------------------------------------------------------------------
# Core sync logic per account
# ---------------------------------------------------------------------------
def sync_account(account, client_id, client_secret, page_token=None):
    """
    Fetch and parse emails for one account.

    Returns a dict:
    {
        "orders": [...],
        "updated_token": str|None,
        "next_page_token": str|None,
        "error": str|None
    }
    """
    access_token = account.get("access_token", "")
    refresh_token = account.get("refresh_token", "")
    email = account.get("email", "")
    updated_token = None

    list_params = {"q": GMAIL_QUERY, "maxResults": str(MAX_RESULTS)}
    if page_token:
        list_params["pageToken"] = page_token

    # 1. List messages
    status, data = gmail_get("/users/me/messages", access_token, params=list_params)

    # Handle 401: try token refresh
    if status == 401:
        new_token = refresh_access_token(refresh_token, client_id, client_secret)
        if new_token:
            access_token = new_token
            updated_token = new_token
            status, data = gmail_get("/users/me/messages", access_token, params=list_params)
        else:
            return {"orders": [], "updated_token": None, "next_page_token": None, "error": "auth_failed"}

    if status != 200:
        return {"orders": [], "updated_token": updated_token, "next_page_token": None, "error": f"gmail_error_{status}"}

    messages = data.get("messages", [])
    next_page_token = data.get("nextPageToken")
    orders = []

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
            new_token = refresh_access_token(refresh_token, client_id, client_secret)
            if new_token:
                access_token = new_token
                updated_token = new_token
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

        # 4.1 Skip blocked senders (digital services, social, marketing, etc.)
        if is_blocked_sender(sender_email, sender_name):
            continue

        retailer = detect_retailer(sender_email, sender_name)
        carrier_from_sender = detect_carrier_from_sender(sender_email)

        # 5. Extract body text
        payload = msg.get("payload", {})
        text_plain, text_html = extract_text_from_message(payload)
        body_text = text_plain if text_plain else strip_html(text_html)

        combined_text = subject + "\n" + body_text

        # 5.5 Extract tracking from HTML links (higher priority than regex)
        html_carrier, html_tracking, html_tracking_url = extract_tracking_from_html(text_html)

        # 5.6 Extract product image
        image_url = extract_product_images(text_html)

        # 6. Find tracking number — prefer HTML link extraction over regex
        if html_tracking:
            carrier = html_carrier or carrier_from_sender or "Unknown"
            tracking_number = html_tracking
            tracking_url = html_tracking_url or ""
        else:
            carrier, tracking_number = extract_tracking_number(combined_text)
            if not carrier and carrier_from_sender:
                carrier = carrier_from_sender
            if tracking_number and carrier:
                base_url = CARRIER_TRACKING_URLS.get(carrier, "")
                tracking_url = base_url + tracking_number if base_url else ""
            else:
                tracking_url = ""

        tracking_number = tracking_number or ""
        carrier = carrier or "Unknown"
        if not tracking_url and tracking_number and carrier:
            base_url = CARRIER_TRACKING_URLS.get(carrier, "")
            tracking_url = base_url + tracking_number if base_url else ""

        # 6.5 Check if this is a real order vs marketing noise
        if not is_real_order(subject, body_text, sender_email, tracking_number):
            continue

        # 7. Extract cost
        cost = extract_cost(combined_text)

        # 8. Extract estimated delivery
        est_delivery = extract_delivery_date(combined_text)

        # 9. Parse order date from email date header
        order_date = _parse_email_date(date_header)

        # 10. Infer status
        status_val = infer_status(subject, body_text, carrier, tracking_number)

        # 11. Build item name
        item_name = build_item_name(subject, retailer)

        orders.append({
            "account_email": email,
            "retailer": retailer,
            "item_name": item_name,
            "order_cost": cost,
            "order_date": order_date or datetime.now().strftime("%Y-%m-%d"),
            "shipping_carrier": carrier,
            "tracking_number": tracking_number,
            "tracking_url": tracking_url,
            "estimated_delivery": est_delivery or "",
            "status": status_val,
            "item_image_url": image_url,
            "raw_email_subject": subject,
            "raw_email_date": date_header,
            "gmail_message_id": msg_id,
        })

    return {
        "orders": orders,
        "updated_token": updated_token,
        "next_page_token": next_page_token,
        "error": None,
    }


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------
class handler(BaseHTTPRequestHandler):

    def do_OPTIONS(self):
        self.send_response(204)
        _cors(self)
        self.end_headers()

    def do_POST(self):
        client_id = os.environ.get("GOOGLE_CLIENT_ID", "")
        client_secret = os.environ.get("GOOGLE_CLIENT_SECRET", "")

        # Read request body
        content_length = int(self.headers.get("Content-Length", 0))
        body_bytes = self.rfile.read(content_length) if content_length > 0 else b"{}"
        try:
            body = json.loads(body_bytes)
        except (json.JSONDecodeError, ValueError):
            _send_json(self, {"success": False, "error": "Invalid JSON body"}, 400)
            return

        accounts = body.get("accounts", [])
        page_token = body.get("page_token")

        if not accounts:
            _send_json(self, {"success": True, "orders": [], "token_updates": {}, "message": "No accounts provided"})
            return

        all_orders = []
        token_updates = {}
        account_errors = {}

        for account in accounts:
            email = account.get("email", "")
            try:
                result = sync_account(account, client_id, client_secret, page_token)
                all_orders.extend(result["orders"])
                if result["updated_token"]:
                    token_updates[email] = result["updated_token"]
                if result["error"]:
                    account_errors[email] = result["error"]
            except Exception as exc:
                account_errors[email] = str(exc)

        _send_json(self, {
            "success": True,
            "orders": all_orders,
            "token_updates": token_updates,
            "account_errors": account_errors,
            "synced_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ"),
        })

    def log_message(self, *args):
        pass
