"""Smoke test suite for orchestrator_web.

Part 1: unit tests (no server).
Part 2: API end-to-end against a mock-mode server (no API costs).

Usage:  python test_orchestrator_web.py
Exits non-zero on any failure.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.request

BASE = "http://127.0.0.1:8766"
PASS, FAIL = 0, 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ok   {name}")
    else:
        FAIL += 1
        print(f"  FAIL {name}  {detail}")


def http(method: str, path: str, body: dict | None = None, timeout: int = 30):
    req = urllib.request.Request(BASE + path, method=method)
    data = None
    if body is not None:
        req.add_header("Content-Type", "application/json")
        data = json.dumps(body).encode()
    with urllib.request.urlopen(req, data=data, timeout=timeout) as r:
        return json.loads(r.read().decode())


# ---------------------------------------------------------------------------
print("== Part 1: unit tests ==")
import orchestrator_web as o

# caveman compression
short = o.caveman_compress("hi")
check("caveman: short prompt not inflated", o.est_tokens(short) <= 8, short)
long_p = ("Please research this topic thoroughly and basically just give me a "
          "really detailed summary of the best practices for the codebase")
saved = o.est_tokens(long_p) - o.est_tokens(o.caveman_compress(long_p))
check("caveman: long prompt saves tokens", saved > 0, f"saved={saved}")
check("caveman: terse instruction present", "terse" in o.caveman_compress("x"))

# auto model
check("auto_model: architecture -> opus", o.auto_model("design complex architecture") == "opus")
check("auto_model: code -> sonnet", o.auto_model("write a test for foo function") == "sonnet")
check("auto_model: simple -> haiku", o.auto_model("what time is it") == "haiku")

# limit patterns
for s in ("Error 429 Too Many Requests", "insufficient_quota", "usage limit reached",
          "You exceeded your quota", "rate limit hit"):
    check(f"limit pattern: {s[:25]}", bool(o.LIMIT_PATTERNS.search(s)))
check("limit pattern: clean text no match",
      not o.LIMIT_PATTERNS.search("normal output about code refactoring"))

# providers config
check("providers: groq + nvidia configured", set(o.PROVIDERS) == {"groq", "nvidia"})
check("executors: all 6 backends", set(o.EXECUTORS) ==
      {"claude", "codex", "agy", "gemini", "groq", "nvidia"})

# registry
st = o.REGISTRY.status()
check("registry: claude installed", st["claude"]["installed"])
check("registry: provider kind=api", st["groq"]["kind"] == "api")
o.REGISTRY.bench("gemini", "test bench")
check("registry: bench works", not o.REGISTRY.available("gemini"))
with o.REGISTRY._lock:
    o.REGISTRY.cooldown_until.pop("gemini", None)
check("registry: cooldown clear works", o.REGISTRY.available("gemini"))

# env round-trip (uses a temp name; cleaned after)
o.save_env_key("ORCH_TEST_KEY", "test-value-123")
check("env: save+load round trip", o.load_env().get("ORCH_TEST_KEY") == "test-value-123")
lines = [l for l in o.ENV_FILE.read_text(encoding="utf-8").splitlines()
         if not l.startswith("ORCH_TEST_KEY")]
o.ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
check("env: cleanup", "ORCH_TEST_KEY" not in o.load_env())

# ---------------------------------------------------------------------------
print("== Part 2: mock server E2E ==")
server = subprocess.Popen(
    [sys.executable, "orchestrator_web.py", "--mock", "8766"],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    creationflags=o.CREATE_NO_WINDOW,
)
try:
    for _ in range(20):
        try:
            http("GET", "/api/status")
            break
        except OSError:
            time.sleep(0.5)
    else:
        raise RuntimeError("mock server did not start")

    d = http("GET", "/api/status")
    check("status: mock flag", d["mock"] is True)
    check("status: 6 backends listed", len(d["clis"]) == 6)

    d = http("GET", "/api/keys")
    check("keys: masked, never raw", all(len(v.get("masked", "")) < 15 for v in d.values()))

    # bad inputs
    try:
        http("POST", "/api/run", {"task": ""})
        check("run: empty task rejected", False)
    except urllib.error.HTTPError as e:
        check("run: empty task rejected", e.code == 400)
    try:
        http("POST", "/api/keys", {"provider": "bogus", "key": "x" * 20})
        check("keys: bogus provider rejected", False)
    except urllib.error.HTTPError as e:
        check("keys: bogus provider rejected", e.code == 400)

    # full mock run with route override + gsd + caveman
    d = http("POST", "/api/run", {
        "task": "design complex architecture test",
        "model": "auto", "caveman": True, "gsd": True,
        "agents": ["research", "code", "local"],
        "routes": {"code": "groq"},
    })
    rid = d["run_id"]
    check("run: started", bool(rid))
    check("run: auto model picked opus", d["model"] == "opus", d["model"])

    # active endpoint sees it
    act = http("GET", "/api/active")
    check("active: run visible", any(r["run_id"] == rid for r in act))

    # wait for completion via polling result presence
    deadline = time.time() + 60
    meta = {}
    while time.time() < deadline:
        try:
            runs = http("GET", "/api/runs")
            meta = next((r for r in runs if r["id"] == rid), {})
            if (meta.get("status") or {}).get("synth") in ("done", "error"):
                break
        except OSError:
            pass
        time.sleep(1)
    status = meta.get("status") or {}
    check("run: all agents done",
          bool(status) and all(v == "done" for v in status.values()), str(status))
    check("run: route override honored", (meta.get("routed") or {}).get("code") == "groq",
          str(meta.get("routed")))

    # SSE replay after completion still serves full history
    req = urllib.request.Request(BASE + f"/api/stream/{rid}")
    events = []
    with urllib.request.urlopen(req, timeout=15) as r:
        for raw in r:
            raw = raw.decode().strip()
            if raw.startswith("data: "):
                events.append(json.loads(raw[6:]))
                if events[-1]["kind"] == "done":
                    break
    kinds = {e["kind"] for e in events}
    check("sse: replay has status+route+log+done",
          {"status", "route", "log", "done"} <= kinds, str(kinds))

    # archived result
    res = http("GET", f"/api/result/{rid}")
    check("result: synthesis archived", "synthesis" in res, str(list(res)))

    # cancel path on fresh run
    d2 = http("POST", "/api/run", {"task": "cancel me", "agents": ["research"]})
    time.sleep(0.5)
    c = http("POST", f"/api/cancel/{d2['run_id']}")
    check("cancel: accepted", c.get("ok") is True)

finally:
    server.kill()

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
