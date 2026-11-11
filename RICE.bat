@echo off
REM RICE — Research Intelligence & Collaboration Engine
REM Starts the bundled Neo4j (if set up) and the RICE server, then opens the browser.
cd /d "%~dp0"
if not exist data\rice.db (
  echo Building the demo database...
  python -m server.seed
)
if exist neo4j\rice-neo4j.json (
  echo Starting Neo4j graph database...
  python tools\neo4j_ctl.py start
) else (
  echo Neo4j is not set up - graphs will use the in-memory engine. Run: python tools\setup_neo4j.py
)
start "" http://127.0.0.1:8320/
python -m uvicorn server.main:app --host 127.0.0.1 --port 8320
