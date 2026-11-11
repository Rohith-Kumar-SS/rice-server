"""Accreditation-ready data packs (NAAC criterion 3, NIRF research parameters) and the annual report."""
from __future__ import annotations

from collections import Counter, defaultdict

from .analytics import (FACULTY_ROLES, Scope, benchmark, departments, h_index, insights, overview, patents_in,
                        people_in, project_card, projects_in, pub_card, pubs_in, topics)
from .db import Snapshot


def naac(s: Snapshot, iid: int, end_year: int = 2026, span: int = 5):
    years = list(range(end_year - span + 1, end_year + 1))
    sc = Scope(frozenset([iid]), y0=years[0], y1=years[-1])
    pubs = pubs_in(s, sc)
    projs = [p for p in projects_in(s, sc) if p["stage"] in ("ongoing", "completed")]
    pats = patents_in(s, sc)
    rows_grants = []
    grants_by_year = defaultdict(lambda: {"government": 0.0, "non_government": 0.0, "count": 0})
    for p in sorted(projs, key=lambda p: (p["start_year"], p["agency"])):
        g = grants_by_year[p["start_year"]]
        key = "government" if p["sector"] == "government" else "non_government"
        g[key] += p["amount"]
        g["count"] += 1
        c = project_card(s, p)
        rows_grants.append({"year": p["start_year"], "title": p["title"], "pi": c["pi"]["name"] if c["pi"] else "",
                            "agency": p["agency"], "scheme": p["scheme"], "sector": p["sector"], "amount_lakh": p["amount"],
                            "duration": f"{p['start_year']}–{p['end_year']}"})
    fac_by_year = {y: sum(1 for f in people_in(s, sc) if (f.get("joined") or 0) <= y) for y in years}
    papers = []
    for y in years:
        yp = [p for p in pubs if p["year"] == y]
        j = sum(1 for p in yp if p["kind"] == "journal")
        bc = sum(1 for p in yp if p["kind"] in ("chapter", "book", "conference"))
        papers.append({"year": y, "faculty": fac_by_year[y], "journal_papers": j,
                       "per_teacher": round(j / fac_by_year[y], 2) if fac_by_year[y] else 0,
                       "books_chapters_proceedings": bc,
                       "bc_per_teacher": round(bc / fac_by_year[y], 2) if fac_by_year[y] else 0,
                       "q1": sum(1 for p in yp if p["quartile"] == "Q1")})
    patents_y = [{"year": y, "filed": sum(1 for p in pats if p["year"] == y and p["stage"] == "filed"),
                  "published": sum(1 for p in pats if p["year"] == y and p["stage"] == "published"),
                  "granted": sum(1 for p in pats if p["year"] == y and p["stage"] == "granted")} for y in years]
    collab = []
    for y in years:
        yp = [p for p in pubs if p["year"] == y]
        collab.append({"year": y, "with_other_institutions": sum(1 for p in yp if len(p["insts"]) > 1 or p["ext"]),
                       "international": sum(1 for p in yp if p["international"]),
                       "partners": len({a for p in yp for a in p["external_affils"]})})
    guides = [f for f in people_in(s, sc) if s.people[f["id"]]["students"]]
    scholars = [p for p in s.people.values() if p["inst_id"] == iid and p["role"] == "scholar" and p["status"] == "active"]
    k = overview(s, sc)["kpis"]
    return {
        "institution": s.inst[iid]["name"], "years": years,
        "summary": {"publications": k["publications"], "citations": k["citations"], "h_index": k["h_index"],
                    "grants_lakh": k["funding_lakh"], "patents": k["patents"], "guides": len(guides), "scholars": len(scholars)},
        "grants_by_year": [{"year": y, "government_lakh": round(grants_by_year[y]["government"], 1),
                            "non_government_lakh": round(grants_by_year[y]["non_government"], 1),
                            "projects": grants_by_year[y]["count"]} for y in years],
        "grants": rows_grants,
        "papers": papers,
        "patents": patents_y,
        "collaboration": collab,
        "guides": [{"name": g["name"], "designation": g["designation"],
                    "dept": (s.dept.get(g["dept_id"]) or {}).get("code", ""),
                    "scholars": sum(1 for x in s.people[g["id"]]["students"] if s.people[x]["role"] == "scholar")} for g in guides],
    }


def nirf(s: Snapshot, iid: int, end_year: int = 2026, peers=None):
    years = list(range(end_year - 2, end_year + 1))
    sc = Scope(frozenset([iid]), y0=years[0], y1=years[-1])
    pubs = pubs_in(s, sc)
    projs = [p for p in projects_in(s, sc) if p["stage"] in ("ongoing", "completed")]
    pats = patents_in(s, Scope(frozenset([iid]), y0=end_year - 4, y1=end_year))
    fac = people_in(s, sc)
    f = max(len(fac), 1)
    sponsored = [p for p in projs if p["sector"] in ("government", "international")]
    consult = [p for p in projs if p["sector"] == "industry"]
    cites = [p["citations"] for p in pubs]
    params = {
        "PU": {"label": "Publications", "value": len(pubs), "per_faculty": round(len(pubs) / f, 2),
               "note": "Journal, conference and book outputs over the last three years"},
        "QP": {"label": "Quality of publications", "value": sum(cites), "cites_per_paper": round(sum(cites) / max(1, len(pubs)), 2),
               "q1_share": round(100 * sum(1 for p in pubs if p["quartile"] == "Q1") / max(1, sum(1 for p in pubs if p["kind"] == "journal")), 1),
               "h_index": h_index(cites), "note": "Citations and share of Q1 journal papers"},
        "IPR": {"label": "Patents", "published": sum(1 for p in pats if p["stage"] in ("published", "granted")),
                "granted": sum(1 for p in pats if p["stage"] == "granted"), "note": "Published and granted, last five years"},
        "FPPP": {"label": "Footprint of projects & practice", "sponsored_lakh": round(sum(p["amount"] for p in sponsored) / 3, 1),
                 "consultancy_lakh": round(sum(p["amount"] for p in consult) / 3, 1),
                 "note": "Average per year — sponsored research and industry consultancy"},
    }
    comp = None
    if peers:
        b = benchmark(s, list(peers), years[0], years[-1])
        comp = [{"short": p["short"], "name": p["name"], "rice_score": p["rice_score"], "rank": p["rank"], "self": p["id"] == iid}
                for p in b["institutions"]]
    return {"institution": s.inst[iid]["name"], "years": years, "faculty": len(fac), "params": params, "peers": comp,
            "yearly": [{"year": y, "publications": sum(1 for p in pubs if p["year"] == y),
                        "citations": sum(p["citations"] for p in pubs if p["year"] == y),
                        "sponsored_lakh": round(sum(p["amount"] for p in sponsored if p["start_year"] == y), 1),
                        "consultancy_lakh": round(sum(p["amount"] for p in consult if p["start_year"] == y), 1)} for y in years]}


def annual(s: Snapshot, iid: int, year: int = 2026):
    sc = Scope(frozenset([iid]), y0=year, y1=year)
    sc_trend = Scope(frozenset([iid]), y0=year - 4, y1=year)
    ov = overview(s, sc)
    pubs = pubs_in(s, sc)
    projs = [p for p in projects_in(s, sc) if p["stage"] in ("ongoing", "completed")]
    pats = [p for p in patents_in(s, Scope(frozenset([iid]), y0=year, y1=year)) if p["stage"] == "granted"]
    tp = topics(s, sc_trend)
    return {
        "institution": s.inst[iid]["name"], "short": s.inst[iid]["short"], "year": year,
        "kpis": ov["kpis"], "trend": overview(s, sc_trend)["trend"],
        "insights": insights(s, sc_trend, s.inst[iid]["short"]),
        "departments": departments(s, sc)["rows"],
        "top_papers": [pub_card(s, p) for p in sorted(pubs, key=lambda p: (-(p["quartile"] == "Q1"), -p["citations"]))[:8]],
        "new_grants": [project_card(s, p) for p in sorted(projs, key=lambda p: -p["amount"])[:8]],
        "patents_granted": [{"title": p["title"], "number": p["number"],
                             "inventors": [s.people[i]["name"] for i in p["inventors"]]} for p in pats],
        "rising_topics": tp["rising"][:6],
        "sdg": tp["sdg"],
    }


def export_rows(s: Snapshot, entity: str, sc: Scope):
    if entity == "publications":
        for p in sorted(pubs_in(s, sc), key=lambda p: (-p["year"], p["title"])):
            yield {"id": p["id"], "title": p["title"], "year": p["year"], "type": p["kind"], "venue": p["venue"],
                   "quartile": p["quartile"] or "", "citations": p["citations"], "doi": p["doi"] or "",
                   "open_access": "yes" if p["open_access"] else "no", "status": p["status"],
                   "authors": "; ".join([s.people[a]["name"] for a in p["authors"]] + [e["name"] for e in p["ext"]]),
                   "institutions": "; ".join(sorted(s.inst[i]["short"] for i in p["insts"])),
                   "keywords": "; ".join(p["keywords"]), "sdgs": "; ".join(f"SDG {g}" for g in p["sdgs"])}
    elif entity == "projects":
        for p in sorted(projects_in(s, sc), key=lambda p: (-p["start_year"], -p["amount"])):
            c = project_card(s, p)
            yield {"id": p["id"], "title": p["title"], "agency": p["agency"], "scheme": p["scheme"], "sector": p["sector"],
                   "amount_lakh": p["amount"], "start": p["start_year"], "end": p["end_year"], "stage": p["stage"],
                   "pi": c["pi"]["name"] if c["pi"] else "", "members": "; ".join(f"{m['name']} ({m['role']})" for m in c["members"])}
    elif entity == "patents":
        for p in sorted(patents_in(s, sc), key=lambda p: -p["year"]):
            yield {"id": p["id"], "title": p["title"], "number": p["number"], "year": p["year"], "stage": p["stage"],
                   "inventors": "; ".join(s.people[i]["name"] for i in p["inventors"])}
    elif entity == "people":
        from .analytics import person_metrics
        for f in people_in(s, sc, ("faculty", "hod", "scholar", "student", "staff")):
            m = person_metrics(s, f["id"], sc.y0, sc.y1)
            yield {"id": f["id"], "name": f["name"], "role": f["role"], "designation": f["designation"],
                   "department": (s.dept.get(f["dept_id"]) or {}).get("name", ""), "email": f["email"] or "",
                   "interests": "; ".join(f["interests"]), **{k: v for k, v in m.items() if v is not None}}
