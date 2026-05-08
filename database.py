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
                    discord_id              TEXT NOT NULL UNIQUE,
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

                -- Default settings
                INSERT OR IGNORE INTO settings (key, value) VALUES ('builders_club_enabled', '0');
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

    def create_application(
        self,
        discord_id: str,
        discord_username: str,
        discord_avatar: Optional[str],
        answers: Dict[str, str],
    ) -> bool:
        """
        Creates a new application. Returns False if one already exists (pending).
        """
        import json
        now        = _utcnow()
        expires_at = now + timedelta(seconds=Config.FORM_EXPIRY_SECONDS)
        builders   = 1 if self.is_builders_club_enabled() else 0

        try:
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
            return True
        except sqlite3.IntegrityError:
            log.warning(f"Duplicate application attempt for {discord_id}")
            return False

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

    def approve_application(self, discord_id: str) -> Optional[Dict[str, Any]]:
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
                "UPDATE applications SET status = 'approved', reviewed_at = ? WHERE discord_id = ?",
                (_iso(now), discord_id)
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

    def deny_application(self, discord_id: str) -> Optional[Dict[str, Any]]:
        app = self.get_application(discord_id)
        if not app or app["status"] != "pending":
            return None

        with self._connect() as conn:
            conn.execute(
                "UPDATE applications SET status = 'denied', reviewed_at = ? WHERE discord_id = ?",
                (_iso(_utcnow()), discord_id)
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
