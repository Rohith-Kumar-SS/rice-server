"""Neo4j knowledge graph + Graph Data Science analytics.

SQLite stays the system of record (accounts, approvals, records). Neo4j holds the research
knowledge graph, rebuilt from the snapshot whenever the data changes, and runs every graph
view and graph algorithm (GDS: Louvain, PageRank, betweenness, clustering, k-core,
articulation points, WCC, node similarity) plus native Cypher path finding and link prediction.

Every query is filtered by the institutions the caller may see, so tenant isolation holds.
If Neo4j is unreachable RICE falls back to the NetworkX engine in graphs.py.
"""
from __future__ import annotations

import logging
import math
import os
import socket
import threading
import time
import uuid
from collections import Counter, defaultdict
from pathlib import Path

import networkx as nx

from . import db
from .catalog import SDG_NAMES

log = logging.getLogger("rice.neo4j")

ROOT = db.ROOT
SECRET_FILE = db.DATA_DIR / "neo4j.secret"
URI = os.environ.get("NEO4J_URI", "bolt://127.0.0.1:7697")
USER = os.environ.get("NEO4J_USER", "neo4j")
DATABASE = os.environ.get("NEO4J_DATABASE", "neo4j")
ENGINE = os.environ.get("RICE_GRAPH_ENGINE", "auto")  # auto | neo4j | networkx
BROWSER_URL = os.environ.get("NEO4J_BROWSER_URL", "http://127.0.0.1:7484/browser/")
LABELS = ["Institution", "Department", "Person", "Publication", "Project", "Patent", "Topic", "Organisation",
          "Agency", "SDG", "Venue"]
FACULTY = ["faculty", "hod"]


def _password():
    if os.environ.get("NEO4J_PASSWORD"):
        return os.environ["NEO4J_PASSWORD"]
    if SECRET_FILE.exists():
        return SECRET_FILE.read_text().strip()
    return None


class Neo:
    def __init__(self):
        self.driver = None
        self.ok = False
        self.state = "off" if ENGINE == "networkx" else "connecting"
        self.error = None
        self.server = None
        self.edition = None
        self.gds = None
        self.procs: set[str] = set()
        self.synced = -1
        self.sync_ms = None
        self.synced_at = None
        self.counts = {}
        self._lock = threading.RLock()
        self._sync_lock = threading.Lock()

    # ── connection ───────────────────────────────────────────────────────────
    def connect(self, wait: float = 0.0) -> bool:
        if ENGINE == "networkx":
            return False
        pw = _password()
        if not pw:
            self.state, self.error = "not configured", "No Neo4j password — run tools/setup_neo4j.py or set NEO4J_PASSWORD."
            return False
        deadline = time.time() + wait
        while True:
            try:
                from neo4j import GraphDatabase
                drv = GraphDatabase.driver(URI, auth=(USER, pw), connection_timeout=4, max_connection_pool_size=20,
                                           notifications_min_severity="OFF")
                drv.verify_connectivity()
                info = drv.execute_query("CALL dbms.components() YIELD name, versions, edition RETURN name, versions[0] AS v, edition",
                                         database_=DATABASE).records
                self.server = info[0]["v"] if info else "?"
                self.edition = info[0]["edition"] if info else "?"
                procs = drv.execute_query("SHOW PROCEDURES YIELD name WHERE name STARTS WITH 'gds.' RETURN collect(name) AS n",
                                          database_=DATABASE).records[0]["n"]
                self.procs = set(procs)
                if procs:
                    try:
                        self.gds = drv.execute_query("RETURN gds.version() AS v", database_=DATABASE).records[0]["v"]
                    except Exception:
                        self.gds = "installed"
                self.driver, self.ok, self.state, self.error = drv, True, "connected", None
                self._schema()
                return True
            except Exception as e:  # noqa: BLE001 — any failure means "not available yet"
                self.ok, self.error = False, str(e).split("\n")[0][:240]
                self.state = "unreachable"
                if time.time() >= deadline:
                    return False
                time.sleep(2)

    def has(self, proc: str) -> bool:
        return proc in self.procs

    def run(self, cypher: str, write=False, **params):
        from neo4j import RoutingControl
        recs = self.driver.execute_query(cypher, params, database_=DATABASE,
                                         routing_=RoutingControl.WRITE if write else RoutingControl.READ).records
        return [r.data() for r in recs]

    def _schema(self):
        stmts = [f"CREATE CONSTRAINT rice_{l.lower()}_id IF NOT EXISTS FOR (n:{l}) REQUIRE n.id IS UNIQUE"
                 for l in ("Institution", "Department", "Person", "Publication", "Project", "Patent")]
        stmts += [f"CREATE CONSTRAINT rice_{l.lower()}_name IF NOT EXISTS FOR (n:{l}) REQUIRE n.name IS UNIQUE"
                  for l in ("Topic", "Organisation", "Agency", "Venue")]
        stmts += ["CREATE CONSTRAINT rice_sdg_goal IF NOT EXISTS FOR (n:SDG) REQUIRE n.goal IS UNIQUE",
                  "CREATE INDEX rice_pub_year IF NOT EXISTS FOR (n:Publication) ON (n.year)",
                  "CREATE INDEX rice_person_inst IF NOT EXISTS FOR (n:Person) ON (n.inst_id)"]
        for s in stmts:
            self.run(s, write=True)

    # ── sync from SQLite snapshot ────────────────────────────────────────────
    def ensure_synced(self, timeout: float = 30.0):
        if not self.ok:
            return False
        if self.synced == db.version():
            return True
        got = self._sync_lock.acquire(timeout=timeout)
        if not got:
            return self.synced >= 0
        try:
            if self.synced != db.version():
                self.sync()
        finally:
            self._sync_lock.release()
        return True

    def sync(self):
        t0 = time.time()
        s = db.snapshot()
        version = s.version
        P = _payload(s)
        steps = [
            ("MATCH (n:Institution|Department|Person|Publication|Project|Patent|Topic|Organisation|Agency|SDG|Venue) DETACH DELETE n", {}),
            ("UNWIND $rows AS r CREATE (n:Institution) SET n = r", {"rows": P["insts"]}),
            ("UNWIND $rows AS r MATCH (i:Institution {id: r.inst_id}) CREATE (d:Department) SET d = r CREATE (d)-[:PART_OF]->(i)", {"rows": P["depts"]}),
            ("UNWIND $rows AS r MATCH (i:Institution {id: r.inst_id}) CREATE (p:Person) SET p = r CREATE (p)-[:AFFILIATED_WITH]->(i)", {"rows": P["people"]}),
            ("UNWIND $rows AS r MATCH (p:Person {id: r.id}), (d:Department {id: r.dept_id}) CREATE (p)-[:WORKS_IN]->(d)", {"rows": [x for x in P["people"] if x.get("dept_id") is not None]}),
            ("UNWIND $rows AS r MATCH (a:Person {id: r.s}), (b:Person {id: r.t}) CREATE (a)-[:SUPERVISES]->(b)", {"rows": P["supervises"]}),
            ("UNWIND $rows AS t CREATE (:Topic {name: t})", {"rows": P["topics"]}),
            ("UNWIND $rows AS r MATCH (p:Person {id: r.p}), (t:Topic {name: r.t}) CREATE (p)-[:INTERESTED_IN]->(t)", {"rows": P["interests"]}),
            ("UNWIND $rows AS r CREATE (:Organisation {name: r.name, country: r.country})", {"rows": P["orgs"]}),
            ("UNWIND $rows AS v CREATE (:Venue {name: v})", {"rows": P["venues"]}),
            ("UNWIND $rows AS r CREATE (:SDG {goal: r.goal, name: r.name})", {"rows": P["sdgs"]}),
            ("UNWIND $rows AS r CREATE (:Agency {name: r.name, sector: r.sector})", {"rows": P["agencies"]}),
            ("UNWIND $rows AS r CREATE (p:Publication) SET p = r", {"rows": P["pubs"]}),
            ("UNWIND $rows AS r MATCH (a:Person {id: r.p}), (b:Publication {id: r.pub}) CREATE (a)-[:AUTHORED {position: r.pos}]->(b)", {"rows": P["authored"]}),
            ("UNWIND $rows AS r MATCH (p:Publication {id: r.pub}), (t:Topic {name: r.t}) CREATE (p)-[:ABOUT]->(t)", {"rows": P["pub_topics"]}),
            ("UNWIND $rows AS r MATCH (p:Publication {id: r.pub}), (g:SDG {goal: r.g}) CREATE (p)-[:SUPPORTS]->(g)", {"rows": P["pub_sdgs"]}),
            ("UNWIND $rows AS r MATCH (p:Publication {id: r.pub}), (v:Venue {name: r.v}) CREATE (p)-[:PUBLISHED_IN]->(v)", {"rows": P["pub_venues"]}),
            ("UNWIND $rows AS r MATCH (p:Publication {id: r.pub}), (o:Organisation {name: r.o}) CREATE (p)-[:WITH_PARTNER {authors: r.n}]->(o)", {"rows": P["pub_orgs"]}),
            ("UNWIND $rows AS r CREATE (j:Project) SET j = r", {"rows": P["projects"]}),
            ("UNWIND $rows AS r MATCH (p:Person {id: r.p}), (j:Project {id: r.j}) CREATE (p)-[:MEMBER_OF {role: r.role}]->(j)", {"rows": P["members"]}),
            ("UNWIND $rows AS r MATCH (j:Project {id: r.j}), (g:Agency {name: r.a}) CREATE (j)-[:FUNDED_BY {scheme: r.scheme}]->(g)", {"rows": P["proj_agency"]}),
            ("UNWIND $rows AS r MATCH (j:Project {id: r.j}), (t:Topic {name: r.t}) CREATE (j)-[:ABOUT]->(t)", {"rows": P["proj_topics"]}),
            ("UNWIND $rows AS r CREATE (x:Patent) SET x = r", {"rows": P["patents"]}),
            ("UNWIND $rows AS r MATCH (p:Person {id: r.p}), (x:Patent {id: r.x}) CREATE (p)-[:INVENTED]->(x)", {"rows": P["inventors"]}),
            ("UNWIND $rows AS r MATCH (x:Patent {id: r.x}), (t:Topic {name: r.t}) CREATE (x)-[:ABOUT]->(t)", {"rows": P["pat_topics"]}),
            ("UNWIND $rows AS r MATCH (a:Person {id: r.a}), (b:Person {id: r.b}) "
             "CREATE (a)-[:COLLABORATES_WITH {pubs: r.pubs, projects: r.projects, weight: r.weight, first: r.first, last: r.last}]->(b)", {"rows": P["collab"]}),
            ("UNWIND $rows AS r MATCH (a:Person {id: r.a}), (b:Person {id: r.b}) CREATE (a)-[:REQUESTED_COLLAB {status: r.status, topic: r.topic}]->(b)", {"rows": P["requests"]}),
        ]

        def work(tx):
            for q, params in steps:
                tx.run(q, **params).consume()

        try:
            with self.driver.session(database=DATABASE) as sess:
                sess.execute_write(work)
        except Exception as e:  # noqa: BLE001 — small hosted tiers cap transaction memory
            log.warning("one-transaction rebuild failed (%s); rebuilding in batches", str(e)[:160])
            self._sync_batched(steps)
        self.synced = version
        self.sync_ms = int(1000 * (time.time() - t0))
        self.synced_at = time.strftime("%Y-%m-%d %H:%M:%S")
        self.counts = self.stats()
        log.info("Neo4j graph rebuilt in %s ms", self.sync_ms)

    def _sync_batched(self, steps, size=2000):
        with self.driver.session(database=DATABASE) as sess:
            sess.run("MATCH (n:Institution|Department|Person|Publication|Project|Patent|Topic|Organisation|Agency|SDG|Venue) "
                     "CALL (n) { DETACH DELETE n } IN TRANSACTIONS OF 2000 ROWS").consume()
            for q, params in steps[1:]:
                rows = params.get("rows", [])
                for i in range(0, len(rows), size):
                    chunk = rows[i:i + size]
                    sess.execute_write(lambda tx, q=q, chunk=chunk: tx.run(q, rows=chunk).consume())

    def stats(self):
        nodes = {r["l"]: r["n"] for r in self.run("MATCH (n) WITH labels(n)[0] AS l, count(*) AS n RETURN l, n")}
        rels = {r["t"]: r["n"] for r in self.run("MATCH ()-[r]->() RETURN type(r) AS t, count(*) AS n")}
        return {"nodes": nodes, "relationships": rels, "total_nodes": sum(nodes.values()), "total_relationships": sum(rels.values())}

    def status(self):
        return {"engine": "neo4j" if self.ok else "networkx", "state": self.state, "error": self.error, "uri": URI,
                "server": self.server, "edition": self.edition, "gds": self.gds, "synced_version": self.synced,
                "data_version": db.version(), "sync_ms": self.sync_ms, "synced_at": self.synced_at, "counts": self.counts,
                "browser": BROWSER_URL, "algorithms": sorted(p for p in self.procs if p.endswith(".stream"))[:60]}

    # ── GDS helpers ──────────────────────────────────────────────────────────
    def _project(self, cypher_match: str, params: dict, props=("weight",)) -> tuple[str, int, int]:
        name = "rice_" + uuid.uuid4().hex[:12]
        rel = ", ".join(f"{p}: toFloat({p})" for p in props)
        q = cypher_match + f"\nWITH gds.graph.project($g, a, b, {{relationshipProperties: {{{rel}}}}}, " \
                           "{undirectedRelationshipTypes: ['*']}) AS g RETURN g.nodeCount AS nodes, g.relationshipCount AS rels"
        r = self.run(q, write=True, g=name, **params)
        return name, (r[0]["nodes"] if r else 0), (r[0]["rels"] if r else 0)

    def _drop(self, name):
        try:
            self.run("CALL gds.graph.drop($g, false) YIELD graphName RETURN graphName", write=True, g=name)
        except Exception:
            pass

    def algorithms(self, name, n, weighted=True, key="id"):
        """Run the GDS suite on a projected undirected graph; returns per-node metrics + summary."""
        w = {"relationshipWeightProperty": "weight"} if weighted else {}
        as_key = f"gds.util.asNode(nodeId).{key}"

        def stream(proc, cfg, field):
            q = f"CALL {proc}($g, $cfg) YIELD nodeId, {field} RETURN {as_key} AS id, {field} AS v"
            return {r["id"]: r["v"] for r in self.run(q, g=name, cfg=cfg)}

        out = {}
        out["community"] = stream("gds.louvain.stream", {**w, "concurrency": 1}, "communityId")
        out["modularity"] = None  # filled by the caller from the streamed edges (saves a round trip)
        out["degree"] = stream("gds.degree.stream", {}, "score")
        out["strength"] = stream("gds.degree.stream", w, "score") if weighted else out["degree"]
        pr = stream("gds.pageRank.stream", {**w, "concurrency": 1}, "score")
        tot = sum(pr.values()) or 1
        out["pagerank"] = {k: v * n / tot for k, v in pr.items()}
        # exact Brandes betweenness up to a few thousand nodes; sampled above that
        cfg_b = {"samplingSize": 1500, "samplingSeed": 3} if n > 4000 else {}
        btw = stream("gds.betweenness.stream", cfg_b, "score")
        norm = ((n - 1) * (n - 2) / 2) if n > 2 else 1
        scale = (n / 1500) if n > 4000 else 1
        out["betweenness"] = {k: v * scale / norm for k, v in btw.items()}  # same scale as NetworkX normalized=True
        out["clustering"] = stream("gds.localClusteringCoefficient.stream", {"concurrency": 1}, "localClusteringCoefficient")
        out["core"] = stream("gds.kcore.stream", {"concurrency": 1}, "coreValue") if self.has("gds.kcore.stream") else {}
        out["component"] = stream("gds.wcc.stream", {"concurrency": 1}, "componentId")
        if self.has("gds.articulationPoints.stream"):
            q = f"CALL gds.articulationPoints.stream($g, {{}}) YIELD nodeId RETURN {as_key} AS id"
            out["bridges"] = {r["id"] for r in self.run(q, g=name)}
        else:
            out["bridges"] = None
        return out

    # ── views ────────────────────────────────────────────────────────────────
    def people_view(self, s, sc, include_students=True, min_weight=1.0):
        from .graphs import describe_communities, layout
        key = ("neo.pgraph", sc.key(), include_students, min_weight, bool(self.gds))

        def build():
            roles = FACULTY + (["scholar", "student", "staff"] if include_students else [])
            params = dict(insts=sorted(sc.insts), depts=sorted(sc.depts) or None, y0=sc.y0, y1=sc.y1, roles=roles, min_w=min_weight)
            match = PEOPLE_EDGES
            G = nx.Graph()
            if self.gds:
                name, n, _ = self._project(match, params, props=("weight", "pubs", "projects"))
                try:
                    if n:
                        for e in self.run(REL_STREAM, g=name):
                            if e["s"] < e["t"]:
                                G.add_edge(e["s"], e["t"], weight=e["weight"], pubs=int(e["pubs"]), projects=int(e["projects"]))
                        alg = self.algorithms(name, n)
                finally:
                    self._drop(name)
            else:  # e.g. AuraDB Free: Cypher in Neo4j, algorithms in Python on the returned edges
                for e in self.run(match + "\nRETURN a.id AS s, b.id AS t, weight, pubs, projects", **params):
                    G.add_edge(e["s"], e["t"], weight=e["weight"], pubs=int(e["pubs"]), projects=int(e["projects"]))
                if G.number_of_nodes():
                    alg = _nx_algorithms(G)
            n = G.number_of_nodes()
            if n == 0:
                return {"mode": "people", "engine": "neo4j", "nodes": [], "edges": [], "summary": {"nodes": 0, "edges": 0},
                        "communities": [], "brokers": [], "hubs": [], "cypher": [match]}
            # renumber communities by size so colours are stable and the biggest is #1
            sizes = Counter(alg["community"].values())
            order = {c: i for i, (c, _) in enumerate(sorted(sizes.items(), key=lambda kv: (-kv[1], kv[0])))}
            cmap = {v: order[c] for v, c in alg["community"].items()}
            groups = defaultdict(set)
            for v, c in cmap.items():
                groups[c].add(v)
            alg["modularity"] = round(nx.community.modularity(G, list(groups.values()), weight="weight"), 3)
            bridges = alg["bridges"] if alg["bridges"] is not None else set(nx.articulation_points(G))
            core = alg["core"] or nx.core_number(G)
            per = {v: {"degree": int(alg["degree"].get(v, 0)), "strength": round(alg["strength"].get(v, 0), 1),
                       "betweenness": round(alg["betweenness"].get(v, 0), 4), "pagerank": round(alg["pagerank"].get(v, 0), 3),
                       "clustering": round(alg["clustering"].get(v, 0), 3), "core": int(core.get(v, 0)), "bridge": v in bridges}
                   for v in G.nodes()}
            comps = Counter(alg["component"].values())
            summ = {"nodes": n, "edges": G.number_of_edges(), "density": round(nx.density(G), 4), "components": len(comps),
                    "giant_share": round(100 * max(comps.values()) / n, 1) if comps else 0,
                    "avg_degree": round(2 * G.number_of_edges() / n, 2),
                    "avg_clustering": round(sum(p["clustering"] for p in per.values()) / n, 3), "bridges": len(bridges),
                    "modularity": alg["modularity"], "communities": len(sizes)}
            summ.update(_path_stats(G))
            pos = layout(G, cmap, iterations=90 if n > 700 else 120)
            from .graphs import serialise_people
            nodes, edges_out = serialise_people(s, G, per, cmap, pos)
            kinds = Counter(e["kind"] for e in edges_out)
            summ.update({"intra_dept": kinds.get("intra_dept", 0), "inter_dept": kinds.get("inter_dept", 0), "cross_inst": kinds.get("cross_inst", 0)})
            top = sorted(nodes, key=lambda x: -x.get("betweenness", 0))[:8]
            hubs = sorted(nodes, key=lambda x: -x.get("strength", 0))[:8]
            return {"mode": "people", "engine": "neo4j", "nodes": nodes, "edges": edges_out, "summary": summ,
                    "communities": describe_communities(s, G, cmap),
                    "brokers": [{"id": x["id"], "name": x["name"], "inst": x["inst"], "dept": x["dept"], "betweenness": x["betweenness"]} for x in top],
                    "hubs": [{"id": x["id"], "name": x["name"], "inst": x["inst"], "dept": x["dept"], "strength": x["strength"]} for x in hubs],
                    "algorithms": (["gds.louvain", "gds.pageRank", "gds.betweenness", "gds.degree", "gds.localClusteringCoefficient",
                                    "gds.kcore", "gds.wcc"] + (["gds.articulationPoints"] if alg["bridges"] is not None else []))
                    if self.gds else ["networkx.louvain", "networkx.pagerank", "networkx.betweenness", "networkx.clustering",
                                      "networkx.core_number", "networkx.articulation_points"],
                    "cypher": [match.strip()]}
        return db.cached(key, build)

    def topic_view(self, s, sc, min_count=3, limit=90):
        from .graphs import layout
        key = ("neo.tgraph", sc.key(), bool(self.gds))

        def build():
            params = dict(insts=sorted(sc.insts), depts=sorted(sc.depts) or None, y0=sc.y0, y1=sc.y1)
            rows = self.run(TOPIC_COUNTS, **params)
            stats = {}
            for r in rows:
                e, rc = r["earlier"], r["recent"]
                g = (rc - e) / max(e, 2)
                mom = (rc - e) / math.sqrt(e + 2)
                trend = "rising" if g > 0.5 and rc >= 6 and mom > 1.5 else "declining" if g < -0.3 and e >= 5 else "steady"
                stats[r["topic"]] = {"count": r["count"], "growth": round(100 * g), "trend": trend}
            keep = [t for t, v in sorted(stats.items(), key=lambda kv: -kv[1]["count"])[:limit] if v["count"] >= min_count]
            params["keep"] = keep
            edges = self.run(TOPIC_EDGES + "\nRETURN a.name AS source, b.name AS target, weight", **params)
            G = nx.Graph()
            G.add_nodes_from(keep)
            for e in edges:
                G.add_edge(e["source"], e["target"], weight=e["weight"])
            cmap, q = {}, 0.0
            if G.number_of_edges() and not self.gds:
                from .graphs import communities_of
                cmap, q = communities_of(G)
            elif G.number_of_edges():
                name, _, _ = self._project(TOPIC_EDGES, params)
                try:
                    raw = {r["id"]: r["v"] for r in self.run(
                        "CALL gds.louvain.stream($g, {relationshipWeightProperty: 'weight', concurrency: 1}) YIELD nodeId, communityId "
                        "RETURN gds.util.asNode(nodeId).name AS id, communityId AS v", g=name)}
                    st = self.run("CALL gds.louvain.stats($g, {relationshipWeightProperty: 'weight', concurrency: 1}) YIELD modularity RETURN modularity", g=name)
                    q = round(st[0]["modularity"], 3) if st else 0.0
                finally:
                    self._drop(name)
                sizes = Counter(raw.values())
                order = {c: i for i, (c, _) in enumerate(sorted(sizes.items(), key=lambda kv: (-kv[1], kv[0])))}
                cmap = {t: order[c] for t, c in raw.items()}
            nxt = max(cmap.values(), default=-1) + 1
            for t in G.nodes():
                if t not in cmap:
                    cmap[t] = nxt
                    nxt += 1
            pos = layout(G, cmap, iterations=150)
            nodes = [{"id": t, "name": t, "count": stats[t]["count"], "trend": stats[t]["trend"], "growth": stats[t]["growth"],
                      "community": cmap.get(t, 0), "x": pos[t][0], "y": pos[t][1], "degree": G.degree(t)} for t in G.nodes()]
            return {"mode": "topics", "engine": "neo4j", "nodes": nodes,
                    "edges": [{"source": u, "target": v, "weight": d["weight"]} for u, v, d in G.edges(data=True)],
                    "summary": {"nodes": G.number_of_nodes(), "edges": G.number_of_edges(), "communities": len(set(cmap.values())), "modularity": q},
                    "algorithms": ["gds.louvain"] if self.gds else ["networkx.louvain"], "cypher": [TOPIC_EDGES.strip()]}
        return db.cached(key, build)

    def department_view(self, s, sc):
        from .graphs import layout
        key = ("neo.dgraph", sc.key())

        def build():
            params = dict(insts=sorted(sc.insts), depts=sorted(sc.depts) or None, y0=sc.y0, y1=sc.y1)
            sizes = {r["d"]: r["n"] for r in self.run(DEPT_SIZES, **params)}
            edges = self.run(DEPT_EDGES, **params)
            G = nx.Graph()
            G.add_nodes_from(sizes)
            for e in edges:
                G.add_edge(e["a"], e["b"], weight=e["w"])
            pos = layout(G, None, iterations=160)
            multi = len(sc.insts) > 1
            nodes = []
            for d in G.nodes():
                dep = s.dept[d]
                inst = s.inst[dep["inst_id"]]
                nodes.append({"id": d, "name": dep["name"], "code": dep["code"], "field": dep["field"], "inst": inst["short"], "brand": inst["brand"],
                              "label": f"{dep['code']} · {inst['short']}" if multi else dep["code"], "pubs": sizes.get(d, 0),
                              "x": pos[d][0], "y": pos[d][1], "degree": G.degree(d)})
            return {"mode": "departments", "engine": "neo4j", "nodes": nodes,
                    "edges": [{"source": u, "target": v, "weight": d["weight"],
                               "kind": "cross_inst" if s.dept[u]["inst_id"] != s.dept[v]["inst_id"] else "inter_dept"} for u, v, d in G.edges(data=True)],
                    "summary": {"nodes": G.number_of_nodes(), "edges": G.number_of_edges()}, "cypher": [DEPT_EDGES.strip()]}
        return db.cached(key, build)

    def institution_view(self, s, sc, include_external=True, top_external=18):
        from .graphs import layout
        key = ("neo.igraph", sc.key(), include_external)

        def build():
            params = dict(insts=sorted(sc.insts), y0=sc.y0, y1=sc.y1)
            pubs_by_inst = {r["i"]: r["n"] for r in self.run(INST_SIZES, **params)}
            G = nx.Graph()
            for e in self.run(INST_EDGES, **params):
                G.add_edge(f"i{e['a']}", f"i{e['b']}", weight=e["w"])
            ext_rows = self.run(ORG_EDGES, **params) if include_external else []
            tot = Counter()
            country = {}
            for r in ext_rows:
                tot[r["o"]] += r["w"]
                country[r["o"]] = r["country"]
            keep = {o for o, _ in tot.most_common(top_external)}
            for r in ext_rows:
                if r["o"] in keep:
                    G.add_edge(f"i{r['i']}", f"x{r['o']}", weight=r["w"])
            for i in sc.insts:
                if not s.inst[i]["external"]:
                    G.add_node(f"i{i}")
            pos = layout(G, None, iterations=160)
            nodes = []
            for v in G.nodes():
                if v.startswith("i"):
                    inst = s.inst[int(v[1:])]
                    nodes.append({"id": v, "kind": "rice", "name": inst["name"], "short": inst["short"], "brand": inst["brand"],
                                  "pubs": pubs_by_inst.get(inst["id"], 0), "ref": inst["id"], "x": pos[v][0], "y": pos[v][1], "degree": G.degree(v)})
                else:
                    nodes.append({"id": v, "kind": "external", "name": v[1:], "short": v[1:], "country": country.get(v[1:]),
                                  "pubs": tot[v[1:]], "x": pos[v][0], "y": pos[v][1], "degree": G.degree(v)})
            return {"mode": "institutions", "engine": "neo4j", "nodes": nodes,
                    "edges": [{"source": u, "target": v, "weight": d["weight"]} for u, v, d in G.edges(data=True)],
                    "summary": {"nodes": G.number_of_nodes(), "edges": G.number_of_edges(),
                                "rice": sum(1 for n in nodes if n["kind"] == "rice"), "external": sum(1 for n in nodes if n["kind"] == "external")},
                    "cypher": [INST_EDGES.strip(), ORG_EDGES.strip()]}
        return db.cached(key, build)

    def mentorship_view(self, s, sc):
        from .graphs import layout
        key = ("neo.mgraph", sc.key())

        def build():
            rows = self.run(MENTOR_EDGES, insts=sorted(sc.insts), depts=sorted(sc.depts) or None)
            G = nx.Graph()
            for r in rows:
                G.add_edge(r["s"], r["t"], weight=1)
            pos = layout(G, None, iterations=120)
            nodes = []
            for v in G.nodes():
                p = s.people[v]
                d = s.dept.get(p["dept_id"])
                nodes.append({"id": v, "name": p["name"], "role": p["role"], "designation": p["designation"], "dept": d["code"] if d else "",
                              "inst": s.inst[p["inst_id"]]["short"], "students": len(p["students"]), "x": pos[v][0], "y": pos[v][1], "degree": G.degree(v)})
            sup = [n for n in nodes if n["students"]]
            return {"mode": "mentorship", "engine": "neo4j", "nodes": nodes,
                    "edges": [{"source": r["s"], "target": r["t"], "weight": 1} for r in rows],
                    "summary": {"nodes": G.number_of_nodes(), "edges": G.number_of_edges(), "supervisors": len(sup),
                                "avg_load": round(sum(n["students"] for n in sup) / max(1, len(sup)), 2)},
                    "cypher": [MENTOR_EDGES.strip()]}
        return db.cached(key, build)

    def ego_view(self, s, pid, insts, y0, y1, depth=1):
        from .graphs import layout
        params = dict(id=pid, insts=sorted(insts), y0=y0, y1=y1)
        co = self.run(EGO_COAUTHORS, **params)
        co_ids = [r["id"] for r in co]
        orgs = self.run(EGO_ORGS, **params)
        topics = self.run(EGO_TOPICS, co=co_ids, **params)
        projects = self.run(EGO_PROJECTS, co=co_ids, **params)
        person = s.people[pid]
        G = nx.Graph()
        me = f"p{pid}"
        nodes = {me: {"id": me, "kind": "person", "name": person["name"], "ref": pid, "focus": True,
                      "inst": s.inst[person["inst_id"]]["short"], "brand": s.inst[person["inst_id"]]["brand"]}}
        G.add_node(me)
        for r in co:
            q = s.people[r["id"]]
            k = f"p{r['id']}"
            nodes[k] = {"id": k, "kind": "person", "name": q["name"], "ref": r["id"], "inst": s.inst[q["inst_id"]]["short"],
                        "brand": s.inst[q["inst_id"]]["brand"], "role": q["role"]}
            G.add_edge(me, k, weight=r["w"])
        for r in orgs:
            k = f"o{r['o']}"
            nodes[k] = {"id": k, "kind": "org", "name": r["o"]}
            G.add_edge(me, k, weight=r["w"])
        for r in topics:
            k = f"t{r['t']}"
            nodes[k] = {"id": k, "kind": "topic", "name": r["t"]}
            G.add_edge(me, k, weight=2)
            for c in r["people"]:
                G.add_edge(f"p{c}", k, weight=1)
        for r in projects:
            k = f"j{r['id']}"
            nodes[k] = {"id": k, "kind": "project", "name": r["title"], "ref": r["id"], "agency": r["agency"]}
            G.add_edge(me, k, weight=2)
            for c in r["people"]:
                G.add_edge(f"p{c}", k, weight=1)
        if depth > 1 and co_ids:
            for r in self.run(EGO_RING, co=co_ids[:25]):
                G.add_edge(f"p{r['a']}", f"p{r['b']}", weight=1)
        for v in G.nodes():
            nodes[v]["degree"] = G.degree(v)
        pos = layout(G, None, iterations=140)
        out = []
        for v in G.nodes():
            nd = nodes[v]
            nd["x"], nd["y"] = pos[v]
            out.append(nd)
        return {"mode": "ego", "engine": "neo4j", "nodes": out,
                "edges": [{"source": u, "target": v, "weight": d["weight"]} for u, v, d in G.edges(data=True)],
                "summary": {"nodes": G.number_of_nodes(), "edges": G.number_of_edges(), "coauthors": len(co)},
                "cypher": [EGO_COAUTHORS.strip(), EGO_TOPICS.strip()]}

    def shortest_path(self, s, insts, a, b):
        r = self.run(SHORTEST, a=a, b=b, insts=sorted(insts))
        if not r:
            return {"path": [], "error": "No chain of collaborations connects these two people yet.", "engine": "neo4j"}
        ids = r[0]["ids"]
        routes = r[0]["routes"]
        pairs = [[u, v] for u, v in zip(ids, ids[1:])]
        ev = {(x["a"], x["b"]): x for x in self.run(PATH_EVIDENCE, pairs=pairs)}
        steps = []
        for u, v in pairs:
            e = ev.get((u, v))
            steps.append({"from": u, "to": v, "pubs": e["n"] if e else 0,
                          "example": {"id": e["id"], "title": e["title"], "year": e["year"]} if e and e["id"] else None})
        people = [{"id": v, "name": s.people[v]["name"], "inst": s.inst[s.people[v]["inst_id"]]["short"],
                   "dept": (s.dept.get(s.people[v]["dept_id"]) or {}).get("code", ""), "role": s.people[v]["role"]} for v in ids]
        return {"path": people, "steps": steps, "hops": len(ids) - 1, "routes": routes, "engine": "neo4j", "cypher": [SHORTEST.strip()]}

    # ── link prediction features for recommendations ─────────────────────────
    def link_features(self, pid, cands, insts):
        rows = self.run(LINK_FEATURES, id=pid, cands=list(cands), insts=sorted(insts))
        return {r["id"]: {"mutual": r["mutual"], "aa": r["aa"] or 0.0, "jaccard": r["jaccard"] or 0.0, "shared": r["shared"]} for r in rows}

    def fof_candidates(self, pid, insts, limit=150):
        return [r["id"] for r in self.run(FOF, id=pid, insts=sorted(insts), lim=limit)]

    # ── curated graph analyses ───────────────────────────────────────────────
    def analyses(self, own, visible, y0, y1):
        params = dict(own=sorted(own), insts=sorted(visible), y0=y0, y1=y1)
        out = []
        for a in ANALYSES:
            if a.get("gds") and not self.gds:  # no GDS (e.g. AuraDB Free): the pure-Cypher Jaccard version
                a = {**a, "cypher": SIM_CYPHER, "uses": "Cypher Jaccard", "gds": None,
                     "why": "Jaccard overlap of research interests, computed in Cypher, finds overlap people miss."}
            try:
                if a.get("gds") == "similarity":
                    rows = self._similarity(params)
                else:
                    rows = self.run(a["cypher"], **params)
                out.append({k: a[k] for k in ("key", "title", "question", "why", "columns")} | {"rows": rows, "cypher": a["cypher"].strip(),
                                                                                                   "uses": a.get("uses", "Cypher")})
            except Exception as e:  # noqa: BLE001
                out.append({k: a[k] for k in ("key", "title", "question", "why", "columns")} | {"rows": [], "error": str(e)[:200],
                                                                                                   "cypher": a["cypher"].strip(), "uses": a.get("uses", "Cypher")})
        return out

    def _similarity(self, params):
        name = "rice_" + uuid.uuid4().hex[:12]
        self.run(SIM_PROJECT, write=True, g=name, **params)
        try:
            return self.run(SIM_STREAM, g=name)
        finally:
            self._drop(name)


# ── Cypher ───────────────────────────────────────────────────────────────────
PEOPLE_EDGES = """
CALL () {
  MATCH (a:Person)-[:AUTHORED]->(p:Publication)<-[:AUTHORED]-(b:Person)
  WHERE a.id < b.id AND p.status = 'verified' AND p.year >= $y0 AND p.year <= $y1
    AND a.inst_id IN $insts AND b.inst_id IN $insts AND a.role IN $roles AND b.role IN $roles
    AND ($depts IS NULL OR (a.dept_id IN $depts AND b.dept_id IN $depts))
  RETURN a, b, 1.0 AS w, 1 AS pub, 0 AS prj
  UNION ALL
  MATCH (a:Person)-[:MEMBER_OF]->(j:Project)<-[:MEMBER_OF]-(b:Person)
  WHERE a.id < b.id AND j.status = 'verified' AND j.stage IN ['ongoing', 'completed']
    AND j.start_year >= $y0 AND j.start_year <= $y1
    AND a.inst_id IN $insts AND b.inst_id IN $insts AND a.role IN $roles AND b.role IN $roles
    AND ($depts IS NULL OR (a.dept_id IN $depts AND b.dept_id IN $depts))
  RETURN a, b, 0.5 AS w, 0 AS pub, 1 AS prj
}
WITH a, b, sum(w) AS weight, sum(pub) AS pubs, sum(prj) AS projects
WHERE weight >= $min_w"""

TOPIC_SCOPE = """p.status = 'verified' AND p.year >= $y0 AND p.year <= $y1
  AND EXISTS { MATCH (p)<-[:AUTHORED]-(x:Person) WHERE x.inst_id IN $insts AND ($depts IS NULL OR x.dept_id IN $depts) }"""
TOPIC_COUNTS = f"""
MATCH (p:Publication)-[:ABOUT]->(t:Topic)
WHERE {TOPIC_SCOPE}
RETURN t.name AS topic, count(p) AS count,
       sum(CASE WHEN p.year > $y1 - 3 THEN 1 ELSE 0 END) AS recent,
       sum(CASE WHEN p.year > $y1 - 6 AND p.year <= $y1 - 3 THEN 1 ELSE 0 END) AS earlier"""
TOPIC_EDGES = f"""
MATCH (a:Topic)<-[:ABOUT]-(p:Publication)-[:ABOUT]->(b:Topic)
WHERE a.name < b.name AND a.name IN $keep AND b.name IN $keep AND {TOPIC_SCOPE}
WITH a, b, toFloat(count(p)) AS weight
WHERE weight >= 2"""

REL_STREAM = """
CALL gds.graph.relationshipProperties.stream($g, ['weight', 'pubs', 'projects'])
YIELD sourceNodeId, targetNodeId, relationshipProperty, propertyValue
WITH gds.util.asNode(sourceNodeId).id AS s, gds.util.asNode(targetNodeId).id AS t,
     collect([relationshipProperty, propertyValue]) AS kv
RETURN s, t, [x IN kv WHERE x[0] = 'weight'][0][1] AS weight, [x IN kv WHERE x[0] = 'pubs'][0][1] AS pubs,
       [x IN kv WHERE x[0] = 'projects'][0][1] AS projects"""

PUB_SCOPE = "p.status = 'verified' AND p.year >= $y0 AND p.year <= $y1"
DEPT_SIZES = f"""
MATCH (d:Department)<-[:WORKS_IN]-(a:Person)-[:AUTHORED]->(p:Publication)
WHERE {PUB_SCOPE} AND d.inst_id IN $insts AND ($depts IS NULL OR d.id IN $depts)
RETURN d.id AS d, count(DISTINCT p) AS n"""
DEPT_EDGES = f"""
MATCH (d1:Department)<-[:WORKS_IN]-(:Person)-[:AUTHORED]->(p:Publication)<-[:AUTHORED]-(:Person)-[:WORKS_IN]->(d2:Department)
WHERE d1.id < d2.id AND {PUB_SCOPE} AND d1.inst_id IN $insts AND d2.inst_id IN $insts
  AND ($depts IS NULL OR (d1.id IN $depts OR d2.id IN $depts))
RETURN d1.id AS a, d2.id AS b, count(DISTINCT p) AS w"""
INST_SIZES = f"""
MATCH (i:Institution)<-[:AFFILIATED_WITH]-(:Person)-[:AUTHORED]->(p:Publication)
WHERE {PUB_SCOPE}
  AND EXISTS {{ MATCH (p)<-[:AUTHORED]-(x:Person) WHERE x.inst_id IN $insts }}
RETURN i.id AS i, count(DISTINCT p) AS n"""
INST_EDGES = f"""
MATCH (i1:Institution)<-[:AFFILIATED_WITH]-(:Person)-[:AUTHORED]->(p:Publication)<-[:AUTHORED]-(:Person)-[:AFFILIATED_WITH]->(i2:Institution)
WHERE i1.id < i2.id AND {PUB_SCOPE}
  AND EXISTS {{ MATCH (p)<-[:AUTHORED]-(x:Person) WHERE x.inst_id IN $insts }}
RETURN i1.id AS a, i2.id AS b, count(DISTINCT p) AS w"""
ORG_EDGES = f"""
MATCH (i:Institution)<-[:AFFILIATED_WITH]-(:Person)-[:AUTHORED]->(p:Publication)-[:WITH_PARTNER]->(o:Organisation)
WHERE i.id IN $insts AND {PUB_SCOPE}
RETURN i.id AS i, o.name AS o, o.country AS country, count(DISTINCT p) AS w"""
MENTOR_EDGES = """
MATCH (s:Person)-[:SUPERVISES]->(t:Person)
WHERE s.inst_id IN $insts AND t.inst_id IN $insts AND ($depts IS NULL OR t.dept_id IN $depts)
RETURN s.id AS s, t.id AS t"""
EGO_COAUTHORS = """
MATCH (me:Person {id: $id})-[:AUTHORED]->(p:Publication)<-[:AUTHORED]-(c:Person)
WHERE p.status = 'verified' AND p.year >= $y0 AND p.year <= $y1 AND c.inst_id IN $insts
RETURN c.id AS id, count(p) AS w ORDER BY w DESC LIMIT 40"""
EGO_ORGS = """
MATCH (me:Person {id: $id})-[:AUTHORED]->(p:Publication)-[:WITH_PARTNER]->(o:Organisation)
WHERE p.status = 'verified' AND p.year >= $y0 AND p.year <= $y1
RETURN o.name AS o, count(p) AS w ORDER BY w DESC LIMIT 15"""
EGO_TOPICS = """
MATCH (me:Person {id: $id})-[:INTERESTED_IN]->(t:Topic)
OPTIONAL MATCH (c:Person)-[:INTERESTED_IN]->(t) WHERE c.id IN $co
RETURN t.name AS t, collect(c.id) AS people"""
EGO_PROJECTS = """
MATCH (me:Person {id: $id})-[:MEMBER_OF]->(j:Project)
WHERE j.stage IN ['ongoing', 'completed']
OPTIONAL MATCH (j)<-[:MEMBER_OF]-(m:Person) WHERE m.id IN $co
RETURN j.id AS id, j.title AS title, j.agency AS agency, collect(m.id) AS people"""
EGO_RING = """
MATCH (a:Person)-[:COLLABORATES_WITH]-(b:Person)
WHERE a.id IN $co AND b.id IN $co AND a.id < b.id
RETURN a.id AS a, b.id AS b"""
SHORTEST = """
MATCH (a:Person {id: $a}), (b:Person {id: $b})
MATCH path = shortestPath((a)-[:COLLABORATES_WITH*..12]-(b))
WHERE all(n IN nodes(path) WHERE n.inst_id IN $insts)
WITH a, b, [n IN nodes(path) | n.id] AS ids, length(path) AS hops
OPTIONAL MATCH alt = allShortestPaths((a)-[:COLLABORATES_WITH*..12]-(b))
WHERE length(alt) = hops AND all(n IN nodes(alt) WHERE n.inst_id IN $insts)
RETURN ids, count(alt) AS routes"""
PATH_EVIDENCE = """
UNWIND $pairs AS pr
MATCH (x:Person {id: pr[0]})-[:AUTHORED]->(p:Publication {status: 'verified'})<-[:AUTHORED]-(y:Person {id: pr[1]})
WITH pr, p ORDER BY p.year DESC
WITH pr, collect(p) AS ps
RETURN pr[0] AS a, pr[1] AS b, size(ps) AS n, ps[0].id AS id, ps[0].title AS title, ps[0].year AS year"""
LINK_FEATURES = """
// Adamic-Adar over shared co-authors + Jaccard over topic profiles (interests and paper topics)
MATCH (me:Person {id: $id})
WITH me, reduce(acc = [], x IN COLLECT { MATCH (me)-[:INTERESTED_IN]->(t:Topic) RETURN t.name }
                              + COLLECT { MATCH (me)-[:AUTHORED]->(:Publication {status: 'verified'})-[:ABOUT]->(t:Topic) RETURN t.name }
                | CASE WHEN x IN acc THEN acc ELSE acc + x END) AS mine
UNWIND $cands AS cid
MATCH (c:Person {id: cid}) WHERE c.inst_id IN $insts
OPTIONAL MATCH (me)-[:COLLABORATES_WITH]-(m:Person)-[:COLLABORATES_WITH]-(c)
WITH me, c, mine, m, CASE WHEN m IS NULL THEN 0 ELSE COUNT { (m)-[:COLLABORATES_WITH]-() } END AS deg
WITH c, mine, collect(m.id) AS mutual,
     sum(CASE WHEN m IS NULL THEN 0.0 ELSE 1.0 / log(CASE WHEN deg < 2 THEN 2.0 ELSE toFloat(deg) END) END) AS aa
WITH c, mine, mutual, aa,
     reduce(acc = [], x IN COLLECT { MATCH (c)-[:INTERESTED_IN]->(t:Topic) RETURN t.name }
                         + COLLECT { MATCH (c)-[:AUTHORED]->(:Publication {status: 'verified'})-[:ABOUT]->(t:Topic) RETURN t.name }
            | CASE WHEN x IN acc THEN acc ELSE acc + x END) AS theirs
WITH c, mutual, aa, [t IN mine WHERE t IN theirs] AS inter, size(mine) + size([t IN theirs WHERE NOT t IN mine]) AS uni
RETURN c.id AS id, mutual, aa, CASE WHEN uni = 0 THEN 0.0 ELSE toFloat(size(inter)) / uni END AS jaccard, inter[..4] AS shared"""
FOF = """
MATCH (me:Person {id: $id})-[:COLLABORATES_WITH]-(:Person)-[:COLLABORATES_WITH]-(c:Person)
WHERE c <> me AND c.inst_id IN $insts AND c.role IN ['faculty', 'hod', 'scholar']
  AND NOT (me)-[:COLLABORATES_WITH]-(c)
RETURN c.id AS id, count(*) AS paths ORDER BY paths DESC LIMIT $lim"""

ANALYSES = [
    {"key": "triadic", "title": "Close, but never published together",
     "question": "Which faculty pairs share two or more co-authors yet have no joint paper?",
     "why": "Triadic closure: people with mutual collaborators are the likeliest next collaborations.",
     "columns": [["a", "Researcher"], ["b", "Researcher"], ["mutual", "Mutual co-authors"], ["shared_topics", "Shared interests"]],
     "cypher": """
MATCH (a:Person)-[:COLLABORATES_WITH]-(m:Person)-[:COLLABORATES_WITH]-(b:Person)
WHERE a.id < b.id AND a.inst_id IN $own AND b.inst_id IN $insts
  AND a.role IN ['faculty', 'hod'] AND b.role IN ['faculty', 'hod']
  AND NOT (a)-[:COLLABORATES_WITH]-(b)
WITH a, b, count(DISTINCT m) AS mutual WHERE mutual >= 2
RETURN a.id AS a_id, a.name AS a, b.id AS b_id, b.name AS b, mutual,
       COLLECT { MATCH (a)-[:INTERESTED_IN]->(t:Topic)<-[:INTERESTED_IN]-(b) RETURN t.name }[..3] AS shared_topics
ORDER BY mutual DESC, size(shared_topics) DESC LIMIT 12"""},
    {"key": "bridges", "title": "Topics that bridge departments",
     "question": "Which research topics bring the most departments together on the same papers?",
     "why": "Bridge topics are natural anchors for interdisciplinary centres and joint proposals.",
     "columns": [["topic", "Topic"], ["departments", "Departments"], ["papers", "Papers"], ["codes", "Which"]],
     "cypher": """
MATCH (t:Topic)<-[:ABOUT]-(p:Publication)<-[:AUTHORED]-(a:Person)-[:WORKS_IN]->(d:Department)
WHERE p.status = 'verified' AND p.year >= $y0 AND p.year <= $y1 AND a.inst_id IN $own
WITH t, count(DISTINCT d) AS departments, count(DISTINCT p) AS papers, collect(DISTINCT d.code)[..6] AS codes
WHERE departments >= 2
RETURN t.name AS topic, departments, papers, codes
ORDER BY departments DESC, papers DESC LIMIT 12"""},
    {"key": "spanners", "title": "Most interdisciplinary researchers",
     "question": "Whose co-authors come from the widest range of departments?",
     "why": "Boundary-spanners carry ideas between groups — good choices for centre leads and mentors.",
     "columns": [["name", "Researcher"], ["departments", "Departments reached"], ["coauthors", "Co-authors"], ["codes", "Which"]],
     "cypher": """
MATCH (a:Person)-[:COLLABORATES_WITH]-(b:Person)-[:WORKS_IN]->(d:Department)
WHERE a.inst_id IN $own AND a.role IN ['faculty', 'hod'] AND b.inst_id IN $insts
WITH a, count(DISTINCT d) AS departments, count(DISTINCT b) AS coauthors, collect(DISTINCT d.code)[..6] AS codes
RETURN a.id AS id, a.name AS name, departments, coauthors, codes
ORDER BY departments DESC, coauthors DESC LIMIT 12"""},
    {"key": "similar", "title": "Twins who haven't met",
     "question": "Which faculty have near-identical topic profiles but have never co-authored?",
     "why": "GDS node similarity (Jaccard) over the Person→Topic graph finds overlap people miss.", "gds": "similarity",
     "uses": "GDS nodeSimilarity",
     "columns": [["a", "Researcher"], ["b", "Researcher"], ["similarity", "Similarity"], ["a_inst", "Institutions"]],
     "cypher": """
// project Person -[:INTERESTED_IN]-> Topic for faculty the caller can see
MATCH (a:Person)-[:INTERESTED_IN]->(t:Topic)
WHERE a.inst_id IN $insts AND a.role IN ['faculty', 'hod']
WITH gds.graph.project($g, a, t) AS g RETURN g.nodeCount;
CALL gds.nodeSimilarity.stream($g, {topK: 2, similarityCutoff: 0.6})
YIELD node1, node2, similarity
WITH gds.util.asNode(node1) AS a, gds.util.asNode(node2) AS b, similarity
WHERE a.id < b.id AND NOT (a)-[:COLLABORATES_WITH]-(b) AND (a.inst_id IN $own OR b.inst_id IN $own)
RETURN a.name AS a, b.name AS b, round(similarity, 2) AS similarity"""},
    {"key": "partners", "title": "Partners who reach across campus",
     "question": "Which outside organisations work with the most of our departments?",
     "why": "Organisations already linked to several departments are candidates for an institutional MoU.",
     "columns": [["organisation", "Organisation"], ["country", "Country"], ["departments", "Departments"], ["papers", "Papers"]],
     "cypher": """
MATCH (o:Organisation)<-[:WITH_PARTNER]-(p:Publication)<-[:AUTHORED]-(a:Person)-[:WORKS_IN]->(d:Department)
WHERE p.status = 'verified' AND p.year >= $y0 AND p.year <= $y1 AND a.inst_id IN $own
RETURN o.name AS organisation, o.country AS country, count(DISTINCT d) AS departments, count(DISTINCT p) AS papers
ORDER BY departments DESC, papers DESC LIMIT 12"""},
    {"key": "isolated", "title": "Thin in-house ties",
     "question": "Which faculty have at most one co-author inside the institution?",
     "why": "Isolation predicts drop-off. These colleagues benefit most from a mentor or a seed-grant pairing.",
     "columns": [["name", "Researcher"], ["dept", "Department"], ["inhouse", "In-house co-authors"], ["papers", "Verified papers"]],
     "cypher": """
MATCH (a:Person)
WHERE a.inst_id IN $own AND a.role IN ['faculty', 'hod']
WITH a, COUNT { MATCH (a)-[:COLLABORATES_WITH]-(b:Person) WHERE b.inst_id = a.inst_id AND b.role IN ['faculty', 'hod'] } AS inhouse
WHERE inhouse <= 1
OPTIONAL MATCH (a)-[:WORKS_IN]->(d:Department)
RETURN a.id AS id, a.name AS name, d.code AS dept, inhouse,
       COUNT { (a)-[:AUTHORED]->(:Publication {status: 'verified'}) } AS papers
ORDER BY inhouse, papers LIMIT 15"""},
    {"key": "new_links", "title": "Collaborations formed recently",
     "question": "Which pairs published together for the first time in the last two years?",
     "why": "New links show where seed grants, events and hiring are paying off.",
     "columns": [["a", "Researcher"], ["b", "Researcher"], ["first", "First joint year"], ["pubs", "Joint papers"], ["cross", "Across institutions"]],
     "cypher": """
MATCH (a:Person)-[r:COLLABORATES_WITH]-(b:Person)
WHERE a.id < b.id AND r.first >= $y1 - 1 AND r.pubs > 0
  AND (a.inst_id IN $own OR b.inst_id IN $own) AND a.inst_id IN $insts AND b.inst_id IN $insts
  AND a.role IN ['faculty', 'hod'] AND b.role IN ['faculty', 'hod']
RETURN a.id AS a_id, a.name AS a, b.id AS b_id, b.name AS b, r.first AS first, r.pubs AS pubs,
       a.inst_id <> b.inst_id AS cross
ORDER BY cross DESC, pubs DESC LIMIT 12"""},
    {"key": "funders", "title": "What each funder pays for",
     "question": "Which topics attract the most sanctioned money, and from whom?",
     "why": "Shows where the institution's funding strength really lies, agency by agency.",
     "columns": [["agency", "Agency"], ["topic", "Topic"], ["projects", "Projects"], ["lakh", "₹ lakh"]],
     "cypher": """
MATCH (g:Agency)<-[:FUNDED_BY]-(j:Project)-[:ABOUT]->(t:Topic)
WHERE j.stage IN ['ongoing', 'completed'] AND j.status = 'verified'
  AND EXISTS { MATCH (j)<-[:MEMBER_OF]-(m:Person) WHERE m.inst_id IN $own }
RETURN g.name AS agency, t.name AS topic, count(j) AS projects, round(sum(j.amount), 1) AS lakh
ORDER BY lakh DESC LIMIT 12"""},
]
SIM_PROJECT = """
MATCH (a:Person)-[:INTERESTED_IN]->(t:Topic)
WHERE a.inst_id IN $insts AND a.role IN ['faculty', 'hod']
WITH gds.graph.project($g, a, t) AS g
RETURN g.nodeCount AS n"""
SIM_STREAM = """
CALL gds.nodeSimilarity.stream($g, {topK: 2, similarityCutoff: 0.6, concurrency: 1})
YIELD node1, node2, similarity
WITH gds.util.asNode(node1) AS a, gds.util.asNode(node2) AS b, similarity
WHERE a.id < b.id AND NOT (a)-[:COLLABORATES_WITH]-(b)
WITH a, b, similarity
MATCH (ia:Institution {id: a.inst_id}), (ib:Institution {id: b.inst_id})
RETURN a.id AS a_id, a.name AS a, b.id AS b_id, b.name AS b, round(similarity, 2) AS similarity,
       ia.short + CASE WHEN ia <> ib THEN ' · ' + ib.short ELSE '' END AS a_inst
ORDER BY similarity DESC, a LIMIT 12"""


SIM_CYPHER = """
MATCH (a:Person)-[:INTERESTED_IN]->(t:Topic)<-[:INTERESTED_IN]-(b:Person)
WHERE a.id < b.id AND a.inst_id IN $insts AND b.inst_id IN $insts AND (a.inst_id IN $own OR b.inst_id IN $own)
  AND a.role IN ['faculty', 'hod'] AND b.role IN ['faculty', 'hod']
  AND NOT (a)-[:COLLABORATES_WITH]-(b)
WITH a, b, count(DISTINCT t) AS shared
WITH a, b, shared, COUNT { (a)-[:INTERESTED_IN]->(:Topic) } AS na, COUNT { (b)-[:INTERESTED_IN]->(:Topic) } AS nb
WITH a, b, toFloat(shared) / (na + nb - shared) AS similarity
WHERE similarity >= 0.6
MATCH (ia:Institution {id: a.inst_id}), (ib:Institution {id: b.inst_id})
RETURN a.id AS a_id, a.name AS a, b.id AS b_id, b.name AS b, round(similarity, 2) AS similarity,
       ia.short + CASE WHEN ia <> ib THEN ' · ' + ib.short ELSE '' END AS a_inst
ORDER BY similarity DESC, a LIMIT 12"""


def _nx_algorithms(G: nx.Graph) -> dict:
    """The GDS suite's equivalents in NetworkX, for Neo4j servers without the GDS plugin."""
    n = G.number_of_nodes()
    comms = nx.community.louvain_communities(G, weight="weight", seed=11)
    pr = nx.pagerank(G, weight="weight")
    btw = nx.betweenness_centrality(G, normalized=True, k=None if n <= 1500 else 600, seed=3)
    comp = {v: i for i, c in enumerate(nx.connected_components(G)) for v in c}
    return {"community": {v: i for i, c in enumerate(comms) for v in c}, "modularity": None,
            "degree": dict(G.degree()), "strength": dict(G.degree(weight="weight")),
            "pagerank": {v: s * n for v, s in pr.items()}, "betweenness": btw, "clustering": nx.clustering(G),
            "core": nx.core_number(G), "component": comp, "bridges": set(nx.articulation_points(G))}


def _path_stats(G):
    out = {}
    comps = list(nx.connected_components(G))
    if not comps:
        return out
    giant = max(comps, key=len)
    if 2 < len(giant) <= 2500:
        sub = G.subgraph(giant)
        sample = list(sub.nodes())[:: max(1, len(giant) // 60)]
        lens = []
        for v in sample:
            lens.extend(nx.single_source_shortest_path_length(sub, v).values())
        out["avg_path"] = round(sum(lens) / max(1, len(lens) - len(sample)), 2)
        out["diameter_est"] = max(lens) if lens else 0
    return out


def _payload(s):
    """Flatten the snapshot into UNWIND-able rows."""
    active = {pid: p for pid, p in s.people.items() if p["status"] == "active" and p["inst_id"] and p["role"] != "platform_admin"}
    P = defaultdict(list)
    P["insts"] = [{"id": i["id"], "code": i["code"], "name": i["name"], "short": i["short"], "share_level": i["share_level"],
                   "external": bool(i["external"]), "brand": i["brand"] or "", "city": i["city"] or ""} for i in s.inst.values()]
    P["depts"] = [{"id": d["id"], "code": d["code"], "name": d["name"], "field": d["field"] or "", "inst_id": d["inst_id"]} for d in s.dept.values()]
    P["people"] = [{k: v for k, v in {"id": p["id"], "name": p["name"], "role": p["role"], "designation": p["designation"] or "",
                                      "inst_id": p["inst_id"], "dept_id": p["dept_id"], "visibility": p["visibility"],
                                      "source": p.get("source") or "", "hue": p["hue"]}.items() if v is not None}
                   for p in active.values()]
    P["supervises"] = [{"s": p["supervisor_id"], "t": p["id"]} for p in active.values() if p.get("supervisor_id") in active]
    topics, orgs, venues = set(), {}, set()
    for p in active.values():
        for t in p["interests"]:
            topics.add(t)
            P["interests"].append({"p": p["id"], "t": t})
    collab = defaultdict(lambda: {"pubs": 0, "projects": 0, "years": []})
    for pub in s.pubs.values():
        if pub["status"] == "rejected":
            continue
        P["pubs"].append({"id": pub["id"], "title": pub["title"], "year": pub["year"], "kind": pub["kind"], "venue": pub["venue"] or "",
                          "quartile": pub["quartile"] or "", "citations": pub["citations"], "open_access": bool(pub["open_access"]),
                          "status": pub["status"], "visibility": pub["visibility"], "international": bool(pub["international"])})
        authors = [a for a in pub["authors"] if a in active]
        for pos, a in enumerate(authors):
            P["authored"].append({"p": a, "pub": pub["id"], "pos": pos})
        for k in dict.fromkeys(pub["keywords"]):
            topics.add(k)
            P["pub_topics"].append({"pub": pub["id"], "t": k})
        for g in pub["sdgs"]:
            P["pub_sdgs"].append({"pub": pub["id"], "g": g})
        if pub["venue"]:
            venues.add(pub["venue"])
            P["pub_venues"].append({"pub": pub["id"], "v": pub["venue"]})
        oc = Counter(e["affil"] for e in pub["ext"] if e.get("affil"))
        for e in pub["ext"]:
            if e.get("affil"):
                orgs[e["affil"]] = e.get("country") or "India"
        for o, n in oc.items():
            P["pub_orgs"].append({"pub": pub["id"], "o": o, "n": n})
        if pub["status"] == "verified":
            for i in range(len(authors)):
                for j in range(i + 1, len(authors)):
                    a, b = sorted((authors[i], authors[j]))
                    collab[(a, b)]["pubs"] += 1
                    collab[(a, b)]["years"].append(pub["year"])
    agencies = {}
    for pr in s.projects.values():
        P["projects"].append({"id": pr["id"], "title": pr["title"], "agency": pr["agency"] or "", "scheme": pr["scheme"] or "",
                              "sector": pr["sector"] or "", "amount": float(pr["amount"] or 0), "start_year": pr["start_year"],
                              "end_year": pr["end_year"], "stage": pr["stage"], "status": pr["status"]})
        if pr["agency"]:
            agencies[pr["agency"]] = pr["sector"] or ""
            P["proj_agency"].append({"j": pr["id"], "a": pr["agency"], "scheme": pr["scheme"] or ""})
        members = [m for m in pr["members"] if m["id"] in active]
        for m in members:
            P["members"].append({"p": m["id"], "j": pr["id"], "role": m["role"]})
        for k in pr["keywords"]:
            topics.add(k)
            P["proj_topics"].append({"j": pr["id"], "t": k})
        if pr["stage"] in ("ongoing", "completed") and pr["status"] == "verified":
            ids = [m["id"] for m in members]
            for i in range(len(ids)):
                for j in range(i + 1, len(ids)):
                    a, b = sorted((ids[i], ids[j]))
                    collab[(a, b)]["projects"] += 1
                    collab[(a, b)]["years"].append(pr["start_year"])
    for pt in s.patents.values():
        P["patents"].append({"id": pt["id"], "title": pt["title"], "stage": pt["stage"], "year": pt["year"], "status": pt["status"],
                             "number": pt["number"] or ""})
        for i in pt["inventors"]:
            if i in active:
                P["inventors"].append({"p": i, "x": pt["id"]})
        for k in pt["keywords"]:
            topics.add(k)
            P["pat_topics"].append({"x": pt["id"], "t": k})
    P["topics"] = sorted(topics)
    P["orgs"] = [{"name": o, "country": c} for o, c in sorted(orgs.items())]
    P["venues"] = sorted(venues)
    P["sdgs"] = [{"goal": g, "name": n} for g, n in SDG_NAMES.items()]
    P["agencies"] = [{"name": a, "sector": sct} for a, sct in sorted(agencies.items())]
    P["collab"] = [{"a": a, "b": b, "pubs": v["pubs"], "projects": v["projects"], "weight": v["pubs"] + 0.5 * v["projects"],
                    "first": min(v["years"]), "last": max(v["years"])} for (a, b), v in collab.items()]
    con = db.connect()
    try:
        P["requests"] = [{"a": r["from_id"], "b": r["to_id"], "status": r["status"], "topic": r["topic"] or ""}
                         for r in db.rows(con, "SELECT from_id, to_id, status, topic FROM collab_requests")
                         if r["from_id"] in active and r["to_id"] in active]
    finally:
        con.close()
    return P


NEO = Neo()
WARMERS: list = []  # callables run once after the first successful sync (cache warm-up)


def _port_open(host="127.0.0.1", port=7697):
    try:
        with socket.create_connection((host, port), timeout=1.0):
            return True
    except OSError:
        return False


def start_background(autostart=True):
    """Connect (starting the bundled Neo4j if needed) and keep the graph in sync, off the request path."""
    if ENGINE == "networkx":
        return

    def loop():
        home = ROOT / "neo4j"
        if autostart and not _port_open() and (home / "rice-neo4j.json").exists():
            try:
                from tools.neo4j_ctl import start as start_neo4j  # type: ignore
                NEO.state = "starting"
                start_neo4j(wait=False)
            except Exception as e:  # noqa: BLE001
                NEO.error = f"Couldn't start the bundled Neo4j: {e}"
        if not NEO.connect(wait=120):
            return
        warmed = False
        while True:
            try:
                if NEO.synced != db.version():
                    NEO.ensure_synced()
                if not warmed and NEO.synced >= 0:
                    warmed = True
                    for fn in WARMERS:
                        fn()
            except Exception as e:  # noqa: BLE001
                NEO.error = f"Sync failed: {str(e)[:200]}"
                log.exception("Neo4j sync failed")
                if not _port_open():
                    NEO.ok, NEO.state = False, "unreachable"
                    NEO.connect(wait=60)
            time.sleep(2)

    threading.Thread(target=loop, name="rice-neo4j", daemon=True).start()


def active():
    """The Neo4j engine when connected and synced, else None (callers fall back to NetworkX)."""
    if not NEO.ok or NEO.synced < 0:  # still starting up — don't make the request wait for the first build
        return None
    try:
        NEO.ensure_synced(timeout=25)
    except Exception as e:  # noqa: BLE001
        NEO.error = str(e)[:200]
        return None
    return NEO if NEO.synced >= 0 else None
