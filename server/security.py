"""Passwords, signed tokens, roles and the per-institution permission matrix."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time

from .db import DATA_DIR

_key_file = DATA_DIR / "secret.key"
if os.environ.get("RICE_SECRET"):
    SECRET = os.environ["RICE_SECRET"].encode()
else:
    if not _key_file.exists():
        _key_file.write_text(secrets.token_hex(32))
    SECRET = _key_file.read_text().strip().encode()

TOKEN_TTL = 60 * 60 * 24 * 7


def hash_pw(pw: str, salt: str | None = None, rounds: int = 120_000) -> str:
    salt = salt or secrets.token_hex(8)
    dk = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), rounds)
    return f"pbkdf2${rounds}${salt}${dk.hex()}"


def check_pw(pw: str, stored: str | None) -> bool:
    if not stored or not stored.startswith("pbkdf2$"):
        return False
    _, rounds, salt, digest = stored.split("$")
    dk = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), int(rounds))
    return hmac.compare_digest(dk.hex(), digest)


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def make_token(uid: int) -> str:
    body = _b64(json.dumps({"u": uid, "exp": int(time.time()) + TOKEN_TTL}).encode())
    sig = _b64(hmac.new(SECRET, body.encode(), hashlib.sha256).digest())
    return f"{body}.{sig}"


def read_token(token: str) -> int | None:
    try:
        body, sig = token.split(".")
        good = _b64(hmac.new(SECRET, body.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(sig, good):
            return None
        data = json.loads(_unb64(body))
        if data["exp"] < time.time():
            return None
        return int(data["u"])
    except Exception:
        return None


# ── Roles ────────────────────────────────────────────────────────────────────
ROLES = {
    "platform_admin": {"label": "RICE platform admin", "short": "Platform", "rank": 100},
    "inst_admin": {"label": "Institution admin", "short": "Admin", "rank": 90},
    "hod": {"label": "Head of department", "short": "HoD", "rank": 70},
    "faculty": {"label": "Faculty", "short": "Faculty", "rank": 60},
    "staff": {"label": "Research staff", "short": "Staff", "rank": 40},
    "scholar": {"label": "Research scholar", "short": "Scholar", "rank": 35},
    "student": {"label": "Student", "short": "Student", "rank": 30},
    "external": {"label": "External partner", "short": "Partner", "rank": 10},
}
INSTITUTION_ROLES = [r for r in ROLES if r != "platform_admin"]

# ── Permissions ──────────────────────────────────────────────────────────────
PERMISSIONS = {
    "analytics.institution": ("Institution analytics", "See institution-wide dashboards and analysis"),
    "analytics.department": ("Department analytics", "See analysis for their own department"),
    "graph.institution": ("Institution graph", "Explore the collaboration graph inside the institution"),
    "graph.network": ("Network graph", "Explore collaborators at other RICE institutions"),
    "discover.experts": ("Expert finder", "Search experts and get collaborator suggestions"),
    "outputs.create": ("Add research", "Add publications, projects and patents"),
    "outputs.verify": ("Verify research", "Approve or reject submitted research records"),
    "opportunities.post": ("Post opportunities", "Publish calls, openings and collaboration asks"),
    "collab.request": ("Request collaboration", "Send collaboration requests to other researchers"),
    "network.benchmark": ("Benchmarking", "Compare the institution with peer institutions"),
    "reports.view": ("Reports", "Generate NAAC / NIRF / annual research reports"),
    "data.export": ("Export data", "Download tables as CSV"),
    "data.import": ("Import data", "Bulk-import people and publications"),
    "people.manage": ("Manage members", "Approve joins, change roles, deactivate members"),
    "settings.manage": ("Institution settings", "Branding, sharing policy and this permission matrix"),
    "audit.view": ("Audit log", "See who changed what"),
}

DEFAULT_MATRIX = {
    "inst_admin": list(PERMISSIONS),
    "hod": ["analytics.institution", "analytics.department", "graph.institution", "graph.network", "discover.experts",
            "outputs.create", "outputs.verify", "opportunities.post", "collab.request", "network.benchmark",
            "reports.view", "data.export"],
    "faculty": ["analytics.institution", "analytics.department", "graph.institution", "graph.network", "discover.experts",
                "outputs.create", "opportunities.post", "collab.request", "data.export"],
    "staff": ["analytics.department", "graph.institution", "discover.experts", "outputs.create", "opportunities.post"],
    "scholar": ["analytics.department", "graph.institution", "graph.network", "discover.experts", "outputs.create",
                "collab.request"],
    "student": ["graph.institution", "discover.experts", "outputs.create"],
    "external": ["discover.experts"],
}
# Permissions only the institution admin may ever hold (cannot be delegated).
LOCKED = {"people.manage", "settings.manage", "audit.view", "data.import"}

DEFAULT_SETTINGS = {
    "require_verification": True,
    "allow_signup": True,
    "matrix": DEFAULT_MATRIX,
}


def merged_settings(settings: dict | None) -> dict:
    s = json.loads(json.dumps(DEFAULT_SETTINGS))
    for k, v in (settings or {}).items():
        if k == "matrix" and isinstance(v, dict):
            for role, perms in v.items():
                if role in s["matrix"]:
                    s["matrix"][role] = [p for p in perms if p in PERMISSIONS]
        else:
            s[k] = v
    return s


def perms_for(role: str, settings: dict | None) -> set[str]:
    if role == "platform_admin":
        return set(PERMISSIONS)
    if role == "inst_admin":
        return set(PERMISSIONS)
    matrix = merged_settings(settings)["matrix"]
    return {p for p in matrix.get(role, []) if p not in LOCKED}


SHARE_LEVELS = {
    "private": "Nothing leaves the institution. Peers see only the name.",
    "summary": "Peers see aggregate numbers for benchmarking. No names.",
    "network": "Peers at RICE institutions see profiles and verified public research.",
    "public": "Everything in Network, plus a public showcase page anyone can open.",
}
LEVEL_ORDER = ["private", "summary", "network", "public"]


def shares_at_least(level: str, needed: str) -> bool:
    return LEVEL_ORDER.index(level or "private") >= LEVEL_ORDER.index(needed)
