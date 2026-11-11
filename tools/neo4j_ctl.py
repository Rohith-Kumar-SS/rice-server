"""Start / stop / check RICE's bundled Neo4j server.

    python tools/neo4j_ctl.py start | stop | status
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOME = ROOT / "neo4j"
META = HOME / "rice-neo4j.json"
PIDFILE = HOME / "rice-neo4j.pid"
BOLT = 7697


def port_open(port=BOLT):
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1.0):
            return True
    except OSError:
        return False


def start(wait=True, timeout=150):
    if port_open():
        return True
    if not META.exists():
        raise RuntimeError("Neo4j isn't set up yet — run: python tools/setup_neo4j.py")
    meta = json.loads(META.read_text())
    server = Path(meta["home"])
    logs = server / "logs"
    logs.mkdir(exist_ok=True)
    env = {**os.environ, "JAVA_HOME": meta["java_home"], "NEO4J_HOME": str(server)}
    flags = 0
    if os.name == "nt":
        flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS | subprocess.CREATE_NO_WINDOW
    out = open(logs / "rice-console.log", "ab")
    proc = subprocess.Popen(["cmd", "/c", str(server / "bin" / "neo4j.bat"), "console"], cwd=server, env=env,
                            stdout=out, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, creationflags=flags)
    PIDFILE.write_text(str(proc.pid))
    if not wait:
        return True
    end = time.time() + timeout
    while time.time() < end:
        if port_open():
            return True
        time.sleep(1.5)
    return False


def _listening_pids(port=BOLT):
    try:
        out = subprocess.run(["netstat", "-ano", "-p", "tcp"], capture_output=True, text=True).stdout
    except OSError:
        return set()
    pids = set()
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[1].endswith(f":{port}") and parts[3] == "LISTENING":
            pids.add(parts[4])
    return pids


def stop():
    pids = _listening_pids()
    if PIDFILE.exists():
        pids.add(PIDFILE.read_text().strip())
    for pid in pids:
        subprocess.run(["taskkill", "/PID", pid, "/T", "/F"], capture_output=True)
    PIDFILE.unlink(missing_ok=True)
    return not port_open()


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "start":
        ok = start()
        print("Neo4j is running on bolt://127.0.0.1:7697 (browser http://127.0.0.1:7484/browser/)" if ok else
              "Neo4j didn't come up — see neo4j/server/logs/rice-console.log")
        sys.exit(0 if ok else 1)
    if cmd == "stop":
        print("Stopped." if stop() else "Neo4j is still running.")
    else:
        print("running" if port_open() else "stopped")


if __name__ == "__main__":
    main()
