"""Search, expert finding, collaborator recommendations and team building."""
from __future__ import annotations

import math
import re
from collections import Counter

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import linear_kernel

from .analytics import FACULTY_ROLES, h_index
from .db import Snapshot, cached

SEARCH_ROLES = ("faculty", "hod", "scholar", "student", "staff")


def _index(s: Snapshot):
    def build():
        ids, docs = [], []
        for p in s.people.values():
            if p["status"] != "active" or p["role"] not in SEARCH_ROLES:
                continue
            parts = [" ".join(p["interests"])] * 4
            for x in p["pubs"][:80]:
                pub = s.pubs[x]
                if pub["status"] == "verified":
                    parts.append(pub["title"])
                    parts.append(" ".join(pub["keywords"]))
            if p.get("bio"):
                parts.append(p["bio"])
            ids.append(p["id"])
            docs.append(" ".join(parts))
        vec = TfidfVectorizer(ngram_range=(1, 2), stop_words="english", sublinear_tf=True, min_df=1, max_features=60000)
        X = vec.fit_transform(docs)
        return {"ids": ids, "row": {pid: i for i, pid in enumerate(ids)}, "vec": vec, "X": X}
    return cached(("tfidf",), build)


def _visible(s: Snapshot, pid, visible_insts, viewer_inst):
    p = s.people[pid]
    if p["inst_id"] not in visible_insts:
        return False
    if p["visibility"] == "internal" and p["inst_id"] != viewer_inst:
        return False
    return True


def _evidence(s: Snapshot, pid, terms, limit=3):
    out = []
    for x in s.people[pid]["pubs"]:
        pub = s.pubs[x]
        if pub["status"] != "verified" or pub["visibility"] != "public":
            continue
        text = (pub["title"] + " " + " ".join(pub["keywords"])).lower()
        hits = sum(1 for t in terms if t in text)
        if hits:
            out.append((hits, pub["year"], pub))
    out.sort(key=lambda t: (-t[0], -t[1]))
    return [{"id": p["id"], "title": p["title"], "year": p["year"], "venue": p["venue"]} for _, _, p in out[:limit]]


def _card(s: Snapshot, pid):
    p = s.people[pid]
    d = s.dept.get(p["dept_id"])
    pubs = [s.pubs[x] for x in p["pubs"] if s.pubs[x]["status"] == "verified"]
    return {"id": pid, "name": p["name"], "role": p["role"], "designation": p["designation"], "hue": p["hue"],
            "inst": s.inst[p["inst_id"]]["short"], "inst_name": s.inst[p["inst_id"]]["name"],
            "brand": s.inst[p["inst_id"]]["brand"], "inst_id": p["inst_id"], "external_inst": bool(s.inst[p["inst_id"]]["external"]),
            "dept": d["code"] if d else "", "dept_name": d["name"] if d else "", "interests": p["interests"],
            "pubs": len(pubs), "citations": sum(x["citations"] for x in pubs), "h_index": h_index([x["citations"] for x in pubs]),
            "scopus_id": p.get("scopus_id"), "source": p.get("source")}


def experts(s: Snapshot, q: str, visible_insts, viewer_inst, limit=24, roles=None):
    q = q.strip()
    if not q:
        return []
    ix = _index(s)
    qv = ix["vec"].transform([q])
    sims = linear_kernel(qv, ix["X"]).ravel()
    terms = [t for t in re.findall(r"[a-z0-9\-]+", q.lower()) if len(t) > 2]
    order = np.argsort(-sims)
    out = []
    best = None
    for i in order[:600]:
        if sims[i] <= 0.01:
            break
        pid = ix["ids"][i]
        if not _visible(s, pid, visible_insts, viewer_inst):
            continue
        if roles and s.people[pid]["role"] not in roles:
            continue
        best = best or sims[i]
        c = _card(s, pid)
        c["match"] = round(100 * float(sims[i]) / float(best), 0)
        c["matched"] = [t for t in s.people[pid]["interests"] if any(w in t.lower() for w in terms)][:4]
        c["evidence"] = _evidence(s, pid, terms)
        out.append(c)
        if len(out) >= limit:
            break
    return out


def coauthors(s: Snapshot, pid):
    co = Counter()
    for x in s.people[pid]["pubs"]:
        for a in s.pubs[x]["authors"]:
            if a != pid:
                co[a] += 1
    return co


def recommendations(s: Snapshot, pid: int, visible_insts, viewer_inst, limit=12, roles=("faculty", "hod", "scholar"), graph=None):
    """Blend text similarity (TF-IDF) with link prediction. With Neo4j, candidates also come from
    friends-of-friends in the graph and Adamic-Adar / topic-Jaccard are computed in Cypher."""
    ix = _index(s)
    if pid not in ix["row"]:
        return []
    sims = linear_kernel(ix["X"][ix["row"][pid]], ix["X"]).ravel()
    sim_of = {ix["ids"][i]: float(sims[i]) for i in range(len(sims))}
    me = s.people[pid]
    mine = coauthors(s, pid)
    neigh = {pid: set(mine)}
    deg_cache = {}

    def nbrs(x):
        if x not in neigh:
            neigh[x] = set(coauthors(s, x))
        return neigh[x]

    def deg(x):
        if x not in deg_cache:
            deg_cache[x] = len(nbrs(x))
        return deg_cache[x]

    def eligible(c):
        return (c != pid and c not in mine and c in s.people and s.people[c]["role"] in roles
                and _visible(s, c, visible_insts, viewer_inst) and not s.inst[s.people[c]["inst_id"]]["external"])

    pool = [ix["ids"][i] for i in np.argsort(-sims)[:400] if eligible(ix["ids"][i])][:220]
    if graph is not None:
        try:
            pool += [c for c in graph.fof_candidates(pid, visible_insts, limit=120) if eligible(c) and c not in pool]
            feats = graph.link_features(pid, pool, visible_insts)
        except Exception:
            graph, feats = None, {}
    my_topics = set(me["interests"]) | {k for x in me["pubs"] for k in s.pubs[x]["keywords"] if s.pubs[x]["status"] == "verified"}
    cands = []
    for c in pool:
        sim = sim_of.get(c, 0.0)
        if graph is not None and c in feats:
            f = feats[c]
            mutual, aa, jacc, shared = set(f["mutual"]), f["aa"], f["jaccard"], f["shared"]
        else:
            mutual = nbrs(pid) & nbrs(c)
            aa = sum(1 / math.log(max(deg(w), 2)) for w in mutual)
            theirs = set(s.people[c]["interests"]) | {k for x in s.people[c]["pubs"] for k in s.pubs[x]["keywords"] if s.pubs[x]["status"] == "verified"}
            jacc = len(my_topics & theirs) / len(my_topics | theirs) if (my_topics | theirs) else 0.0
            shared = [t for t in s.people[c]["interests"] if t in me["interests"]]
        cross_dept = s.people[c]["dept_id"] != me["dept_id"]
        cross_inst = s.people[c]["inst_id"] != me["inst_id"]
        related = max(sim, jacc)
        score = 0.52 * sim + 0.18 * jacc + 0.14 * min(aa, 3) / 3 + (0.08 if cross_dept and related > 0.15 else 0) \
            + (0.06 if cross_inst and related > 0.15 else 0)
        reasons = []
        if shared:
            reasons.append("Both work on " + ", ".join(shared[:2]))
        else:
            top_terms = _shared_terms(ix, pid, c)
            if top_terms:
                reasons.append("Overlapping vocabulary: " + ", ".join(top_terms[:3]))
        if mutual:
            names = [s.people[w]["name"] for w in list(mutual)[:2]]
            reasons.append(f"{len(mutual)} mutual co-author{'s' if len(mutual) > 1 else ''}: " + ", ".join(names))
        if cross_inst:
            reasons.append(f"Opens a link to {s.inst[s.people[c]['inst_id']]['name']}")
        elif cross_dept:
            dn = s.dept.get(s.people[c]["dept_id"])
            reasons.append(f"Interdisciplinary — {dn['name'] if dn else 'another department'}")
        card = _card(s, c)
        card.update({"score": round(100 * score, 0), "similarity": round(sim, 3), "mutual": len(mutual), "reasons": reasons,
                     "cross_inst": cross_inst, "cross_dept": cross_dept, "shared": list(shared),
                     "signals": {"text": round(sim, 2), "topics": round(jacc, 2), "adamic_adar": round(aa, 2)},
                     "engine": "neo4j" if graph is not None else "networkx"})
        cands.append(card)
    cands.sort(key=lambda x: -x["score"])
    return cands[:limit]


def _shared_terms(ix, a, b):
    if a not in ix["row"] or b not in ix["row"]:
        return []
    va = ix["X"][ix["row"][a]].toarray().ravel()
    vb = ix["X"][ix["row"][b]].toarray().ravel()
    prod = va * vb
    top = np.argsort(-prod)[:5]
    names = ix["vec"].get_feature_names_out()
    return [names[i] for i in top if prod[i] > 0]


def team(s: Snapshot, brief: str, visible_insts, viewer_inst, size=4):
    pool = experts(s, brief, visible_insts, viewer_inst, limit=40, roles=FACULTY_ROLES)
    if not pool:
        return {"team": [], "coverage": []}
    terms = [t for t in re.findall(r"[a-z0-9\-]+", brief.lower()) if len(t) > 3]
    chosen = [pool[0]]
    while len(chosen) < size and len(chosen) < len(pool):
        depts = {(c["inst"], c["dept"]) for c in chosen}
        insts = {c["inst"] for c in chosen}
        ties = set()
        for c in chosen:
            ties |= set(coauthors(s, c["id"]))
        best, best_score = None, -1
        for c in pool:
            if c in chosen:
                continue
            sc = c["match"] / 100
            sc += 0.18 if (c["inst"], c["dept"]) not in depts else 0
            sc += 0.1 if c["inst"] not in insts else 0
            sc += 0.08 if c["id"] in ties else 0
            if sc > best_score:
                best, best_score = c, sc
        chosen.append(best)
    for c in chosen:
        why = []
        if c["matched"]:
            why.append("Brings " + ", ".join(c["matched"][:2]))
        elif c["interests"]:
            why.append("Brings " + ", ".join(c["interests"][:2]))
        why.append(f"{c['pubs']} papers · h-index {c['h_index']}")
        c["why"] = why
    covered = {t: [c["name"] for c in chosen if any(t in (i.lower()) for i in c["interests"]) or
                   any(t in e["title"].lower() for e in c["evidence"])] for t in terms[:8]}
    ids = [c["id"] for c in chosen]
    existing = sum(1 for i in range(len(ids)) for j in range(i + 1, len(ids)) if ids[j] in coauthors(s, ids[i]))
    return {"team": chosen, "coverage": [{"term": t, "by": v} for t, v in covered.items()],
            "existing_ties": existing, "pairs": len(ids) * (len(ids) - 1) // 2,
            "depts": len({(c["inst"], c["dept"]) for c in chosen}), "insts": len({c["inst"] for c in chosen})}


def search(s: Snapshot, q: str, visible_insts, viewer_inst, own_inst):
    ql = q.strip().lower()
    if len(ql) < 2:
        return {}
    toks = ql.split()

    def score(text):
        t = text.lower()
        if t == ql:
            return 100
        if t.startswith(ql):
            return 85
        if ql in t:
            return 70
        if all(tok in t for tok in toks):
            return 50
        return 0

    people = []
    for p in s.people.values():
        if p["status"] != "active" or p["role"] == "platform_admin" or not p["inst_id"]:
            continue
        if not _visible(s, p["id"], visible_insts, viewer_inst):
            continue
        sc = max(score(p["name"]), 0.6 * max((score(t) for t in p["interests"]), default=0))
        if sc:
            people.append((sc + (5 if p["inst_id"] == own_inst else 0), p["id"]))
    people.sort(key=lambda x: -x[0])
    pubs = []
    for p in s.pubs.values():
        if p["status"] != "verified" or not (p["insts"] & visible_insts):
            continue
        if p["visibility"] != "public" and own_inst not in p["insts"]:
            continue
        sc = score(p["title"])
        if sc:
            pubs.append((sc + p["citations"] / 100, p))
    pubs.sort(key=lambda x: -x[0])
    projects = []
    for p in s.projects.values():
        if p["status"] != "verified" or not (p["insts"] & visible_insts) or p["stage"] == "not_funded":
            continue
        if own_inst not in p["insts"] and p["stage"] == "submitted":
            continue
        sc = score(p["title"])
        if sc:
            projects.append((sc, p))
    projects.sort(key=lambda x: -x[0])
    topics = Counter()
    for p in s.people.values():
        if p["inst_id"] in visible_insts:
            for t in p["interests"]:
                if ql in t.lower():
                    topics[t] += 1
    insts = [i for i in s.inst.values() if score(i["name"]) or score(i["short"]) or score(i.get("city") or "")]
    depts = [d for d in s.dept.values() if d["inst_id"] == own_inst and (score(d["name"]) or score(d["code"]))]
    return {
        "people": [_card(s, pid) for _, pid in people[:7]],
        "publications": [{"id": p["id"], "title": p["title"], "year": p["year"], "venue": p["venue"], "citations": p["citations"]} for _, p in pubs[:6]],
        "projects": [{"id": p["id"], "title": p["title"], "agency": p["agency"], "amount": p["amount"], "stage": p["stage"]} for _, p in projects[:5]],
        "topics": [{"topic": t, "people": c} for t, c in topics.most_common(5)],
        "institutions": [{"id": i["id"], "name": i["name"], "short": i["short"], "city": i["city"], "external": bool(i["external"])} for i in insts[:5]],
        "departments": [{"id": d["id"], "name": d["name"], "code": d["code"]} for d in depts[:4]],
    }
