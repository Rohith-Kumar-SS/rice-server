"""Deterministic demo data: six fictional institutions on one RICE platform.

Run:  python -m server.seed            (rebuilds data/rice.db)
Every seeded account uses the password in RICE_DEMO_PASSWORD (default below).
"""
from __future__ import annotations

import math
import os
import random
import re
from collections import defaultdict

import numpy as np

from . import db
from .catalog import (ADJ, AGENCIES, CHAPTER_VENUES, DEPARTMENTS, EXT_FIRST, EXT_LAST, EXTERNAL_AFFILS, FIRST, FRAME,
                      LAST, STUDY, SUFFIX, VENUES, sdgs_for, topic_weight, venue_group)
from .security import DEFAULT_SETTINGS, hash_pw

DEMO_PASSWORD = os.environ.get("RICE_DEMO_PASSWORD", "rice-demo-2026")
NOW_YEAR = 2026
START_YEAR = 2015

INSTITUTIONS = [
    dict(code="KAVU", name="Kaveri University", city="Bengaluru", state="Karnataka", kind="University", established=1962,
         brand="#2B59FF", share_level="public", plan="Enterprise", lat=12.97, lon=77.59,
         tagline="Research that travels from the lab to the Kaveri basin",
         depts=["CSE", "AIDS", "ECE", "EEE", "MECH", "PHY", "MATH", "MGMT"], fac=(8, 12),
         productivity=1.15, impact=1.15, bridge=1.25, growth=0.07, funding=1.2),
    dict(code="WGIT", name="Western Ghats Institute of Technology", city="Kochi", state="Kerala", kind="Institute",
         established=1984, brand="#0E9F6E", share_level="network", plan="Research+", lat=9.93, lon=76.27,
         tagline="Engineering for the coast, the hills and the grid",
         depts=["CSE", "CYS", "ECE", "EEE", "CIVIL", "MECH", "MATH"], fac=(7, 11),
         productivity=1.0, impact=0.95, bridge=1.0, growth=0.08, funding=1.0),
    dict(code="DIAS", name="Deccan Institute of Advanced Studies", city="Hyderabad", state="Telangana", kind="Institute",
         established=1999, brand="#7A3FF2", share_level="network", plan="Enterprise", lat=17.39, lon=78.49,
         tagline="Fundamental science, applied with intent",
         depts=["CHEM", "PHY", "BIO", "MATH", "CSE", "AIDS"], fac=(7, 11),
         productivity=1.05, impact=1.55, bridge=1.1, growth=0.06, funding=1.35),
    dict(code="GVU", name="Ganga Valley University", city="Varanasi", state="Uttar Pradesh", kind="University",
         established=1957, brand="#E8590C", share_level="summary", plan="Campus", lat=25.32, lon=82.97,
         tagline="A heritage campus building its research engine",
         depts=["CIVIL", "MGMT", "MATH", "CHEM", "CSE", "ECE", "BIO"], fac=(6, 10),
         productivity=0.72, impact=0.8, bridge=0.7, growth=0.11, funding=0.7),
    dict(code="CTU", name="Coromandel Technological University", city="Chennai", state="Tamil Nadu", kind="University",
         established=2008, brand="#D6336C", share_level="network", plan="Research+", lat=13.08, lon=80.27,
         tagline="Young, fast and built around industry problems",
         depts=["MECH", "EEE", "CSE", "CYS", "ECE", "AIDS", "CHEM"], fac=(7, 10),
         productivity=0.95, impact=0.9, bridge=1.05, growth=0.15, funding=1.1),
    dict(code="HIRT", name="Himgiri Institute of Research & Technology", city="Dehradun", state="Uttarakhand",
         kind="Institute", established=2012, brand="#0B7285", share_level="private", plan="Campus", lat=30.32, lon=78.03,
         tagline="Mountain science for a warming world",
         depts=["ENV", "CIVIL", "CSE", "PHY"], fac=(5, 8),
         productivity=0.85, impact=1.0, bridge=0.8, growth=0.09, funding=0.9),
]

DESIG_FACTOR = {"Professor": 1.35, "Associate Professor": 1.1, "Assistant Professor": 0.82}
STUDENT_PROG = {"Computing": ["B.Tech", "M.Tech"], "Engineering": ["B.Tech", "M.Tech"], "Sciences": ["M.Sc", "Integrated M.Sc"],
                "Life Sciences": ["M.Sc", "B.Tech"], "Management": ["MBA", "BBA"]}


class Gen:
    def __init__(self, seed=2026):
        self.r = random.Random(seed)
        self.n = np.random.default_rng(seed)
        self.used_names = set()
        self.used_emails = set()

    def name(self):
        for _ in range(200):
            nm = f"{self.r.choice(FIRST)} {self.r.choice(LAST)}"
            if nm not in self.used_names:
                self.used_names.add(nm)
                return nm
        nm = f"{self.r.choice(FIRST)} {self.r.choice(LAST)} {self.r.choice('ABCDEFGHKMNPRST')}."
        self.used_names.add(nm)
        return nm

    def email(self, name, code):
        base = "".join(c for c in name.lower().replace(" ", ".") if c.isalnum() or c == ".").strip(".")
        e, k = f"{base}@{code.lower()}.demo", 2
        while e in self.used_emails:
            e, k = f"{base}{k}@{code.lower()}.demo", k + 1
        self.used_emails.add(e)
        return e

    def poisson(self, lam):
        return int(self.n.poisson(max(lam, 0.0)))

    def wchoice(self, items, weights):
        tot = sum(weights)
        if tot <= 0:
            return self.r.choice(items)
        x, acc = self.r.random() * tot, 0.0
        for it, w in zip(items, weights):
            acc += w
            if x <= acc:
                return it
        return items[-1]


def make_title(g: Gen, topic, topic2, app):
    r = g.r
    adj = r.choice(ADJ)
    words = [w for w in re.findall(r"[A-Za-z]+", topic) if len(w) > 2]
    acr = (words[0][:4].capitalize() if len(words) == 1 else "".join(w[0] for w in words[:3]).upper()) + r.choice(SUFFIX)
    pats = [
        f"{adj.capitalize()} {topic} for {app}",
        f"{topic} for {app}: a {r.choice(STUDY)}",
        f"Towards {adj} {app} using {topic}",
        f"Enhancing {app} through {topic} and {topic2}",
        f"An empirical study of {topic} in {app}",
        f"{acr}: {adj} {topic} for {app}",
        f"Rethinking {app} with {topic}",
        f"A {r.choice(FRAME)} {topic} framework for {app}",
        f"{topic} meets {topic2}: towards {adj} {app}",
        f"Benchmarking {topic} methods for {app}",
        f"On the role of {topic} in {app}",
    ]
    return r.choice(pats)


def project_title(g: Gen, topic, app):
    r = g.r
    pats = [f"{topic}-enabled {app}", f"Development of a {r.choice(ADJ)} platform for {app}",
            f"Design and field validation of {topic} for {app}", f"{app.capitalize()} using {topic}: from lab to deployment",
            f"Indigenous {topic} solutions for {app}"]
    return r.choice(pats)


def patent_title(g: Gen, topic, app):
    r = g.r
    pats = [f"A system and method for {app} using {topic}", f"Device for {r.choice(ADJ)} {app}",
            f"Method of {app} based on {topic}", f"Apparatus for {app} with integrated {topic}"]
    return r.choice(pats)


def build(path=None, with_scival=True, quiet=False):
    if path:
        db.DB_PATH = path
    if db.DB_PATH.exists():
        db.DB_PATH.unlink()
    for ext in ("-wal", "-shm"):
        p = db.DB_PATH.with_name(db.DB_PATH.name + ext)
        if p.exists():
            p.unlink()
    con = db.connect()
    db.init_schema(con)
    g = Gen()
    r = g.r
    pw = hash_pw(DEMO_PASSWORD, salt="ricedemo")
    cur = con.cursor()

    def add_person(**kw):
        kw.setdefault("pw_hash", pw)
        kw.setdefault("hue", r.randint(0, 359))
        kw["interests"] = db.jd(kw.get("interests", []))
        cols = ",".join(kw)
        cur.execute(f"INSERT INTO people ({cols}) VALUES ({','.join('?' * len(kw))})", list(kw.values()))
        return cur.lastrowid

    # ── Platform admin ───────────────────────────────────────────────────────
    add_person(inst_id=None, dept_id=None, name="Aditi Raghavan", email="admin@rice.demo", role="platform_admin",
               designation="RICE platform operations", interests=["Research analytics"], joined=2024)

    inst_rows = {}
    faculty_by_inst = defaultdict(list)
    people = {}  # id -> dict(meta for generation)
    dept_of = {}
    for cfg in INSTITUTIONS:
        cur.execute(
            "INSERT INTO institutions (code,name,short,city,state,kind,established,brand,share_level,plan,status,is_demo,"
            "external,source,lat,lon,tagline,settings) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (cfg["code"], cfg["name"], cfg["code"], cfg["city"], cfg["state"], cfg["kind"], cfg["established"],
             cfg["brand"], cfg["share_level"], cfg["plan"], "active", 1, 0, "seed", cfg["lat"], cfg["lon"],
             cfg["tagline"], db.jd({"require_verification": True, "allow_signup": True})))
        iid = cur.lastrowid
        inst_rows[cfg["code"]] = (iid, cfg)
        code = cfg["code"]

        # institution admin + research staff
        admin_name = g.name()
        admin_email = "research.cell@kavu.demo" if code == "KAVU" else f"admin@{code.lower()}.demo"
        g.used_emails.add(admin_email)
        add_person(inst_id=iid, dept_id=None, name=admin_name, email=admin_email, role="inst_admin",
                   designation="Dean (Research)", interests=["Research administration"], joined=2010 + r.randint(0, 10))
        for desig in ("Research cell officer", "IPR & funding coordinator"):
            nm = g.name()
            add_person(inst_id=iid, dept_id=None, name=nm, email=g.email(nm, code), role="staff", designation=desig,
                       interests=["Research administration"], joined=2016 + r.randint(0, 8))

        for dcode in cfg["depts"]:
            dname, field, topics, apps = DEPARTMENTS[dcode]
            cur.execute("INSERT INTO departments (inst_id, code, name, field) VALUES (?,?,?,?)", (iid, dcode, dname, field))
            did = cur.lastrowid
            dept_of[did] = (dcode, field, topics, apps, iid)
            nfac = r.randint(*cfg["fac"])
            desigs = ["Professor"] * max(1, round(nfac * 0.22)) + ["Associate Professor"] * round(nfac * 0.3)
            desigs += ["Assistant Professor"] * (nfac - len(desigs))
            fac_ids = []
            for i, desig in enumerate(desigs):
                nm = g.name()
                k = r.randint(3, 5)
                weights = [1.6 if t in topics[:4] else 1.0 for t in topics]
                interests = []
                while len(interests) < k:
                    t = g.wchoice(topics, weights)
                    if t not in interests:
                        interests.append(t)
                if r.random() < 0.3:  # a cross-cutting interest borrowed from another department
                    other = DEPARTMENTS[r.choice(list(DEPARTMENTS))][2]
                    t = r.choice(other)
                    if t not in interests:
                        interests.append(t)
                joined = {"Professor": r.randint(1994, 2011), "Associate Professor": r.randint(2004, 2017),
                          "Assistant Professor": r.randint(2012, 2024)}[desig]
                joined = max(joined, cfg["established"])
                role = "hod" if i == 0 else "faculty"
                pid = add_person(inst_id=iid, dept_id=did, name=nm, email=g.email(nm, code), role=role, designation=desig,
                                 interests=interests, joined=joined,
                                 bio=f"Works on {', '.join(interests[:2]).lower()} with a focus on {r.choice(apps)}.")
                prod = float(g.n.lognormal(0, 0.5)) * cfg["productivity"] * DESIG_FACTOR[desig]
                if r.random() < 0.13:  # some faculty are research-dormant — realistic and worth flagging
                    prod *= 0.12
                impact = float(g.n.lognormal(0, 0.45)) * cfg["impact"]
                bridge = min(1.0, (r.random() ** 1.7) * cfg["bridge"])
                people[pid] = dict(id=pid, inst=iid, dept=did, field=field, interests=interests, apps=apps, desig=desig,
                                   joined=joined, prod=prod, impact=impact, bridge=bridge, role=role, scholars=[],
                                   students=[], mates=[], partners=[], code=code)
                fac_ids.append(pid)
                faculty_by_inst[iid].append(pid)

            # research scholars and students
            for fid in fac_ids:
                f = people[fid]
                n_sch = {"Professor": r.randint(1, 4), "Associate Professor": r.randint(0, 3),
                         "Assistant Professor": r.randint(0, 1)}[f["desig"]]
                for _ in range(n_sch):
                    nm = g.name()
                    joined = r.randint(2019, 2025)
                    ints = r.sample(f["interests"], min(2, len(f["interests"])))
                    sid = add_person(inst_id=iid, dept_id=did, name=nm, email=g.email(nm, code), role="scholar",
                                     designation="PhD scholar", interests=ints, joined=joined, supervisor_id=fid)
                    people[sid] = dict(id=sid, inst=iid, dept=did, field=field, interests=ints, joined=joined, role="scholar",
                                       supervisor=fid)
                    f["scholars"].append(sid)
            for _ in range(r.randint(2, 5)):
                fid = r.choice(fac_ids)
                f = people[fid]
                nm = g.name()
                prog = r.choice(STUDENT_PROG.get(field, ["B.Tech"]))
                joined = r.randint(2022, 2025)
                ints = [r.choice(f["interests"])]
                sid = add_person(inst_id=iid, dept_id=did, name=nm, email=g.email(nm, code), role="student",
                                 designation=f"{prog} student", interests=ints, joined=joined, supervisor_id=fid)
                people[sid] = dict(id=sid, inst=iid, dept=did, field=field, interests=ints, joined=joined, role="student",
                                   supervisor=fid)
                f["students"].append(sid)

    faculty = [p for p in people.values() if p["role"] in ("faculty", "hod")]

    def overlap(a, b):
        return len(set(a["interests"]) & set(b["interests"]))

    # preferred collaborators: lab mates (mostly same department) and cross-institution partners
    by_dept = defaultdict(list)
    for f in faculty:
        by_dept[f["dept"]].append(f)
    by_inst = defaultdict(list)
    for f in faculty:
        by_inst[f["inst"]].append(f)
    for f in faculty:
        same = [x for x in by_dept[f["dept"]] if x["id"] != f["id"]]
        other = [x for x in by_inst[f["inst"]] if x["dept"] != f["dept"]]
        k = r.randint(2, 4)
        for _ in range(k):
            if other and r.random() < 0.18 + 0.35 * f["bridge"]:
                cand = sorted(other, key=lambda x: -(overlap(f, x) + r.random()))[:4]
            else:
                cand = sorted(same, key=lambda x: -(overlap(f, x) + r.random() * 1.5))[:4]
            if cand:
                m = r.choice(cand)["id"]
                if m not in f["mates"]:
                    f["mates"].append(m)
        if r.random() < 0.15 + 0.6 * f["bridge"]:
            pool = [x for x in faculty if x["inst"] != f["inst"] and (x["field"] == f["field"] or overlap(f, x))]
            if pool:
                cand = sorted(pool, key=lambda x: -(overlap(f, x) * 2 + r.random() * 2))[:6]
                for m in r.sample(cand, min(len(cand), r.randint(1, 2))):
                    f["partners"].append(m["id"])
                    people[m["id"]]["partners"].append(f["id"])

    # ── Publications ─────────────────────────────────────────────────────────
    pub_rows, author_rows = [], []
    pid_counter = 0
    for f in faculty:
        cfg = inst_rows[f["code"]][1]
        start = max(START_YEAR, f["joined"])
        for year in range(start, NOW_YEAR + 1):
            growth = (1 + cfg["growth"]) ** (year - 2020)
            lam = 0.95 * f["prod"] * growth * (0.9 if year == NOW_YEAR else 1.0)
            for _ in range(g.poisson(lam)):
                pid_counter += 1
                weights = [topic_weight(t, year) for t in f["interests"]]
                if sum(weights) == 0:
                    weights = [1] * len(f["interests"])
                topic = g.wchoice(f["interests"], weights)
                authors = [f["id"]]
                scholars = [s for s in f["scholars"] if people[s]["joined"] < year]
                if scholars and r.random() < 0.72:
                    s = r.choice(scholars)
                    authors.insert(0, s) if r.random() < 0.65 else authors.append(s)
                    if len(scholars) > 1 and r.random() < 0.2:
                        authors.append(r.choice([x for x in scholars if x != s]))
                for m in f["mates"]:
                    if r.random() < 0.3 and people[m]["joined"] <= year:
                        authors.append(m)
                for m in f["partners"]:
                    if r.random() < (0.12 + 0.3 * f["bridge"]) * (0.45 if year < 2019 else 1.0):
                        authors.append(m)
                studs = [s for s in f["students"] if people[s]["joined"] < year]
                if studs and r.random() < 0.18:
                    authors.append(r.choice(studs))
                authors = list(dict.fromkeys(authors))
                topic2_pool = [t for a in authors for t in people[a]["interests"] if t != topic] or f["interests"]
                topic2 = r.choice(topic2_pool)
                app = r.choice(f["apps"])
                title = make_title(g, topic, topic2, app)
                u = r.random()
                kind = "journal" if u < 0.58 else "conference" if u < 0.9 else "chapter" if u < 0.97 else "preprint"
                if kind == "preprint" and year < 2019:
                    kind = "journal"
                group = VENUES[venue_group(f["field"])]
                if kind == "journal":
                    jlist = group["journal"]
                    qw = [{"Q1": 1.0 * f["impact"], "Q2": 1.1, "Q3": 0.9 / f["impact"], "Q4": 0.6 / f["impact"]}[q] for _, q in jlist]
                    venue, quart = g.wchoice(jlist, qw)
                elif kind == "conference":
                    venue, quart = r.choice(group["conference"]), None
                elif kind == "chapter":
                    venue, quart = r.choice(CHAPTER_VENUES), None
                else:
                    venue, quart = "arXiv", None
                base = {"Q1": 13, "Q2": 6.5, "Q3": 3.2, "Q4": 1.4}.get(quart, {"conference": 3.0, "chapter": 1.4, "preprint": 2.0}.get(kind, 2))
                age = NOW_YEAR - year
                agef = (min(1.0, (age + 0.3) / 4.0) ** 0.9) * (1 + 0.09 * age)
                lam_c = base * f["impact"] * agef
                cites = int(g.n.lognormal(math.log(lam_c + 0.05), 0.85)) if r.random() > 0.1 else 0
                oa = 1 if ("MDPI" in venue or venue in ("Sensors", "Electronics", "Mathematics", "IEEE Access", "PLOS ONE",
                                                         "Scientific Reports", "Frontiers in Microbiology", "arXiv", "RSC Advances")) \
                    else int(r.random() < min(0.6, 0.22 + 0.03 * (year - START_YEAR)))
                kws = list(dict.fromkeys([topic, topic2] + ([r.choice(f["interests"])] if r.random() < 0.4 else [])))
                status = "verified"
                if year == NOW_YEAR and r.random() < 0.14:
                    status = "pending"
                vis = "public" if r.random() > 0.07 else "internal"
                pub_rows.append((pid_counter, f["inst"], title, kind, venue, year, quart, cites,
                                 f"10.5555/ricedemo.{year}.{pid_counter:05d}", db.jd(kws), db.jd(sdgs_for(title + " " + " ".join(kws))),
                                 oa, status, vis, f["id"]))
                pos = 0
                for a in authors:
                    author_rows.append((pid_counter, pos, a, None, None, None))
                    pos += 1
                if r.random() < 0.26 + 0.25 * f["bridge"]:
                    affil, country = r.choice(EXTERNAL_AFFILS)
                    for _ in range(r.randint(1, 3)):
                        if country == "India":
                            en = f"{r.choice(FIRST)} {r.choice(LAST)}"
                        else:
                            en = f"{r.choice(EXT_FIRST)} {r.choice(EXT_LAST)}"
                        author_rows.append((pid_counter, pos, None, en, affil, country))
                        pos += 1
    cur.executemany("INSERT INTO publications (id,inst_id,title,kind,venue,year,quartile,citations,doi,keywords,sdgs,"
                    "open_access,status,visibility,created_by) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", pub_rows)
    cur.executemany("INSERT INTO pub_authors (pub_id,position,person_id,ext_name,ext_affil,ext_country) VALUES (?,?,?,?,?,?)",
                    author_rows)

    # ── Projects & funding ───────────────────────────────────────────────────
    agencies = list(AGENCIES)
    proj_n = 0
    for f in faculty:
        cfg = inst_rows[f["code"]][1]
        n_apps = g.poisson(1.5 * DESIG_FACTOR[f["desig"]] * cfg["funding"] * (0.6 + f["prod"] * 0.4))
        for _ in range(n_apps):
            eligible = [a for a in agencies if AGENCIES[a][3] is None or f["field"] in AGENCIES[a][3]]
            w = [{"Internal": 1.4, "SERB": 1.2, "ANRF": 1.0, "DST": 1.0, "Industry": 1.1, "International": 0.35}.get(a, 0.7) for a in eligible]
            agency = g.wchoice(eligible, w)
            sector, schemes, (lo, hi), _ = AGENCIES[agency]
            start = r.randint(max(START_YEAR, f["joined"]), NOW_YEAR)
            if agency == "SERB" and start >= 2024:
                agency = "ANRF"
                sector, schemes, (lo, hi), _ = AGENCIES[agency]
            if agency == "ANRF" and start < 2024:
                agency = "SERB"
                sector, schemes, (lo, hi), _ = AGENCIES[agency]
            scheme = r.choice(schemes)
            amount = round(r.uniform(lo, hi) * (0.8 + 0.4 * cfg["funding"]), 1)
            dur = r.randint(2, 4)
            succ = {"Internal": 0.85, "Industry": 0.7}.get(agency, 0.42 + 0.1 * cfg["funding"])
            if start >= NOW_YEAR and r.random() < 0.6:
                stage = "submitted"
            elif r.random() > succ:
                stage = "not_funded"
            else:
                stage = "completed" if start + dur < NOW_YEAR else "ongoing"
            topic = r.choice(f["interests"])
            title = project_title(g, topic, r.choice(f["apps"]))
            proj_n += 1
            status = "pending" if (stage in ("ongoing",) and start == NOW_YEAR and r.random() < 0.3) else "verified"
            cur.execute("INSERT INTO projects (id,inst_id,title,agency,scheme,sector,amount,start_year,end_year,stage,keywords,"
                        "status,created_by) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (proj_n, f["inst"], title, agency, scheme, sector, amount, start, start + dur, stage,
                         db.jd([topic]), status, f["id"]))
            members = [(f["id"], "PI")]
            for m in f["mates"][:2]:
                if r.random() < 0.45:
                    members.append((m, "Co-PI"))
            for m in f["partners"]:
                if r.random() < 0.25 and stage != "not_funded":
                    members.append((m, "Co-PI"))
            for s in f["scholars"]:
                if r.random() < 0.45:
                    members.append((s, "Scholar"))
            seen = set()
            for mid, role in members:
                if mid in seen:
                    continue
                seen.add(mid)
                cur.execute("INSERT INTO project_members (project_id, person_id, role) VALUES (?,?,?)", (proj_n, mid, role))

    # ── Patents ──────────────────────────────────────────────────────────────
    pat_n = 0
    for f in faculty:
        p_rate = {"Engineering": 0.24, "Computing": 0.16, "Sciences": 0.2, "Life Sciences": 0.22, "Management": 0.03}[f["field"]]
        if r.random() < p_rate * (0.7 + f["prod"] * 0.4):
            for _ in range(r.randint(1, 3)):
                pat_n += 1
                year = r.randint(max(2016, f["joined"]), NOW_YEAR)
                age = NOW_YEAR - year
                stage = "granted" if age >= 4 and r.random() < 0.6 else "published" if age >= 1 and r.random() < 0.75 else "filed"
                topic = r.choice(f["interests"])
                cur.execute("INSERT INTO patents (id,inst_id,title,stage,year,number,keywords,status,created_by) VALUES (?,?,?,?,?,?,?,?,?)",
                            (pat_n, f["inst"], patent_title(g, topic, r.choice(f["apps"])), stage, year,
                             f"DEMO-{year}-{pat_n:04d}", db.jd([topic]),
                             "pending" if year == NOW_YEAR and r.random() < 0.35 else "verified", f["id"]))
                inv = [f["id"]] + [m for m in f["mates"][:2] if r.random() < 0.4] + [s for s in f["scholars"][:2] if r.random() < 0.3]
                for m in dict.fromkeys(inv):
                    cur.execute("INSERT INTO patent_inventors (patent_id, person_id) VALUES (?,?)", (pat_n, m))

    # ── Demo personas (stable, memorable logins) ─────────────────────────────
    kavu_id = inst_rows["KAVU"][0]
    kavu_cse = db.scalar(con, "SELECT id FROM departments WHERE inst_id=? AND code='CSE'", (kavu_id,))
    pub_count = defaultdict(int)
    for row in author_rows:
        if row[2]:
            pub_count[row[2]] += 1
    cse_fac = [f for f in faculty if f["dept"] == kavu_cse]
    hod = next(f for f in cse_fac if f["role"] == "hod")
    prof = max((f for f in cse_fac if f["role"] == "faculty" and f["scholars"]),
               key=lambda f: pub_count[f["id"]] * (1 + len(f["partners"])))
    scholar = prof["scholars"][0]
    student_row = db.one(con, "SELECT id FROM people WHERE inst_id=? AND role='student' ORDER BY id LIMIT 1", (kavu_id,))
    for pid, email in ((hod["id"], "hod.cse@kavu.demo"), (prof["id"], "prof@kavu.demo"), (scholar, "scholar@kavu.demo"),
                       (student_row["id"], "student@kavu.demo")):
        cur.execute("UPDATE people SET email=? WHERE id=?", (email, pid))
    add_person(inst_id=kavu_id, dept_id=None, name="Farhan Siddiqui", email="partner@rice.demo", role="external",
               designation="Industry partner — applied AI lab", interests=["Edge Computing", "Computer Vision"], joined=2025)

    # ── Pending join requests ────────────────────────────────────────────────
    for code, (iid, cfg) in inst_rows.items():
        depts = db.rows(con, "SELECT id, code FROM departments WHERE inst_id=?", (iid,))
        for _ in range(r.randint(1, 3)):
            d = r.choice(depts)
            nm = g.name()
            role = r.choice(["scholar", "scholar", "faculty", "student"])
            add_person(inst_id=iid, dept_id=d["id"], name=nm, email=g.email(nm, code), role=role, requested_role=role,
                       designation={"scholar": "PhD scholar", "faculty": "Assistant Professor", "student": "M.Tech student"}[role],
                       interests=r.sample(DEPARTMENTS[d["code"]][2], 2), joined=NOW_YEAR, status="pending", source="signup")

    # ── Opportunities ────────────────────────────────────────────────────────
    opp_templates = [
        ("call", "ANRF Core Research Grant 2027 — internal review window", "Submit a 2-page concept note to the research cell for internal review before the national deadline.", ["Funding", "ANRF"], "2026-12-05", "internal"),
        ("call", "DST-FIST equipment proposals from departments", "Departments planning shared instrumentation can propose items for the FIST application.", ["Funding", "Infrastructure"], "2026-12-20", "internal"),
        ("position", "Junior Research Fellow — federated learning for hospitals", "Funded JRF position on a MeitY project. GATE/NET qualified candidates preferred.", ["JRF", "Federated Learning", "Healthcare Analytics"], "2026-12-15", "network"),
        ("collab", "Co-PI wanted: battery state-of-health with physics-informed ML", "Looking for a co-PI from Chemistry or Data Science to strengthen an ANRF proposal.", ["Battery Management Systems", "Machine Learning"], "2026-12-10", "network"),
        ("event", "Research methodology & paper-writing bootcamp", "Three evenings on literature review, reproducible experiments and writing for Q1 venues.", ["Training", "Scholars"], "2026-11-28", "internal"),
        ("position", "Post-doctoral fellow — perovskite photovoltaics", "Two-year post-doc on device fabrication and stability testing.", ["Post-doc", "Photonics", "Condensed Matter"], "2027-01-10", "network"),
        ("collab", "Field partners for LoRaWAN flood sensors in the Western Ghats", "We have 40 nodes deployed and seek hydrology and GIS collaborators.", ["LoRaWAN", "Climate Resilience", "Remote Sensing & GIS"], "2027-01-31", "network"),
        ("call", "Institution seed grants — 2027 cycle", "Seed grants up to 5 lakh for first-time PIs and interdisciplinary pairs.", ["Funding", "Seed grant"], "2027-01-15", "internal"),
        ("position", "Research intern (summer) — LLMs for regional languages", "Eight-week internship for UG/PG students with Python experience.", ["Internship", "Large Language Models", "Natural Language Processing"], "2027-02-28", "network"),
        ("collab", "Looking for datasets on urban heat islands in tier-2 cities", "Happy to share satellite-derived land-surface temperature maps in return.", ["Remote Sensing & GIS", "Climate Resilience"], "2026-12-31", "network"),
        ("event", "Inter-institution symposium on post-quantum cryptography", "Half-day symposium with talks from four RICE institutions. Hybrid format.", ["Post-Quantum Cryptography", "Cryptography"], "2026-12-12", "network"),
        ("collab", "Industry problem: predictive maintenance on CNC lines", "A manufacturing partner offers sensor data and a site visit for a joint project.", ["Industry 4.0", "Digital Twins", "Machine Learning"], "2027-01-20", "network"),
    ]
    for i, (kind, title, body, tags, deadline, aud) in enumerate(opp_templates):
        code = list(inst_rows)[i % len(inst_rows)]
        iid = inst_rows[code][0]
        poster = r.choice([f for f in faculty if f["inst"] == iid])["id"] if kind != "call" else \
            db.scalar(con, "SELECT id FROM people WHERE inst_id=? AND role='inst_admin'", (iid,))
        status = "pending" if i in (9,) else "open"
        cur.execute("INSERT INTO opportunities (inst_id,posted_by,kind,title,body,tags,deadline,audience,status,created_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?,datetime('now', ?))",
                    (iid, poster, kind, title, body, db.jd(tags), deadline, aud, status, f"-{r.randint(1, 20)} days"))
    # make sure KAVU has its own internal calls
    for title, body, tags, deadline in [
        ("Kaveri seed grant for interdisciplinary pairs", "Up to 6 lakh for two PIs from different departments working on one problem.", ["Funding", "Seed grant"], "2027-01-05"),
        ("Call for NAAC criterion 3 evidence — verify your 2025–26 records", "Please verify pending publications and upload sanction letters before 30 November.", ["NAAC", "Compliance"], "2026-11-30"),
    ]:
        cur.execute("INSERT INTO opportunities (inst_id,posted_by,kind,title,body,tags,deadline,audience,status) VALUES (?,?,?,?,?,?,?,?,?)",
                    (kavu_id, db.scalar(con, "SELECT id FROM people WHERE email='research.cell@kavu.demo'"), "call", title, body,
                     db.jd(tags), deadline, "internal", "open"))

    # ── Collaboration requests ───────────────────────────────────────────────
    def collab(a, b, topic, msg, status, days):
        cur.execute("INSERT INTO collab_requests (from_id,to_id,topic,message,status,created_at,responded_at) VALUES "
                    "(?,?,?,?,?,datetime('now', ?), CASE WHEN ?='pending' THEN NULL ELSE datetime('now', ?) END)",
                    (a, b, topic, msg, status, f"-{days} days", status, f"-{max(0, days - 2)} days"))

    others = [f for f in faculty if f["inst"] != kavu_id and inst_rows_by_id(inst_rows)[f["inst"]]["share_level"] in ("network", "public")]
    prof_i = set(prof["interests"])
    near = sorted(others, key=lambda x: -(len(prof_i & set(x["interests"])) + r.random()))
    collab(near[0]["id"], prof["id"], (list(prof_i & set(near[0]["interests"])) or prof["interests"])[0],
           "Your recent work fits a proposal we're drafting. Would you be open to a call next week?", "pending", 2)
    collab(near[1]["id"], prof["id"], prof["interests"][0], "Could we co-supervise a scholar on this? We have compute and data.", "pending", 5)
    collab(prof["id"], near[2]["id"], prof["interests"][1], "Interested in a joint paper combining our datasets.", "pending", 3)
    collab(prof["id"], near[3]["id"], prof["interests"][0], "Following up from the symposium — shall we co-author?", "accepted", 40)
    for _ in range(12):
        a, b = r.sample(faculty, 2)
        if a["inst"] == b["inst"]:
            continue
        status = r.choice(["accepted", "accepted", "declined", "pending"])
        collab(a["id"], b["id"], r.choice(a["interests"]), "Exploring a joint proposal in this area.", status, r.randint(3, 120))

    # ── Notifications for personas ───────────────────────────────────────────
    def notify(pid, kind, text, link, days):
        cur.execute("INSERT INTO notifications (person_id,kind,text,link,created_at) VALUES (?,?,?,?,datetime('now', ?))",
                    (pid, kind, text, link, f"-{days} hours"))
    notify(prof["id"], "collab", "2 researchers asked to collaborate with you", "#/collaborate", 5)
    notify(prof["id"], "citation", "Your papers gained 31 citations this month", f"#/people/{prof['id']}", 30)
    notify(prof["id"], "match", "New collaborator suggestions based on your 2026 work", "#/discover", 60)
    hid = db.scalar(con, "SELECT id FROM people WHERE email='hod.cse@kavu.demo'")
    notify(hid, "verify", "Department records are waiting for your verification", "#/approvals", 3)
    aid = db.scalar(con, "SELECT id FROM people WHERE email='research.cell@kavu.demo'")
    notify(aid, "join", "New members asked to join Kaveri University", "#/approvals", 2)
    notify(aid, "report", "NAAC criterion 3 draft is ready to review", "#/reports", 26)
    notify(scholar, "opportunity", "A new JRF opening matches your interests", "#/opportunities", 12)

    # ── Onboarding requests (SaaS pipeline) ──────────────────────────────────
    for inst_name, city, state, kind, contact, role_, size, msg in [
        ("Malabar College of Engineering", "Kozhikode", "Kerala", "College", "Dr. Reshma Kurian", "Principal", "120 faculty",
         "We track research in spreadsheets and need NAAC-ready reports."),
        ("Narmada School of Management", "Vadodara", "Gujarat", "Institute", "Prof. Hemant Desai", "Director (Research)", "45 faculty",
         "Interested in benchmarking against peer B-schools."),
        ("Brahmaputra Institute of Science", "Guwahati", "Assam", "Institute", "Dr. Ankita Bora", "IQAC coordinator", "210 faculty",
         "Looking for collaboration discovery across North-East institutions."),
    ]:
        cur.execute("INSERT INTO onboarding_requests (inst_name,city,state,kind,contact_name,contact_email,contact_role,size,message,created_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?,datetime('now', ?))",
                    (inst_name, city, state, kind, contact, f"contact@{inst_name.split()[0].lower()}.demo", role_, size, msg,
                     f"-{r.randint(1, 9)} days"))

    # ── Audit trail ──────────────────────────────────────────────────────────
    for code, (iid, cfg) in inst_rows.items():
        admin = db.scalar(con, "SELECT id FROM people WHERE inst_id=? AND role='inst_admin'", (iid,))
        for i, (action, target, detail) in enumerate([
            ("settings.update", "Sharing policy", f"Set to {cfg['share_level']}"),
            ("import.people", "Faculty roster", "Imported department rosters"),
            ("verify.batch", "Publications", "Verified records for 2025"),
            ("role.change", "Member", "Promoted a faculty member to HoD"),
        ]):
            cur.execute("INSERT INTO audit (inst_id,actor_id,action,target,detail,created_at) VALUES (?,?,?,?,?,datetime('now', ?))",
                        (iid, admin, action, target, detail, f"-{(4 - i) * 9} days"))

    con.commit()

    if with_scival:
        from .importers import import_scival
        sample = db.ROOT / "samples" / "mySciVal_Researchers_Export.xlsx"
        if sample.exists():
            res = import_scival(con, sample.read_bytes(), owner_inst=None, actor=None, commit=True)
            if not quiet:
                print(f"  tracked institutions from SciVal: {res['institutions']} ({res['people']} researchers)")
    con.commit()
    stats = {t: db.scalar(con, f"SELECT COUNT(*) FROM {t}") for t in
             ("institutions", "departments", "people", "publications", "projects", "patents", "opportunities")}
    con.close()
    db.bump()
    if not quiet:
        print("RICE demo database built:", stats)
    return stats


def inst_rows_by_id(inst_rows):
    return {iid: cfg for code, (iid, cfg) in inst_rows.items()}


if __name__ == "__main__":
    build()
