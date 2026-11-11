# RICE — Research Intelligence & Collaboration Engine

RICE is a multi-institution research-intelligence service. Each college or university
gets its own space where every paper, project, patent and person becomes part of one
verified **knowledge graph in Neo4j**, with analytics, collaborator discovery and
NAAC / NIRF-ready reports. Institutions decide who sees what, and how much they share with
the rest of the network.

It replaces the original single-page SciVal collaboration viewer (`D:\Kernels\RICE`).

## Run it

```bat
RICE.bat
```

or by hand:

```bat
python tools\neo4j_ctl.py start                       :: graph database (bolt 7697, browser 7484)
python -m uvicorn server.main:app --port 8320         :: RICE at http://127.0.0.1:8320
```

The server also starts the bundled Neo4j by itself if it isn't running
(`RICE_NEO4J_AUTOSTART=0` turns that off). If Neo4j is unreachable, RICE keeps working on
its in-memory engine (NetworkX) and shows that in the UI.

First time on a new machine:

```bat
pip install -r requirements.txt
python -m server.seed            :: demo database (6 fictional institutions)
python tools\setup_neo4j.py      :: unpacks Neo4j Community + GDS into .\neo4j, sets a password
```

`setup_neo4j.py` expects `neo4j\_dist\neo4j-community-<version>-windows.zip`
(from neo4j.com/deployment-center) and finds Java 21 and the Graph Data Science jar in
Neo4j Desktop's cache, or in `RICE_JAVA_HOME` / `RICE_GDS_JAR`. Neo4j **Community** (GPLv3)
plus GDS community features are used deliberately: they are free for a commercial service.
The Enterprise build that Neo4j Desktop caches is evaluation-licensed, so RICE doesn't use it.

## Demo sign-in

The sign-in page lists one-click demo roles. All seeded accounts also accept the password
in `RICE_DEMO_PASSWORD` (default `rice-demo-2026`). Turn demo sign-in off with `RICE_DEMO=0`.

| Role | Email |
|---|---|
| RICE platform team | admin@rice.demo |
| Dean (Research), Kaveri University | research.cell@kavu.demo |
| Head of CSE, Kaveri University | hod.cse@kavu.demo |
| Professor | prof@kavu.demo |
| PhD scholar | scholar@kavu.demo |
| Student | student@kavu.demo |
| Industry partner | partner@rice.demo |
| Admin, Western Ghats Inst. of Technology | admin@wgit.demo |

All six institutions and their people, papers and grants are **generated demo data**.
The SciVal export in `samples/` is imported as *tracked* institutions: real names and
Scopus links only, nothing invented about them.

## What's inside

**Roles & control.** Platform team → institution admin → HoD → faculty / staff / scholar /
student / external partner. Each institution edits its own permission matrix, approves
joins, verifies records (or lets HoDs verify their department), and sets its sharing level:
`private`, `summary` (benchmarking only), `network` (profiles + verified research) or
`public` (adds a public showcase). Sharing is reciprocal: you see peers at most at the
level you share. Every change lands in the audit log.

**Neo4j knowledge graph.** SQLite is the system of record. The graph is rebuilt in Neo4j
on every change, in one transaction. Nodes: `Institution, Department, Person, Publication,
Project, Patent, Topic, Organisation, Agency, Venue, SDG`. Relationships include `AUTHORED`,
`COLLABORATES_WITH` (weighted, first/last year), `SUPERVISES`, `INTERESTED_IN`, `ABOUT`,
`MEMBER_OF`, `FUNDED_BY`, `INVENTED`, `WITH_PARTNER`, `SUPPORTS`, `REQUESTED_COLLAB`.

**Graph analysis (all in Neo4j / GDS).**
- Graph Explorer lenses: people, departments, institutions + partners, topics, mentorship,
  and a per-person knowledge graph.
- Louvain communities, PageRank, exact betweenness, degree / strength, local clustering,
  k-core, articulation points (bridges) and WCC, on a scoped in-memory GDS projection.
- Shortest collaboration path with route count and evidence papers (Cypher `shortestPath`).
- Collaborator suggestions: friends-of-friends candidates, Adamic-Adar and topic-Jaccard
  computed in Cypher, blended with TF-IDF text similarity.
- Eight curated "graph questions", with their Cypher shown in the app:
  - triadic closure
  - topics that bridge departments
  - boundary-spanning researchers
  - GDS node-similarity "twins"
  - campus-wide partners
  - thin in-house ties
  - newly formed links
  - what each funder pays for

GDS results are checked against NetworkX: degree, strength, clustering, core number and
articulation points match exactly, and betweenness matches NetworkX's scale.

**Analytics.**
- Output, impact (h-index, i10, field-weighted citation impact against the platform), topics
  (heatmap, rising and cooling, auto-tagged SDGs), funding (agencies, success rates, Sankey).
- People (distribution, Gini, inactive list, supervision load), collaboration reach, a
  department scorecard, and benchmarking with a NIRF-style RICE score.
- Plain-language findings with highlighted figures.

**Everyday flows.**
- Add or import research: forms, Excel/CSV templates, SciVal exports, ORCID → OpenAlex.
- Verification queue with bulk approve.
- Opportunities board and collaboration requests.
- Expert finder and proposal team builder.
- NAAC criterion 3 pack, NIRF inputs and an annual report (print to PDF), CSV exports.
- Tenant onboarding for the platform team.

**Design.** Five bright themes plus each campus's own brand colour, the "research highlighter"
look, and responsive down to phone width.

## Layout

```
server/  main.py (API) · neo.py (Neo4j + GDS) · graphs.py (NetworkX fallback + layout)
         analytics.py · intel.py (search, experts, recommendations, teams) · reports.py
         importers.py · seed.py · catalog.py · security.py · db.py
web/     index.html · assets/css/rice.css · assets/js/{app,api,ui,charts}.js · assets/js/pages/*
tools/   setup_neo4j.py · neo4j_ctl.py
```
