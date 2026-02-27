# ShipPull

A reseller shipment tracker that aggregates orders from multiple Gmail accounts into a single real-time dashboard. Connect any email address to see all your orders — Nike, StockX, GOAT, eBay, Amazon, and more — in one place.

## Features

- Multi-account support (connect multiple email addresses)
- Order cards with status badges, carrier info, and tracking links
- Dashboard stats: total orders, in transit, delivered, processing, total spent
- Filter by status, retailer, or search term; sort by newest, status, ETA, or cost
- Order detail modal with shipment progress timeline
- Dark industrial UI with skeleton loading states

## Architecture

```
shippull-vercel/
├── public/          # Static frontend (Vercel serves automatically)
│   ├── index.html
│   ├── style.css
│   └── app.js
├── api/
│   └── index.py     # Vercel Python serverless function
├── vercel.json      # Route /api → /api/index
├── requirements.txt # No external deps
└── README.md
```

## Deploy to Vercel

### Prerequisites

- [Vercel CLI](https://vercel.com/docs/cli): `npm i -g vercel`
- A Vercel account (free tier works)

### Steps

```bash
# 1. Clone / copy this directory
cd shippull-vercel

# 2. Deploy
vercel

# Follow the prompts:
#   - Link to existing project or create new
#   - Framework: Other
#   - Root directory: ./
#   - Build command: (leave empty)
#   - Output directory: public
```

Vercel automatically:
- Serves everything in `public/` as static files
- Deploys `api/index.py` as a serverless Python function at `/api`
- Applies the rewrite rule from `vercel.json`

### Environment

No environment variables required. The app uses an in-memory store — data resets on cold starts, which is fine for demo/MVP purposes.

## API Endpoints

All requests go to `GET /api` or `POST /api` or `DELETE /api` with an `action` query parameter.

| Method   | action          | Description                              |
|----------|-----------------|------------------------------------------|
| GET      | `accounts`      | List all connected accounts              |
| POST     | `add_account`   | Connect a new account (seeds sample data)|
| DELETE   | `remove_account`| Remove an account and its orders         |
| GET      | `orders`        | List orders (supports filtering/sorting) |
| GET      | `order`         | Get a single order by `id`               |
| GET      | `stats`         | Aggregate counts and total spent         |
| POST     | `sync`          | Update `last_synced` timestamp           |

### Filter params for `orders`

- `status` — `processing` | `shipped` | `in_transit` | `out_for_delivery` | `delivered`
- `retailer` — exact retailer name
- `account_id` — filter by account
- `search` — substring match on item name, retailer, or tracking number
- `sort` — `newest` (default) | `status` | `eta` | `cost_desc`

## Notes on State

This is a stateless serverless deployment. All data lives in module-level Python dictionaries that survive across warm Lambda invocations but reset on cold starts or redeployments. For a production version, swap the in-memory store for a persistent database (e.g., Vercel Postgres, PlanetScale, or Upstash Redis).
