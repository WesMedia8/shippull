"""
api/callback.py
GET /api/callback — Handle the Google OAuth2 callback.
Exchanges auth code for tokens, fetches user email, then redirects
to the frontend with tokens in the URL fragment (hash) so they never
appear in server logs.
"""
import json
import os
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs, urlencode, quote
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError


def _cors(h):
    h.send_header("Access-Control-Allow-Origin", "*")
    h.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
    h.send_header("Access-Control-Allow-Headers", "Content-Type")


def _redirect(h, url):
    h.send_response(302)
    _cors(h)
    h.send_header("Location", url)
    h.end_headers()


class handler(BaseHTTPRequestHandler):

    def do_OPTIONS(self):
        self.send_response(204)
        _cors(self)
        self.end_headers()

    def do_GET(self):
        app_url = os.environ.get("APP_URL", "").rstrip("/")
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)

        error = params.get("error", [""])[0]
        if error:
            _redirect(self, f"{app_url}/#/callback?error={quote(error)}")
            return

        code = params.get("code", [""])[0]
        if not code:
            _redirect(self, f"{app_url}/#/callback?error=no_code")
            return

        # Exchange code for tokens
        token_body = urlencode({
            "code": code,
            "client_id": os.environ.get("GOOGLE_CLIENT_ID", ""),
            "client_secret": os.environ.get("GOOGLE_CLIENT_SECRET", ""),
            "redirect_uri": f"{app_url}/api/callback",
            "grant_type": "authorization_code",
        }).encode("utf-8")

        req = Request(
            "https://oauth2.googleapis.com/token",
            data=token_body,
            method="POST",
        )
        req.add_header("Content-Type", "application/x-www-form-urlencoded")

        try:
            resp = urlopen(req, timeout=10)
            tokens = json.loads(resp.read())
        except (HTTPError, URLError):
            _redirect(self, f"{app_url}/#/callback?error=token_exchange")
            return

        access_token = tokens.get("access_token", "")
        refresh_token = tokens.get("refresh_token", "")

        if not access_token:
            _redirect(self, f"{app_url}/#/callback?error=no_access_token")
            return

        # Fetch user email via userinfo endpoint
        try:
            user_req = Request("https://www.googleapis.com/oauth2/v2/userinfo")
            user_req.add_header("Authorization", f"Bearer {access_token}")
            user_resp = urlopen(user_req, timeout=10)
            user_info = json.loads(user_resp.read())
            email = user_info.get("email", "")
        except Exception:
            email = ""

        if not email:
            _redirect(self, f"{app_url}/#/callback?error=no_email")
            return

        # Redirect to frontend with tokens in the URL fragment.
        # Using the fragment (#) means the tokens are never sent to the server
        # in future requests and don't appear in server-side access logs.
        fragment_params = urlencode({
            "access_token": access_token,
            "refresh_token": refresh_token,
            "email": email,
        })
        _redirect(self, f"{app_url}/#/callback?{fragment_params}")

    def log_message(self, *args):
        pass
