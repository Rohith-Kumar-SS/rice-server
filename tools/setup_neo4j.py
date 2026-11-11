"""One-time setup of RICE's own Neo4j Community server (+ Graph Data Science) inside ./neo4j.

    python tools/setup_neo4j.py [path-to-neo4j-community-*-windows.zip]

- Unzips Neo4j Community Edition (GPLv3 — fine for a commercial service) into neo4j/server
- Installs the Graph Data Science plugin (community features need no licence key)
- Uses a Java 21 runtime: $RICE_JAVA_HOME, or the one bundled with Neo4j Desktop
- Listens on 127.0.0.1 only, on its own ports (bolt 7697, browser 7484), so it never
  clashes with other Neo4j databases on this machine
- Generates a password into data/neo4j.secret (never committed)
"""
from __future__ import annotations

import glob
import json
import os
import secrets
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOME = ROOT / "neo4j"
SERVER = HOME / "server"
JRE = HOME / "jre"
SECRET = ROOT / "data" / "neo4j.secret"
DESKTOP = Path.home() / ".Neo4jDesktop2"
BOLT, HTTP = 7697, 7484

CONF = f"""
# ---- RICE settings ----
server.default_listen_address=127.0.0.1
server.bolt.listen_address=127.0.0.1:{BOLT}
server.bolt.advertised_address=127.0.0.1:{BOLT}
server.http.listen_address=127.0.0.1:{HTTP}
server.http.advertised_address=127.0.0.1:{HTTP}
server.https.enabled=false
dbms.security.procedures.unrestricted=gds.*
dbms.security.procedures.allowlist=gds.*
server.memory.heap.initial_size=512m
server.memory.heap.max_size=1536m
server.memory.pagecache.size=256m
"""


def find_zip(arg):
    if arg:
        return Path(arg)
    hits = sorted((HOME / "_dist").glob("neo4j-community-*-windows.zip"))
    if not hits:
        sys.exit("Put neo4j-community-<version>-windows.zip in neo4j/_dist (https://neo4j.com/deployment-center/).")
    return hits[-1]


def find_java():
    env = os.environ.get("RICE_JAVA_HOME")
    if env and (Path(env) / "bin" / "java.exe").exists():
        return Path(env)
    cands = sorted(glob.glob(str(DESKTOP / "Cache" / "runtime" / "zulu21*")))
    if cands:
        return Path(cands[-1])
    sys.exit("Need a Java 21 runtime. Set RICE_JAVA_HOME to a JDK/JRE 21 folder.")


def find_gds(neo_version: str):
    env = os.environ.get("RICE_GDS_JAR")
    if env and Path(env).exists():
        return Path(env)
    # GDS 2.26 pairs with Neo4j 2026.01; prefer the jar that ships next to the same Neo4j version.
    same = glob.glob(str(DESKTOP / "Cache" / "dbmss" / f"*{neo_version}" / "products" / "neo4j-graph-data-science-*.jar"))
    anyv = sorted(glob.glob(str(DESKTOP / "**" / "neo4j-graph-data-science-*.jar"), recursive=True))
    if same:
        return Path(same[0])
    if anyv:
        return Path(anyv[-1])
    return None


def write_conf(conf: Path):
    """Set each RICE key exactly once: replace an existing uncommented line, else append."""
    wanted = dict(l.split("=", 1) for l in CONF.strip().splitlines() if "=" in l and not l.startswith("#"))
    lines = conf.read_text(encoding="utf-8").splitlines()
    seen, out = set(), []
    for line in lines:
        key = line.split("=", 1)[0].strip() if "=" in line and not line.lstrip().startswith("#") else None
        if key in wanted:
            if key in seen:
                continue
            out.append(f"{key}={wanted[key]}")
            seen.add(key)
        else:
            out.append(line)
    missing = [k for k in wanted if k not in seen]
    if missing:
        out.append("# ---- RICE settings ----")
        out += [f"{k}={wanted[k]}" for k in missing]
    conf.write_text("\n".join(out) + "\n", encoding="utf-8")


def main():
    z = find_zip(sys.argv[1] if len(sys.argv) > 1 else None)
    version = z.name.replace("neo4j-community-", "").replace("-windows.zip", "")
    if not SERVER.exists():
        print(f"Unzipping {z.name} …")
        with zipfile.ZipFile(z) as zf:
            top = zf.namelist()[0].split("/")[0]
            zf.extractall(HOME)
        (HOME / top).rename(SERVER)
    if not JRE.exists():
        src = find_java()
        print(f"Copying Java runtime from {src} …")
        shutil.copytree(src, JRE)
    gds = find_gds(version)
    plugins = SERVER / "plugins"
    if gds:
        if not any(plugins.glob("neo4j-graph-data-science-*.jar")):
            shutil.copy2(gds, plugins / gds.name)
            print(f"Installed {gds.name}")
    else:
        print("WARNING: Graph Data Science jar not found — set RICE_GDS_JAR. RICE will use Cypher + NetworkX for algorithms.")
    conf = SERVER / "conf" / "neo4j.conf"
    write_conf(conf)
    SECRET.parent.mkdir(exist_ok=True)
    if not SECRET.exists():
        pw = secrets.token_urlsafe(18)
        env = {**os.environ, "JAVA_HOME": str(JRE), "NEO4J_HOME": str(SERVER)}
        r = subprocess.run(["cmd", "/c", str(SERVER / "bin" / "neo4j-admin.bat"), "dbms", "set-initial-password", pw],
                           cwd=SERVER, env=env, capture_output=True, text=True)
        if r.returncode != 0:
            sys.exit(f"Setting the initial password failed:\n{r.stdout}\n{r.stderr}")
        SECRET.write_text(pw)
        print("Password written to data/neo4j.secret")
    meta = {"home": str(SERVER), "java_home": str(JRE), "version": version, "edition": "community",
            "gds": gds.name if gds else None, "bolt": f"bolt://127.0.0.1:{BOLT}", "browser": f"http://127.0.0.1:{HTTP}/browser/"}
    (HOME / "rice-neo4j.json").write_text(json.dumps(meta, indent=2))
    print("Neo4j ready:", json.dumps(meta, indent=2))
    print("Start it with:  python tools/neo4j_ctl.py start")


if __name__ == "__main__":
    main()
