# ShipPull — Reseller Shipment Tracker

A Vercel-hosted shipment tracker that reads Gmail for order confirmation and shipping emails. Built for resellers who buy from multiple retailers and need one unified dashboard.

## Architecture

**Stateless serverless — all state lives in the browser.**

The original in-memory `_store.py` approach does not work on Vercel because each serverless function invocation runs in an isolated container with no shared memory. This version moves all state to `localStorage`.

```
Browser (localStorage)
  shippull_accounts:  [{email, access_token, refresh_token, connected_at, last_synced}]
  shippull_orders:    [{gmail_message_id, account_email, retailer, ...}]

API (stateless)
  GET  /api/auth      — Build Google OAuth URL and redirect
  GET  /api/callback  — Exchange code for tokens, redirect to /#/callback?...tokens...
  POST /api/sync      — Accept tokens from browser, fetch Gmail, return parsed orders
```

### OAuth flow
1. User clicks "Connect Gmail" → `/api/auth` redirects to Google
2. Google redirects to `/api/callback?code=...`
3. `callback.py` exchanges code for tokens, fetches user email
4. Redirects to `/#/callback?access_token=...&refresh_token=...&email=...` (fragment = never hits server logs)
5. Frontend reads tokens from hash, saves to localStorage, auto-syncs

### Sync flow
1. User clicks Sync (or auto-syncs on connect)
2. Frontend POSTs `{accounts: [{email, access_token, refresh_token}]}` to `/api/sync`
3. `sync.py` calls Gmail API for each account, parses emails, returns orders as JSON
4. Frontend merges orders into localStorage (dedup by `gmail_message_id`)
5. Frontend updates any refreshed tokens from `token_updates` in response

## Setup

### 1. Google OAuth credentials
- Create a project in [Google Cloud Console](https://console.cloud.google.com)
- Enable the **Gmail API** and **Google People API**
- Create OAuth 2.0 credentials (Web application type)
- Add authorized redirect URI: `https://your-app.vercel.app/api/callback`

### 2. Environment variables (Vercel)
```
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
APP_URL=https://your-app.vercel.app
```

### 3. Deploy
```bash
vercel --prod
```

## Project Structure

```
shippull-vercel/
├── api/
│   ├── auth.py         # GET /api/auth — redirect to Google OAuth
│   ├── callback.py     # GET /api/callback — exchange code, redirect with tokens
│   ├── sync.py         # POST /api/sync — stateless Gmail fetch + parse
│   └── _store.py       # Empty placeholder (not used)
├── public/
│   ├── index.html      # Single-page app shell
│   ├── app.js          # Client-side logic + localStorage state
│   └── style.css       # Dark industrial theme
├── vercel.json         # Routes config
└── requirements.txt    # Empty — stdlib only
```

## Email Parsing

`sync.py` contains a comprehensive parsing engine:
- **30+ retailers** detected from sender domain (Nike, StockX, GOAT, Amazon, etc.)
- **UPS, FedEx, USPS, DHL** tracking number extraction with regex patterns
- **Order cost** extraction (total/subtotal patterns + dollar amount fallback)
- **Estimated delivery** date extraction
- **Status inference** from email subject/body keywords
- **Token refresh** — if an access token expires during sync, it's refreshed and returned to the frontend

## Privacy

- OAuth tokens are stored only in your browser's `localStorage`
- Tokens are sent to the sync endpoint only to authenticate Gmail API requests
- No emails are stored anywhere — only parsed metadata (retailer, tracking number, cost, etc.)
- "Clear Data" in the Accounts page wipes everything from localStorage
