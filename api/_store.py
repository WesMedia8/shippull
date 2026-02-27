"""
api/_store.py
Shared in-memory store for ShipPull.
Persists across warm invocations in the same Vercel container. Resets on cold starts.
"""
import random
from datetime import datetime

accounts = {}      # {account_id: {id, email, display_name, avatar_color, access_token, refresh_token, connected_at, last_synced}}
orders = {}        # {order_id: {all order fields}}

_next_account_id = [1]   # list for mutability in module scope
_next_order_id = [1]

AVATAR_COLORS = [
    "#3B82F6", "#10B981", "#F59E0B", "#EF4444",
    "#8B5CF6", "#EC4899", "#06B6D4", "#F97316",
]


def add_account(email, access_token, refresh_token):
    aid = _next_account_id[0]
    _next_account_id[0] += 1
    accounts[aid] = {
        "id": aid,
        "email": email,
        "display_name": email.split("@")[0].replace(".", " ").title(),
        "avatar_color": random.choice(AVATAR_COLORS),
        "access_token": access_token,
        "refresh_token": refresh_token,
        "connected_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "last_synced": None,
    }
    return accounts[aid]


def add_order(account_id, **kwargs):
    oid = _next_order_id[0]
    _next_order_id[0] += 1
    order = {
        "id": oid,
        "account_id": account_id,
        **kwargs,
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    orders[oid] = order
    return order


def remove_account(account_id):
    accounts.pop(account_id, None)
    to_remove = [oid for oid, o in orders.items() if o["account_id"] == account_id]
    for oid in to_remove:
        del orders[oid]


def get_account_by_email(email):
    for a in accounts.values():
        if a["email"] == email:
            return a
    return None


def get_accounts_public():
    """Return accounts without sensitive token fields."""
    return [
        {k: v for k, v in a.items() if k not in ("access_token", "refresh_token")}
        for a in accounts.values()
    ]
