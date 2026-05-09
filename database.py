"""
EVILISM Bot — Database Layer
database.py

Uses SQLite for simplicity and zero-dependency hosting.
All timestamps are stored as ISO-8601 UTC strings.
"""

import sqlite3
import secrets
import hashlib
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, List

from config import Config

log = logging.getLogger("evilism.db")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _from_iso(s: str) -> datetime:
    return datetime.fromisoformat(s)


class Database:
    def __init__(self):
        self.path = Config.DATABASE_PATH
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_db(self):
        with self._connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS applications (
                    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
                    discord_id              TEXT NOT NULL,
                    discord_username        TEXT NOT NULL,
                    discord_avatar          TEXT,
                    answers                 TEXT NOT NULL,  -- JSON string
                    builders_club_at_submission INTEGER DEFAULT 0,
                    status                  TEXT NOT NULL DEFAULT 'pending',
                    -- pending | approved | denied | expired
                    submitted_at            TEXT NOT NULL,
                    expires_at              TEXT NOT NULL,
                    reviewed_at             TEXT,
                    reviewed_by             TEXT
                );

                CREATE TABLE IF NOT EXISTS verification_keys (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    discord_id      TEXT NOT NULL,
                    key_hash        TEXT NOT NULL UNIQUE,
                    builders_club   INTEGER DEFAULT 0,
                    status          TEXT NOT NULL DEFAULT 'active',
                    -- active | redeemed | expired
                    issued_at       TEXT NOT NULL,
                    expires_at      TEXT NOT NULL,
                    redeemed_at     TEXT
                );

                CREATE TABLE IF NOT EXISTS settings (
                    key     TEXT PRIMARY KEY,
                    value   TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS bans (
                    discord_id      TEXT PRIMARY KEY,
                    reason          TEXT,
                    banned_at       TEXT NOT NULL,
                    banned_by       TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS secret_records (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    discord_id      TEXT NOT NULL,
                    event_type      TEXT NOT NULL, -- 'ban', 'kick', 'warn', 'note'
                    content         TEXT NOT NULL,
                    recorded_at     TEXT NOT NULL,
                    recorded_by     TEXT NOT NULL
                );

                -- Default settings
                INSERT OR IGNORE INTO settings (key, value) VALUES ('builders_club_enabled', '0');
                INSERT OR IGNORE INTO settings (key, value) VALUES ('forms_locked', '0');
            """)
        log.info("Database initialised.")

    # ══════════════════════════════════════════════════════════
    #  SETTINGS
    # ══════════════════════════════════════════════════════════

    def set_builders_club(self, enabled: bool):
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO settings (key, value) VALUES ('builders_club_enabled', ?)",
                ("1" if enabled else "0",)
            )

    def is_builders_club_enabled(self) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT value FROM settings WHERE key = 'builders_club_enabled'"
            ).fetchone()
            return row and row["value"] == "1"

    def set_forms_locked(self, locked: bool, reason: str = "Users cannot submit join requests at this time."):
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO settings (key, value) VALUES ('forms_locked', ?)",
                ("1" if locked else "0",)
            )
            conn.execute(
                "INSERT OR REPLACE INTO settings (key, value) VALUES ('forms_lock_reason', ?)",
                (reason,)
            )

    def is_forms_locked(self) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT value FROM settings WHERE key = 'forms_locked'"
            ).fetchone()
            return bool(row and row["value"] == "1")

    def get_forms_lock_reason(self) -> str:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT value FROM settings WHERE key = 'forms_lock_reason'"
            ).fetchone()
            return row["value"] if row else "Users cannot submit join requests at this time."

    # ══════════════════════════════════════════════════════════
    #  BANS
    # ══════════════════════════════════════════════════════════

    def ban_user(self, discord_id: str, reason: str, banned_by: str):
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO bans (discord_id, reason, banned_at, banned_by) VALUES (?, ?, ?, ?)",
                (discord_id, reason, _iso(_utcnow()), banned_by)
            )
            # Add to Secret Records
            self.add_secret_record(discord_id, "ban", f"Banned for: {reason}", banned_by)

    def unban_user(self, discord_id: str):
        with self._connect() as conn:
            conn.execute("DELETE FROM bans WHERE discord_id = ?", (discord_id,))

    def add_secret_record(self, discord_id: str, event_type: str, content: str, recorded_by: str):
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO secret_records (discord_id, event_type, content, recorded_at, recorded_by) VALUES (?, ?, ?, ?, ?)",
                (discord_id, event_type, content, _iso(_utcnow()), recorded_by)
            )

    def get_secret_records(self, discord_id: str) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM secret_records WHERE discord_id = ? ORDER BY recorded_at DESC",
                (discord_id,)
            ).fetchall()
            return [dict(r) for r in rows]

    def is_banned(self, discord_id: str) -> bool:
        with self._connect() as conn:
            row = conn.execute("SELECT discord_id FROM bans WHERE discord_id = ?", (discord_id,)).fetchone()
            return row is not None

    def get_ban_info(self, discord_id: str) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM bans WHERE discord_id = ?", (discord_id,)).fetchone()
            return dict(row) if row else None

    # ══════════════════════════════════════════════════════════
    #  APPLICATIONS
    # ══════════════════════════════════════════════════════════

    def has_pending_application(self, discord_id: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id FROM applications WHERE discord_id = ? AND status = 'pending'",
                (discord_id,)
            ).fetchone()
            return row is not None

    def has_any_application(self, discord_id: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id FROM applications WHERE discord_id = ?",
                (discord_id,)
            ).fetchone()
            return row is not None

    def can_apply(self, discord_id: str) -> tuple[bool, str]:
        """
        Checks if a user is eligible to submit a new application.
        Returns (bool, reason_message).
        """
        if self.is_banned(discord_id):
            return False, "BANNED"
        
        if self.is_forms_locked():
            return False, "LOCKED"

        last_app = self.get_application(discord_id)
        if not last_app:
            return True, ""

        status = last_app["status"]
        
        if status == "pending":
            return False, "You already have a pending application. Please wait for review or for it to expire (7 days)."
        
        if status == "approved":
            # The requirement is: "if the user leaves the server, and rejoin and needs to verify they are able to submit an application."
            # We will handle the check of whether they are CURRENTLY in the server with a specific role in the bot logic,
            # but here in the database, we can allow re-application if they are approved but the bot explicitly requests a re-verify.
            # To simplify, we'll allow re-application for 'approved' users as long as they aren't banned/locked.
            return True, ""

        # Check for 7-day cooldown on denied or expired applications
        # The requirement says: "if denied they may resubmit a new request in 7 days"
        # and "if it hasnt been denied or accepted within 7 days, as this is when that application has expired"
        # This implies we check the last event time (reviewed_at or submitted_at/expires_at)
        
        last_event_str = last_app["reviewed_at"] or last_app["submitted_at"]
        last_event = _from_iso(last_event_str)
        cooldown_end = last_event + timedelta(seconds=Config.FORM_EXPIRY_SECONDS)
        
        if _utcnow() < cooldown_end:
            remaining = cooldown_end - _utcnow()
            days = remaining.days
            hours = remaining.seconds // 3600
            return False, f"You must wait {days}d {hours}h before submitting a new application."

        return True, ""

    def create_application(
        self,
        discord_id: str,
        discord_username: str,
        discord_avatar: Optional[str],
        answers: Dict[str, str],
    ) -> tuple[bool, str]:
        """
        Creates a new application. Returns (success, error_message).
        """
        can, reason = self.can_apply(discord_id)
        if not can:
            return False, reason

        import json
        now        = _utcnow()
        expires_at = now + timedelta(seconds=Config.FORM_EXPIRY_SECONDS)
        builders   = 1 if self.is_builders_club_enabled() else 0

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO applications
                    (discord_id, discord_username, discord_avatar, answers,
                     builders_club_at_submission, status, submitted_at, expires_at)
                VALUES (?, ?, ?, ?, ?, 'pending', ?, ?)
                """,
                (
                    discord_id,
                    discord_username,
                    discord_avatar,
                    json.dumps(answers),
                    builders,
                    _iso(now),
                    _iso(expires_at),
                )
            )
        log.info(f"Application created for {discord_username} ({discord_id})")
        return True, ""

    def get_application(self, discord_id: str) -> Optional[Dict[str, Any]]:
        import json
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM applications WHERE discord_id = ? ORDER BY id DESC LIMIT 1",
                (discord_id,)
            ).fetchone()
            if not row:
                return None
            d = dict(row)
            d["answers"] = json.loads(d["answers"])
            return d

    def get_pending_applications(self) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT discord_id, discord_username, submitted_at, expires_at "
                "FROM applications WHERE status = 'pending' ORDER BY submitted_at ASC"
            ).fetchall()
            return [dict(r) for r in rows]

    def approve_application(self, discord_id: str, reviewed_by: str) -> Optional[Dict[str, Any]]:
        """
        Approves a pending application, generates a verification key, and returns it.
        Returns None if no pending application exists.
        """
        app = self.get_application(discord_id)
        if not app or app["status"] != "pending":
            return None

        # Generate a cryptographically secure key
        raw_key  = secrets.token_hex(32)  # 64 hex chars
        key_hash = hashlib.sha256(raw_key.encode()).hexdigest()

        now        = _utcnow()
        expires_at = now + timedelta(seconds=Config.KEY_EXPIRY_SECONDS)
        builders   = app.get("builders_club_at_submission", 0)

        with self._connect() as conn:
            conn.execute(
                "UPDATE applications SET status = 'approved', reviewed_at = ?, reviewed_by = ? WHERE discord_id = ? AND status = 'pending'",
                (_iso(now), reviewed_by, discord_id)
            )
            conn.execute(
                """
                INSERT INTO verification_keys
                    (discord_id, key_hash, builders_club, status, issued_at, expires_at)
                VALUES (?, ?, ?, 'active', ?, ?)
                """,
                (discord_id, key_hash, builders, _iso(now), _iso(expires_at))
            )

        log.info(f"Application approved for {discord_id}. Key issued.")
        return {
            "key":                       raw_key,
            "builders_club_at_submission": bool(builders),
        }

    def deny_application(self, discord_id: str, reviewed_by: str) -> Optional[Dict[str, Any]]:
        app = self.get_application(discord_id)
        if not app or app["status"] != "pending":
            return None

        with self._connect() as conn:
            conn.execute(
                "UPDATE applications SET status = 'denied', reviewed_at = ?, reviewed_by = ? WHERE discord_id = ? AND status = 'pending'",
                (_iso(_utcnow()), reviewed_by, discord_id)
            )

        log.info(f"Application denied for {discord_id}.")
        return app

    def get_expired_pending_forms(self) -> List[Dict[str, Any]]:
        now = _iso(_utcnow())
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, discord_id FROM applications WHERE status = 'pending' AND expires_at < ?",
                (now,)
            ).fetchall()
            return [dict(r) for r in rows]

    def mark_form_expired(self, app_id: int):
        with self._connect() as conn:
            conn.execute(
                "UPDATE applications SET status = 'expired' WHERE id = ?",
                (app_id,)
            )

    # ══════════════════════════════════════════════════════════
    #  VERIFICATION KEYS
    # ══════════════════════════════════════════════════════════

    def redeem_key(self, raw_key: str, discord_id: str) -> Dict[str, Any]:
        """
        Attempts to redeem a key for a given Discord user.
        Returns a dict with 'status': one of:
          'success', 'invalid', 'expired', 'already_used', 'wrong_user'
        """
        key_hash = hashlib.sha256(raw_key.lower().encode()).hexdigest()

        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM verification_keys WHERE key_hash = ?",
                (key_hash,)
            ).fetchone()

            if not row:
                return {"status": "invalid"}

            entry = dict(row)

            if entry["discord_id"] != discord_id:
                return {"status": "wrong_user", "issued_to": entry["discord_id"]}

            if entry["status"] == "redeemed":
                return {"status": "already_used"}

            if entry["status"] == "expired":
                return {"status": "expired"}

            # Check expiry by time even if status wasn't updated yet
            if _from_iso(entry["expires_at"]) < _utcnow():
                conn.execute(
                    "UPDATE verification_keys SET status = 'expired' WHERE id = ?",
                    (entry["id"],)
                )
                return {"status": "expired"}

            # Mark as redeemed
            conn.execute(
                "UPDATE verification_keys SET status = 'redeemed', redeemed_at = ? WHERE id = ?",
                (_iso(_utcnow()), entry["id"])
            )

        log.info(f"Key redeemed successfully by {discord_id}")
        return {
            "status":       "success",
            "builders_club": bool(entry["builders_club"]),
        }

    def get_expired_keys(self) -> List[Dict[str, Any]]:
        now = _iso(_utcnow())
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, discord_id FROM verification_keys WHERE status = 'active' AND expires_at < ?",
                (now,)
            ).fetchall()
            return [dict(r) for r in rows]

    def mark_key_expired(self, key_id: int):
        with self._connect() as conn:
            conn.execute(
                "UPDATE verification_keys SET status = 'expired' WHERE id = ?",
                (key_id,)
            )

    # ══════════════════════════════════════════════════════════
    #  SESSION TOKENS (for OAuth flow)
    # ══════════════════════════════════════════════════════════

    def create_session(self, discord_id: str, discord_username: str, discord_avatar: Optional[str]) -> str:
        """Creates a short-lived session token after OAuth, returns the token."""
        import json
        token = secrets.token_urlsafe(48)
        expires_at = _iso(_utcnow() + timedelta(hours=2))

        with self._connect() as conn:
            # Store session in a simple settings-style table
            conn.execute(
                "CREATE TABLE IF NOT EXISTS sessions ("
                "  token TEXT PRIMARY KEY,"
                "  discord_id TEXT NOT NULL,"
                "  discord_username TEXT NOT NULL,"
                "  discord_avatar TEXT,"
                "  expires_at TEXT NOT NULL"
                ")"
            )
            conn.execute(
                "INSERT OR REPLACE INTO sessions (token, discord_id, discord_username, discord_avatar, expires_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (token, discord_id, discord_username, discord_avatar, expires_at)
            )

        return token

    def get_session(self, token: str) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS sessions ("
                "  token TEXT PRIMARY KEY,"
                "  discord_id TEXT NOT NULL,"
                "  discord_username TEXT NOT NULL,"
                "  discord_avatar TEXT,"
                "  expires_at TEXT NOT NULL"
                ")"
            )
            row = conn.execute(
                "SELECT * FROM sessions WHERE token = ?", (token,)
            ).fetchone()
            if not row:
                return None
            entry = dict(row)
            if _from_iso(entry["expires_at"]) < _utcnow():
                conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
                return None
            return entry

    def delete_session(self, token: str):
        with self._connect() as conn:
            conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
