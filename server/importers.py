"""Bulk import: SciVal researcher exports, people rosters, publication lists, OpenAlex."""
from __future__ import annotations

import csv
import io
import re

from . import db
from .catalog import sdgs_for
from .security import hash_pw

SCIVAL_NAMES = {  # raw SciVal group prefix -> (display name, city, state, code)
    "BITS": ("BITS Pilani", "Pilani", "Rajasthan", "BITS"),
    "Jamia Millia Islamia": ("Jamia Millia Islamia", "New Delhi", "Delhi", "JMI"),
    "Manipal Academy of Higher Education": ("Manipal Academy of Higher Education", "Manipal", "Karnataka", "MAHE"),
    "NIT Calicut": ("NIT Calicut", "Kozhikode", "Kerala", "NITC"),
    "NIT Rourkela": ("NIT Rourkela", "Rourkela", "Odisha", "NITR"),
    "NIT Trichy": ("NIT Tiruchirappalli", "Tiruchirappalli", "Tamil Nadu", "NITT"),
    "NIT Warangal": ("NIT Warangal", "Warangal", "Telangana", "NITW"),
    "SASTRA": ("SASTRA Deemed University", "Thanjavur", "Tamil Nadu", "SASTRA"),
    "SRM": ("SRM Institute of Science and Technology", "Chennai", "Tamil Nadu", "SRMIST"),
    "TIFAC-CORE in Cyber Security": ("TIFAC-CORE in Cyber Security", "Coimbatore", "Tamil Nadu", "TIFAC"),
    "VIT": ("VIT University", "Vellore", "Tamil Nadu", "VIT"),
}


def parse_table(data: bytes, filename: str) -> tuple[list[str], list[dict]]:
    name = (filename or "").lower()
    if name.endswith((".xlsx", ".xlsm")):
        import openpyxl
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        ws = wb.active
        it = ws.iter_rows(values_only=True)
        header = [str(h or "").strip() for h in next(it, [])]
        out = []
        for row in it:
            if not row or all(v in (None, "") for v in row):
                continue
            out.append({header[i]: row[i] for i in range(min(len(header), len(row))) if header[i]})
        return header, out
    text = data.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    header = [h.strip() for h in (reader.fieldnames or [])]
    out = [{(k or "").strip(): v for k, v in r.items()} for r in reader]
    return header, out


def detect(header: list[str]) -> str:
    h = {x.lower() for x in header}
    if "author" in h and "scopus author id" in h:
        return "scival"
    if "title" in h and "year" in h:
        return "publications"
    if "name" in h and ("email" in h or "role" in h or "department" in h):
        return "people"
    return "unknown"


def _code(name: str) -> str:
    words = re.findall(r"[A-Za-z]+", name)
    code = "".join(w[0] for w in words if w[0].isupper())[:6] or name[:4]
    return code.upper()


def import_scival(con, data: bytes, owner_inst, actor, commit: bool, filename="scival.xlsx"):
    header, table = parse_table(data, filename)
    groups: dict[str, list] = {}
    warnings_ = []
    for r in table:
        name = (r.get("Author") or "").strip()
        if not name:
            continue
        sid = r.get("Scopus Author ID")
        try:
            sid = str(int(float(sid))) if sid not in (None, "") else None
        except (TypeError, ValueError):
            sid = str(sid)
        levels = [r.get(f"Level {i}") for i in range(1, 11)]
        levels = [str(x).strip() for x in levels if x]
        primary = levels[0] if levels else "Unassigned"
        parts = re.split(r"\s*-\s*", primary, maxsplit=1)
        inst_raw = parts[0].strip()
        domain = parts[1].strip() if len(parts) > 1 and parts[1].strip() else "Cyber Security"
        domain = "Cyber Security" if domain.replace(" ", "").lower() == "cybersecurity" else domain
        if inst_raw.startswith("TIFAC"):
            inst_raw, domain = "TIFAC-CORE in Cyber Security", "Cyber Security"
        groups.setdefault(inst_raw, []).append({"name": name, "scopus": sid, "domain": domain, "groups": levels})
    preview = [{"institution": SCIVAL_NAMES.get(k, (k,))[0], "researchers": len(v)} for k, v in groups.items()]
    preview.sort(key=lambda x: -x["researchers"])
    result = {"format": "scival", "institutions": len(groups), "people": sum(len(v) for v in groups.values()),
              "preview": preview, "warnings": warnings_}
    if not commit:
        return result
    created_people = 0
    for raw, members in groups.items():
        disp, city, state, known_code = SCIVAL_NAMES.get(raw, (raw, None, None, None))
        inst = db.one(con, "SELECT id FROM institutions WHERE name=? AND external=1", (disp,))
        if inst:
            iid = inst["id"]
        else:
            code = known_code or _code(disp)
            base, k = code, 2
            while db.scalar(con, "SELECT 1 FROM institutions WHERE code=?", (code,)):
                code, k = f"{base}{k}", k + 1
            settings = {"owner_inst": owner_inst} if owner_inst else {}
            cur = con.execute(
                "INSERT INTO institutions (code,name,short,city,state,kind,share_level,plan,status,external,source,settings,tagline) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (code, disp, code, city, state, "Tracked", "network", "Tracked", "tracked", 1, "SciVal import",
                 db.jd(settings), "Tracked from a SciVal researcher export"))
            iid = cur.lastrowid
        dept = db.one(con, "SELECT id FROM departments WHERE inst_id=? AND code='CYS'", (iid,))
        did = dept["id"] if dept else con.execute(
            "INSERT INTO departments (inst_id, code, name, field) VALUES (?,?,?,?)", (iid, "CYS", "Cyber Security", "Computing")).lastrowid
        for m in members:
            if m["scopus"] and db.scalar(con, "SELECT 1 FROM people WHERE scopus_id=?", (m["scopus"],)):
                continue
            last, _, first = m["name"].partition(",")
            display = f"{first.strip()} {last.strip()}".strip() if first else m["name"]
            con.execute("INSERT INTO people (inst_id,dept_id,name,role,designation,interests,scopus_id,status,source,visibility,hue) "
                        "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                        (iid, did, display, "faculty", "Researcher (tracked)", db.jd([m["domain"]]), m["scopus"], "active",
                         "scival", "network", (hash(display) % 360)))
            created_people += 1
    if actor:
        con.execute("INSERT INTO audit (inst_id, actor_id, action, target, detail) VALUES (?,?,?,?,?)",
                    (owner_inst, actor, "import.scival", "Tracked institutions", f"{len(groups)} institutions, {created_people} researchers"))
    con.commit()
    db.bump()
    result["created"] = created_people
    return result


def _split(v):
    if v is None:
        return []
    return [x.strip() for x in re.split(r"[;|]", str(v)) if x.strip()]


ROLE_ALIASES = {"professor": "faculty", "faculty": "faculty", "teacher": "faculty", "hod": "hod", "head": "hod",
                "scholar": "scholar", "phd": "scholar", "research scholar": "scholar", "student": "student",
                "staff": "staff", "external": "external", "partner": "external"}


def import_people(con, table, inst_id, actor, commit: bool, temp_password: str):
    depts = db.rows(con, "SELECT id, code, name FROM departments WHERE inst_id=?", (inst_id,))
    dmap = {d["code"].lower(): d["id"] for d in depts} | {d["name"].lower(): d["id"] for d in depts}
    ok, errors, seen = [], [], set()
    for i, r in enumerate(table, start=2):
        low = {k.lower(): (str(v).strip() if v is not None else "") for k, v in r.items()}
        name, email = low.get("name", ""), low.get("email", "").lower()
        if not name:
            errors.append(f"Row {i}: name is empty")
            continue
        if email and (email in seen or db.scalar(con, "SELECT 1 FROM people WHERE email=?", (email,))):
            errors.append(f"Row {i}: {email} already exists")
            continue
        seen.add(email)
        role = ROLE_ALIASES.get(low.get("role", "faculty").lower(), "faculty")
        dept = low.get("department", "").lower()
        did = dmap.get(dept)
        if dept and not did:
            errors.append(f"Row {i}: department '{low.get('department')}' not found — added without department")
        ok.append({"name": name, "email": email or None, "role": role, "dept_id": did,
                   "designation": low.get("designation") or {"faculty": "Assistant Professor", "scholar": "PhD scholar"}.get(role, role.title()),
                   "interests": _split(low.get("interests")), "orcid": low.get("orcid") or None,
                   "scopus_id": low.get("scopus id") or low.get("scopus_id") or None})
    res = {"format": "people", "rows": len(table), "valid": len(ok), "errors": errors[:50],
           "preview": [{k: v for k, v in x.items() if k in ("name", "email", "role", "designation")} for x in ok[:8]]}
    if not commit:
        return res
    pw = hash_pw(temp_password)
    for x in ok:
        con.execute("INSERT INTO people (inst_id,dept_id,name,email,pw_hash,role,designation,interests,orcid,scopus_id,status,source,hue,joined) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,strftime('%Y','now'))",
                    (inst_id, x["dept_id"], x["name"], x["email"], pw, x["role"], x["designation"], db.jd(x["interests"]),
                     x["orcid"], x["scopus_id"], "active", "import", hash(x["name"]) % 360))
    con.execute("INSERT INTO audit (inst_id, actor_id, action, target, detail) VALUES (?,?,?,?,?)",
                (inst_id, actor, "import.people", "Members", f"{len(ok)} people imported"))
    con.commit()
    db.bump()
    res["created"] = len(ok)
    return res


def import_publications(con, table, inst_id, actor, commit: bool, require_verification=True):
    people = db.rows(con, "SELECT id, name FROM people WHERE inst_id=? AND status='active'", (inst_id,))
    pmap = {p["name"].lower(): p["id"] for p in people}
    ok, errors = [], []
    for i, r in enumerate(table, start=2):
        low = {k.lower(): (str(v).strip() if v is not None else "") for k, v in r.items()}
        title = low.get("title", "")
        try:
            year = int(float(low.get("year", "")))
        except ValueError:
            errors.append(f"Row {i}: year is missing or not a number")
            continue
        if not title:
            errors.append(f"Row {i}: title is empty")
            continue
        authors = _split(low.get("authors"))
        matched = [pmap.get(a.lower()) for a in authors]
        if not any(matched):
            errors.append(f"Row {i}: none of the authors match a member — imported with no internal author")
        kind = (low.get("type") or low.get("kind") or "journal").lower()
        kind = kind if kind in ("journal", "conference", "chapter", "book", "preprint") else "journal"
        try:
            cites = int(float(low.get("citations") or 0))
        except ValueError:
            cites = 0
        q = (low.get("quartile") or "").upper() or None
        ok.append({"title": title, "year": year, "venue": low.get("venue"), "kind": kind, "authors": list(zip(authors, matched)),
                   "doi": low.get("doi") or None, "keywords": _split(low.get("keywords")), "citations": cites,
                   "quartile": q if q in ("Q1", "Q2", "Q3", "Q4") else None,
                   "oa": 1 if low.get("open_access", "").lower() in ("1", "yes", "true", "y") else 0})
    res = {"format": "publications", "rows": len(table), "valid": len(ok), "errors": errors[:50],
           "preview": [{"title": x["title"], "year": x["year"], "venue": x["venue"],
                        "matched": sum(1 for _, m in x["authors"] if m)} for x in ok[:8]]}
    if not commit:
        return res
    status = "pending" if require_verification else "verified"
    for x in ok:
        cur = con.execute("INSERT INTO publications (inst_id,title,kind,venue,year,quartile,citations,doi,keywords,sdgs,open_access,status,source,created_by) "
                          "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                          (inst_id, x["title"], x["kind"], x["venue"], x["year"], x["quartile"], x["citations"], x["doi"],
                           db.jd(x["keywords"]), db.jd(sdgs_for(x["title"] + " " + " ".join(x["keywords"]))), x["oa"], status,
                           "import", actor))
        pid = cur.lastrowid
        for pos, (name, mid) in enumerate(x["authors"]):
            con.execute("INSERT INTO pub_authors (pub_id, position, person_id, ext_name) VALUES (?,?,?,?)",
                        (pid, pos, mid, None if mid else name))
    con.execute("INSERT INTO audit (inst_id, actor_id, action, target, detail) VALUES (?,?,?,?,?)",
                (inst_id, actor, "import.publications", "Publications", f"{len(ok)} publications imported as {status}"))
    con.commit()
    db.bump()
    res["created"] = len(ok)
    return res


TEMPLATES = {
    "people": "name,email,department,role,designation,interests,orcid,scopus_id\n"
              "Asha Varma,asha.varma@yourcollege.edu,CSE,faculty,Associate Professor,Machine Learning;Edge Computing,,\n"
              "Rahul Iyer,rahul.iyer@yourcollege.edu,ECE,scholar,PhD scholar,Internet of Things,,\n",
    "publications": "title,year,venue,type,authors,doi,keywords,citations,quartile,open_access\n"
                    "Lightweight intrusion detection for smart meters,2025,IEEE Access,journal,Asha Varma;Rahul Iyer,,Intrusion Detection;Smart Grid,4,Q1,yes\n",
}


def fetch_openalex(orcid: str) -> list[dict]:
    """Pull an author's works from OpenAlex by ORCID. Raises on network failure."""
    import httpx
    orcid = orcid.strip().replace("https://orcid.org/", "")
    if not re.fullmatch(r"\d{4}-\d{4}-\d{4}-\d{3}[\dX]", orcid):
        raise ValueError("ORCID should look like 0000-0002-1825-0097")
    url = "https://api.openalex.org/works"
    params = {"filter": f"author.orcid:{orcid}", "per-page": 50, "sort": "publication_year:desc"}
    resp = httpx.get(url, params=params, timeout=20, headers={"User-Agent": "RICE-research-engine/1.0"})
    resp.raise_for_status()
    out = []
    for w in resp.json().get("results", []):
        src = ((w.get("primary_location") or {}).get("source") or {})
        kind = {"article": "journal", "proceedings-article": "conference", "book-chapter": "chapter", "book": "book",
                "preprint": "preprint"}.get(w.get("type_crossref") or w.get("type"), "journal")
        authors = []
        for a in w.get("authorships", []):
            insts = a.get("institutions") or [{}]
            authors.append({"name": (a.get("author") or {}).get("display_name"),
                            "orcid": ((a.get("author") or {}).get("orcid") or "").replace("https://orcid.org/", ""),
                            "affil": insts[0].get("display_name"), "country": insts[0].get("country_code")})
        out.append({"title": w.get("title") or w.get("display_name"), "year": w.get("publication_year"),
                    "venue": src.get("display_name"), "kind": kind, "citations": w.get("cited_by_count", 0),
                    "doi": (w.get("doi") or "").replace("https://doi.org/", "") or None,
                    "open_access": 1 if (w.get("open_access") or {}).get("is_oa") else 0,
                    "keywords": [k.get("display_name") for k in (w.get("keywords") or [])[:4] if k.get("display_name")],
                    "authors": authors})
    return out
