"""
EVILISM Bot — Backend API Server
backend.py

A lightweight Flask server that runs alongside the Discord bot.
Handles:
  • Discord OAuth2 callback (/auth/callback)
  • Session identity endpoint (/api/me)
  • Form submission endpoint (/api/submit)
  • BuildersClub status endpoint (/api/builders-status)
  • Security log forwarding to Discord (internal)

Run this with: python backend.py
Or run both bot + backend together with: python main.py
"""

import json
import logging
import requests
from functools import wraps

from flask import Flask, request, jsonify, redirect
from flask_cors import CORS

from config import Config
from database import Database

log = logging.getLogger("evilism.backend")
app = Flask(__name__)
# Extract the base origin (scheme + host) for CORS
from urllib.parse import urlparse
parsed_url = urlparse(Config.GITHUB_PAGES_URL)
base_origin = f"{parsed_url.scheme}://{parsed_url.netloc}"

CORS(app, origins=[base_origin, "http://localhost:*", "https://*.github.io"] )


db = Database()


# ════════════════════════════════════════════════════════════
#  AUTH HELPERS
# ════════════════════════════════════════════════════════════

def require_auth(f):
    """Decorator: validates Bearer session token from Authorization header."""
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return jsonify({"error": "Missing or invalid Authorization header"}), 401
        token = auth[7:]
        session = db.get_session(token)
        if not session:
            return jsonify({"error": "Session expired or invalid. Please log in again."}), 401
        request.session = session
        return f(*args, **kwargs)
    return decorated


# ════════════════════════════════════════════════════════════
#  DISCORD OAUTH2 CALLBACK
#  Discord redirects here after the user logs in on the form page.
#  We exchange the code for an access token, fetch the user, create
#  a session, then redirect back to GitHub Pages with ?token=<session>
# ════════════════════════════════════════════════════════════

@app.route("/auth/callback")
def oauth_callback():
    code  = request.args.get("code")
    state = request.args.get("state")

    if not code:
        return redirect(f"{Config.GITHUB_PAGES_URL}?expired=1")

    # Exchange code for access token
    token_res = requests.post(
        "https://discord.com/api/oauth2/token",
        data={
            "client_id":     Config.DISCORD_CLIENT_ID,
            "client_secret": Config.DISCORD_CLIENT_SECRET,
            "grant_type":    "authorization_code",
            "code":          code,
            "redirect_uri":  f"{Config.BACKEND_URL}/auth/callback",
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=10,
    )

    if not token_res.ok:
        log.error(f"OAuth token exchange failed: {token_res.text}")
        return redirect(f"{Config.GITHUB_PAGES_URL}?expired=1")

    token_data   = token_res.json()
    access_token = token_data.get("access_token")

    if not access_token:
        return redirect(f"{Config.GITHUB_PAGES_URL}?expired=1")

    # Fetch Discord user identity
    user_res = requests.get(
        "https://discord.com/api/v10/users/@me",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=10,
    )

    if not user_res.ok:
        log.error(f"Discord user fetch failed: {user_res.text}")
        return redirect(f"{Config.GITHUB_PAGES_URL}?expired=1")

    user = user_res.json()
    discord_id       = user.get("id")
    discord_username = user.get("global_name") or user.get("username", "Unknown")
    discord_avatar   = user.get("avatar")

    # Check if this user already has a pending application (can't resubmit)
    if db.has_pending_application(discord_id):
        return redirect(f"{Config.GITHUB_PAGES_URL}?already_submitted=1")

    # Create session
    session_token = db.create_session(discord_id, discord_username, discord_avatar)

    log.info(f"OAuth success for {discord_username} ({discord_id})")
    return redirect(f"{Config.GITHUB_PAGES_URL}?token={session_token}")


# ════════════════════════════════════════════════════════════
#  GET /api/me — returns the authenticated user's identity
# ════════════════════════════════════════════════════════════

@app.route("/api/me")
@require_auth
def get_me():
    s = request.session
    return jsonify({
        "id":          s["discord_id"],
        "username":    s["discord_username"],
        "avatar":      s.get("discord_avatar"),
        "global_name": s["discord_username"],
    })


# ════════════════════════════════════════════════════════════
#  GET /api/builders-status — public endpoint for the form page
# ════════════════════════════════════════════════════════════

@app.route("/api/builders-status")
def builders_status():
    return jsonify({"enabled": db.is_builders_club_enabled()})


# ════════════════════════════════════════════════════════════
#  POST /api/submit — receives the completed form
# ════════════════════════════════════════════════════════════

@app.route("/api/submit", methods=["POST"])
@require_auth
def submit_form():
    s       = request.session
    discord_id       = s["discord_id"]
    discord_username = s["discord_username"]
    discord_avatar   = s.get("discord_avatar")

    # Prevent double submission
    if db.has_pending_application(discord_id):
        return jsonify({"error": "Application already submitted."}), 409

    body = request.get_json(silent=True)
    if not body:
        return jsonify({"error": "Invalid request body."}), 400

    answers = body.get("answers", {})

    # Basic server-side validation — ensure required fields are present
    required_keys = ["q1", "q2", "q3", "q4", "q5", "q6", "q7", "q8", "q9", "q10", "q11", "q12"]
    missing = [k for k in required_keys if not answers.get(k, "").strip()]
    if missing:
        return jsonify({"error": f"Missing required fields: {', '.join(missing)}"}), 400

    # Minimum length check for text answers
    text_fields = ["q1", "q2", "q4", "q5", "q6", "q10", "q11", "q12"]
    for key in text_fields:
        if len(answers.get(key, "").strip()) < 10:
            return jsonify({"error": f"Answer to {key} is too short."}), 400

    created = db.create_application(discord_id, discord_username, discord_avatar, answers)
    if not created:
        return jsonify({"error": "Application already submitted."}), 409

    # Invalidate session so the form can't be reloaded and resubmitted
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        db.delete_session(auth[7:])

    log.info(f"Form submitted by {discord_username} ({discord_id})")

    # Post to #security-logs via the bot (we call a shared internal queue)
    _notify_security_log(discord_id, discord_username, answers)

    return jsonify({"success": True}), 200


# ════════════════════════════════════════════════════════════
#  INTERNAL — post a notification to security logs
#  We write to a simple file queue; the bot reads it on its loop.
#  This avoids circular imports between bot.py and backend.py.
# ════════════════════════════════════════════════════════════

import queue
import threading

_security_queue: queue.Queue = queue.Queue()


def _notify_security_log(discord_id: str, discord_username: str, answers: dict):
    """Push a security log notification onto the shared queue."""
    _security_queue.put({
        "type":             "new_application",
        "discord_id":       discord_id,
        "discord_username": discord_username,
        "preview":          answers.get("q1", "")[:120],
    })


def get_security_queue() -> queue.Queue:
    """Exposed so bot.py can consume from this queue."""
    return _security_queue


# ════════════════════════════════════════════════════════════
#  HEALTH CHECK
# ════════════════════════════════════════════════════════════

@app.route("/health")
def health():
    return jsonify({"status": "ok", "service": "EVILISM Verification Backend"}), 200


# ════════════════════════════════════════════════════════════
#  RUN (standalone mode)
# ════════════════════════════════════════════════════════════

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    app.run(host=Config.BACKEND_HOST, port=Config.BACKEND_PORT, debug=False)
