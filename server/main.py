"""RICE — Research Intelligence & Collaboration Engine. FastAPI application."""
from __future__ import annotations

import csv
import io
import os
import re
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import analytics as A
from . import db, graphs, importers, intel, neo, reports
from .catalog import AGENCIES, DEPARTMENTS, SDG_NAMES, sdgs_for
from .security import (INSTITUTION_ROLES, LEVEL_ORDER, LOCKED, PERMISSIONS, ROLES, SHARE_LEVELS, check_pw, hash_pw,
                       make_token, merged_settings, perms_for, read_token, shares_at_least)

WEB = db.ROOT / "web"
DEMO_ENABLED = os.environ.get("RICE_DEMO", "1") == "1"
NOW_YEAR = 2026

app = FastAPI(title="RICE — Research Intelligence & Collaboration Engine", version="2.0")


def _ensure_db():
    if not db.DB_PATH.exists():
        from .seed import build
        build(quiet=True)
    con = db.connect()
    db.init_schema(con)
    con.close()


_ensure_db()


_cors = [o.strip() for o in os.environ.get("RICE_CORS_ORIGINS", "").split(",") if o.strip()]
if _cors:  # the GitHub Pages site calls this API from another origin; bearer tokens, no cookies
    from fastapi.middleware.cors import CORSMiddleware
    app.add_middleware(CORSMiddleware, allow_origins=_cors, allow_methods=["*"], allow_headers=["*"],
                       expose_headers=["Content-Disposition"], max_age=86400)


@app.middleware("http")
async def _revalidate_assets(request: Request, call_next):
    """Browsers must revalidate app code (cheap 304s) so a redeploy is never half-cached."""
    resp = await call_next(request)
    if request.url.path.startswith("/assets/js/") or request.url.path.startswith("/assets/css/"):
        resp.headers["Cache-Control"] = "no-cache"
    return resp


@app.exception_handler(HTTPException)
async def _http_error(request: Request, exc: HTTPException):
    return JSONResponse({"error": exc.detail}, status_code=exc.status_code)


def get_con():
    con = db.connect()
    try:
        yield con
    finally:
        con.close()


# ── request context ──────────────────────────────────────────────────────────
class Ctx:
    def __init__(self, user, inst, perms, settings):
        self.user = user
        self.uid = user["id"]
        self.role = user["role"]
        self.platform = user["role"] == "platform_admin"
        self.inst = inst
        self.inst_id = inst["id"] if inst else None
        self.perms = perms
        self.settings = settings

    def can(self, perm):
        return perm in self.perms

    def need(self, perm):
        if perm not in self.perms:
            raise HTTPException(403, f"Your role doesn't include “{PERMISSIONS[perm][0]}”. Ask your institution admin.")

    def visible(self, level="network"):
        """Institutions whose data this user may see at the given sharing level (reciprocal)."""
        if self.platform:
            return set(db.snapshot().inst)
        return visible_for(self.inst_id, self.inst["share_level"] if self.inst else "private", level)


def visible_for(inst_id, own_level, level="network"):
    """Reciprocal sharing: an institution sees peers at most at the level it shares itself."""
    s = db.snapshot()
    eff = level if LEVEL_ORDER.index(own_level) >= LEVEL_ORDER.index(level) else own_level
    out = {inst_id}
    for i in s.inst.values():
        if i["id"] == inst_id:
            continue
        if i["external"]:
            owner = i["settings"].get("owner_inst")
            if owner in (None, inst_id) and level != "summary":
                out.add(i["id"])
            continue
        if i["status"] != "active" or eff == "private":
            continue
        if shares_at_least(i["share_level"], eff):
            out.add(i["id"])
    return out


def _warm_graphs():
    """Pre-compute each campus's default graph views right after the first Neo4j sync."""
    s = db.snapshot()
    y0, y1 = max(2015, s.min_year), s.max_year
    for i in s.inst.values():
        if i["external"] or i["status"] != "active":
            continue
        own = A.Scope(frozenset([i["id"]]), y0=y0, y1=y1)
        neo.NEO.people_view(s, own, include_students=True, min_weight=1.0)
        net = frozenset(x for x in visible_for(i["id"], i["share_level"], "network") if not s.inst[x]["external"])
        if len(net) > 1:
            neo.NEO.people_view(s, A.Scope(net, y0=y0, y1=y1), include_students=True, min_weight=1.0)
        neo.NEO.topic_view(s, own)


neo.WARMERS.append(_warm_graphs)


def ctx(request: Request, con=Depends(get_con)) -> Ctx:
    auth = request.headers.get("authorization", "")
    token = auth[7:] if auth.lower().startswith("bearer ") else request.query_params.get("token", "")
    uid = read_token(token) if token else None
    if not uid:
        raise HTTPException(401, "Sign in to continue.")
    user = db.one(con, "SELECT * FROM people WHERE id=?", (uid,))
    if not user or user["status"] != "active":
        raise HTTPException(401, "This account is not active.")
    user["interests"] = db.jl(user["interests"])
    inst = None
    if user["role"] == "platform_admin":
        want = request.headers.get("x-rice-inst") or request.query_params.get("inst")
        if want and want.isdigit():
            inst = db.one(con, "SELECT * FROM institutions WHERE id=?", (int(want),))
        if not inst:
            inst = db.one(con, "SELECT * FROM institutions WHERE external=0 ORDER BY id LIMIT 1")
    elif user["inst_id"]:
        inst = db.one(con, "SELECT * FROM institutions WHERE id=?", (user["inst_id"],))
        if inst and inst["status"] == "suspended":
            raise HTTPException(403, "This institution's RICE subscription is suspended. Contact your institution admin.")
    settings = merged_settings(db.jl(inst["settings"], {}) if inst else {})
    if inst:
        inst["settings"] = settings
    return Ctx(user, inst, perms_for(user["role"], settings), settings)


def audit(con, c: Ctx, action, target, detail=""):
    con.execute("INSERT INTO audit (inst_id, actor_id, action, target, detail) VALUES (?,?,?,?,?)",
                (c.inst_id, c.uid, action, target, detail))


def notify(con, pid, kind, text, link):
    con.execute("INSERT INTO notifications (person_id, kind, text, link) VALUES (?,?,?,?)", (pid, kind, text, link))


def person_public(s, pid):
    p = s.people[pid]
    d = s.dept.get(p["dept_id"])
    inst = s.inst.get(p["inst_id"]) or {}
    return {"id": pid, "name": p["name"], "role": p["role"], "role_label": ROLES[p["role"]]["label"],
            "designation": p["designation"], "hue": p["hue"], "inst": inst.get("short"), "inst_name": inst.get("name"),
            "inst_id": p["inst_id"], "brand": inst.get("brand"), "dept": d["code"] if d else "",
            "dept_name": d["name"] if d else "", "dept_id": p["dept_id"], "interests": p["interests"]}


# ── scope resolution ─────────────────────────────────────────────────────────
def resolve_scope(c: Ctx, scope="institution", dept: int | None = None, person: int | None = None,
                  y0: int | None = None, y1: int | None = None, pending: bool = False) -> tuple[A.Scope, str]:
    s = db.snapshot()
    y0 = y0 or max(2015, s.min_year)
    y1 = y1 or s.max_year
    if y0 > y1:
        y0, y1 = y1, y0
    own = frozenset([c.inst_id]) if c.inst_id else frozenset()
    if scope == "network":
        if not c.platform:
            raise HTTPException(403, "Network-wide analytics are available to the RICE platform team.")
        ids = frozenset(i for i, x in s.inst.items() if not x["external"])
        return A.Scope(ids, y0=y0, y1=y1, verified_only=not pending), "the RICE network"
    if scope == "me" or (scope == "person" and person in (None, c.uid)):
        return A.Scope(own, person=c.uid, y0=y0, y1=y1, verified_only=not pending), "You"
    if scope == "person":
        if person not in s.people:
            raise HTTPException(404, "Person not found.")
        if s.people[person]["inst_id"] not in c.visible("network"):
            raise HTTPException(403, "This profile isn't shared with your institution.")
        return A.Scope(frozenset([s.people[person]["inst_id"]]), person=person, y0=y0, y1=y1,
                       verified_only=True), s.people[person]["name"]
    if scope == "department" or (scope == "institution" and not c.can("analytics.institution")):
        if not (c.can("analytics.department") or c.can("analytics.institution")):
            raise HTTPException(403, "Your role can see only your own research. Open “My research” instead.")
        d = dept or c.user.get("dept_id")
        if d and not c.can("analytics.institution") and d != c.user.get("dept_id"):
            raise HTTPException(403, "You can analyse only your own department.")
        if not d:
            raise HTTPException(400, "Pick a department.")
        if d not in s.dept or s.dept[d]["inst_id"] != c.inst_id:
            raise HTTPException(404, "Department not found in this institution.")
        return A.Scope(own, frozenset([d]), y0=y0, y1=y1, verified_only=not pending), s.dept[d]["name"]
    c.need("analytics.institution")
    return A.Scope(own, y0=y0, y1=y1, verified_only=not pending), c.inst["short"] if c.inst else ""


# ── public endpoints ─────────────────────────────────────────────────────────
PERSONAS = [
    ("platform", "admin@rice.demo", "RICE platform team", "Onboard institutions, watch the whole network"),
    ("inst_admin", "research.cell@kavu.demo", "Dean (Research), Kaveri University", "Control members, sharing, approvals and reports"),
    ("hod", "hod.cse@kavu.demo", "Head of CSE, Kaveri University", "Verify department records, compare departments"),
    ("faculty", "prof@kavu.demo", "Professor, Kaveri University", "Your research, collaborators and requests"),
    ("scholar", "scholar@kavu.demo", "PhD scholar, Kaveri University", "Find mentors, openings and co-authors"),
    ("student", "student@kavu.demo", "Student, Kaveri University", "Join projects and discover labs"),
    ("partner", "partner@rice.demo", "Industry partner", "Find experts for an industry problem"),
    ("peer_admin", "admin@wgit.demo", "Admin, Western Ghats Inst. of Technology", "See tenant isolation from another campus"),
]


@app.get("/api/health")
def health():
    return {"ok": True, "version": app.version, "data_version": db.version()}


@app.get("/api/public/landing")
def landing(con=Depends(get_con)):
    s = db.snapshot()
    tenants = [i for i in s.inst.values() if not i["external"] and i["status"] == "active"]
    return {
        "stats": {"institutions": len(tenants), "tracked": sum(1 for i in s.inst.values() if i["external"]),
                  "researchers": sum(1 for p in s.people.values() if p["status"] == "active" and p["role"] in A.RESEARCHER_ROLES),
                  "publications": sum(1 for p in s.pubs.values() if p["status"] == "verified"),
                  "links": sum(len(p["authors"]) * (len(p["authors"]) - 1) // 2 for p in s.pubs.values()),
                  "funding_crore": round(sum(p["amount"] for p in s.projects.values() if p["stage"] in ("ongoing", "completed")) / 100, 1)},
        "institutions": [{"id": i["id"], "name": i["name"], "short": i["short"], "city": i["city"], "brand": i["brand"],
                          "share_level": i["share_level"], "showcase": i["share_level"] == "public"} for i in tenants],
        "personas": [{"key": k, "email": e, "title": t, "blurb": b} for k, e, t, b in PERSONAS] if DEMO_ENABLED else [],
        "demo": DEMO_ENABLED,
    }


class LoginIn(BaseModel):
    email: str
    password: str


def _login_response(con, user):
    con.execute("UPDATE people SET last_login=datetime('now') WHERE id=?", (user["id"],))
    con.commit()
    return {"token": make_token(user["id"])}


@app.post("/api/auth/login")
def login(body: LoginIn, con=Depends(get_con)):
    user = db.one(con, "SELECT * FROM people WHERE lower(email)=lower(?)", (body.email.strip(),))
    if not user or not check_pw(body.password, user["pw_hash"]):
        raise HTTPException(401, "That email and password don't match.")
    if user["status"] == "pending":
        raise HTTPException(403, "Your request to join is waiting for approval from your institution admin.")
    if user["status"] != "active":
        raise HTTPException(403, "This account has been deactivated by your institution admin.")
    return _login_response(con, user)


class DemoIn(BaseModel):
    persona: str


@app.post("/api/auth/demo")
def demo_login(body: DemoIn, con=Depends(get_con)):
    if not DEMO_ENABLED:
        raise HTTPException(404, "Demo sign-in is turned off.")
    email = next((e for k, e, *_ in PERSONAS if k == body.persona), None)
    user = db.one(con, "SELECT * FROM people WHERE email=?", (email,)) if email else None
    if not user:
        raise HTTPException(404, "Unknown demo persona.")
    return _login_response(con, user)


class SignupIn(BaseModel):
    name: str = Field(min_length=2)
    email: str
    password: str = Field(min_length=8)
    institution_id: int
    dept_id: int | None = None
    role: str = "scholar"
    designation: str | None = None
    interests: list[str] = []


@app.post("/api/auth/signup")
def signup(body: SignupIn, con=Depends(get_con)):
    inst = db.one(con, "SELECT * FROM institutions WHERE id=? AND external=0 AND status='active'", (body.institution_id,))
    if not inst:
        raise HTTPException(404, "Institution not found.")
    settings = merged_settings(db.jl(inst["settings"], {}))
    if not settings.get("allow_signup", True):
        raise HTTPException(403, f"{inst['name']} adds members by invitation only.")
    if body.role not in ("faculty", "scholar", "student", "staff"):
        raise HTTPException(400, "Choose faculty, scholar, student or staff.")
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", body.email):
        raise HTTPException(400, "Enter a valid email address.")
    if db.scalar(con, "SELECT 1 FROM people WHERE lower(email)=lower(?)", (body.email,)):
        raise HTTPException(409, "An account with this email already exists.")
    cur = con.execute("INSERT INTO people (inst_id, dept_id, name, email, pw_hash, role, requested_role, designation, interests, "
                      "status, source, joined, hue) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                      (inst["id"], body.dept_id, body.name.strip(), body.email.strip().lower(), hash_pw(body.password),
                       body.role, body.role, body.designation or ROLES[body.role]["label"], db.jd(body.interests[:8]),
                       "pending", "signup", NOW_YEAR, hash(body.email) % 360))
    for a in db.rows(con, "SELECT id FROM people WHERE inst_id=? AND role='inst_admin' AND status='active'", (inst["id"],)):
        notify(con, a["id"], "join", f"{body.name} asked to join as {ROLES[body.role]['label'].lower()}", "#/approvals")
    con.commit()
    db.bump()
    return {"ok": True, "pending": True, "id": cur.lastrowid,
            "message": f"Request sent. An admin at {inst['short']} will approve your account."}


@app.get("/api/public/institutions/{iid}/departments")
def public_departments(iid: int, con=Depends(get_con)):
    return db.rows(con, "SELECT id, code, name FROM departments WHERE inst_id=? ORDER BY name", (iid,))


class OnboardIn(BaseModel):
    inst_name: str = Field(min_length=3)
    city: str = ""
    state: str = ""
    kind: str = "College"
    contact_name: str = Field(min_length=2)
    contact_email: str
    contact_role: str = ""
    size: str = ""
    message: str = ""


@app.post("/api/public/onboarding")
def onboarding_request(body: OnboardIn, con=Depends(get_con)):
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", body.contact_email):
        raise HTTPException(400, "Enter a valid email address.")
    con.execute("INSERT INTO onboarding_requests (inst_name, city, state, kind, contact_name, contact_email, contact_role, size, message) "
                "VALUES (?,?,?,?,?,?,?,?,?)", (body.inst_name, body.city, body.state, body.kind, body.contact_name,
                                                body.contact_email, body.contact_role, body.size, body.message))
    for a in db.rows(con, "SELECT id FROM people WHERE role='platform_admin'"):
        notify(con, a["id"], "onboarding", f"{body.inst_name} asked to join RICE", "#/platform")
    con.commit()
    return {"ok": True, "message": "Thanks — the RICE team will set up your workspace and email you."}


@app.get("/api/public/showcase/{code}")
def showcase(code: str):
    s = db.snapshot()
    inst = next((i for i in s.inst.values() if i["code"].lower() == code.lower()), None)
    if not inst or inst["share_level"] != "public" or inst["external"]:
        raise HTTPException(404, "This institution doesn't publish a public showcase.")
    sc = A.Scope(frozenset([inst["id"]]), y0=2019, y1=s.max_year)
    ov = A.overview(s, sc)
    tp = A.topics(s, sc)
    pubs = sorted([p for p in A.pubs_in(s, sc) if p["visibility"] == "public"], key=lambda p: -p["citations"])[:8]
    return {"institution": {k: inst[k] for k in ("id", "name", "short", "city", "state", "brand", "tagline", "established", "kind")},
            "kpis": ov["kpis"], "trend": ov["trend"], "topics": tp["topics"][:20], "sdg": tp["sdg"],
            "papers": [A.pub_card(s, p) for p in pubs],
            "departments": [{"code": d["code"], "name": d["name"]} for d in s.dept.values() if d["inst_id"] == inst["id"]]}


# ── me ───────────────────────────────────────────────────────────────────────
@app.get("/api/me")
def me(c: Ctx = Depends(ctx), con=Depends(get_con)):
    s = db.snapshot()
    u = {k: c.user[k] for k in ("id", "name", "email", "role", "designation", "dept_id", "interests", "orcid", "scopus_id",
                                 "visibility", "hue", "bio", "inst_id", "supervisor_id")}
    u["role_label"] = ROLES[c.role]["label"]
    u["dept"] = (s.dept.get(c.user["dept_id"]) or {}).get("name")
    inst = None
    if c.inst:
        inst = {k: c.inst[k] for k in ("id", "code", "name", "short", "city", "state", "brand", "share_level", "plan", "status",
                                        "tagline", "established", "kind")}
        inst["require_verification"] = c.settings.get("require_verification", True)
    tenants = []
    if c.platform:
        tenants = [{"id": i["id"], "short": i["short"], "name": i["name"], "brand": i["brand"]}
                   for i in s.inst.values() if not i["external"]]
    unread = db.scalar(con, "SELECT COUNT(*) FROM notifications WHERE person_id=? AND read=0", (c.uid,))
    return {
        "user": u, "inst": inst, "perms": sorted(c.perms), "tenants": tenants, "unread": unread,
        "departments": [{"id": d["id"], "code": d["code"], "name": d["name"], "field": d["field"]}
                        for d in s.dept.values() if d["inst_id"] == c.inst_id],
        "roles": {k: v["label"] for k, v in ROLES.items()},
        "permissions": {k: {"label": v[0], "help": v[1], "locked": k in LOCKED} for k, v in PERMISSIONS.items()},
        "share_levels": SHARE_LEVELS,
        "years": [max(2015, s.min_year), s.max_year],
        "agencies": list(AGENCIES), "sdgs": SDG_NAMES,
        "topics": sorted({t for d in DEPARTMENTS.values() for t in d[2]}),
        "graph_engine": engine_badge(),
    }


class MeIn(BaseModel):
    designation: str | None = None
    interests: list[str] | None = None
    bio: str | None = None
    orcid: str | None = None
    scopus_id: str | None = None
    visibility: str | None = None


@app.patch("/api/me")
def update_me(body: MeIn, c: Ctx = Depends(ctx), con=Depends(get_con)):
    data = body.model_dump(exclude_none=True)
    if "visibility" in data and data["visibility"] not in ("network", "internal"):
        raise HTTPException(400, "Visibility must be network or internal.")
    if "orcid" in data and data["orcid"] and not re.fullmatch(r"\d{4}-\d{4}-\d{4}-\d{3}[\dX]", data["orcid"].strip()):
        raise HTTPException(400, "ORCID should look like 0000-0002-1825-0097.")
    if "interests" in data:
        data["interests"] = db.jd([t.strip() for t in data["interests"] if t.strip()][:10])
    if not data:
        return {"ok": True}
    sets = ", ".join(f"{k}=?" for k in data)
    con.execute(f"UPDATE people SET {sets} WHERE id=?", (*data.values(), c.uid))
    con.commit()
    db.bump()
    return {"ok": True}


class PwIn(BaseModel):
    current: str
    new: str = Field(min_length=8)


@app.post("/api/me/password")
def change_password(body: PwIn, c: Ctx = Depends(ctx), con=Depends(get_con)):
    if not check_pw(body.current, c.user["pw_hash"]):
        raise HTTPException(400, "Your current password is incorrect.")
    con.execute("UPDATE people SET pw_hash=? WHERE id=?", (hash_pw(body.new), c.uid))
    con.commit()
    return {"ok": True}


@app.get("/api/notifications")
def notifications(c: Ctx = Depends(ctx), con=Depends(get_con)):
    return db.rows(con, "SELECT * FROM notifications WHERE person_id=? ORDER BY created_at DESC LIMIT 40", (c.uid,))


@app.post("/api/notifications/read")
def notifications_read(c: Ctx = Depends(ctx), con=Depends(get_con)):
    con.execute("UPDATE notifications SET read=1 WHERE person_id=?", (c.uid,))
    con.commit()
    return {"ok": True}


# ── dashboard ────────────────────────────────────────────────────────────────
def _tasks(c: Ctx, con):
    t = []
    if c.can("outputs.verify"):
        n = len(_pending_records(c, con))
        if n:
            t.append({"kind": "verify", "count": n, "text": f"{n} research record{'s' if n != 1 else ''} to verify", "link": "#/approvals"})
    if c.can("people.manage"):
        n = db.scalar(con, "SELECT COUNT(*) FROM people WHERE inst_id=? AND status='pending'", (c.inst_id,))
        if n:
            t.append({"kind": "join", "count": n, "text": f"{n} member request{'s' if n != 1 else ''} to approve", "link": "#/approvals"})
        n = db.scalar(con, "SELECT COUNT(*) FROM opportunities WHERE inst_id=? AND status='pending'", (c.inst_id,))
        if n:
            t.append({"kind": "opportunity", "count": n, "text": f"{n} opportunity post{'s' if n != 1 else ''} awaiting approval", "link": "#/approvals"})
    n = db.scalar(con, "SELECT COUNT(*) FROM collab_requests WHERE to_id=? AND status='pending'", (c.uid,))
    if n:
        t.append({"kind": "collab", "count": n, "text": f"{n} collaboration request{'s' if n != 1 else ''} for you", "link": "#/collaborate"})
    n = db.scalar(con, "SELECT COUNT(*) FROM publications WHERE created_by=? AND status='pending'", (c.uid,))
    if n:
        t.append({"kind": "mine", "count": n, "text": f"{n} of your records await verification", "link": "#/repository?status=pending&mine=1"})
    if c.platform:
        n = db.scalar(con, "SELECT COUNT(*) FROM onboarding_requests WHERE status='new'")
        if n:
            t.append({"kind": "onboarding", "count": n, "text": f"{n} institution{'s' if n != 1 else ''} asked to join RICE", "link": "#/platform"})
    return t


@app.get("/api/dashboard")
def dashboard(c: Ctx = Depends(ctx), con=Depends(get_con)):
    s = db.snapshot()
    out = {"tasks": _tasks(c, con)}
    if c.can("analytics.institution"):
        sc, name = resolve_scope(c, "institution")
        out["scope"] = {"kind": "institution", "name": c.inst["name"]}
    elif c.can("analytics.department") and c.user.get("dept_id"):
        sc, name = resolve_scope(c, "department")
        out["scope"] = {"kind": "department", "name": name}
    else:
        sc, name = resolve_scope(c, "me")
        out["scope"] = {"kind": "me", "name": "Your research"}
    ov = A.overview(s, sc)
    out["kpis"], out["trend"] = ov["kpis"], ov["trend"]
    out["collab"] = ov["collab"]
    out["insights"] = A.insights(s, sc, name if sc.person is None else "You")
    tp = A.topics(s, sc)
    out["rising"] = tp["rising"][:6]
    out["top_topics"] = tp["topics"][:12]
    if c.role in A.RESEARCHER_ROLES and c.uid in s.people:
        out["me"] = A.person_metrics(s, c.uid)
        out["me_trend"] = A.overview(s, A.Scope(frozenset([c.inst_id]), person=c.uid, y0=sc.y0, y1=sc.y1))["trend"]
        if c.can("discover.experts"):
            vis = c.visible("network") if c.can("graph.network") else {c.inst_id}
            out["suggestions"] = intel.recommendations(s, c.uid, vis, c.inst_id, limit=4, graph=neo.active())
    if c.role == "external":
        out["me"] = None
    opps = db.rows(con, "SELECT o.*, p.name AS poster FROM opportunities o LEFT JOIN people p ON p.id=o.posted_by "
                        "WHERE o.status='open' AND (o.inst_id=? OR o.audience='network') AND o.deadline >= date('now') "
                        "ORDER BY o.deadline LIMIT 5", (c.inst_id,))
    for o in opps:
        o["tags"] = db.jl(o["tags"])
        o["inst"] = s.inst[o["inst_id"]]["short"] if o["inst_id"] in s.inst else ""
    out["deadlines"] = opps
    feed = []
    recent = sorted((p for p in A.pubs_in(s, sc) if p["status"] == "verified"), key=lambda p: (-p["year"], -p["id"]))[:6]
    for p in recent:
        feed.append({"kind": "publication", "id": p["id"], "title": p["title"], "year": p["year"], "venue": p["venue"],
                     "people": [s.people[a]["name"] for a in p["authors"][:3]], "quartile": p["quartile"]})
    out["feed"] = feed
    if c.platform:
        out["platform"] = platform_overview_data(con)
    return out


# ── analytics ────────────────────────────────────────────────────────────────
SECTIONS = {"overview": A.overview, "output": A.output, "impact": A.impact, "topics": A.topics, "funding": A.funding,
            "people": A.people_section, "collaboration": A.collaboration, "departments": A.departments}


@app.get("/api/analytics/{section}")
def analytics(section: str, scope: str = "institution", dept: int | None = None, person: int | None = None,
              y0: int | None = None, y1: int | None = None, pending: bool = False, c: Ctx = Depends(ctx)):
    s = db.snapshot()
    sc, name = resolve_scope(c, scope, dept, person, y0, y1, pending)
    if section == "insights":
        return {"scope": name, "insights": A.insights(s, sc, name)}
    fn = SECTIONS.get(section)
    if not fn:
        raise HTTPException(404, "Unknown analytics section.")
    if section == "departments" and sc.person is not None:
        raise HTTPException(400, "Department comparison needs an institution or department scope.")
    data = fn(s, sc)
    return {"scope": name, "range": [sc.y0, sc.y1], **data}


# ── graphs ───────────────────────────────────────────────────────────────────
def graph_scope(c: Ctx, scope, dept, y0, y1):
    s = db.snapshot()
    y0 = y0 or max(2015, s.min_year)
    y1 = y1 or s.max_year
    if scope == "network":
        c.need("graph.network")
        ids = frozenset(i for i in c.visible("network") if not s.inst[i]["external"])
        return A.Scope(ids, y0=y0, y1=y1)
    c.need("graph.institution")
    if scope == "department":
        d = dept or c.user.get("dept_id")
        if not d or d not in s.dept or s.dept[d]["inst_id"] != c.inst_id:
            raise HTTPException(400, "Pick a department in your institution.")
        return A.Scope(frozenset([c.inst_id]), frozenset([d]), y0=y0, y1=y1)
    return A.Scope(frozenset([c.inst_id]), y0=y0, y1=y1)


def engine_badge():
    st = neo.NEO.status()
    if neo.NEO.ok:
        label = f"Neo4j {st['server']}" + (f" {st['edition']}" if st["edition"] and "aura" not in (st["server"] or "") else "")
        return {"engine": "neo4j", "label": label + (f" · GDS {st['gds']}" if st["gds"] else " · algorithms in Python"),
                "gds": bool(st["gds"])}
    return {"engine": "networkx", "label": "In-memory engine (NetworkX)", "note": st["error"] or st["state"]}


@app.get("/api/graph/{mode}")
def graph(mode: str, scope: str = "institution", dept: int | None = None, y0: int | None = None, y1: int | None = None,
          students: bool = True, min_weight: float = 1.0, external: bool = True, c: Ctx = Depends(ctx)):
    s = db.snapshot()
    sc = graph_scope(c, scope, dept, y0, y1)
    eng = neo.active()
    data = None
    if eng is not None:
        try:
            data = {"people": lambda: eng.people_view(s, sc, include_students=students, min_weight=max(1.0, min_weight)),
                    "institutions": lambda: eng.institution_view(s, sc, include_external=external),
                    "departments": lambda: eng.department_view(s, sc),
                    "topics": lambda: eng.topic_view(s, sc),
                    "mentorship": lambda: eng.mentorship_view(s, sc)}[mode]()
        except KeyError:
            raise HTTPException(404, "Unknown graph mode.")
        except Exception as e:  # Neo4j hiccup — serve the in-memory engine rather than fail
            neo.NEO.error = f"{mode} view failed: {str(e)[:160]}"
            data = None
    if data is None:
        if mode == "people":
            data = graphs.build_people_view(s, sc, include_students=students, min_weight=max(1.0, min_weight))
        elif mode == "institutions":
            data = graphs.institution_view(s, sc, include_external=external)
        elif mode == "departments":
            data = graphs.department_view(s, sc)
        elif mode == "topics":
            data = graphs.topic_view(s, sc)
        elif mode == "mentorship":
            data = graphs.mentorship_view(s, sc)
        else:
            raise HTTPException(404, "Unknown graph mode.")
        data = {**data, "engine": "networkx"}
    return {"scope": scope, "range": [sc.y0, sc.y1], "engine_info": engine_badge(), **data}


@app.get("/api/graph-ego/{pid}")
def graph_ego(pid: int, depth: int = 1, c: Ctx = Depends(ctx)):
    s = db.snapshot()
    if pid not in s.people:
        raise HTTPException(404, "Person not found.")
    vis = c.visible("network")
    if s.people[pid]["inst_id"] not in vis:
        raise HTTPException(403, "This profile isn't shared with your institution.")
    eng = neo.active()
    if eng is not None:
        try:
            return {**eng.ego_view(s, pid, vis, 2015, s.max_year, depth=min(depth, 2)), "engine_info": engine_badge()}
        except Exception as e:
            neo.NEO.error = f"ego view failed: {str(e)[:160]}"
    sc = A.Scope(frozenset(vis), y0=2015, y1=s.max_year)
    return {**graphs.ego_view(s, pid, sc, depth=min(depth, 2)), "engine": "networkx", "engine_info": engine_badge()}


@app.get("/api/graph-path")
def graph_path(a: int, b: int, scope: str = "network", c: Ctx = Depends(ctx)):
    s = db.snapshot()
    sc = graph_scope(c, scope if c.can("graph.network") else "institution", None, None, None)
    eng = neo.active()
    if eng is not None:
        try:
            return eng.shortest_path(s, sc.insts, a, b)
        except Exception as e:
            neo.NEO.error = f"path failed: {str(e)[:160]}"
    return {**graphs.shortest_path(s, sc, a, b), "engine": "networkx"}


@app.get("/api/graph-analyses")
def graph_analyses(y0: int | None = None, y1: int | None = None, c: Ctx = Depends(ctx)):
    c.need("graph.institution")
    s = db.snapshot()
    eng = neo.active()
    if eng is None:
        if neo.NEO.ok:
            raise HTTPException(503, "RICE is building the knowledge graph in Neo4j right now — open this tab again in a few seconds.")
        raise HTTPException(503, "The graph database is offline, so graph analyses are paused. "
                                 "Start Neo4j (python tools/neo4j_ctl.py start) — RICE reconnects by itself.")
    vis = {i for i in c.visible("network") if not s.inst[i]["external"]} if c.can("graph.network") else {c.inst_id}
    y0 = y0 or max(2015, s.min_year)
    y1 = y1 or s.max_year
    key = ("analyses", c.inst_id, tuple(sorted(vis)), y0, y1)
    rows = db.cached(key, lambda: eng.analyses({c.inst_id}, vis, y0, y1))
    return {"engine_info": engine_badge(), "range": [y0, y1], "analyses": rows,
            "scope": "your institution and the RICE institutions that share with it" if len(vis) > 1 else "your institution"}


@app.get("/api/graph-engine")
def graph_engine(c: Ctx = Depends(ctx)):
    st = neo.NEO.status()
    badge = engine_badge()
    if not c.platform:
        return {**badge, "state": st["state"], "server": st["server"], "gds": st["gds"]}
    return {**badge, **st}


@app.post("/api/platform/graph-resync")
def graph_resync(c: Ctx = Depends(ctx)):
    if not c.platform:
        raise HTTPException(403, "For the RICE platform team only.")
    if not neo.NEO.ok and not neo.NEO.connect(wait=5):
        raise HTTPException(503, f"Can't reach Neo4j: {neo.NEO.error}")
    neo.NEO.synced = -1
    neo.NEO.ensure_synced(timeout=120)
    return {"ok": True, **neo.NEO.status()}


# ── discovery ────────────────────────────────────────────────────────────────
@app.get("/api/search")
def search(q: str, c: Ctx = Depends(ctx)):
    s = db.snapshot()
    vis = c.visible("network") if c.can("graph.network") or c.can("discover.experts") else {c.inst_id}
    return intel.search(s, q, vis, c.inst_id, c.inst_id)


@app.get("/api/experts")
def experts(q: str, scope: str = "network", c: Ctx = Depends(ctx)):
    c.need("discover.experts")
    s = db.snapshot()
    vis = c.visible("network") if scope == "network" else {c.inst_id}
    if scope == "network" and c.role not in ("external",) and not c.can("graph.network"):
        vis = {c.inst_id}
    return {"q": q, "results": intel.experts(s, q, vis, c.inst_id)}


@app.get("/api/recommendations")
def recommendations(person: int | None = None, c: Ctx = Depends(ctx)):
    c.need("discover.experts")
    s = db.snapshot()
    pid = person or c.uid
    if pid != c.uid and not (c.can("people.manage") or c.role == "hod"):
        raise HTTPException(403, "You can see suggestions only for yourself.")
    if pid not in s.people:
        raise HTTPException(404, "Person not found.")
    vis = c.visible("network") if c.can("graph.network") else {c.inst_id}
    return {"results": intel.recommendations(s, pid, vis, c.inst_id, limit=12, graph=neo.active()), "engine_info": engine_badge()}


class TeamIn(BaseModel):
    brief: str = Field(min_length=3)
    size: int = 4
    scope: str = "network"


@app.post("/api/team")
def team(body: TeamIn, c: Ctx = Depends(ctx)):
    c.need("discover.experts")
    s = db.snapshot()
    vis = c.visible("network") if body.scope == "network" and c.can("graph.network") else {c.inst_id}
    vis = {i for i in vis if not s.inst[i]["external"]}
    return intel.team(s, body.brief, vis, c.inst_id, size=max(2, min(body.size, 6)))


# ── people ───────────────────────────────────────────────────────────────────
@app.get("/api/people")
def people(q: str = "", dept: int | None = None, role: str = "", inst: int | None = None, sort: str = "name",
           page: int = 1, size: int = 48, c: Ctx = Depends(ctx)):
    s = db.snapshot()
    vis = c.visible("network")
    target = {inst} if inst else {c.inst_id}
    if inst and inst not in vis:
        raise HTTPException(403, "This institution doesn't share its directory with you.")
    ql = q.lower().strip()
    rows = []
    for p in s.people.values():
        if p["inst_id"] not in target or p["status"] != "active" or p["role"] == "platform_admin":
            continue
        if p["visibility"] == "internal" and p["inst_id"] != c.inst_id and not c.platform:
            continue
        if dept and p["dept_id"] != dept:
            continue
        if role and p["role"] != role:
            continue
        if ql and ql not in p["name"].lower() and not any(ql in t.lower() for t in p["interests"]):
            continue
        card = person_public(s, p["id"])
        m = A.person_metrics(s, p["id"])
        card.update({"pubs": m["pubs"], "citations": m["citations"], "h_index": m["h_index"], "students": m["students"],
                     "scopus_id": p.get("scopus_id"), "source": p.get("source")})
        rows.append(card)
    key = {"name": lambda r: r["name"], "pubs": lambda r: -r["pubs"], "citations": lambda r: -r["citations"],
           "h_index": lambda r: -r["h_index"]}.get(sort, lambda r: r["name"])
    rows.sort(key=key)
    counts = {}
    for r in rows:
        counts[r["role"]] = counts.get(r["role"], 0) + 1
    return {"total": len(rows), "counts": counts, "page": page, "rows": rows[(page - 1) * size: page * size]}


@app.get("/api/people/{pid}")
def person(pid: int, c: Ctx = Depends(ctx)):
    s = db.snapshot()
    if pid not in s.people:
        raise HTTPException(404, "Person not found.")
    p = s.people[pid]
    own_inst = p["inst_id"] == c.inst_id
    if not c.platform and not own_inst:
        if p["inst_id"] not in c.visible("network") or p["visibility"] == "internal":
            raise HTTPException(403, "This profile isn't shared with your institution.")
    card = person_public(s, pid)
    card.update({"bio": p.get("bio"), "orcid": p.get("orcid"), "scopus_id": p.get("scopus_id"), "joined": p.get("joined"),
                 "source": p.get("source"), "visibility": p["visibility"],
                 "email": p["email"] if (own_inst or c.platform) else None,
                 "external_inst": bool(s.inst[p["inst_id"]]["external"])})
    pubs = [s.pubs[x] for x in p["pubs"] if s.pubs[x]["status"] == "verified" or own_inst]
    if not own_inst:
        pubs = [x for x in pubs if x["visibility"] == "public"]
    pubs.sort(key=lambda x: (-x["year"], -x["citations"]))
    years = list(range(max(2015, (p.get("joined") or 2015)), s.max_year + 1))
    by_year = {y: [x for x in pubs if x["year"] == y and x["status"] == "verified"] for y in years}
    co = intel.coauthors(s, pid)
    sup = p.get("supervisor_id")
    topic_years = {}
    for x in pubs:
        for k in x["keywords"]:
            topic_years.setdefault(k, {}).setdefault(x["year"], 0)
            topic_years[k][x["year"]] += 1
    top_topics = sorted(topic_years, key=lambda k: -sum(topic_years[k].values()))[:8]
    return {
        **card,
        "metrics": A.person_metrics(s, pid),
        "trend": {"years": years, "pubs": [len(by_year[y]) for y in years], "citations": [sum(x["citations"] for x in by_year[y]) for y in years]},
        "topic_timeline": {"topics": top_topics, "years": years,
                           "cells": [[j, i, topic_years[t].get(y, 0)] for i, t in enumerate(top_topics) for j, y in enumerate(years)]},
        "publications": [A.pub_card(s, x) for x in pubs[:200]],
        "projects": [A.project_card(s, s.projects[x]) for x in p["projects"] if s.projects[x]["stage"] != "not_funded" or own_inst],
        "patents": [{"id": s.patents[x]["id"], "title": s.patents[x]["title"], "stage": s.patents[x]["stage"], "year": s.patents[x]["year"],
                     "number": s.patents[x]["number"]} for x in p["patents"]],
        "coauthors": [{**person_public(s, a), "count": n} for a, n in co.most_common(14) if s.people[a]["inst_id"] in c.visible("network") or c.platform],
        "students": [person_public(s, x) for x in p["students"]],
        "supervisor": person_public(s, sup) if sup and sup in s.people else None,
        "external_partners": sorted({a for x in pubs for a in x["external_affils"]})[:12],
        "can_edit": pid == c.uid or (c.can("people.manage") and own_inst),
        "can_request": c.can("collab.request") and pid != c.uid and s.people[pid]["role"] in ("faculty", "hod", "scholar")
                       and not s.inst[p["inst_id"]]["external"],
    }


@app.get("/api/people/{pid}/similar")
def person_similar(pid: int, c: Ctx = Depends(ctx)):
    s = db.snapshot()
    if pid not in s.people:
        raise HTTPException(404, "Person not found.")
    if not c.can("discover.experts"):
        return {"results": []}
    vis = c.visible("network") if c.can("graph.network") else {c.inst_id}
    return {"results": intel.recommendations(s, pid, vis, c.inst_id, limit=6, graph=neo.active())}


# ── research records ─────────────────────────────────────────────────────────
def _record_scope_ok(c: Ctx, s, insts: set, depts: set, creator: int | None):
    """May this user verify/edit a record touching these institutions/departments?"""
    if c.platform:
        return True
    if c.inst_id not in insts:
        return False
    if c.role == "inst_admin":
        return True
    if c.role == "hod":
        return c.user.get("dept_id") in depts or (creator and s.people.get(creator, {}).get("dept_id") == c.user.get("dept_id"))
    return False


def _pending_records(c: Ctx, con):
    s = db.snapshot()
    out = []
    for kind, coll in (("publication", s.pubs), ("project", s.projects), ("patent", s.patents)):
        for r in coll.values():
            if r["status"] != "pending":
                continue
            if _record_scope_ok(c, s, r["insts"] or {r["inst_id"]}, r["depts"], r.get("created_by")):
                out.append((kind, r))
    return out


@app.get("/api/publications")
def list_pubs(q: str = "", dept: int | None = None, person: int | None = None, mine: bool = False, year: int | None = None,
              kind: str = "", status: str = "", quartile: str = "", oa: str = "", sort: str = "recent", page: int = 1,
              size: int = 25, c: Ctx = Depends(ctx)):
    s = db.snapshot()
    ql = q.lower().strip()
    rows = []
    for p in s.pubs.values():
        if c.inst_id not in p["insts"] and p["inst_id"] != c.inst_id:
            continue
        if mine and c.uid not in p["authors"] and p["created_by"] != c.uid:
            continue
        if person and person not in p["authors"]:
            continue
        if dept and dept not in p["depts"]:
            continue
        if year and p["year"] != year:
            continue
        if kind and p["kind"] != kind:
            continue
        if status and p["status"] != status:
            continue
        if not status and p["status"] == "rejected" and p["created_by"] != c.uid:
            continue
        if quartile and p["quartile"] != quartile:
            continue
        if oa and bool(p["open_access"]) != (oa == "yes"):
            continue
        if ql and ql not in p["title"].lower() and not any(ql in k.lower() for k in p["keywords"]) and \
                not any(ql in s.people[a]["name"].lower() for a in p["authors"]):
            continue
        rows.append(p)
    key = {"recent": lambda p: (-p["year"], -p["id"]), "cited": lambda p: -p["citations"], "title": lambda p: p["title"]}.get(sort)
    rows.sort(key=key or (lambda p: -p["year"]))
    facet = {"kind": {}, "status": {}, "quartile": {}}
    for p in rows:
        facet["kind"][p["kind"]] = facet["kind"].get(p["kind"], 0) + 1
        facet["status"][p["status"]] = facet["status"].get(p["status"], 0) + 1
        if p["quartile"]:
            facet["quartile"][p["quartile"]] = facet["quartile"].get(p["quartile"], 0) + 1
    page_rows = []
    for p in rows[(page - 1) * size: page * size]:
        card = A.pub_card(s, p)
        card["can_verify"] = p["status"] == "pending" and c.can("outputs.verify") and \
            _record_scope_ok(c, s, p["insts"] or {p["inst_id"]}, p["depts"], p["created_by"])
        card["can_edit"] = p["created_by"] == c.uid or card["can_verify"] or (c.role == "inst_admin")
        page_rows.append(card)
    return {"total": len(rows), "page": page, "size": size, "facets": facet, "rows": page_rows}


class AuthorIn(BaseModel):
    person_id: int | None = None
    name: str | None = None
    affil: str | None = None
    country: str | None = None


class PubIn(BaseModel):
    title: str = Field(min_length=5)
    year: int
    kind: str = "journal"
    venue: str = ""
    quartile: str | None = None
    citations: int = 0
    doi: str | None = None
    keywords: list[str] = []
    open_access: bool = False
    visibility: str = "public"
    authors: list[AuthorIn] = []


def _status_for_new(c: Ctx):
    if c.can("outputs.verify") or not c.settings.get("require_verification", True):
        return "verified"
    return "pending"


def _notify_verifiers(con, c: Ctx, what: str):
    s = db.snapshot()
    ids = [p["id"] for p in s.people.values() if p["inst_id"] == c.inst_id and p["status"] == "active" and
           (p["role"] == "inst_admin" or (p["role"] == "hod" and p["dept_id"] == c.user.get("dept_id")))]
    for i in ids:
        if i != c.uid:
            notify(con, i, "verify", f"{c.user['name']} added {what} for verification", "#/approvals")


@app.post("/api/publications")
def create_pub(body: PubIn, c: Ctx = Depends(ctx), con=Depends(get_con)):
    c.need("outputs.create")
    if body.kind not in ("journal", "conference", "chapter", "book", "preprint"):
        raise HTTPException(400, "Unknown publication type.")
    if not (1950 <= body.year <= NOW_YEAR + 1):
        raise HTTPException(400, "Year looks wrong.")
    authors = body.authors or [AuthorIn(person_id=c.uid)]
    ids = [a.person_id for a in authors if a.person_id]
    if c.role not in ("inst_admin", "hod") and c.uid not in ids:
        raise HTTPException(400, "Add yourself as an author — or ask your HoD to add records on behalf of others.")
    status = _status_for_new(c)
    cur = con.execute("INSERT INTO publications (inst_id,title,kind,venue,year,quartile,citations,doi,keywords,sdgs,open_access,"
                      "status,visibility,source,created_by,verified_by) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                      (c.inst_id, body.title.strip(), body.kind, body.venue.strip(), body.year,
                       body.quartile if body.quartile in ("Q1", "Q2", "Q3", "Q4") else None, max(0, body.citations),
                       body.doi, db.jd(body.keywords[:8]), db.jd(sdgs_for(body.title + " " + " ".join(body.keywords))),
                       int(body.open_access), status, body.visibility if body.visibility in ("public", "internal") else "public",
                       "manual", c.uid, c.uid if status == "verified" else None))
    pid = cur.lastrowid
    for pos, a in enumerate(authors):
        con.execute("INSERT INTO pub_authors (pub_id, position, person_id, ext_name, ext_affil, ext_country) VALUES (?,?,?,?,?,?)",
                    (pid, pos, a.person_id, None if a.person_id else a.name, a.affil, a.country or ("India" if a.affil else None)))
    for a in ids:
        if a != c.uid:
            notify(con, a, "coauthor", f"{c.user['name']} listed you as a co-author on “{body.title[:70]}”", f"#/repository?q={body.title[:30]}")
    if status == "pending":
        _notify_verifiers(con, c, "a publication")
    audit(con, c, "publication.create", body.title[:80], status)
    con.commit()
    db.bump()
    return {"ok": True, "id": pid, "status": status}


@app.delete("/api/publications/{pid}")
def delete_pub(pid: int, c: Ctx = Depends(ctx), con=Depends(get_con)):
    p = db.one(con, "SELECT * FROM publications WHERE id=?", (pid,))
    if not p:
        raise HTTPException(404, "Publication not found.")
    if not (p["created_by"] == c.uid and p["status"] != "verified") and not (c.role == "inst_admin" and p["inst_id"] == c.inst_id) and not c.platform:
        raise HTTPException(403, "Only the person who added it (before verification) or an admin can delete this record.")
    con.execute("DELETE FROM publications WHERE id=?", (pid,))
    audit(con, c, "publication.delete", p["title"][:80])
    con.commit()
    db.bump()
    return {"ok": True}


@app.get("/api/projects")
def list_projects(q: str = "", stage: str = "", status: str = "", agency: str = "", mine: bool = False, dept: int | None = None,
                  page: int = 1, size: int = 25, c: Ctx = Depends(ctx)):
    s = db.snapshot()
    ql = q.lower().strip()
    rows = []
    for p in s.projects.values():
        if c.inst_id not in p["insts"] and p["inst_id"] != c.inst_id:
            continue
        member_ids = {m["id"] for m in p["members"]}
        if mine and c.uid not in member_ids:
            continue
        if p["stage"] in ("submitted", "not_funded") and not (c.uid in member_ids or c.can("reports.view")):
            continue
        if dept and dept not in p["depts"]:
            continue
        if stage and p["stage"] != stage:
            continue
        if status and p["status"] != status:
            continue
        if agency and p["agency"] != agency:
            continue
        if ql and ql not in p["title"].lower() and not any(ql in s.people[m]["name"].lower() for m in member_ids):
            continue
        rows.append(p)
    rows.sort(key=lambda p: (-(p["start_year"] or 0), -p["amount"]))
    out = []
    for p in rows[(page - 1) * size: page * size]:
        card = A.project_card(s, p)
        card["can_verify"] = p["status"] == "pending" and c.can("outputs.verify") and \
            _record_scope_ok(c, s, p["insts"] or {p["inst_id"]}, p["depts"], p["created_by"])
        out.append(card)
    total_amount = round(sum(p["amount"] for p in rows if p["stage"] in ("ongoing", "completed")), 1)
    return {"total": len(rows), "amount": total_amount, "page": page, "size": size, "rows": out}


class ProjectIn(BaseModel):
    title: str = Field(min_length=5)
    agency: str
    scheme: str = ""
    amount: float = 0
    start_year: int
    end_year: int
    stage: str = "ongoing"
    keywords: list[str] = []
    members: list[dict] = []   # {person_id, role}


@app.post("/api/projects")
def create_project(body: ProjectIn, c: Ctx = Depends(ctx), con=Depends(get_con)):
    c.need("outputs.create")
    if body.stage not in ("submitted", "ongoing", "completed", "not_funded"):
        raise HTTPException(400, "Unknown project stage.")
    if body.end_year < body.start_year:
        raise HTTPException(400, "End year is before start year.")
    sector = AGENCIES.get(body.agency, ("government",))[0]
    status = _status_for_new(c)
    cur = con.execute("INSERT INTO projects (inst_id,title,agency,scheme,sector,amount,start_year,end_year,stage,keywords,status,created_by) "
                      "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                      (c.inst_id, body.title.strip(), body.agency, body.scheme, sector, max(0.0, body.amount), body.start_year,
                       body.end_year, body.stage, db.jd(body.keywords[:6]), status, c.uid))
    prj = cur.lastrowid
    members = body.members or [{"person_id": c.uid, "role": "PI"}]
    if not any(m.get("person_id") == c.uid for m in members) and c.role not in ("inst_admin", "hod"):
        members.insert(0, {"person_id": c.uid, "role": "PI"})
    seen = set()
    for m in members:
        if m.get("person_id") and m["person_id"] not in seen:
            seen.add(m["person_id"])
            con.execute("INSERT INTO project_members (project_id, person_id, role) VALUES (?,?,?)",
                        (prj, m["person_id"], m.get("role") or "Member"))
    if status == "pending":
        _notify_verifiers(con, c, "a project")
    audit(con, c, "project.create", body.title[:80], status)
    con.commit()
    db.bump()
    return {"ok": True, "id": prj, "status": status}


@app.get("/api/patents")
def list_patents(q: str = "", stage: str = "", status: str = "", mine: bool = False, c: Ctx = Depends(ctx)):
    s = db.snapshot()
    ql = q.lower().strip()
    rows = []
    for p in s.patents.values():
        if c.inst_id not in p["insts"] and p["inst_id"] != c.inst_id:
            continue
        if mine and c.uid not in p["inventors"]:
            continue
        if stage and p["stage"] != stage:
            continue
        if status and p["status"] != status:
            continue
        if ql and ql not in p["title"].lower():
            continue
        rows.append({"id": p["id"], "title": p["title"], "stage": p["stage"], "year": p["year"], "number": p["number"],
                     "status": p["status"], "keywords": p["keywords"],
                     "inventors": [{"id": i, "name": s.people[i]["name"]} for i in p["inventors"]],
                     "can_verify": p["status"] == "pending" and c.can("outputs.verify") and
                     _record_scope_ok(c, s, p["insts"] or {p["inst_id"]}, p["depts"], p["created_by"])})
    rows.sort(key=lambda r: -r["year"])
    return {"total": len(rows), "rows": rows}


class PatentIn(BaseModel):
    title: str = Field(min_length=5)
    stage: str = "filed"
    year: int
    number: str = ""
    keywords: list[str] = []
    inventors: list[int] = []


@app.post("/api/patents")
def create_patent(body: PatentIn, c: Ctx = Depends(ctx), con=Depends(get_con)):
    c.need("outputs.create")
    if body.stage not in ("filed", "published", "granted"):
        raise HTTPException(400, "Unknown patent stage.")
    status = _status_for_new(c)
    cur = con.execute("INSERT INTO patents (inst_id,title,stage,year,number,keywords,status,created_by) VALUES (?,?,?,?,?,?,?,?)",
                      (c.inst_id, body.title.strip(), body.stage, body.year, body.number, db.jd(body.keywords[:6]), status, c.uid))
    pat = cur.lastrowid
    inv = body.inventors or [c.uid]
    if c.uid not in inv and c.role not in ("inst_admin", "hod"):
        inv.insert(0, c.uid)
    for i in dict.fromkeys(inv):
        con.execute("INSERT INTO patent_inventors (patent_id, person_id) VALUES (?,?)", (pat, i))
    if status == "pending":
        _notify_verifiers(con, c, "a patent")
    audit(con, c, "patent.create", body.title[:80], status)
    con.commit()
    db.bump()
    return {"ok": True, "id": pat, "status": status}


class VerifyIn(BaseModel):
    decision: str
    note: str = ""


@app.post("/api/verify/{entity}/{rid}")
def verify(entity: str, rid: int, body: VerifyIn, c: Ctx = Depends(ctx), con=Depends(get_con)):
    c.need("outputs.verify")
    s = db.snapshot()
    coll = {"publication": s.pubs, "project": s.projects, "patent": s.patents}.get(entity)
    table = {"publication": "publications", "project": "projects", "patent": "patents"}.get(entity)
    if coll is None:
        raise HTTPException(404, "Unknown record type.")
    r = coll.get(rid)
    if not r:
        raise HTTPException(404, "Record not found.")
    if not _record_scope_ok(c, s, r["insts"] or {r["inst_id"]}, r["depts"], r.get("created_by")):
        raise HTTPException(403, "This record belongs to another department or institution.")
    if body.decision not in ("verified", "rejected"):
        raise HTTPException(400, "Decision must be verified or rejected.")
    extra = ", verified_by=?" if entity == "publication" else ""
    args = (body.decision, c.uid, rid) if entity == "publication" else (body.decision, rid)
    con.execute(f"UPDATE {table} SET status=?{extra} WHERE id=?", args)
    if r.get("created_by"):
        word = "verified" if body.decision == "verified" else "returned"
        note = f" — {body.note}" if body.note else ""
        notify(con, r["created_by"], "verify", f"Your {entity} “{r['title'][:60]}” was {word}{note}", "#/repository?mine=1")
    audit(con, c, f"{entity}.{body.decision}", r["title"][:80], body.note)
    con.commit()
    db.bump()
    return {"ok": True}


class BulkVerifyIn(BaseModel):
    items: list[dict]   # {entity, id}
    decision: str = "verified"


@app.post("/api/verify-bulk")
def verify_bulk(body: BulkVerifyIn, c: Ctx = Depends(ctx), con=Depends(get_con)):
    done = 0
    for it in body.items[:200]:
        try:
            verify(it["entity"], int(it["id"]), VerifyIn(decision=body.decision), c, con)
            done += 1
        except HTTPException:
            continue
    return {"ok": True, "done": done}


# ── opportunities & collaboration ────────────────────────────────────────────
@app.get("/api/opportunities")
def opportunities(kind: str = "", c: Ctx = Depends(ctx), con=Depends(get_con)):
    s = db.snapshot()
    rows = db.rows(con, "SELECT o.*, p.name AS poster, (SELECT COUNT(*) FROM opportunity_interest i WHERE i.opp_id=o.id) AS interested, "
                        "(SELECT COUNT(*) FROM opportunity_interest i WHERE i.opp_id=o.id AND i.person_id=?) AS mine "
                        "FROM opportunities o LEFT JOIN people p ON p.id=o.posted_by ORDER BY o.deadline", (c.uid,))
    vis = c.visible("network")
    out = []
    for o in rows:
        own = o["inst_id"] == c.inst_id
        if not own and not (o["audience"] == "network" and o["inst_id"] in vis):
            continue
        if o["status"] == "pending" and not (own and (c.can("people.manage") or o["posted_by"] == c.uid)):
            continue
        if kind and o["kind"] != kind:
            continue
        o["tags"] = db.jl(o["tags"])
        o["inst"] = s.inst[o["inst_id"]]["short"] if o["inst_id"] in s.inst else ""
        o["inst_name"] = s.inst[o["inst_id"]]["name"] if o["inst_id"] in s.inst else ""
        o["brand"] = s.inst[o["inst_id"]]["brand"] if o["inst_id"] in s.inst else None
        o["own"] = own
        o["match"] = len(set(o["tags"]) & set(c.user["interests"]))
        out.append(o)
    return {"rows": out, "can_post": c.can("opportunities.post")}


class OppIn(BaseModel):
    kind: str
    title: str = Field(min_length=5)
    body: str = ""
    tags: list[str] = []
    deadline: str
    audience: str = "internal"


@app.post("/api/opportunities")
def post_opportunity(body: OppIn, c: Ctx = Depends(ctx), con=Depends(get_con)):
    c.need("opportunities.post")
    if body.kind not in ("call", "position", "collab", "event"):
        raise HTTPException(400, "Unknown opportunity type.")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", body.deadline):
        raise HTTPException(400, "Deadline must be a date.")
    status = "open" if (body.audience == "internal" or c.can("people.manage")) else "pending"
    con.execute("INSERT INTO opportunities (inst_id, posted_by, kind, title, body, tags, deadline, audience, status) VALUES (?,?,?,?,?,?,?,?,?)",
                (c.inst_id, c.uid, body.kind, body.title, body.body, db.jd(body.tags[:6]), body.deadline,
                 body.audience if body.audience in ("internal", "network") else "internal", status))
    if status == "pending":
        for a in db.rows(con, "SELECT id FROM people WHERE inst_id=? AND role='inst_admin'", (c.inst_id,)):
            notify(con, a["id"], "opportunity", f"{c.user['name']} wants to share “{body.title[:50]}” with the network", "#/approvals")
    audit(con, c, "opportunity.post", body.title[:80], status)
    con.commit()
    return {"ok": True, "status": status,
            "message": "Posted." if status == "open" else "Sent to your institution admin — network posts need approval."}


class InterestIn(BaseModel):
    note: str = ""


@app.post("/api/opportunities/{oid}/interest")
def opp_interest(oid: int, body: InterestIn, c: Ctx = Depends(ctx), con=Depends(get_con)):
    o = db.one(con, "SELECT * FROM opportunities WHERE id=? AND status='open'", (oid,))
    if not o:
        raise HTTPException(404, "This opportunity is closed.")
    try:
        con.execute("INSERT INTO opportunity_interest (opp_id, person_id, note) VALUES (?,?,?)", (oid, c.uid, body.note))
    except Exception:
        con.execute("DELETE FROM opportunity_interest WHERE opp_id=? AND person_id=?", (oid, c.uid))
        con.commit()
        return {"ok": True, "interested": False}
    if o["posted_by"]:
        notify(con, o["posted_by"], "opportunity", f"{c.user['name']} is interested in “{o['title'][:60]}”", "#/opportunities")
    con.commit()
    return {"ok": True, "interested": True}


class OppDecisionIn(BaseModel):
    status: str


@app.post("/api/opportunities/{oid}/status")
def opp_status(oid: int, body: OppDecisionIn, c: Ctx = Depends(ctx), con=Depends(get_con)):
    o = db.one(con, "SELECT * FROM opportunities WHERE id=?", (oid,))
    if not o or (o["inst_id"] != c.inst_id and not c.platform):
        raise HTTPException(404, "Opportunity not found.")
    if not (c.can("people.manage") or o["posted_by"] == c.uid):
        raise HTTPException(403, "Only the poster or an admin can change this.")
    if body.status not in ("open", "closed"):
        raise HTTPException(400, "Status must be open or closed.")
    if o["status"] == "pending" and not c.can("people.manage"):
        raise HTTPException(403, "An admin needs to approve this post.")
    con.execute("UPDATE opportunities SET status=? WHERE id=?", (body.status, oid))
    if o["status"] == "pending" and o["posted_by"]:
        notify(con, o["posted_by"], "opportunity", f"“{o['title'][:60]}” is now live on the network", "#/opportunities")
    audit(con, c, f"opportunity.{body.status}", o["title"][:80])
    con.commit()
    return {"ok": True}


@app.get("/api/collab")
def collab_list(c: Ctx = Depends(ctx), con=Depends(get_con)):
    s = db.snapshot()
    rows = db.rows(con, "SELECT * FROM collab_requests WHERE from_id=? OR to_id=? ORDER BY created_at DESC", (c.uid, c.uid))
    for r in rows:
        r["direction"] = "incoming" if r["to_id"] == c.uid else "outgoing"
        other = r["from_id"] if r["direction"] == "incoming" else r["to_id"]
        r["other"] = person_public(s, other) if other in s.people else None
    return {"rows": rows}


class CollabIn(BaseModel):
    to: int
    topic: str = ""
    message: str = Field(min_length=10)


@app.post("/api/collab")
def collab_send(body: CollabIn, c: Ctx = Depends(ctx), con=Depends(get_con)):
    c.need("collab.request")
    s = db.snapshot()
    if body.to not in s.people or body.to == c.uid:
        raise HTTPException(404, "Person not found.")
    if s.people[body.to]["inst_id"] not in c.visible("network"):
        raise HTTPException(403, "This researcher's institution doesn't accept requests from yours.")
    if db.scalar(con, "SELECT 1 FROM collab_requests WHERE from_id=? AND to_id=? AND status='pending'", (c.uid, body.to)):
        raise HTTPException(409, "You already have a pending request with this person.")
    con.execute("INSERT INTO collab_requests (from_id, to_id, topic, message) VALUES (?,?,?,?)", (c.uid, body.to, body.topic, body.message))
    notify(con, body.to, "collab", f"{c.user['name']} ({c.inst['short']}) wants to collaborate on {body.topic or 'a shared topic'}", "#/collaborate")
    audit(con, c, "collab.request", s.people[body.to]["name"], body.topic)
    con.commit()
    return {"ok": True}


class RespondIn(BaseModel):
    accept: bool


@app.post("/api/collab/{rid}/respond")
def collab_respond(rid: int, body: RespondIn, c: Ctx = Depends(ctx), con=Depends(get_con)):
    r = db.one(con, "SELECT * FROM collab_requests WHERE id=? AND to_id=? AND status='pending'", (rid, c.uid))
    if not r:
        raise HTTPException(404, "Request not found.")
    st = "accepted" if body.accept else "declined"
    con.execute("UPDATE collab_requests SET status=?, responded_at=datetime('now') WHERE id=?", (st, rid))
    notify(con, r["from_id"], "collab", f"{c.user['name']} {st} your collaboration request", "#/collaborate")
    con.commit()
    return {"ok": True, "status": st}


# ── network & benchmarking ───────────────────────────────────────────────────
@app.get("/api/network/institutions")
def network_institutions(c: Ctx = Depends(ctx)):
    s = db.snapshot()
    summ = c.visible("summary")
    netw = c.visible("network")
    out = []
    for i in s.inst.values():
        if i["external"] and i["settings"].get("owner_inst") not in (None, c.inst_id) and not c.platform:
            continue
        row = {"id": i["id"], "name": i["name"], "short": i["short"], "city": i["city"], "state": i["state"], "brand": i["brand"],
               "kind": i["kind"], "share_level": i["share_level"], "external": bool(i["external"]), "self": i["id"] == c.inst_id,
               "source": i["source"], "established": i["established"], "tagline": i["tagline"],
               "access": "network" if i["id"] in netw else "summary" if i["id"] in summ else "name"}
        people = [p for p in s.people.values() if p["inst_id"] == i["id"] and p["status"] == "active" and p["role"] in A.RESEARCHER_ROLES]
        if i["external"]:
            row["researchers"] = len(people)
        elif row["access"] != "name":
            k = A.overview(s, A.Scope(frozenset([i["id"]]), y0=2019, y1=s.max_year))["kpis"]
            row.update({"researchers": len(people), "publications": k["publications"], "citations": k["citations"],
                        "h_index": k["h_index"], "funding_lakh": k["funding_lakh"]})
        out.append(row)
    out.sort(key=lambda r: (not r["self"], r["external"], r["name"]))
    own = c.inst["share_level"] if c.inst else "private"
    return {"rows": out, "own_level": own, "reciprocity": SHARE_LEVELS[own]}


@app.get("/api/network/benchmark")
def network_benchmark(ids: str = "", y0: int = 2019, y1: int | None = None, c: Ctx = Depends(ctx)):
    c.need("network.benchmark")
    s = db.snapshot()
    allowed = {i for i in c.visible("summary") if not s.inst[i]["external"]}
    want = {int(x) for x in ids.split(",") if x.strip().isdigit()} or allowed
    want = (want & allowed) | ({c.inst_id} if c.inst_id else set())
    data = A.benchmark(s, sorted(want), y0, y1 or s.max_year)
    return {**data, "available": [{"id": i, "short": s.inst[i]["short"], "name": s.inst[i]["name"], "brand": s.inst[i]["brand"]}
                                  for i in sorted(allowed)], "self": c.inst_id}


@app.get("/api/network/institution/{iid}")
def network_institution(iid: int, c: Ctx = Depends(ctx)):
    s = db.snapshot()
    if iid not in s.inst:
        raise HTTPException(404, "Institution not found.")
    i = s.inst[iid]
    netw = c.visible("network")
    summ = c.visible("summary")
    base = {k: i[k] for k in ("id", "name", "short", "city", "state", "brand", "kind", "share_level", "tagline", "established", "source")}
    base["external"] = bool(i["external"])
    if i["external"]:
        if iid not in netw:
            raise HTTPException(403, "Not shared with you.")
        ppl = [person_public(s, p["id"]) | {"scopus_id": p.get("scopus_id")} for p in s.people.values() if p["inst_id"] == iid]
        return {**base, "access": "network", "people": sorted(ppl, key=lambda p: p["name"])}
    if iid not in summ:
        return {**base, "access": "name"}
    sc = A.Scope(frozenset([iid]), y0=2019, y1=s.max_year)
    ov = A.overview(s, sc)
    out = {**base, "access": "network" if iid in netw else "summary", "kpis": ov["kpis"], "trend": ov["trend"]}
    if iid in netw:
        tp = A.topics(s, sc)
        out["topics"] = tp["topics"][:16]
        out["departments"] = [{"id": d["id"], "code": d["code"], "name": d["name"]} for d in s.dept.values() if d["inst_id"] == iid]
        top = A.people_section(s, sc)["rows"][:10]
        out["top_researchers"] = [r for r in top if s.people[r["id"]]["visibility"] == "network" or iid == c.inst_id]
        own_sc = A.Scope(frozenset([c.inst_id, iid]), y0=2015, y1=s.max_year)
        joint = [p for p in A.pubs_in(s, own_sc) if c.inst_id in p["insts"] and iid in p["insts"]]
        out["joint"] = {"count": len(joint), "papers": [A.pub_card(s, p) for p in sorted(joint, key=lambda p: -p["year"])[:6]]}
    return out


# ── admin ────────────────────────────────────────────────────────────────────
@app.get("/api/admin/approvals")
def approvals(c: Ctx = Depends(ctx), con=Depends(get_con)):
    s = db.snapshot()
    out = {"records": [], "members": [], "opportunities": [], "collab": []}
    if c.can("outputs.verify"):
        for kind, r in _pending_records(c, con):
            people = r.get("authors") or [m["id"] for m in r.get("members", [])] or r.get("inventors", [])
            out["records"].append({"entity": kind, "id": r["id"], "title": r["title"],
                                   "year": r.get("year") or r.get("start_year"), "venue": r.get("venue") or r.get("agency"),
                                   "kind": r.get("kind") or r.get("stage"), "amount": r.get("amount"),
                                   "by": s.people[r["created_by"]]["name"] if r.get("created_by") in s.people else "",
                                   "people": [s.people[a]["name"] for a in people[:4] if a in s.people],
                                   "depts": sorted({s.dept[d]["code"] for d in r["depts"]}), "created_at": r.get("created_at")})
    if c.can("people.manage"):
        for p in db.rows(con, "SELECT * FROM people WHERE inst_id=? AND status='pending' ORDER BY created_at DESC", (c.inst_id,)):
            out["members"].append({"id": p["id"], "name": p["name"], "email": p["email"], "role": p["requested_role"] or p["role"],
                                   "designation": p["designation"], "dept_id": p["dept_id"],
                                   "dept": (s.dept.get(p["dept_id"]) or {}).get("name", ""), "interests": db.jl(p["interests"]),
                                   "created_at": p["created_at"]})
        for o in db.rows(con, "SELECT o.*, p.name AS poster FROM opportunities o LEFT JOIN people p ON p.id=o.posted_by "
                              "WHERE o.inst_id=? AND o.status='pending'", (c.inst_id,)):
            o["tags"] = db.jl(o["tags"])
            out["opportunities"].append(o)
    out["collab"] = [r for r in collab_list(c, con)["rows"] if r["direction"] == "incoming" and r["status"] == "pending"]
    return out


class MemberDecisionIn(BaseModel):
    approve: bool
    role: str | None = None
    dept_id: int | None = None


@app.post("/api/admin/members/{pid}/decision")
def member_decision(pid: int, body: MemberDecisionIn, c: Ctx = Depends(ctx), con=Depends(get_con)):
    c.need("people.manage")
    p = db.one(con, "SELECT * FROM people WHERE id=? AND inst_id=? AND status='pending'", (pid, c.inst_id))
    if not p:
        raise HTTPException(404, "Request not found.")
    if body.approve:
        role = body.role or p["requested_role"] or p["role"]
        if role not in INSTITUTION_ROLES or role == "inst_admin":
            raise HTTPException(400, "Choose a valid role.")
        con.execute("UPDATE people SET status='active', role=?, dept_id=COALESCE(?, dept_id) WHERE id=?", (role, body.dept_id, pid))
        notify(con, pid, "welcome", f"Welcome to RICE at {c.inst['name']}", "#/")
        audit(con, c, "member.approve", p["name"], role)
    else:
        con.execute("UPDATE people SET status='rejected' WHERE id=?", (pid,))
        audit(con, c, "member.reject", p["name"])
    con.commit()
    db.bump()
    return {"ok": True}


@app.get("/api/admin/members")
def admin_members(q: str = "", role: str = "", dept: int | None = None, status: str = "", c: Ctx = Depends(ctx), con=Depends(get_con)):
    c.need("people.manage")
    sql = "SELECT id, name, email, role, designation, dept_id, status, last_login, source, visibility, created_at FROM people WHERE inst_id=?"
    args = [c.inst_id]
    if q:
        sql += " AND (lower(name) LIKE ? OR lower(email) LIKE ?)"
        args += [f"%{q.lower()}%", f"%{q.lower()}%"]
    if role:
        sql += " AND role=?"
        args.append(role)
    if dept:
        sql += " AND dept_id=?"
        args.append(dept)
    if status:
        sql += " AND status=?"
        args.append(status)
    sql += " ORDER BY CASE role WHEN 'inst_admin' THEN 0 WHEN 'hod' THEN 1 WHEN 'faculty' THEN 2 WHEN 'staff' THEN 3 WHEN 'scholar' THEN 4 ELSE 5 END, name"
    rows = db.rows(con, sql, args)
    s = db.snapshot()
    for r in rows:
        r["dept"] = (s.dept.get(r["dept_id"]) or {}).get("code", "")
    counts = {}
    for r in db.rows(con, "SELECT role, COUNT(*) n FROM people WHERE inst_id=? AND status='active' GROUP BY role", (c.inst_id,)):
        counts[r["role"]] = r["n"]
    return {"rows": rows, "counts": counts}


class MemberIn(BaseModel):
    role: str | None = None
    dept_id: int | None = None
    status: str | None = None
    designation: str | None = None


@app.patch("/api/admin/members/{pid}")
def admin_member_update(pid: int, body: MemberIn, c: Ctx = Depends(ctx), con=Depends(get_con)):
    c.need("people.manage")
    p = db.one(con, "SELECT * FROM people WHERE id=? AND inst_id=?", (pid, c.inst_id))
    if not p:
        raise HTTPException(404, "Member not found.")
    if pid == c.uid and (body.role or body.status):
        raise HTTPException(400, "You can't change your own role or status.")
    data = body.model_dump(exclude_none=True)
    if "role" in data and data["role"] not in INSTITUTION_ROLES:
        raise HTTPException(400, "Unknown role.")
    if "status" in data and data["status"] not in ("active", "inactive"):
        raise HTTPException(400, "Status must be active or inactive.")
    if not data:
        return {"ok": True}
    con.execute(f"UPDATE people SET {', '.join(f'{k}=?' for k in data)} WHERE id=?", (*data.values(), pid))
    audit(con, c, "member.update", p["name"], ", ".join(f"{k} → {v}" for k, v in data.items()))
    if "role" in data:
        notify(con, pid, "role", f"Your role at {c.inst['short']} is now {ROLES[data['role']]['label']}", "#/")
    con.commit()
    db.bump()
    return {"ok": True}


class InviteIn(BaseModel):
    name: str = Field(min_length=2)
    email: str
    role: str = "faculty"
    dept_id: int | None = None
    designation: str = ""


@app.post("/api/admin/members")
def admin_invite(body: InviteIn, c: Ctx = Depends(ctx), con=Depends(get_con)):
    c.need("people.manage")
    if body.role not in INSTITUTION_ROLES:
        raise HTTPException(400, "Unknown role.")
    if db.scalar(con, "SELECT 1 FROM people WHERE lower(email)=lower(?)", (body.email,)):
        raise HTTPException(409, "Someone already uses this email.")
    import secrets as _s
    temp = "rice-" + _s.token_hex(4)
    con.execute("INSERT INTO people (inst_id, dept_id, name, email, pw_hash, role, designation, status, source, joined, hue) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)", (c.inst_id, body.dept_id, body.name, body.email.lower(), hash_pw(temp), body.role,
                                                  body.designation or ROLES[body.role]["label"], "active", "invite", NOW_YEAR,
                                                  hash(body.email) % 360))
    audit(con, c, "member.invite", body.name, body.role)
    con.commit()
    db.bump()
    return {"ok": True, "temp_password": temp,
            "message": f"{body.name} can sign in with the temporary password shown once below."}


@app.get("/api/admin/settings")
def get_settings(c: Ctx = Depends(ctx)):
    c.need("settings.manage")
    return {"inst": {k: c.inst[k] for k in ("name", "short", "brand", "share_level", "tagline", "city", "state", "plan")},
            "settings": c.settings, "roles": {r: ROLES[r]["label"] for r in INSTITUTION_ROLES if r != "inst_admin"},
            "permissions": {k: {"label": v[0], "help": v[1], "locked": k in LOCKED} for k, v in PERMISSIONS.items()},
            "share_levels": SHARE_LEVELS}


class SettingsIn(BaseModel):
    brand: str | None = None
    tagline: str | None = None
    share_level: str | None = None
    require_verification: bool | None = None
    allow_signup: bool | None = None
    matrix: dict[str, list[str]] | None = None


@app.put("/api/admin/settings")
def put_settings(body: SettingsIn, c: Ctx = Depends(ctx), con=Depends(get_con)):
    c.need("settings.manage")
    changes = []
    if body.brand is not None:
        if not re.fullmatch(r"#[0-9a-fA-F]{6}", body.brand):
            raise HTTPException(400, "Brand colour must be a hex value like #2B59FF.")
        con.execute("UPDATE institutions SET brand=? WHERE id=?", (body.brand, c.inst_id))
        changes.append(f"brand {body.brand}")
    if body.tagline is not None:
        con.execute("UPDATE institutions SET tagline=? WHERE id=?", (body.tagline[:140], c.inst_id))
        changes.append("tagline")
    if body.share_level is not None:
        if body.share_level not in SHARE_LEVELS:
            raise HTTPException(400, "Unknown sharing level.")
        con.execute("UPDATE institutions SET share_level=? WHERE id=?", (body.share_level, c.inst_id))
        changes.append(f"sharing {body.share_level}")
    raw = db.jl(db.scalar(con, "SELECT settings FROM institutions WHERE id=?", (c.inst_id,)), {})
    if body.require_verification is not None:
        raw["require_verification"] = body.require_verification
        changes.append(f"verification {'on' if body.require_verification else 'off'}")
    if body.allow_signup is not None:
        raw["allow_signup"] = body.allow_signup
        changes.append(f"self sign-up {'on' if body.allow_signup else 'off'}")
    if body.matrix is not None:
        clean = {}
        for role, perms in body.matrix.items():
            if role in INSTITUTION_ROLES and role != "inst_admin":
                clean[role] = [p for p in perms if p in PERMISSIONS and p not in LOCKED]
        raw["matrix"] = clean
        changes.append("permission matrix")
    con.execute("UPDATE institutions SET settings=? WHERE id=?", (db.jd(raw), c.inst_id))
    audit(con, c, "settings.update", "Institution settings", "; ".join(changes))
    con.commit()
    db.bump()
    return {"ok": True}


class DeptIn(BaseModel):
    code: str = Field(min_length=2, max_length=8)
    name: str = Field(min_length=3)
    field: str = "Engineering"


@app.post("/api/admin/departments")
def add_department(body: DeptIn, c: Ctx = Depends(ctx), con=Depends(get_con)):
    c.need("settings.manage")
    if db.scalar(con, "SELECT 1 FROM departments WHERE inst_id=? AND upper(code)=upper(?)", (c.inst_id, body.code)):
        raise HTTPException(409, "A department with this code exists.")
    con.execute("INSERT INTO departments (inst_id, code, name, field) VALUES (?,?,?,?)", (c.inst_id, body.code.upper(), body.name, body.field))
    audit(con, c, "department.add", body.name)
    con.commit()
    db.bump()
    return {"ok": True}


@app.post("/api/admin/import")
async def admin_import(file: UploadFile = File(...), commit: bool = Form(False), c: Ctx = Depends(ctx), con=Depends(get_con)):
    c.need("data.import")
    data = await file.read()
    if len(data) > 8 * 1024 * 1024:
        raise HTTPException(413, "Files up to 8 MB, please.")
    try:
        header, table = importers.parse_table(data, file.filename)
    except Exception:
        raise HTTPException(400, "Couldn't read this file. Upload .xlsx or .csv with a header row.")
    fmt = importers.detect(header)
    if fmt == "scival":
        res = importers.import_scival(con, data, c.inst_id if not c.platform else None, c.uid, commit, file.filename)
    elif fmt == "people":
        res = importers.import_people(con, table, c.inst_id, c.uid, commit, temp_password=os.environ.get("RICE_IMPORT_PASSWORD", "rice-welcome-2026"))
    elif fmt == "publications":
        res = importers.import_publications(con, table, c.inst_id, c.uid, commit, c.settings.get("require_verification", True))
    else:
        raise HTTPException(400, "Unrecognised columns. Use a RICE template or a SciVal researcher export.")
    res["header"] = header
    res["committed"] = commit
    return res


@app.get("/api/admin/templates/{kind}")
def template(kind: str):
    if kind not in importers.TEMPLATES:
        raise HTTPException(404, "Unknown template.")
    return PlainTextResponse(importers.TEMPLATES[kind], media_type="text/csv",
                             headers={"Content-Disposition": f'attachment; filename="rice-{kind}-template.csv"'})


@app.get("/api/admin/audit")
def audit_log(c: Ctx = Depends(ctx), con=Depends(get_con)):
    c.need("audit.view")
    rows = db.rows(con, "SELECT a.*, p.name AS actor FROM audit a LEFT JOIN people p ON p.id=a.actor_id WHERE a.inst_id=? "
                        "ORDER BY a.created_at DESC, a.id DESC LIMIT 200", (c.inst_id,))
    return {"rows": rows}


# ── OpenAlex sync ────────────────────────────────────────────────────────────
class OpenAlexIn(BaseModel):
    orcid: str
    commit: bool = False
    pick: list[int] = []


@app.post("/api/me/openalex")
def openalex(body: OpenAlexIn, c: Ctx = Depends(ctx), con=Depends(get_con)):
    c.need("outputs.create")
    try:
        works = importers.fetch_openalex(body.orcid)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception:
        raise HTTPException(502, "OpenAlex didn't respond. Check the internet connection and try again.")
    existing = {(r["doi"] or "").lower() for r in db.rows(con, "SELECT doi FROM publications WHERE doi IS NOT NULL")}
    existing_titles = {r["t"] for r in db.rows(con, "SELECT lower(title) t FROM publications WHERE created_by=?", (c.uid,))}
    for i, w in enumerate(works):
        w["index"] = i
        w["duplicate"] = bool(w["doi"] and w["doi"].lower() in existing) or (w["title"] or "").lower() in existing_titles
    if not body.commit:
        return {"works": works}
    added = 0
    orcid = body.orcid.strip().replace("https://orcid.org/", "")
    status = _status_for_new(c)
    for i in body.pick:
        if i >= len(works) or works[i]["duplicate"] or not works[i]["title"]:
            continue
        w = works[i]
        cur = con.execute("INSERT INTO publications (inst_id,title,kind,venue,year,citations,doi,keywords,sdgs,open_access,status,source,created_by) "
                          "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                          (c.inst_id, w["title"], w["kind"], w["venue"], w["year"], w["citations"], w["doi"], db.jd(w["keywords"]),
                           db.jd(sdgs_for(w["title"] + " " + " ".join(w["keywords"]))), w["open_access"], status, "openalex", c.uid))
        pid = cur.lastrowid
        for pos, a in enumerate(w["authors"][:30]):
            mine = a.get("orcid") == orcid
            con.execute("INSERT INTO pub_authors (pub_id, position, person_id, ext_name, ext_affil, ext_country) VALUES (?,?,?,?,?,?)",
                        (pid, pos, c.uid if mine else None, None if mine else a["name"], None if mine else a.get("affil"),
                         None if mine else ({"IN": "India"}.get(a.get("country"), a.get("country")))))
        added += 1
    con.execute("UPDATE people SET orcid=? WHERE id=?", (orcid, c.uid))
    audit(con, c, "import.openalex", c.user["name"], f"{added} works")
    con.commit()
    db.bump()
    return {"ok": True, "added": added, "status": status}


# ── reports & export ─────────────────────────────────────────────────────────
@app.get("/api/reports/{kind}")
def report(kind: str, year: int = NOW_YEAR, c: Ctx = Depends(ctx)):
    c.need("reports.view")
    s = db.snapshot()
    if kind == "naac":
        return reports.naac(s, c.inst_id, year)
    if kind == "nirf":
        peers = {i for i in c.visible("summary") if not s.inst[i]["external"]}
        return reports.nirf(s, c.inst_id, year, peers)
    if kind == "annual":
        return reports.annual(s, c.inst_id, year)
    raise HTTPException(404, "Unknown report.")


@app.get("/api/export/{entity}.csv")
def export_csv(entity: str, scope: str = "institution", dept: int | None = None, y0: int | None = None, y1: int | None = None,
               c: Ctx = Depends(ctx)):
    c.need("data.export")
    if entity not in ("publications", "projects", "patents", "people"):
        raise HTTPException(404, "Unknown export.")
    s = db.snapshot()
    sc, _ = resolve_scope(c, scope, dept, None, y0, y1)
    rows = list(reports.export_rows(s, entity, sc))
    buf = io.StringIO()
    if rows:
        w = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    name = f"rice-{(c.inst['code'] if c.inst else 'all').lower()}-{entity}.csv"
    return StreamingResponse(iter(["﻿" + buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": f'attachment; filename="{name}"'})


# ── platform (SaaS operator) ─────────────────────────────────────────────────
def platform_overview_data(con):
    s = db.snapshot()
    tenants = []
    for i in s.inst.values():
        if i["external"]:
            continue
        ppl = [p for p in s.people.values() if p["inst_id"] == i["id"]]
        active = sum(1 for p in ppl if p["status"] == "active")
        logins = db.scalar(con, "SELECT COUNT(*) FROM people WHERE inst_id=? AND last_login >= datetime('now','-30 days')", (i["id"],))
        k = A.overview(s, A.Scope(frozenset([i["id"]]), y0=2019, y1=s.max_year))["kpis"]
        tenants.append({"id": i["id"], "name": i["name"], "short": i["short"], "city": i["city"], "state": i["state"],
                        "brand": i["brand"], "plan": i["plan"], "status": i["status"], "share_level": i["share_level"],
                        "members": active, "pending": sum(1 for p in ppl if p["status"] == "pending"), "active_30d": logins,
                        "publications": k["publications"], "citations": k["citations"], "funding_lakh": k["funding_lakh"],
                        "created_at": i["created_at"], "is_demo": bool(i["is_demo"])})
    plans = {}
    for t in tenants:
        plans[t["plan"]] = plans.get(t["plan"], 0) + 1
    return {"tenants": sorted(tenants, key=lambda t: t["name"]), "plans": plans,
            "tracked": sum(1 for i in s.inst.values() if i["external"]),
            "onboarding": db.rows(con, "SELECT * FROM onboarding_requests ORDER BY CASE status WHEN 'new' THEN 0 ELSE 1 END, created_at DESC")}


@app.get("/api/platform/overview")
def platform_overview(c: Ctx = Depends(ctx), con=Depends(get_con)):
    if not c.platform:
        raise HTTPException(403, "For the RICE platform team only.")
    s = db.snapshot()
    data = platform_overview_data(con)
    sc = A.Scope(frozenset(i for i, x in s.inst.items() if not x["external"]), y0=2015, y1=s.max_year)
    data["network"] = A.overview(s, sc)
    data["benchmark"] = A.benchmark(s, sorted(sc.insts), 2019, s.max_year)
    return data


class TenantIn(BaseModel):
    name: str = Field(min_length=3)
    short: str = Field(min_length=2, max_length=10)
    city: str = ""
    state: str = ""
    kind: str = "College"
    plan: str = "Campus"
    brand: str = "#2B59FF"
    admin_name: str = Field(min_length=2)
    admin_email: str
    departments: list[str] = ["CSE", "ECE", "MECH"]
    onboarding_id: int | None = None


@app.post("/api/platform/tenants")
def create_tenant(body: TenantIn, c: Ctx = Depends(ctx), con=Depends(get_con)):
    if not c.platform:
        raise HTTPException(403, "For the RICE platform team only.")
    code = re.sub(r"[^A-Z0-9]", "", body.short.upper())
    if db.scalar(con, "SELECT 1 FROM institutions WHERE code=?", (code,)):
        raise HTTPException(409, "That short code is taken.")
    if db.scalar(con, "SELECT 1 FROM people WHERE lower(email)=lower(?)", (body.admin_email,)):
        raise HTTPException(409, "The admin email is already in use.")
    cur = con.execute("INSERT INTO institutions (code,name,short,city,state,kind,brand,share_level,plan,status,source,settings) "
                      "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", (code, body.name, code, body.city, body.state, body.kind, body.brand,
                                                          "summary", body.plan, "active", "onboarding", "{}"))
    iid = cur.lastrowid
    for d in body.departments:
        if d in DEPARTMENTS:
            con.execute("INSERT INTO departments (inst_id, code, name, field) VALUES (?,?,?,?)", (iid, d, DEPARTMENTS[d][0], DEPARTMENTS[d][1]))
    import secrets as _s
    temp = "rice-" + _s.token_hex(4)
    con.execute("INSERT INTO people (inst_id, name, email, pw_hash, role, designation, status, source, joined, hue) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (iid, body.admin_name, body.admin_email.lower(), hash_pw(temp), "inst_admin", "Institution admin", "active", "onboarding", NOW_YEAR, 200))
    if body.onboarding_id:
        con.execute("UPDATE onboarding_requests SET status='approved' WHERE id=?", (body.onboarding_id,))
    con.execute("INSERT INTO audit (inst_id, actor_id, action, target, detail) VALUES (?,?,?,?,?)",
                (iid, c.uid, "tenant.create", body.name, body.plan))
    con.commit()
    db.bump()
    return {"ok": True, "id": iid, "code": code, "temp_password": temp,
            "message": f"{body.name} is live. Share the admin sign-in with {body.admin_name}."}


class TenantPatch(BaseModel):
    plan: str | None = None
    status: str | None = None


@app.patch("/api/platform/tenants/{iid}")
def patch_tenant(iid: int, body: TenantPatch, c: Ctx = Depends(ctx), con=Depends(get_con)):
    if not c.platform:
        raise HTTPException(403, "For the RICE platform team only.")
    data = body.model_dump(exclude_none=True)
    if "status" in data and data["status"] not in ("active", "trial", "suspended"):
        raise HTTPException(400, "Unknown status.")
    if "plan" in data and data["plan"] not in ("Campus", "Research+", "Enterprise"):
        raise HTTPException(400, "Unknown plan.")
    if data:
        con.execute(f"UPDATE institutions SET {', '.join(f'{k}=?' for k in data)} WHERE id=? AND external=0", (*data.values(), iid))
        con.execute("INSERT INTO audit (inst_id, actor_id, action, target, detail) VALUES (?,?,?,?,?)",
                    (iid, c.uid, "tenant.update", str(iid), ", ".join(f"{k} → {v}" for k, v in data.items())))
        con.commit()
        db.bump()
    return {"ok": True}


@app.post("/api/platform/onboarding/{rid}/decline")
def decline_onboarding(rid: int, c: Ctx = Depends(ctx), con=Depends(get_con)):
    if not c.platform:
        raise HTTPException(403, "For the RICE platform team only.")
    con.execute("UPDATE onboarding_requests SET status='declined' WHERE id=?", (rid,))
    con.commit()
    return {"ok": True}


# ── static web app ───────────────────────────────────────────────────────────
app.mount("/assets", StaticFiles(directory=WEB / "assets"), name="assets")


@app.get("/")
def index():
    return FileResponse(WEB / "index.html", headers={"Cache-Control": "no-cache"})


@app.get("/favicon.svg")
def favicon():
    return FileResponse(WEB / "favicon.svg")


# Connect to Neo4j (starting the bundled server if it's installed), sync the knowledge graph and warm caches.
neo.start_background(autostart=os.environ.get("RICE_NEO4J_AUTOSTART", "1") == "1")
