"""Graph construction, metrics and layout for the Graph Explorer."""
from __future__ import annotations

import math
from collections import Counter, defaultdict

import networkx as nx
import numpy as np

from .analytics import FACULTY_ROLES, Scope, pubs_in, projects_in, topic_stats
from .db import Snapshot, cached


# ── layout ───────────────────────────────────────────────────────────────────
def layout(G: nx.Graph, communities: dict | None = None, iterations: int = 110, seed: int = 7):
    """Vectorised Fruchterman–Reingold seeded by community, so clusters separate cleanly."""
    nodes = list(G.nodes())
    n = len(nodes)
    if n == 0:
        return {}
    if n == 1:
        return {nodes[0]: (0.0, 0.0)}
    rng = np.random.default_rng(seed)
    idx = {v: i for i, v in enumerate(nodes)}
    pos = rng.uniform(-1, 1, (n, 2)).astype(np.float32)
    if communities:
        comms = sorted(set(communities.values()))
        sizes = Counter(communities.values())
        # place big communities on an inner ring, small ones outside
        order = sorted(comms, key=lambda c: -sizes[c])
        centres = {}
        for k, c in enumerate(order):
            ring = 0.0 if k == 0 else (0.55 if k < 7 else 0.95)
            ang = 2 * math.pi * k / max(1, min(len(order) - 1, 6) if k < 7 else max(1, len(order) - 7))
            centres[c] = (ring * math.cos(ang + k), ring * math.sin(ang + k))
        for v in nodes:
            cx, cy = centres[communities.get(v, order[0])]
            spread = 0.12 + 0.25 * math.sqrt(sizes[communities.get(v, order[0])] / n)
            pos[idx[v]] = (cx + rng.normal(0, spread), cy + rng.normal(0, spread))
    A = np.zeros((n, n), dtype=np.float32)
    for u, v, d in G.edges(data=True):
        w = float(d.get("weight", 1.0))
        w = 1.0 + math.log1p(w)
        if communities and communities.get(u) != communities.get(v):
            w *= 0.22  # weak pull across communities so clusters read as separate islands
        A[idx[u], idx[v]] = A[idx[v], idx[u]] = w
    k = np.float32(math.sqrt(1.0 / n) * 1.6)
    k2 = k * k
    x, y = pos[:, 0].copy(), pos[:, 1].copy()
    t = 0.12
    dt = t / (iterations + 1)
    for _ in range(iterations):
        dx = x[:, None] - x[None, :]
        dy = y[:, None] - y[None, :]
        d2 = dx * dx + dy * dy
        np.maximum(d2, 6.4e-5, out=d2)
        force = k2 / d2 - A * np.sqrt(d2) / k   # repulsion − weighted spring attraction
        fx = (dx * force).sum(axis=1) - x * 0.9 * k  # gravity keeps islands on screen
        fy = (dy * force).sum(axis=1) - y * 0.9 * k
        length = np.sqrt(fx * fx + fy * fy)
        np.maximum(length, 0.01, out=length)
        step = np.minimum(length, t) / length
        x += fx * step
        y += fy * step
        t -= dt
    pos = np.stack([x, y], axis=1)
    pos -= pos.mean(axis=0)
    scale = np.abs(pos).max() or 1.0
    pos = pos / scale * 1000
    return {v: (round(float(pos[idx[v], 0]), 1), round(float(pos[idx[v], 1]), 1)) for v in nodes}


def communities_of(G: nx.Graph, seed=11):
    if G.number_of_edges() == 0:
        return {v: i for i, v in enumerate(G.nodes())}, 0.0
    comms = nx.community.louvain_communities(G, weight="weight", seed=seed, resolution=1.0)
    comms = sorted(comms, key=len, reverse=True)
    cmap = {v: i for i, c in enumerate(comms) for v in c}
    try:
        q = nx.community.modularity(G, comms, weight="weight")
    except Exception:
        q = 0.0
    return cmap, round(q, 3)


def metrics(G: nx.Graph):
    n = G.number_of_nodes()
    if n == 0:
        return {}, {}
    deg = dict(G.degree())
    wdeg = dict(G.degree(weight="weight"))
    k = min(n, 220)
    btw = nx.betweenness_centrality(G, k=k if n > 220 else None, seed=3, normalized=True)
    pr = nx.pagerank(G, weight="weight") if G.number_of_edges() else {v: 1 / n for v in G}
    clust = nx.clustering(G)
    core = nx.core_number(G) if G.number_of_edges() else {v: 0 for v in G}
    arts = set(nx.articulation_points(G)) if G.number_of_edges() else set()
    per = {v: {"degree": deg[v], "strength": round(wdeg[v], 1), "betweenness": round(btw.get(v, 0), 4),
               "pagerank": round(pr.get(v, 0) * n, 3), "clustering": round(clust.get(v, 0), 3), "core": core.get(v, 0),
               "bridge": v in arts} for v in G.nodes()}
    comps = list(nx.connected_components(G))
    giant = max(comps, key=len) if comps else set()
    summ = {
        "nodes": n, "edges": G.number_of_edges(),
        "density": round(nx.density(G), 4),
        "components": len(comps),
        "giant_share": round(100 * len(giant) / n, 1) if n else 0,
        "avg_degree": round(sum(deg.values()) / n, 2),
        "avg_clustering": round(sum(clust.values()) / n, 3),
        "bridges": len(arts),
    }
    if 2 < len(giant) <= 1500:
        sub = G.subgraph(giant)
        sample = list(sub.nodes())[:: max(1, len(giant) // 120)]
        lens = []
        for v in sample:
            lens.extend(nx.single_source_shortest_path_length(sub, v).values())
        summ["avg_path"] = round(sum(lens) / max(1, len(lens) - len(sample)), 2)
        summ["diameter_est"] = max(lens) if lens else 0
    return per, summ


# ── people graph ─────────────────────────────────────────────────────────────
def people_graph(s: Snapshot, sc: Scope, include_students=True, include_projects=True, min_weight=1.0):
    roles = set(FACULTY_ROLES) | ({"scholar", "student", "staff"} if include_students else set())
    G = nx.Graph()
    evidence = defaultdict(lambda: {"pubs": 0, "projects": 0})
    for p in pubs_in(s, sc):
        ids = [a for a in p["authors"] if s.people[a]["role"] in roles and s.people[a]["status"] == "active"]
        ids = [a for a in ids if s.people[a]["inst_id"] in sc.insts and (not sc.depts or s.people[a]["dept_id"] in sc.depts)] \
            if not sc.person else ids
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                a, b = sorted((ids[i], ids[j]))
                evidence[(a, b)]["pubs"] += 1
    if include_projects:
        for pr in projects_in(s, sc):
            if pr["stage"] not in ("ongoing", "completed"):
                continue
            ids = [m["id"] for m in pr["members"] if s.people[m["id"]]["role"] in roles]
            ids = [a for a in ids if s.people[a]["inst_id"] in sc.insts and (not sc.depts or s.people[a]["dept_id"] in sc.depts)]
            for i in range(len(ids)):
                for j in range(i + 1, len(ids)):
                    a, b = sorted((ids[i], ids[j]))
                    evidence[(a, b)]["projects"] += 1
    for (a, b), ev in evidence.items():
        w = ev["pubs"] + 0.5 * ev["projects"]
        if w >= min_weight:
            G.add_edge(a, b, weight=w, pubs=ev["pubs"], projects=ev["projects"])
    return G


def edge_kind(s: Snapshot, a, b):
    pa, pb = s.people[a], s.people[b]
    if pa["inst_id"] != pb["inst_id"]:
        return "cross_inst"
    if pa["dept_id"] != pb["dept_id"]:
        return "inter_dept"
    return "intra_dept"


def serialise_people(s: Snapshot, G, per, cmap, pos, focus=None):
    nodes = []
    for v in G.nodes():
        p = s.people[v]
        d = s.dept.get(p["dept_id"])
        nodes.append({"id": v, "name": p["name"], "role": p["role"], "designation": p["designation"],
                      "inst": s.inst[p["inst_id"]]["short"], "inst_id": p["inst_id"],
                      "brand": s.inst[p["inst_id"]]["brand"],
                      "dept": d["code"] if d else "", "dept_name": d["name"] if d else "",
                      "pubs": len(p["pubs"]), "community": cmap.get(v, 0),
                      "x": pos.get(v, (0, 0))[0], "y": pos.get(v, (0, 0))[1],
                      "focus": v == focus, **per.get(v, {})})
    edges = [{"source": u, "target": v, "weight": round(d["weight"], 1), "pubs": d.get("pubs", 0),
              "projects": d.get("projects", 0), "kind": edge_kind(s, u, v)} for u, v, d in G.edges(data=True)]
    return nodes, edges


def describe_communities(s: Snapshot, G, cmap):
    groups = defaultdict(list)
    for v, c in cmap.items():
        groups[c].append(v)
    out = []
    for c, members in sorted(groups.items(), key=lambda kv: -len(kv[1]))[:14]:
        topics = Counter(t for v in members for t in s.people[v]["interests"])
        depts = Counter((s.dept[s.people[v]["dept_id"]]["code"] if s.people[v]["dept_id"] in s.dept else "—") for v in members)
        insts = Counter(s.inst[s.people[v]["inst_id"]]["short"] for v in members)
        hub = max(members, key=lambda v: G.degree(v, weight="weight"))
        out.append({"id": c, "size": len(members), "topics": [t for t, _ in topics.most_common(3)],
                    "depts": [d for d, _ in depts.most_common(3)], "insts": [i for i, _ in insts.most_common(3)],
                    "hub": {"id": hub, "name": s.people[hub]["name"]}})
    return out


def build_people_view(s: Snapshot, sc: Scope, include_students=True, hide_isolated=True, min_weight=1.0):
    key = ("pgraph", sc.key(), include_students, min_weight)

    def build():
        G = people_graph(s, sc, include_students=include_students, min_weight=min_weight)
        if not hide_isolated:
            for p in s.people.values():
                if p["inst_id"] in sc.insts and p["role"] in FACULTY_ROLES and p["status"] == "active" \
                        and (not sc.depts or p["dept_id"] in sc.depts):
                    G.add_node(p["id"])
        cmap, modularity = communities_of(G)
        per, summ = metrics(G)
        pos = layout(G, cmap, iterations=90 if G.number_of_nodes() > 700 else 120)
        nodes, edges = serialise_people(s, G, per, cmap, pos)
        kinds = Counter(e["kind"] for e in edges)
        summ.update({"modularity": modularity, "communities": len(set(cmap.values())),
                     "intra_dept": kinds.get("intra_dept", 0), "inter_dept": kinds.get("inter_dept", 0),
                     "cross_inst": kinds.get("cross_inst", 0)})
        top = sorted(nodes, key=lambda x: -x.get("betweenness", 0))[:8]
        brokers = [{"id": x["id"], "name": x["name"], "inst": x["inst"], "dept": x["dept"], "betweenness": x["betweenness"]} for x in top]
        hubs = sorted(nodes, key=lambda x: -x.get("strength", 0))[:8]
        return {"mode": "people", "nodes": nodes, "edges": edges, "summary": summ,
                "communities": describe_communities(s, G, cmap), "brokers": brokers,
                "hubs": [{"id": x["id"], "name": x["name"], "inst": x["inst"], "dept": x["dept"], "strength": x["strength"]} for x in hubs]}
    return cached(key, build)


def ego_view(s: Snapshot, pid: int, sc: Scope, depth=1):
    """Knowledge graph around one person: co-authors, topics, projects, partner organisations."""
    person = s.people[pid]
    G = nx.Graph()
    G.add_node(f"p{pid}")
    nodes = {f"p{pid}": {"id": f"p{pid}", "kind": "person", "name": person["name"], "ref": pid, "focus": True,
                         "inst": s.inst[person["inst_id"]]["short"], "brand": s.inst[person["inst_id"]]["brand"]}}
    co = Counter()
    for x in person["pubs"]:
        p = s.pubs[x]
        if p["status"] != "verified" or not (sc.y0 <= p["year"] <= sc.y1):
            continue
        for a in p["authors"]:
            if a != pid and s.people[a]["inst_id"] in sc.insts:
                co[a] += 1
        for aff in p["external_affils"]:
            key = f"o{aff}"
            nodes.setdefault(key, {"id": key, "kind": "org", "name": aff})
            G.add_edge(f"p{pid}", key, weight=G.get_edge_data(f"p{pid}", key, {"weight": 0})["weight"] + 1)
    for a, w in co.most_common(40):
        key = f"p{a}"
        q = s.people[a]
        nodes[key] = {"id": key, "kind": "person", "name": q["name"], "ref": a, "inst": s.inst[q["inst_id"]]["short"],
                      "brand": s.inst[q["inst_id"]]["brand"], "role": q["role"]}
        G.add_edge(f"p{pid}", key, weight=w)
    if depth > 1:
        keep = set(co)
        for a in list(co)[:25]:
            for x in s.people[a]["pubs"]:
                p = s.pubs[x]
                if p["status"] != "verified":
                    continue
                for b in p["authors"]:
                    if b in keep and b != a:
                        G.add_edge(f"p{a}", f"p{b}", weight=1)
    for t in person["interests"]:
        key = f"t{t}"
        nodes[key] = {"id": key, "kind": "topic", "name": t}
        G.add_edge(f"p{pid}", key, weight=2)
        for a in co:
            if t in s.people[a]["interests"]:
                G.add_edge(f"p{a}", key, weight=1)
    for x in person["projects"]:
        pr = s.projects[x]
        if pr["stage"] not in ("ongoing", "completed"):
            continue
        key = f"j{x}"
        nodes[key] = {"id": key, "kind": "project", "name": pr["title"], "ref": x, "agency": pr["agency"]}
        G.add_edge(f"p{pid}", key, weight=2)
        for m in pr["members"]:
            if f"p{m['id']}" in nodes and m["id"] != pid:
                G.add_edge(f"p{m['id']}", key, weight=1)
    for v in G.nodes():
        nodes[v]["degree"] = G.degree(v)
    pos = layout(G, None, iterations=140)
    out = []
    for v in G.nodes():
        nd = nodes[v]
        nd["x"], nd["y"] = pos[v]
        out.append(nd)
    return {"mode": "ego", "nodes": out,
            "edges": [{"source": u, "target": v, "weight": d["weight"]} for u, v, d in G.edges(data=True)],
            "summary": {"nodes": G.number_of_nodes(), "edges": G.number_of_edges(), "coauthors": len(co)}}


def institution_view(s: Snapshot, sc: Scope, include_external=True, top_external=18):
    def build():
        G = nx.Graph()
        weight = Counter()
        ext_count = Counter()
        for p in pubs_in(s, sc):
            insts = sorted(p["insts"])
            for i in range(len(insts)):
                for j in range(i + 1, len(insts)):
                    weight[(f"i{insts[i]}", f"i{insts[j]}")] += 1
            if include_external:
                for aff in p["external_affils"]:
                    for i in insts:
                        if i in sc.insts:
                            weight[(f"i{i}", f"x{aff}")] += 1
                            ext_count[aff] += 1
        keep_ext = {a for a, _ in ext_count.most_common(top_external)}
        for (a, b), w in weight.items():
            if b.startswith("x") and b[1:] not in keep_ext:
                continue
            G.add_edge(a, b, weight=w)
        for i in sc.insts:
            if not s.inst[i]["external"]:
                G.add_node(f"i{i}")
        pos = layout(G, None, iterations=160)
        pubs_by_inst = Counter(i for p in pubs_in(s, sc) for i in p["insts"])
        country = {}
        for p in s.pubs.values():
            for e in p["ext"]:
                if e.get("affil"):
                    country[e["affil"]] = e.get("country")
        nodes = []
        for v in G.nodes():
            if v.startswith("i"):
                inst = s.inst[int(v[1:])]
                nodes.append({"id": v, "kind": "rice", "name": inst["name"], "short": inst["short"], "brand": inst["brand"],
                              "pubs": pubs_by_inst.get(inst["id"], 0), "ref": inst["id"], "x": pos[v][0], "y": pos[v][1],
                              "degree": G.degree(v)})
            else:
                nodes.append({"id": v, "kind": "external", "name": v[1:], "short": v[1:], "country": country.get(v[1:]),
                              "pubs": ext_count[v[1:]], "x": pos[v][0], "y": pos[v][1], "degree": G.degree(v)})
        return {"mode": "institutions", "nodes": nodes,
                "edges": [{"source": u, "target": v, "weight": d["weight"]} for u, v, d in G.edges(data=True)],
                "summary": {"nodes": G.number_of_nodes(), "edges": G.number_of_edges(),
                            "rice": sum(1 for n in nodes if n["kind"] == "rice"),
                            "external": sum(1 for n in nodes if n["kind"] == "external")}}
    return cached(("igraph", sc.key(), include_external), build)


def department_view(s: Snapshot, sc: Scope):
    def build():
        G = nx.Graph()
        size = Counter()
        for p in pubs_in(s, sc):
            ds = sorted(d for d in p["depts"] if s.dept[d]["inst_id"] in sc.insts)
            for d in ds:
                size[d] += 1
            for i in range(len(ds)):
                for j in range(i + 1, len(ds)):
                    if G.has_edge(ds[i], ds[j]):
                        G[ds[i]][ds[j]]["weight"] += 1
                    else:
                        G.add_edge(ds[i], ds[j], weight=1)
        for d in size:
            G.add_node(d)
        pos = layout(G, None, iterations=160)
        multi = len(sc.insts) > 1
        nodes = [{"id": d, "name": s.dept[d]["name"], "code": s.dept[d]["code"], "field": s.dept[d]["field"],
                  "inst": s.inst[s.dept[d]["inst_id"]]["short"], "brand": s.inst[s.dept[d]["inst_id"]]["brand"],
                  "label": f"{s.dept[d]['code']} · {s.inst[s.dept[d]['inst_id']]['short']}" if multi else s.dept[d]["code"],
                  "pubs": size[d], "x": pos[d][0], "y": pos[d][1], "degree": G.degree(d)} for d in G.nodes()]
        return {"mode": "departments", "nodes": nodes,
                "edges": [{"source": u, "target": v, "weight": d["weight"],
                           "kind": "cross_inst" if s.dept[u]["inst_id"] != s.dept[v]["inst_id"] else "inter_dept"}
                          for u, v, d in G.edges(data=True)],
                "summary": {"nodes": G.number_of_nodes(), "edges": G.number_of_edges()}}
    return cached(("dgraph", sc.key()), build)


def topic_view(s: Snapshot, sc: Scope, min_count=3, limit=90):
    def build():
        pubs = pubs_in(s, sc)
        stats = {r["topic"]: r for r in topic_stats(s, pubs, sc.y1)}
        keep = {t for t, r in sorted(stats.items(), key=lambda kv: -kv[1]["count"])[:limit] if r["count"] >= min_count}
        G = nx.Graph()
        for p in pubs:
            ks = sorted(k for k in set(p["keywords"]) if k in keep)
            for k in ks:
                G.add_node(k)
            for i in range(len(ks)):
                for j in range(i + 1, len(ks)):
                    if G.has_edge(ks[i], ks[j]):
                        G[ks[i]][ks[j]]["weight"] += 1
                    else:
                        G.add_edge(ks[i], ks[j], weight=1)
        weak = [(u, v) for u, v, d in G.edges(data=True) if d["weight"] < 2]
        G.remove_edges_from(weak)
        cmap, q = communities_of(G)
        pos = layout(G, cmap, iterations=150)
        nodes = [{"id": t, "name": t, "count": stats[t]["count"], "trend": stats[t]["trend"], "growth": stats[t]["growth"],
                  "community": cmap.get(t, 0), "x": pos[t][0], "y": pos[t][1], "degree": G.degree(t)} for t in G.nodes()]
        return {"mode": "topics", "nodes": nodes,
                "edges": [{"source": u, "target": v, "weight": d["weight"]} for u, v, d in G.edges(data=True)],
                "summary": {"nodes": G.number_of_nodes(), "edges": G.number_of_edges(), "communities": len(set(cmap.values())),
                            "modularity": q}}
    return cached(("tgraph", sc.key()), build)


def mentorship_view(s: Snapshot, sc: Scope):
    def build():
        G = nx.Graph()
        for p in s.people.values():
            if p["status"] != "active" or p["inst_id"] not in sc.insts:
                continue
            if sc.depts and p["dept_id"] not in sc.depts:
                continue
            sup = p.get("supervisor_id")
            if sup and sup in s.people:
                G.add_edge(sup, p["id"], weight=1)
        pos = layout(G, None, iterations=120)
        nodes = []
        for v in G.nodes():
            p = s.people[v]
            d = s.dept.get(p["dept_id"])
            nodes.append({"id": v, "name": p["name"], "role": p["role"], "designation": p["designation"],
                          "dept": d["code"] if d else "", "inst": s.inst[p["inst_id"]]["short"],
                          "students": len(p["students"]), "x": pos[v][0], "y": pos[v][1], "degree": G.degree(v)})
        sup_load = [n for n in nodes if n["students"]]
        return {"mode": "mentorship", "nodes": nodes,
                "edges": [{"source": u, "target": v, "weight": 1} if s.people[v].get("supervisor_id") == u
                          else {"source": v, "target": u, "weight": 1} for u, v in G.edges()],
                "summary": {"nodes": G.number_of_nodes(), "edges": G.number_of_edges(), "supervisors": len(sup_load),
                            "avg_load": round(sum(n["students"] for n in sup_load) / max(1, len(sup_load)), 2)}}
    return cached(("mgraph", sc.key()), build)


def shortest_path(s: Snapshot, sc: Scope, a: int, b: int):
    G = people_graph(s, sc, include_students=True)
    if a not in G or b not in G:
        return {"path": [], "error": "One of these people has no collaborations in the selected scope."}
    try:
        path = nx.shortest_path(G, a, b)
    except nx.NetworkXNoPath:
        return {"path": [], "error": "No chain of collaborations connects these two people yet."}
    steps = []
    for u, v in zip(path, path[1:]):
        shared = [s.pubs[x] for x in set(s.people[u]["pubs"]) & set(s.people[v]["pubs"]) if s.pubs[x]["status"] == "verified"]
        shared.sort(key=lambda p: -p["year"])
        steps.append({"from": u, "to": v, "pubs": len(shared),
                      "example": {"id": shared[0]["id"], "title": shared[0]["title"], "year": shared[0]["year"]} if shared else None})
    people = [{"id": v, "name": s.people[v]["name"], "inst": s.inst[s.people[v]["inst_id"]]["short"],
               "dept": (s.dept.get(s.people[v]["dept_id"]) or {}).get("code", ""), "role": s.people[v]["role"]} for v in path]
    return {"path": people, "steps": steps, "hops": len(path) - 1}
