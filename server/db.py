"""SQLite persistence + an in-memory snapshot used by analytics, graphs and search.

Writes go to SQLite and call bump(); readers call snapshot(), which is rebuilt
lazily whenever the data version changes.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)
DB_PATH = Path(os.environ.get("RICE_DB", DATA_DIR / "rice.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS institutions (
  id INTEGER PRIMARY KEY,
  code TEXT UNIQUE NOT NULL,
  name TEXT NOT NULL,
  short TEXT NOT NULL,
  city TEXT, state TEXT, country TEXT DEFAULT 'India',
  kind TEXT,                 -- University / Institute / College / External
  established INTEGER,
  brand TEXT DEFAULT '#2B59FF',
  share_level TEXT DEFAULT 'summary',  -- private | summary | network | public
  plan TEXT DEFAULT 'Campus',           -- Campus | Research+ | Enterprise | Tracked
  status TEXT DEFAULT 'active',         -- active | trial | suspended | tracked
  is_demo INTEGER DEFAULT 0,
  external INTEGER DEFAULT 0,           -- 1 = tracked externally (no tenant account)
  source TEXT,                          -- seed | onboarding | scival import ...
  lat REAL, lon REAL,
  tagline TEXT,
  settings TEXT DEFAULT '{}',
  created_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS departments (
  id INTEGER PRIMARY KEY,
  inst_id INTEGER NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  code TEXT NOT NULL,
  name TEXT NOT NULL,
  field TEXT
);
CREATE TABLE IF NOT EXISTS people (
  id INTEGER PRIMARY KEY,
  inst_id INTEGER REFERENCES institutions(id) ON DELETE CASCADE,
  dept_id INTEGER REFERENCES departments(id) ON DELETE SET NULL,
  name TEXT NOT NULL,
  email TEXT UNIQUE,
  pw_hash TEXT,
  role TEXT NOT NULL,          -- platform_admin inst_admin hod faculty scholar student staff external
  designation TEXT,
  interests TEXT DEFAULT '[]',
  orcid TEXT, scopus_id TEXT,
  joined INTEGER,
  supervisor_id INTEGER REFERENCES people(id) ON DELETE SET NULL,
  status TEXT DEFAULT 'active', -- active | pending | inactive | rejected
  requested_role TEXT,
  visibility TEXT DEFAULT 'network', -- network | internal
  hue INTEGER DEFAULT 210,
  bio TEXT,
  source TEXT DEFAULT 'seed',
  last_login TEXT,
  created_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS publications (
  id INTEGER PRIMARY KEY,
  inst_id INTEGER REFERENCES institutions(id) ON DELETE CASCADE,
  title TEXT NOT NULL,
  kind TEXT NOT NULL,          -- journal | conference | chapter | book | preprint
  venue TEXT, year INTEGER, quartile TEXT,
  citations INTEGER DEFAULT 0,
  doi TEXT,
  keywords TEXT DEFAULT '[]',
  sdgs TEXT DEFAULT '[]',
  open_access INTEGER DEFAULT 0,
  status TEXT DEFAULT 'verified', -- pending | verified | rejected
  visibility TEXT DEFAULT 'public',
  source TEXT DEFAULT 'seed',
  created_by INTEGER REFERENCES people(id) ON DELETE SET NULL,
  verified_by INTEGER REFERENCES people(id) ON DELETE SET NULL,
  created_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS pub_authors (
  pub_id INTEGER NOT NULL REFERENCES publications(id) ON DELETE CASCADE,
  position INTEGER NOT NULL,
  person_id INTEGER REFERENCES people(id) ON DELETE CASCADE,
  ext_name TEXT, ext_affil TEXT, ext_country TEXT
);
CREATE TABLE IF NOT EXISTS projects (
  id INTEGER PRIMARY KEY,
  inst_id INTEGER REFERENCES institutions(id) ON DELETE CASCADE,
  title TEXT NOT NULL,
  agency TEXT, scheme TEXT, sector TEXT,     -- sector: government | industry | international | internal
  amount REAL DEFAULT 0,                     -- in lakh INR
  start_year INTEGER, end_year INTEGER,
  stage TEXT DEFAULT 'ongoing',              -- submitted | ongoing | completed | not_funded
  keywords TEXT DEFAULT '[]',
  status TEXT DEFAULT 'verified',
  created_by INTEGER REFERENCES people(id) ON DELETE SET NULL,
  created_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS project_members (
  project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  person_id INTEGER NOT NULL REFERENCES people(id) ON DELETE CASCADE,
  role TEXT DEFAULT 'Member'                 -- PI | Co-PI | Scholar | Member
);
CREATE TABLE IF NOT EXISTS patents (
  id INTEGER PRIMARY KEY,
  inst_id INTEGER REFERENCES institutions(id) ON DELETE CASCADE,
  title TEXT NOT NULL,
  stage TEXT DEFAULT 'filed',                -- filed | published | granted
  year INTEGER, number TEXT,
  keywords TEXT DEFAULT '[]',
  status TEXT DEFAULT 'verified',
  created_by INTEGER REFERENCES people(id) ON DELETE SET NULL,
  created_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS patent_inventors (
  patent_id INTEGER NOT NULL REFERENCES patents(id) ON DELETE CASCADE,
  person_id INTEGER NOT NULL REFERENCES people(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS opportunities (
  id INTEGER PRIMARY KEY,
  inst_id INTEGER REFERENCES institutions(id) ON DELETE CASCADE,
  posted_by INTEGER REFERENCES people(id) ON DELETE SET NULL,
  kind TEXT,                    -- call | position | collab | event
  title TEXT NOT NULL, body TEXT,
  tags TEXT DEFAULT '[]',
  deadline TEXT,
  audience TEXT DEFAULT 'internal', -- internal | network
  status TEXT DEFAULT 'open',       -- open | closed | pending
  created_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS opportunity_interest (
  opp_id INTEGER NOT NULL REFERENCES opportunities(id) ON DELETE CASCADE,
  person_id INTEGER NOT NULL REFERENCES people(id) ON DELETE CASCADE,
  note TEXT,
  created_at TEXT DEFAULT (datetime('now')),
  UNIQUE(opp_id, person_id)
);
CREATE TABLE IF NOT EXISTS collab_requests (
  id INTEGER PRIMARY KEY,
  from_id INTEGER NOT NULL REFERENCES people(id) ON DELETE CASCADE,
  to_id INTEGER NOT NULL REFERENCES people(id) ON DELETE CASCADE,
  topic TEXT, message TEXT,
  status TEXT DEFAULT 'pending',   -- pending | accepted | declined
  created_at TEXT DEFAULT (datetime('now')),
  responded_at TEXT
);
CREATE TABLE IF NOT EXISTS onboarding_requests (
  id INTEGER PRIMARY KEY,
  inst_name TEXT NOT NULL, city TEXT, state TEXT, kind TEXT,
  contact_name TEXT, contact_email TEXT, contact_role TEXT,
  size TEXT, message TEXT,
  status TEXT DEFAULT 'new',       -- new | approved | declined
  created_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS notifications (
  id INTEGER PRIMARY KEY,
  person_id INTEGER NOT NULL REFERENCES people(id) ON DELETE CASCADE,
  kind TEXT, text TEXT, link TEXT,
  read INTEGER DEFAULT 0,
  created_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS audit (
  id INTEGER PRIMARY KEY,
  inst_id INTEGER,
  actor_id INTEGER,
  action TEXT, target TEXT, detail TEXT,
  created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS ix_people_inst ON people(inst_id);
CREATE INDEX IF NOT EXISTS ix_people_dept ON people(dept_id);
CREATE INDEX IF NOT EXISTS ix_pa_pub ON pub_authors(pub_id);
CREATE INDEX IF NOT EXISTS ix_pa_person ON pub_authors(person_id);
CREATE INDEX IF NOT EXISTS ix_pm_project ON project_members(project_id);
CREATE INDEX IF NOT EXISTS ix_pm_person ON project_members(person_id);
CREATE INDEX IF NOT EXISTS ix_notif_person ON notifications(person_id);
CREATE INDEX IF NOT EXISTS ix_audit_inst ON audit(inst_id);
"""

_lock = threading.RLock()
_version = 0
_snapshot = None


def connect() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    return con


def init_schema(con: sqlite3.Connection) -> None:
    con.executescript(SCHEMA)
    con.execute("PRAGMA journal_mode=WAL")


def rows(con, sql, args=()):
    return [dict(r) for r in con.execute(sql, args)]


def one(con, sql, args=()):
    r = con.execute(sql, args).fetchone()
    return dict(r) if r else None


def scalar(con, sql, args=()):
    r = con.execute(sql, args).fetchone()
    return r[0] if r else None


def jl(s, default=None):
    if s is None or s == "":
        return [] if default is None else default
    try:
        return json.loads(s)
    except (ValueError, TypeError):
        return [] if default is None else default


def jd(o) -> str:
    return json.dumps(o, ensure_ascii=False)


def bump() -> None:
    """Mark data as changed so the snapshot and every derived cache rebuild."""
    global _version
    with _lock:
        _version += 1


def version() -> int:
    return _version


class Snapshot:
    """Denormalised, read-only view of everything analytics needs."""

    def __init__(self, con):
        self.version = _version
        self.inst = {r["id"]: {**r, "settings": jl(r["settings"], {})} for r in rows(con, "SELECT * FROM institutions")}
        self.dept = {r["id"]: r for r in rows(con, "SELECT * FROM departments")}
        self.people = {}
        for r in rows(con, "SELECT id, inst_id, dept_id, name, email, role, designation, interests, orcid, scopus_id, joined, supervisor_id, status, visibility, hue, source, bio FROM people"):
            r["interests"] = jl(r["interests"])
            r["pubs"] = []
            r["projects"] = []
            r["patents"] = []
            r["students"] = []
            self.people[r["id"]] = r
        for p in self.people.values():
            sup = p.get("supervisor_id")
            if sup and sup in self.people:
                self.people[sup]["students"].append(p["id"])

        self.pubs = {}
        for r in rows(con, "SELECT * FROM publications"):
            r["keywords"] = jl(r["keywords"])
            r["sdgs"] = jl(r["sdgs"])
            r["authors"] = []      # internal person ids in order
            r["ext"] = []          # external authors
            r["insts"] = set()     # RICE institutions involved
            r["depts"] = set()
            self.pubs[r["id"]] = r
        for a in rows(con, "SELECT * FROM pub_authors ORDER BY pub_id, position"):
            p = self.pubs.get(a["pub_id"])
            if not p:
                continue
            pid = a["person_id"]
            if pid and pid in self.people:
                p["authors"].append(pid)
                person = self.people[pid]
                p["insts"].add(person["inst_id"])
                if person["dept_id"]:
                    p["depts"].add(person["dept_id"])
                person["pubs"].append(p["id"])
            else:
                p["ext"].append({"name": a["ext_name"], "affil": a["ext_affil"], "country": a["ext_country"]})
        for p in self.pubs.values():
            p["international"] = any((e.get("country") or "India") != "India" for e in p["ext"])
            p["external_affils"] = sorted({e["affil"] for e in p["ext"] if e.get("affil")})

        self.projects = {}
        for r in rows(con, "SELECT * FROM projects"):
            r["keywords"] = jl(r["keywords"])
            r["members"] = []
            r["insts"] = set()
            r["depts"] = set()
            self.projects[r["id"]] = r
        for m in rows(con, "SELECT * FROM project_members"):
            pr = self.projects.get(m["project_id"])
            person = self.people.get(m["person_id"])
            if not pr or not person:
                continue
            pr["members"].append({"id": m["person_id"], "role": m["role"]})
            pr["insts"].add(person["inst_id"])
            if person["dept_id"]:
                pr["depts"].add(person["dept_id"])
            person["projects"].append(pr["id"])

        self.patents = {}
        for r in rows(con, "SELECT * FROM patents"):
            r["keywords"] = jl(r["keywords"])
            r["inventors"] = []
            r["insts"] = set()
            r["depts"] = set()
            self.patents[r["id"]] = r
        for m in rows(con, "SELECT * FROM patent_inventors"):
            pt = self.patents.get(m["patent_id"])
            person = self.people.get(m["person_id"])
            if not pt or not person:
                continue
            pt["inventors"].append(m["person_id"])
            pt["insts"].add(person["inst_id"])
            if person["dept_id"]:
                pt["depts"].add(person["dept_id"])
            person["patents"].append(pt["id"])

        years = [p["year"] for p in self.pubs.values() if p["year"]]
        self.min_year = min(years) if years else 2016
        self.max_year = max(years) if years else 2026


def snapshot() -> Snapshot:
    global _snapshot
    with _lock:
        if _snapshot is None or _snapshot.version != _version:
            con = connect()
            try:
                _snapshot = Snapshot(con)
            finally:
                con.close()
        return _snapshot


_caches: dict = {}


def cached(key, fn):
    """Memoise fn() for the current data version."""
    with _lock:
        hit = _caches.get(key)
        if hit and hit[0] == _version:
            return hit[1]
    val = fn()
    with _lock:
        if len(_caches) > 400:
            _caches.clear()
        _caches[key] = (_version, val)
    return val
