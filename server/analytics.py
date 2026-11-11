"""Research analytics over the in-memory snapshot.

A Scope says *whose* research is counted: a set of institutions, optionally narrowed to
departments or a single person, within a year range.
"""
from __future__ import annotations

import math
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from .catalog import SDG_NAMES
from .db import Snapshot, cached

FACULTY_ROLES = ("faculty", "hod")
CURRENT_YEAR = 2026
RESEARCHER_ROLES = ("faculty", "hod", "scholar", "student", "staff")


@dataclass(frozen=True)
class Scope:
    insts: frozenset
    depts: frozenset = frozenset()
    person: int | None = None
    y0: int = 2015
    y1: int = 2026
    verified_only: bool = True
    label: str = ""

    def key(self):
        return (tuple(sorted(self.insts)), tuple(sorted(self.depts)), self.person, self.y0, self.y1, self.verified_only)


# ── selection ────────────────────────────────────────────────────────────────
def pubs_in(s: Snapshot, sc: Scope, years=True):
    out = []
    for p in s.pubs.values():
        if years and not (sc.y0 <= (p["year"] or 0) <= sc.y1):
            continue
        if sc.verified_only and p["status"] != "verified":
            continue
        if p["status"] == "rejected":
            continue
        if sc.person is not None:
            if sc.person not in p["authors"]:
                continue
        elif sc.depts:
            if not (p["depts"] & sc.depts):
                continue
        elif not (p["insts"] & sc.insts):
            continue
        out.append(p)
    return out


def projects_in(s: Snapshot, sc: Scope, years=True):
    out = []
    for p in s.projects.values():
        if years and not (sc.y0 <= (p["start_year"] or 0) <= sc.y1):
            continue
        if sc.verified_only and p["status"] != "verified":
            continue
        if sc.person is not None:
            if sc.person not in {m["id"] for m in p["members"]}:
                continue
        elif sc.depts:
            if not (p["depts"] & sc.depts):
                continue
        elif not (p["insts"] & sc.insts):
            continue
        out.append(p)
    return out


def patents_in(s: Snapshot, sc: Scope, years=True):
    out = []
    for p in s.patents.values():
        if years and not (sc.y0 <= (p["year"] or 0) <= sc.y1):
            continue
        if sc.verified_only and p["status"] != "verified":
            continue
        if sc.person is not None:
            if sc.person not in p["inventors"]:
                continue
        elif sc.depts:
            if not (p["depts"] & sc.depts):
                continue
        elif not (p["insts"] & sc.insts):
            continue
        out.append(p)
    return out


def people_in(s: Snapshot, sc: Scope, roles=FACULTY_ROLES):
    out = []
    for p in s.people.values():
        if p["status"] != "active" or p["role"] not in roles:
            continue
        if sc.person is not None:
            if p["id"] != sc.person:
                continue
        elif sc.depts:
            if p["dept_id"] not in sc.depts:
                continue
        elif p["inst_id"] not in sc.insts:
            continue
        out.append(p)
    return out


# ── metrics ──────────────────────────────────────────────────────────────────
def h_index(cites):
    h = 0
    for i, c in enumerate(sorted(cites, reverse=True), start=1):
        if c >= i:
            h = i
        else:
            break
    return h


def pub_field(s: Snapshot, p):
    for a in p["authors"]:
        d = s.dept.get(s.people[a]["dept_id"])
        if d:
            return d["field"]
    return "Other"


def baselines(s: Snapshot):
    """Average citations per (field, year, kind) across the whole platform — the FWCI denominator."""
    def build():
        acc = defaultdict(list)
        for p in s.pubs.values():
            if p["status"] != "verified":
                continue
            acc[(pub_field(s, p), p["year"], p["kind"])].append(p["citations"])
        return {k: (sum(v) / len(v)) for k, v in acc.items() if v}
    return cached(("baselines",), build)


def fwci(s: Snapshot, pubs):
    base = baselines(s)
    ratios = []
    for p in pubs:
        b = base.get((pub_field(s, p), p["year"], p["kind"]))
        if b and b > 0.3:
            ratios.append(p["citations"] / b)
    return round(sum(ratios) / len(ratios), 2) if ratios else None


def collab_class(s: Snapshot, p, home_insts):
    """single | inter_dept | cross_inst | national | international — the widest reach of the paper."""
    if p["international"]:
        return "international"
    if p["ext"]:
        return "national"
    if len(p["insts"]) > 1:
        return "cross_inst"
    if len(p["depts"]) > 1:
        return "inter_dept"
    return "single"


def pct(a, b):
    return round(100.0 * a / b, 1) if b else 0.0


def growth(cur, prev):
    if not prev:
        return None
    return round(100.0 * (cur - prev) / prev, 1)


def years_range(sc: Scope):
    return list(range(sc.y0, sc.y1 + 1))


# ── sections ─────────────────────────────────────────────────────────────────
def overview(s: Snapshot, sc: Scope):
    def build():
        pubs = pubs_in(s, sc)
        all_pubs_any_year = pubs_in(s, sc, years=False)
        projs = projects_in(s, sc)
        pats = patents_in(s, sc)
        fac = people_in(s, sc)
        researchers = people_in(s, sc, RESEARCHER_ROLES)
        yrs = years_range(sc)
        by_year = Counter(p["year"] for p in pubs)
        cites = [p["citations"] for p in pubs]
        sanctioned = [p for p in projs if p["stage"] in ("ongoing", "completed")]
        decided = [p for p in projs if p["stage"] in ("ongoing", "completed", "not_funded")]
        # compare complete years: when the range ends in the current (partial) year, use the two before it
        last = sc.y1 - 1 if (sc.y1 >= CURRENT_YEAR and sc.y1 - sc.y0 >= 2) else sc.y1
        prev = last - 1
        q = Counter(p["quartile"] for p in pubs if p["kind"] == "journal")
        journals = sum(q.values())
        collab = Counter(collab_class(s, p, sc.insts) for p in pubs)
        fund_year = defaultdict(float)
        for p in sanctioned:
            fund_year[p["start_year"]] += p["amount"]
        kpis = {
            "publications": len(pubs),
            "publications_growth": growth(by_year.get(last, 0), by_year.get(prev, 0)),
            "citations": sum(cites),
            "h_index": h_index(cites),
            "cites_per_paper": round(sum(cites) / len(pubs), 1) if pubs else 0,
            "fwci": fwci(s, pubs),
            "q1_share": pct(q.get("Q1", 0), journals),
            "open_access_share": pct(sum(1 for p in pubs if p["open_access"]), len(pubs)),
            "funding_lakh": round(sum(p["amount"] for p in sanctioned), 1),
            "funding_growth": growth(fund_year.get(last, 0), fund_year.get(prev, 0)),
            "active_projects": sum(1 for p in projects_in(s, sc, years=False) if p["stage"] == "ongoing"),
            "success_rate": pct(len(sanctioned), len(decided)),
            "patents": len(pats),
            "patents_granted": sum(1 for p in pats if p["stage"] == "granted"),
            "faculty": len(fac),
            "researchers": len(researchers),
            "scholars": sum(1 for p in researchers if p["role"] == "scholar"),
            "pubs_per_faculty": round(len(pubs) / len(fac), 2) if fac else 0,
            "collab_share": pct(len(pubs) - collab.get("single", 0), len(pubs)),
            "international_share": pct(collab.get("international", 0), len(pubs)),
            "cross_inst_share": pct(collab.get("cross_inst", 0) + collab.get("national", 0) + collab.get("international", 0), len(pubs)),
            "growth_basis": f"{last} vs {prev}",
            "pending": sum(1 for p in all_pubs_any_year if p["status"] == "pending") if not sc.verified_only else
                       sum(1 for p in pubs_in(s, Scope(sc.insts, sc.depts, sc.person, sc.y0, sc.y1, False)) if p["status"] == "pending"),
        }
        cit_year = Counter()
        for p in pubs:
            cit_year[p["year"]] += p["citations"]
        trend = {
            "years": yrs,
            "publications": [by_year.get(y, 0) for y in yrs],
            "citations": [cit_year.get(y, 0) for y in yrs],
            "funding": [round(fund_year.get(y, 0), 1) for y in yrs],
            "patents": [sum(1 for p in pats if p["year"] == y) for y in yrs],
            "international": [sum(1 for p in pubs if p["year"] == y and p["international"]) for y in yrs],
        }
        kinds = Counter(p["kind"] for p in pubs)
        return {"kpis": kpis, "trend": trend,
                "kinds": [{"name": k, "value": v} for k, v in kinds.most_common()],
                "quartiles": [{"name": k, "value": q.get(k, 0)} for k in ("Q1", "Q2", "Q3", "Q4")],
                "collab": {k: collab.get(k, 0) for k in ("single", "inter_dept", "cross_inst", "national", "international")}}
    return cached(("overview",) + sc.key(), build)


def output(s: Snapshot, sc: Scope):
    pubs = pubs_in(s, sc)
    yrs = years_range(sc)
    kinds = ["journal", "conference", "chapter", "book", "preprint"]
    by = defaultdict(Counter)
    qy = defaultdict(Counter)
    oa = Counter()
    for p in pubs:
        by[p["kind"]][p["year"]] += 1
        if p["kind"] == "journal":
            qy[p["quartile"] or "Unranked"][p["year"]] += 1
        if p["open_access"]:
            oa[p["year"]] += 1
    tot = Counter(p["year"] for p in pubs)
    venues = Counter((p["venue"], p["kind"], p["quartile"]) for p in pubs if p["venue"])
    fac_by_year = {y: sum(1 for f in people_in(s, sc) if (f.get("joined") or 0) <= y) for y in yrs}
    return {
        "years": yrs,
        "by_kind": {k: [by[k].get(y, 0) for y in yrs] for k in kinds if by[k]},
        "by_quartile": {k: [qy[k].get(y, 0) for y in yrs] for k in ("Q1", "Q2", "Q3", "Q4") if qy[k]},
        "oa_share": [pct(oa.get(y, 0), tot.get(y, 0)) for y in yrs],
        "per_faculty": [round(tot.get(y, 0) / fac_by_year[y], 2) if fac_by_year[y] else 0 for y in yrs],
        "top_venues": [{"venue": v, "kind": k, "quartile": q, "count": c} for (v, k, q), c in venues.most_common(15)],
    }


def impact(s: Snapshot, sc: Scope):
    pubs = pubs_in(s, sc)
    yrs = years_range(sc)
    cites = [p["citations"] for p in pubs]
    buckets = [(0, 0, "0"), (1, 4, "1–4"), (5, 9, "5–9"), (10, 24, "10–24"), (25, 49, "25–49"), (50, 99, "50–99"), (100, 10**9, "100+")]
    hist = [{"bucket": lab, "count": sum(1 for c in cites if lo <= c <= hi)} for lo, hi, lab in buckets]
    by_year = []
    for y in yrs:
        yp = [p for p in pubs if p["year"] == y]
        by_year.append({"year": y, "papers": len(yp), "citations": sum(p["citations"] for p in yp),
                        "cpp": round(sum(p["citations"] for p in yp) / len(yp), 1) if yp else 0, "fwci": fwci(s, yp)})
    q_cpp = {}
    for q in ("Q1", "Q2", "Q3", "Q4"):
        qp = [p["citations"] for p in pubs if p["quartile"] == q]
        q_cpp[q] = round(sum(qp) / len(qp), 1) if qp else 0
    top = sorted(pubs, key=lambda p: -p["citations"])[:12]
    return {
        "h_index": h_index(cites),
        "i10": sum(1 for c in cites if c >= 10),
        "fwci": fwci(s, pubs),
        "uncited_share": pct(sum(1 for c in cites if c == 0), len(cites)),
        "histogram": hist,
        "by_year": by_year,
        "quartile_cpp": q_cpp,
        "oa_cpp": {
            "open": round(statistics.mean([p["citations"] for p in pubs if p["open_access"]] or [0]), 1),
            "closed": round(statistics.mean([p["citations"] for p in pubs if not p["open_access"]] or [0]), 1),
        },
        "top_papers": [pub_card(s, p) for p in top],
    }


def pub_card(s: Snapshot, p):
    return {"id": p["id"], "title": p["title"], "year": p["year"], "venue": p["venue"], "kind": p["kind"],
            "quartile": p["quartile"], "citations": p["citations"], "open_access": bool(p["open_access"]),
            "status": p["status"], "doi": p["doi"], "keywords": p["keywords"], "sdgs": p["sdgs"],
            "authors": [{"id": a, "name": s.people[a]["name"], "inst": s.inst[s.people[a]["inst_id"]]["short"]} for a in p["authors"]]
                       + [{"id": None, "name": e["name"], "inst": e["affil"]} for e in p["ext"]],
            "insts": sorted(s.inst[i]["short"] for i in p["insts"])}


def topic_stats(s: Snapshot, pubs, y_last):
    cnt = Counter()
    recent, earlier = Counter(), Counter()
    for p in pubs:
        for k in p["keywords"]:
            cnt[k] += 1
            if p["year"] > y_last - 3:
                recent[k] += 1
            elif p["year"] > y_last - 6:
                earlier[k] += 1
    rows = []
    for k, c in cnt.items():
        r, e = recent.get(k, 0), earlier.get(k, 0)
        g = (r - e) / max(e, 2)
        momentum = (r - e) / math.sqrt(e + 2)
        trend = "rising" if g > 0.5 and r >= 6 and momentum > 1.5 else "declining" if g < -0.3 and e >= 5 else "steady"
        rows.append({"topic": k, "count": c, "recent": r, "earlier": e, "growth": round(100 * g, 0),
                     "momentum": round(momentum, 2), "trend": trend})
    rows.sort(key=lambda x: -x["count"])
    return rows


def topics(s: Snapshot, sc: Scope):
    pubs = pubs_in(s, sc)
    yrs = years_range(sc)
    stats = topic_stats(s, pubs, sc.y1)
    top = [r["topic"] for r in stats[:16]]
    heat = []
    idx = {t: i for i, t in enumerate(top)}
    hc = Counter()
    for p in pubs:
        for k in p["keywords"]:
            if k in idx:
                hc[(k, p["year"])] += 1
    for t in top:
        for j, y in enumerate(yrs):
            heat.append([j, idx[t], hc.get((t, y), 0)])
    sdg = Counter(g for p in pubs for g in p["sdgs"])
    rising = sorted([r for r in stats if r["trend"] == "rising"], key=lambda x: -x["momentum"])[:8]
    # who leads each top topic
    leaders = {}
    for t in top[:10]:
        c = Counter(a for p in pubs if t in p["keywords"] for a in p["authors"] if s.people[a]["role"] in FACULTY_ROLES)
        leaders[t] = [{"id": a, "name": s.people[a]["name"], "count": n} for a, n in c.most_common(3)]
    return {
        "years": yrs, "topics": stats[:40], "heat_topics": top, "heat": heat,
        "rising": rising, "declining": [r for r in stats if r["trend"] == "declining"][:6],
        "sdg": [{"goal": gl, "name": SDG_NAMES.get(gl, str(gl)), "count": c} for gl, c in sorted(sdg.items())],
        "leaders": leaders,
    }


def funding(s: Snapshot, sc: Scope):
    projs = projects_in(s, sc)
    yrs = years_range(sc)
    sanctioned = [p for p in projs if p["stage"] in ("ongoing", "completed")]
    by_agency = defaultdict(lambda: {"amount": 0.0, "count": 0, "decided": 0, "won": 0})
    for p in projs:
        a = by_agency[p["agency"]]
        if p["stage"] in ("ongoing", "completed"):
            a["amount"] += p["amount"]
            a["count"] += 1
            a["won"] += 1
        if p["stage"] in ("ongoing", "completed", "not_funded"):
            a["decided"] += 1
    agencies = sorted(by_agency, key=lambda k: -by_agency[k]["amount"])
    sector_year = defaultdict(lambda: defaultdict(float))
    for p in sanctioned:
        sector_year[p["sector"]][p["start_year"]] += p["amount"]
    # sankey: sector -> agency -> department
    links = defaultdict(float)
    for p in sanctioned:
        links[(f"{(p['sector'] or 'other').title()} funding", p["agency"])] += p["amount"]
        depts = [s.dept[d] for d in p["depts"]] or [None]
        lead = depts[0]
        label = f"{lead['code']} · {s.inst[lead['inst_id']]['short']}" if lead and len(sc.insts) > 1 else (lead["name"] if lead else "Unassigned")
        links[(p["agency"], label)] += p["amount"]
    nodes = sorted({a for a, _ in links} | {b for _, b in links})
    return {
        "years": yrs,
        "total": round(sum(p["amount"] for p in sanctioned), 1),
        "projects": len(sanctioned),
        "ongoing": sum(1 for p in sanctioned if p["stage"] == "ongoing"),
        "submitted": sum(1 for p in projs if p["stage"] == "submitted"),
        "success_rate": pct(len(sanctioned), sum(1 for p in projs if p["stage"] != "submitted")),
        "by_agency": [{"agency": k, "amount": round(by_agency[k]["amount"], 1), "count": by_agency[k]["count"],
                       "success": pct(by_agency[k]["won"], by_agency[k]["decided"])} for k in agencies],
        "by_sector_year": {k: [round(v.get(y, 0), 1) for y in yrs] for k, v in sector_year.items()},
        "sankey": {"nodes": [{"name": n} for n in nodes],
                   "links": [{"source": a, "target": b, "value": round(v, 1)} for (a, b), v in links.items() if v > 0]},
        "top_projects": [project_card(s, p) for p in sorted(sanctioned, key=lambda p: -p["amount"])[:10]],
    }


def project_card(s: Snapshot, p):
    pi = next((m for m in p["members"] if m["role"] == "PI"), None)
    return {"id": p["id"], "title": p["title"], "agency": p["agency"], "scheme": p["scheme"], "amount": p["amount"],
            "start_year": p["start_year"], "end_year": p["end_year"], "stage": p["stage"], "status": p["status"],
            "keywords": p["keywords"],
            "pi": {"id": pi["id"], "name": s.people[pi["id"]]["name"]} if pi else None,
            "members": [{"id": m["id"], "name": s.people[m["id"]]["name"], "role": m["role"],
                         "inst": s.inst[s.people[m["id"]]["inst_id"]]["short"]} for m in p["members"]],
            "insts": sorted(s.inst[i]["short"] for i in p["insts"])}


def person_metrics(s: Snapshot, pid, y0=2015, y1=2026, verified_only=True):
    p = s.people[pid]
    pubs = [s.pubs[x] for x in p["pubs"] if (not verified_only or s.pubs[x]["status"] == "verified") and y0 <= s.pubs[x]["year"] <= y1]
    cites = [x["citations"] for x in pubs]
    coauthors = Counter(a for x in pubs for a in x["authors"] if a != pid)
    projs = [s.projects[x] for x in p["projects"]]
    funded = [x for x in projs if x["stage"] in ("ongoing", "completed")]
    return {"pubs": len(pubs), "citations": sum(cites), "h_index": h_index(cites), "fwci": fwci(s, pubs),
            "q1": sum(1 for x in pubs if x["quartile"] == "Q1"),
            "recent": sum(1 for x in pubs if x["year"] >= y1 - 1),
            "coauthors": len(coauthors), "projects": len(funded),
            "funding": round(sum(x["amount"] for x in funded if any(m["id"] == pid and m["role"] in ("PI", "Co-PI") for m in x["members"])), 1),
            "patents": len(p["patents"]), "students": len(p["students"]),
            "cross_inst": sum(1 for x in pubs if len(x["insts"]) > 1 or x["ext"])}


def people_section(s: Snapshot, sc: Scope):
    fac = people_in(s, sc)
    pubs = pubs_in(s, sc)
    pubset = {p["id"] for p in pubs}
    rows = []
    for f in fac:
        m = person_metrics(s, f["id"], sc.y0, sc.y1, sc.verified_only)
        d = s.dept.get(f["dept_id"])
        rows.append({"id": f["id"], "name": f["name"], "designation": f["designation"], "role": f["role"],
                     "dept": d["code"] if d else "", "inst": s.inst[f["inst_id"]]["short"], "hue": f["hue"], **m})
    dist = Counter(min(r["pubs"], 40) // 5 for r in rows)
    hist = [{"bucket": f"{b * 5}–{b * 5 + 4}" if b < 8 else "40+", "count": dist.get(b, 0)} for b in range(0, 9)]
    by_desig = defaultdict(list)
    for r in rows:
        by_desig[r["designation"]].append(r["pubs"])
    box = []
    for k in ("Professor", "Associate Professor", "Assistant Professor"):
        v = sorted(by_desig.get(k, []))
        if len(v) >= 2:
            qs = statistics.quantiles(v, n=4)
            box.append({"designation": k, "box": [v[0], qs[0], statistics.median(v), qs[2], v[-1]], "n": len(v),
                        "mean": round(statistics.mean(v), 1)})
    inactive = [r for r in rows if r["recent"] == 0]
    scholars = people_in(s, sc, ("scholar",))
    stud_share = [pct(sum(1 for p in pubs if p["year"] == y and any(s.people[a]["role"] in ("scholar", "student") for a in p["authors"])),
                      sum(1 for p in pubs if p["year"] == y)) for y in years_range(sc)]
    load = Counter(len(s.people[f["id"]]["students"]) for f in fac)
    return {
        "faculty": len(fac), "scholars": len(scholars),
        "rows": sorted(rows, key=lambda r: (-r["citations"])),
        "histogram": hist, "box": box,
        "inactive": sorted(inactive, key=lambda r: r["name"]),
        "student_share": {"years": years_range(sc), "values": stud_share},
        "mentorship": [{"students": k, "faculty": v} for k, v in sorted(load.items())],
        "gini": gini([r["pubs"] for r in rows]),
        "top_share": pct(sum(sorted([r["pubs"] for r in rows], reverse=True)[:max(1, len(rows) // 5)]), sum(r["pubs"] for r in rows)),
        "pubs_considered": len(pubset),
    }


def gini(values):
    v = sorted(values)
    n = len(v)
    if n == 0 or sum(v) == 0:
        return 0
    cum = sum((i + 1) * x for i, x in enumerate(v))
    return round((2 * cum) / (n * sum(v)) - (n + 1) / n, 3)


def collaboration(s: Snapshot, sc: Scope):
    pubs = pubs_in(s, sc)
    yrs = years_range(sc)
    classes = ("single", "inter_dept", "cross_inst", "national", "international")
    by = defaultdict(Counter)
    partners = Counter()
    countries = Counter()
    rice_partners = Counter()
    for p in pubs:
        c = collab_class(s, p, sc.insts)
        by[c][p["year"]] += 1
        for a in p["external_affils"]:
            partners[a] += 1
        for e in p["ext"]:
            if e.get("country") and e["country"] != "India":
                countries[e["country"]] += 1
        for i in p["insts"]:
            if i not in sc.insts:
                rice_partners[i] += 1
    # department matrix (chord)
    dept_ids = sorted({d for p in pubs for d in p["depts"]})
    if sc.depts:
        dept_ids = sorted(set(dept_ids))
    if len(sc.insts) == 1:
        dept_ids = [d for d in dept_ids if s.dept[d]["inst_id"] in sc.insts]
    idx = {d: i for i, d in enumerate(dept_ids)}
    matrix = [[0] * len(dept_ids) for _ in dept_ids]
    for p in pubs:
        ds = [d for d in p["depts"] if d in idx]
        for i in range(len(ds)):
            for j in range(i + 1, len(ds)):
                a, b = idx[ds[i]], idx[ds[j]]
                matrix[a][b] += 1
                matrix[b][a] += 1
    return {
        "years": yrs,
        "by_class": {k: [by[k].get(y, 0) for y in yrs] for k in classes},
        "partners": [{"name": k, "count": v} for k, v in partners.most_common(15)],
        "countries": [{"name": k, "count": v} for k, v in countries.most_common(12)],
        "rice_partners": [{"id": i, "name": s.inst[i]["name"], "short": s.inst[i]["short"], "count": v} for i, v in rice_partners.most_common(10)],
        "dept_labels": [f"{s.dept[d]['code']}" + ("" if len(sc.insts) == 1 else f" · {s.inst[s.dept[d]['inst_id']]['short']}") for d in dept_ids],
        "dept_matrix": matrix,
    }


def departments(s: Snapshot, sc: Scope):
    out = []
    for did, d in s.dept.items():
        if d["inst_id"] not in sc.insts or (sc.depts and did not in sc.depts):
            continue
        if s.inst[d["inst_id"]]["external"]:
            continue
        dsc = Scope(sc.insts, frozenset([did]), None, sc.y0, sc.y1, sc.verified_only)
        ov = overview(s, dsc)["kpis"]
        out.append({"id": did, "code": d["code"], "name": d["name"], "field": d["field"], "inst": s.inst[d["inst_id"]]["short"],
                    "faculty": ov["faculty"], "scholars": ov["scholars"], "publications": ov["publications"],
                    "pubs_per_faculty": ov["pubs_per_faculty"], "citations": ov["citations"], "h_index": ov["h_index"],
                    "cites_per_paper": ov["cites_per_paper"], "fwci": ov["fwci"], "q1_share": ov["q1_share"],
                    "funding_lakh": ov["funding_lakh"], "patents": ov["patents"], "collab_share": ov["collab_share"],
                    "growth": ov["publications_growth"]})
    out.sort(key=lambda r: -r["publications"])
    return {"rows": out}


# ── benchmarking across institutions ─────────────────────────────────────────
BENCH_AXES = [("output", "Output / faculty"), ("impact", "Citations / paper"), ("quality", "Q1 share"),
              ("funding", "Funding / faculty"), ("ipr", "Patents / 100 faculty"), ("collab", "External collaboration"),
              ("open", "Open access"), ("growth", "3-year growth")]


def institution_profile(s: Snapshot, iid, y0, y1):
    sc = Scope(frozenset([iid]), y0=y0, y1=y1)
    ov = overview(s, sc)
    k = ov["kpis"]
    t = ov["trend"]
    pubs = t["publications"]
    g3 = None
    if len(pubs) >= 4 and pubs[-4] > 0:
        g3 = round(100 * ((pubs[-1] / pubs[-4]) ** (1 / 3) - 1), 1)
    f = max(k["faculty"], 1)
    raw = {"output": round(k["publications"] / f, 2), "impact": k["cites_per_paper"], "quality": k["q1_share"],
           "funding": round(k["funding_lakh"] / f, 2), "ipr": round(100 * k["patents"] / f, 1),
           "collab": k["cross_inst_share"], "open": k["open_access_share"], "growth": g3 or 0}
    return {"id": iid, "kpis": k, "raw": raw, "trend": t}


def benchmark(s: Snapshot, inst_ids, y0, y1):
    profiles = [institution_profile(s, i, y0, y1) for i in inst_ids]
    maxes = {a: max((p["raw"][a] for p in profiles), default=1) or 1 for a, _ in BENCH_AXES}
    for p in profiles:
        p["normalised"] = {a: round(100 * max(p["raw"][a], 0) / maxes[a], 1) for a, _ in BENCH_AXES}
        r = p["normalised"]
        # NIRF-RP style blend (PU, QP, IPR, FPPP) — an estimate, not an official score
        p["rice_score"] = round(0.35 * r["output"] + 0.2 * r["impact"] + 0.15 * r["quality"] + 0.15 * r["ipr"] + 0.15 * r["funding"], 1)
        inst = s.inst[p["id"]]
        p.update({"name": inst["name"], "short": inst["short"], "brand": inst["brand"], "city": inst["city"],
                  "state": inst["state"], "share_level": inst["share_level"]})
    profiles.sort(key=lambda p: -p["rice_score"])
    for i, p in enumerate(profiles, start=1):
        p["rank"] = i
    return {"axes": [{"key": a, "label": l} for a, l in BENCH_AXES], "institutions": profiles}


# ── plain-language findings ──────────────────────────────────────────────────
def insights(s: Snapshot, sc: Scope, scope_name: str):
    ov = overview(s, sc)
    k, t = ov["kpis"], ov["trend"]
    out = []
    yrs = t["years"]
    partial = yrs and yrs[-1] >= CURRENT_YEAR
    off = 1 if partial and len(yrs) >= 3 else 0
    if len(yrs) >= 2 + off:
        cur, prev = t["publications"][-1 - off], t["publications"][-2 - off]
        if prev:
            g = round(100 * (cur - prev) / prev)
            word = "up" if g >= 0 else "down"
            tail = ""
            if off:
                pend = sum(1 for p in pubs_in(s, Scope(sc.insts, sc.depts, sc.person, yrs[-1], yrs[-1], False)) if p["status"] == "pending")
                tail = f" {yrs[-1]} stands at {t['publications'][-1]} so far" + (f", with {pend} more awaiting verification." if pend else ".")
            out.append({"tone": "green" if g >= 0 else "pink", "link": "#/analytics/output",
                        "text": f"{scope_name} published {{{{{cur} papers|yellow}}}} in {yrs[-1 - off]}, {word} {{{{{abs(g)}%|{'green' if g >= 0 else 'pink'}}}}} on {yrs[-2 - off]}.{tail}"})
    tp = topics(s, sc)
    if tp["rising"]:
        r0 = tp["rising"][0]
        out.append({"tone": "blue", "link": "#/analytics/topics",
                    "text": f"{{{{{r0['topic']}|blue}}}} is the fastest-rising topic: {r0['recent']} papers in the last three years against {r0['earlier']} in the three before."})
    if k["publications"]:
        out.append({"tone": "orange", "link": "#/analytics/collaboration",
                    "text": f"{{{{{k['cross_inst_share']}%|orange}}}} of papers involve another institution, and {{{{{k['international_share']}%|pink}}}} have an international co-author."})
    if k["fwci"]:
        word = "above" if k["fwci"] >= 1 else "below"
        out.append({"tone": "green" if k["fwci"] >= 1 else "pink", "link": "#/analytics/impact",
                    "text": f"Citation impact is {{{{{k['fwci']}×|{'green' if k['fwci'] >= 1 else 'pink'}}}}} the platform average for the same field and year — {word} par."})
    if sc.person is None:
        ppl = people_section(s, sc)
        if ppl["faculty"]:
            lead = (f"{{{{{len(ppl['inactive'])} of {ppl['faculty']} faculty|pink}}}} have no verified paper in the last two years."
                    if ppl["inactive"] else "{{Every faculty member|green}} has a verified paper in the last two years.")
            out.append({"tone": "pink", "link": "#/analytics/people",
                        "text": f"{lead} The top fifth of faculty write {{{{{ppl['top_share']}%|yellow}}}} of the papers."})
        if len(sc.insts) == 1 and not sc.depts:
            deps = departments(s, sc)["rows"]
            deps = [d for d in deps if d["publications"] >= 10 and d["fwci"]]
            if deps:
                best = max(deps, key=lambda d: d["fwci"])
                out.append({"tone": "green", "link": "#/analytics/departments",
                            "text": f"{{{{{best['name']}|green}}}} has the strongest citation impact ({best['fwci']}× field average) across departments."})
    fd = funding(s, sc)
    if fd["by_agency"]:
        top = fd["by_agency"][0]
        share = pct(top["amount"], fd["total"])
        out.append({"tone": "yellow", "link": "#/analytics/funding",
                    "text": f"{{{{₹{fd['total'] / 100:.1f} crore|yellow}}}} in sanctioned grants; {top['agency']} alone is {{{{{share}%|orange}}}} of it. Proposal success rate is {fd['success_rate']}%."})
    return out
