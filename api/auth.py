"""
api/auth.py
GET /api/auth — Build and redirect to the Google OAuth2 authorization URL.
"""
import os
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlencode

SCOPES = (
    "https://www.googleapis.com/auth/gmail.readonly "
    "https://www.googleapis.com/auth/userinfo.email"
)


def _cors(h):
    h.send_header("Access-Control-Allow-Origin", "*")
    h.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
    h.send_header("Access-Control-Allow-Headers", "Content-Type")


class handler(BaseHTTPRequestHandler):

    def do_OPTIONS(self):
        self.send_response(204)
        _cors(self)
        self.end_headers()

    def do_GET(self):
        client_id = os.environ.get("GOOGLE_CLIENT_ID", "")
        app_url = os.environ.get("APP_URL", "").rstrip("/")

        if not client_id or not app_url:
            body = b"Missing GOOGLE_CLIENT_ID or APP_URL environment variable."
            self.send_response(500)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            _cors(self)
            self.end_headers()
            self.wfile.write(body)
            return

        redirect_uri = f"{app_url}/api/callback"

        params = urlencode({
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": SCOPES,
            "access_type": "offline",
            "prompt": "consent",
        })

        auth_url = f"https://accounts.google.com/o/oauth2/v2/auth?{params}"

        self.send_response(302)
        _cors(self)
        self.send_header("Location", auth_url)
        self.end_headers()

    def log_message(self, *args):
        pass
