"""
EVILISM Bot Configuration
config.py

Fill in all values marked with !! REQUIRED !! before running the bot.
"""

import os


class Config:
    # ── Bot Credentials ────────────────────────────────────────
    # !! REQUIRED !! Your Discord bot token from the Developer Portal
    BOT_TOKEN: str = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")

    # !! REQUIRED !! Your Discord application's Client ID
    DISCORD_CLIENT_ID: str = os.getenv("DISCORD_CLIENT_ID", "YOUR_CLIENT_ID_HERE")

    # !! REQUIRED !! Your Discord application's Client Secret (for OAuth2)
    DISCORD_CLIENT_SECRET: str = os.getenv("DISCORD_CLIENT_SECRET", "YOUR_CLIENT_SECRET_HERE")

    # ── UMBRA Identity ─────────────────────────────────────────
    # UMBRA's Discord user ID — only this user can toggle BuildersClub
    UMBRA_DISCORD_ID: str = "1125940452282093618"

    # ── URLs ───────────────────────────────────────────────────
    # !! REQUIRED !! The public URL where your GitHub Pages site is hosted
    # e.g. "https://yourusername.github.io/evilism-verify"
    GITHUB_PAGES_URL: str = os.getenv("GITHUB_PAGES_URL", "https://yourusername.github.io/evilism-verify")

    # !! REQUIRED !! The public URL of THIS backend server
    # e.g. "https://your-bot-host.com"  (no trailing slash)
    BACKEND_URL: str = os.getenv("BACKEND_URL", "https://your-bot-host.com")

    # ── Server Channel Names ────────────────────────────────────
    # These must match EXACTLY the channel names in your Discord server
    CHANNEL_VERIFICATION_PORTAL: str = "verification-portal"
    CHANNEL_SECURITY_LOGS:       str = "security-logs"

    # ── Role Names ─────────────────────────────────────────────
    # These must match EXACTLY the role names in your Discord server
    ROLE_UNINITIATED:     str = "The Uninitiated"
    ROLE_ACOLYTE:         str = "Acolytes of Evil"
    ROLE_BUILDERS_CLUB:   str = "Umbra's BuildersClub"
    ROLE_SACRIFICIAL_LAMBS: str = "Sacrificial Lambs"
    ROLE_DARK_COUNCIL:    str = "The Dark Council"
    ROLE_HARBINGERS:      str = "Harbingers of Chaos"

    # ── Expiry Durations ───────────────────────────────────────
    # How long (in seconds) a submitted form stays valid before auto-denial
    FORM_EXPIRY_SECONDS: int = 7 * 24 * 60 * 60       # 7 days

    # How long (in seconds) an issued verification key stays valid
    KEY_EXPIRY_SECONDS: int = int(3.5 * 24 * 60 * 60)  # 84 hours (3.5 days)

    # ── Backend Server ─────────────────────────────────────────
    BACKEND_HOST: str = "0.0.0.0"
    BACKEND_PORT: int = int(os.getenv("PORT", 8080))

    # ── Database ───────────────────────────────────────────────
    # SQLite database file path (relative to bot directory)
    DATABASE_PATH: str = os.getenv("DATABASE_PATH", "evilism.db")
