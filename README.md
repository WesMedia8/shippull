# ShipPull — Reseller Shipment Tracker

A fully functional Gmail-connected shipment tracker for resellers, deployed on Vercel. ShipPull connects to your Gmail via OAuth 2.0, reads shipping confirmation and order notification emails, extracts tracking numbers, carriers, costs, and delivery dates, then displays them in a dark industrial dashboard with grid and list views.

---

## Setup

### 1. Create a Google Cloud OAuth Client

1. Go to [Google Cloud Console](https://console.cloud.google.com/) and create a new project.
2. Navigate to **APIs & Services → Credentials → Create Credentials → OAuth 2.0 Client ID**.
3. Set application type to **Web Application**.
4. Under **Authorized redirect URIs**, add:
   ```
   https://your-deployment.vercel.app/api/callback
   ```
   Replace `your-deployment.vercel.app` with your actual Vercel domain.
5. Copy your **Client ID** and **Client Secret**.

### 2. Enable Required APIs

In the Google Cloud Console, enable:
- **Gmail API** — for reading emails
- **Google People API** (or Google OAuth2 API v2) — for fetching the user's email address

### 3. Deploy to Vercel

```bash
cd shippull-vercel
vercel deploy
```

### 4. Set Environment Variables in Vercel

In your Vercel project settings under **Environment Variables**, add:

| Variable              | Value                                    |
|-----------------------|------------------------------------------|
| `GOOGLE_CLIENT_ID`    | Your OAuth 2.0 Client ID                 |
| `GOOGLE_CLIENT_SECRET`| Your OAuth 2.0 Client Secret             |
| `APP_URL`             | Your Vercel deployment URL (no trailing `/`) e.g. `https://shippull.vercel.app` |

Redeploy after setting the variables.

---

## How It Works

### OAuth Flow

1. User clicks **Connect Gmail Account** → browser redirects to `/api/auth`
2. `/api/auth` builds a Google OAuth URL with scopes:
   - `https://www.googleapis.com/auth/gmail.readonly`
   - `https://www.googleapis.com/auth/userinfo.email`
3. User grants access on Google's consent page
4. Google redirects to `/api/callback?code=XXX`
5. `/api/callback` exchanges the code for `access_token` + `refresh_token`, fetches the user's email, stores the account, redirects to `/#dashboard?connected=1`
6. Frontend detects `?connected=1`, triggers initial sync, displays dashboard

### Email Parsing

When sync is triggered (`POST /api/sync`):
1. For each connected account, searches Gmail for shipping-related emails (up to 50 most recent)
2. Fetches each email's full payload
3. Parses:
   - **Retailer** — detected from sender email domain (Nike, Amazon, StockX, etc.)
   - **Tracking number** — regex patterns for UPS (1Z...), USPS (94...), FedEx (15-digit), DHL (10-digit)
   - **Carrier** — inferred from tracking number format or sender domain
   - **Cost** — largest dollar amount found (heuristic: order total)
   - **Estimated delivery date** — scans for "delivery by", "arriving", "estimated delivery" patterns
   - **Status** — inferred from keywords: delivered / out for delivery / in transit / shipped / processing
4. Deduplicates orders by tracking number per account

### Data Storage

Orders and accounts are stored in **module-level Python dicts** inside `api/_store.py`. This data persists across warm Vercel invocations but **resets on cold starts** or new deployments. For production use, replace the store with Vercel KV, PlanetScale, or another persistent database.

---

## API Endpoints

| Method | Path             | Description                                      |
|--------|------------------|--------------------------------------------------|
| GET    | `/api/auth`      | Redirect to Google OAuth consent screen          |
| GET    | `/api/callback`  | OAuth callback — exchange code, store account    |
| GET    | `/api/accounts`  | List connected accounts (no tokens returned)     |
| DELETE | `/api/accounts?id=N` | Remove account and all its orders           |
| POST   | `/api/sync`      | Fetch Gmail emails, parse, store new orders      |
| GET    | `/api/orders`    | List orders (supports `status`, `retailer`, `search`, `sort`, `account_id` params) |
| GET    | `/api/order?id=N`| Single order detail                              |
| GET    | `/api/stats`     | Dashboard aggregate stats                        |

---

## File Structure

```
shippull-vercel/
├── public/
│   ├── index.html       # Single-page app shell
│   ├── style.css        # Dark industrial theme + list view styles
│   └── app.js           # Frontend logic (routing, OAuth detection, grid/list view)
├── api/
│   ├── _store.py        # Shared in-memory store (accounts + orders)
│   ├── auth.py          # OAuth URL generator
│   ├── callback.py      # OAuth callback handler
│   ├── sync.py          # Gmail fetcher + email parser
│   ├── accounts.py      # Account CRUD
│   ├── orders.py        # Order listing with filters
│   ├── order.py         # Single order detail
│   └── stats.py         # Dashboard stats
├── vercel.json          # Serverless function routing
├── pyproject.toml       # Project metadata
├── requirements.txt     # Empty — stdlib only
└── README.md            # This file
```

---

## Dashboard Features

- **Grid view** — cards with retailer, item, cost, status badge, carrier, tracking link, ETA, account tag
- **List view** — dense spreadsheet-style table with status dot, sortable via filter bar
- **View toggle** — persisted in localStorage
- **Filters** — by status, retailer, free-text search, sort order
- **Stats bar** — total orders, in transit, delivered, processing, total spent
- **Sync button** — manually triggers Gmail re-scan for new emails
- **Multi-account** — connect multiple Gmail accounts, filter per account in orders list
- **Order detail modal** — full shipment timeline, all extracted metadata, source email subject

---

## Supported Retailers (sender domain detection)

Nike, Apple, Amazon, StockX, Best Buy, Target, Walmart, SSENSE, Lululemon, Foot Locker, GOAT, eBay, Etsy, Nordstrom, Adidas, New Balance, Zappos, Gap, Zara, H&M, Uniqlo, Patagonia, REI, Dick's Sporting Goods, Costco, Saks, Bloomingdale's, Macy's, Neiman Marcus, UPS, FedEx, USPS, DHL, and any other sender (falls back to sender display name).
