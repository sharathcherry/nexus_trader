#!/usr/bin/env python3
"""Nexus Orchestrator — production web control panel for multi-CLI agent orchestration.

Implements the multi-agent CLI orchestration flow (Claude Code as orchestrator
AND agent) with:

  * Agent roster: codex (code), agy/gemini (web research), claude (local/validate)
  * Automatic failover: a CLI that is rate-limited / out of quota / erroring is
    put on cooldown and its task is rerouted to the next CLI in its chain.
  * Caveman prompt compression (toggle) — strips filler from prompts and asks
    agents for terse replies to save tokens.
  * Model selection per run — manual (haiku / sonnet / opus) or "auto" where
    the orchestrator picks based on task complexity.
  * GSD toggle — when on, Claude agents are instructed to use GSD skills.
  * Live SSE streaming per agent, cancel, run history, persisted artifacts.

Usage:
    python orchestrator_web.py [port]     # default port 8765
    python orchestrator_web.py --mock     # simulated agents, no API calls

Artifacts: .orch_runs/<run_id>/   Logs: .orch_runs/orchestrator.log
"""

from __future__ import annotations

import json
import logging

import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

import requests
from flask import Flask, Response, jsonify, request

MOCK = "--mock" in sys.argv
ENV_FILE = Path(__file__).parent / ".env"


def load_env() -> dict[str, str]:
    out: dict[str, str] = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            m = re.match(r"\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)\s*$", line)
            if m:
                out[m.group(1)] = m.group(2).strip().strip('"').strip("'")
    return out


def save_env_key(name: str, value: str) -> None:
    lines = ENV_FILE.read_text(encoding="utf-8").splitlines() if ENV_FILE.exists() else []
    pat = re.compile(rf"\s*{re.escape(name)}\s*=")
    replaced = False
    for i, line in enumerate(lines):
        if pat.match(line):
            lines[i] = f"{name}={value}"
            replaced = True
            break
    if not replaced:
        lines.append(f"{name}={value}")
    ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")


ENV = load_env()

# API-key providers (OpenAI-compatible chat completions)
PROVIDERS = {
    "groq": {
        "url": "https://api.groq.com/openai/v1/chat/completions",
        "key_env": "GROQ_API_KEY",
        "model": ENV.get("GROQ_MODEL", "llama-3.3-70b-versatile"),
    },
    "nvidia": {
        "url": "https://integrate.api.nvidia.com/v1/chat/completions",
        "key_env": "NVIDIA_API_KEY",
        "model": ENV.get("NVIDIA_MODEL", "meta/llama-3.3-70b-instruct"),
    },
}
PORT = next((int(a) for a in sys.argv[1:] if a.isdigit()), 8765)
RUNS_DIR = Path(__file__).parent / ".orch_runs"
AGENT_TIMEOUT_SECS = 300
COOLDOWN_SECS = 300  # how long a rate-limited CLI stays benched

RUNS_DIR.mkdir(exist_ok=True)
logging.basicConfig(
    filename=RUNS_DIR / "orchestrator.log",
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(threadName)s %(message)s",
)
logger = logging.getLogger("orchestrator")

CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0

# --------------------------------------------------------------------------
# CLI adapters
# --------------------------------------------------------------------------

LIMIT_PATTERNS = re.compile(
    r"rate.?limit|429|too many requests|quota|usage limit|out of credits|"
    r"insufficient_quota|exhausted|overloaded|capacity|limit reached|"
    r"resource_exhausted|billing",
    re.IGNORECASE,
)

CLAUDE_MODELS = {"haiku": "haiku", "sonnet": "sonnet", "opus": "opus"}


def which(*names: str) -> str | None:
    for n in names:
        p = shutil.which(n)
        if p:
            return p
    return None


class CLIRegistry:
    """Tracks availability + cooldown state of every CLI."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.paths = {
            "claude": which("claude.exe", "claude.cmd", "claude"),
            "codex": which("codex.cmd", "codex.exe", "codex"),
            "agy": which("agy.exe", "agy.cmd", "agy"),
            "gemini": which("gemini.cmd", "gemini.exe", "gemini"),
        }
        self.cooldown_until: dict[str, float] = {}
        self.last_error: dict[str, str] = {}

    def installed(self, cli: str) -> bool:
        if cli in PROVIDERS:
            return bool(ENV.get(PROVIDERS[cli]["key_env"]))
        return bool(self.paths.get(cli))

    def available(self, cli: str) -> bool:
        if MOCK:
            return True
        if not self.installed(cli):
            return False
        with self._lock:
            return time.monotonic() >= self.cooldown_until.get(cli, 0)

    def bench(self, cli: str, reason: str) -> None:
        with self._lock:
            self.cooldown_until[cli] = time.monotonic() + COOLDOWN_SECS
            self.last_error[cli] = reason[:300]
        logger.warning("benched %s for %ss: %s", cli, COOLDOWN_SECS, reason[:200])

    def status(self) -> dict:
        now = time.monotonic()
        out = {}
        with self._lock:
            for cli in list(self.paths) + list(PROVIDERS):
                inst = self.installed(cli)
                cd = max(0, self.cooldown_until.get(cli, 0) - now)
                out[cli] = {
                    "installed": inst,
                    "kind": "api" if cli in PROVIDERS else "cli",
                    "cooldown_secs": round(cd),
                    "available": inst and cd == 0,
                    "last_error": self.last_error.get(cli, ""),
                }
        return out


REGISTRY = CLIRegistry()

# --------------------------------------------------------------------------
# Caveman prompt compression — deterministic, zero-API token saver
# --------------------------------------------------------------------------

_FILLER = re.compile(
    r"\b(?:a|an|the|just|really|basically|actually|simply|very|quite|please|"
    r"kindly|certainly|definitely|in order to|that is to say|as well as|"
    r"it should be noted that|it is important to note that)\b",
    re.IGNORECASE,
)


def caveman_compress(prompt: str) -> str:
    """Strip articles/filler, collapse whitespace, demand terse output.

    Never returns something longer than the original + suffix; for short
    prompts where stripping saves nothing, the original text is kept.
    """
    suffix = "\nReply terse, no filler."
    out = _FILLER.sub("", prompt)
    out = re.sub(r"[ \t]{2,}", " ", out)
    out = re.sub(r" ([,.;:])", r"\1", out)
    out = "\n".join(line.strip() for line in out.splitlines()).strip()
    if len(out) >= len(prompt):
        out = prompt
    return out + suffix


def est_tokens(text: str) -> int:
    return max(1, len(text) // 4)


# --------------------------------------------------------------------------
# Model auto-selection heuristic
# --------------------------------------------------------------------------

HEAVY_HINTS = re.compile(
    r"architect|design|refactor|migrate|security|audit|complex|deep|"
    r"strategy|debug|root cause|optimi[sz]e|concurrenc",
    re.IGNORECASE,
)
CODE_HINTS = re.compile(r"code|implement|write|fix|test|function|class|api|bug", re.IGNORECASE)


def auto_model(task: str) -> str:
    if HEAVY_HINTS.search(task):
        return "opus"
    if CODE_HINTS.search(task) or len(task) > 200:
        return "sonnet"
    return "haiku"


# --------------------------------------------------------------------------
# Agent roster + failover chains
# --------------------------------------------------------------------------

AGENTS = {
    "research": {
        "title": "Research (web)",
        "chain": ["agy", "gemini", "groq", "nvidia", "claude"],  # reroute order on limit/error
        "claude_tools": "WebSearch,WebFetch",
        "prompt": "Research this topic thoroughly: {task}. Return 5 key findings with source URLs.",
    },
    "code": {
        "title": "Code analysis",
        "chain": ["codex", "claude", "groq", "nvidia", "gemini"],
        "claude_tools": "Read,Grep,Glob",
        "prompt": "Technical analysis for: {task}. Scan relevant code in current project. Give 3 concrete code-level recommendations.",
    },
    "local": {
        "title": "Local context",
        "chain": ["claude", "gemini", "groq", "nvidia", "codex"],
        "claude_tools": "Read,WebFetch",
        "prompt": "Scan local project files for context on: {task}. Summarize what you find.",
    },
}

SYNTH_PROMPT = (
    "You are a synthesis agent. Combine the agent reports below into one "
    "concise final answer for the task: {task}\n\n{reports}\n\n"
    "Produce a single unified answer. Resolve contradictions, drop duplication."
)

GSD_PREFIX = (
    "Use GSD workflow skills where applicable (e.g. /gsd:quick for small fixes, "
    "/gsd:debug for investigation). "
)


# --------------------------------------------------------------------------
# Run engine
# --------------------------------------------------------------------------

class Run:
    def __init__(self, task: str, model: str, caveman: bool, gsd: bool,
                 agents: list[str], routes: dict[str, str] | None = None):
        self.id = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:6]
        self.task = task
        self.model = model if model != "auto" else auto_model(task)
        self.model_mode = "auto" if model == "auto" else "manual"
        self.caveman = caveman
        self.gsd = gsd
        self.agents = agents
        self.route_overrides = routes or {}
        self.history: list[dict] = []
        self.cancelled = False
        self.procs: list[subprocess.Popen] = []
        self.results: dict[str, str] = {}
        self.status: dict[str, str] = {a: "queued" for a in agents}
        self.routed: dict[str, str] = {}
        self.dir = RUNS_DIR / self.id
        self.dir.mkdir(parents=True, exist_ok=True)
        self.done = False
        self.started = time.time()

    def emit(self, agent: str, kind: str, text: str = "") -> None:
        ev = {"agent": agent, "kind": kind, "text": text, "ts": time.time()}
        self.history.append(ev)  # replay buffer for (re)connecting clients

    def set_status(self, agent: str, status: str) -> None:
        self.status[agent] = status
        self.emit(agent, "status", status)


RUNS: dict[str, Run] = {}
RUNS_LOCK = threading.Lock()


def build_prompt(run: Run, base: str) -> str:
    prompt = base
    if run.gsd:
        prompt = GSD_PREFIX + prompt
    if run.caveman:
        before = est_tokens(prompt)
        prompt = caveman_compress(prompt)
        logger.info("caveman compress %d -> %d est tokens", before, est_tokens(prompt))
    return prompt


# ---- CLI executors ---------------------------------------------------------

def exec_claude(run: Run, agent: str, prompt: str, tools: str, model: str) -> str:
    cmd = [REGISTRY.paths["claude"], "-p", "--output-format", "stream-json", "--verbose"]
    if model:
        cmd += ["--model", CLAUDE_MODELS.get(model, model)]
    if tools:
        cmd += ["--allowedTools", tools]
    return _stream_proc(run, agent, cmd, prompt, stdin_prompt=True, parser="claude")


def exec_codex(run: Run, agent: str, prompt: str, tools: str, model: str) -> str:
    # --output-last-message gives the clean final answer; stdout transcript is
    # streamed as progress only (codex dumps banners + full session otherwise).
    out_file = run.dir / f"_codex_{agent}.txt"
    cmd = [REGISTRY.paths["codex"], "exec", "--output-last-message", str(out_file), prompt]
    _stream_proc(run, agent, cmd, prompt, stdin_prompt=False, parser="plain")
    try:
        text = out_file.read_text(encoding="utf-8", errors="replace").strip()
        out_file.unlink(missing_ok=True)
    except OSError:
        text = ""
    if not text:
        raise RuntimeError("codex produced no final message")
    return text


def exec_agy(run: Run, agent: str, prompt: str, tools: str, model: str) -> str:
    cmd = [REGISTRY.paths["agy"], "-p", prompt]
    return _stream_proc(run, agent, cmd, prompt, stdin_prompt=False, parser="plain")


def exec_gemini(run: Run, agent: str, prompt: str, tools: str, model: str) -> str:
    cmd = [REGISTRY.paths["gemini"], "-p", prompt]
    return _stream_proc(run, agent, cmd, prompt, stdin_prompt=False, parser="plain")


def _make_provider_exec(provider: str):
    def exec_provider(run: Run, agent: str, prompt: str, tools: str, model: str) -> str:
        cfg = PROVIDERS[provider]
        key = ENV.get(cfg["key_env"], "")
        if not key:
            raise RuntimeError(f"{cfg['key_env']} not set")
        run.emit(agent, "log", f"· POST {cfg['url'].split('/')[2]} model={cfg['model']}")
        try:
            resp = requests.post(
                cfg["url"],
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json={
                    "model": cfg["model"],
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.4,
                    "max_tokens": 2048,
                },
                timeout=AGENT_TIMEOUT_SECS,
            )
        except requests.RequestException as exc:
            raise RuntimeError(f"{provider} request failed: {exc}") from exc
        if resp.status_code == 429 or resp.status_code == 402:
            raise LimitError(f"{provider} HTTP {resp.status_code}: {resp.text[:200]}")
        if resp.status_code != 200:
            body = resp.text[:300]
            if LIMIT_PATTERNS.search(body):
                raise LimitError(f"{provider} HTTP {resp.status_code}: {body}")
            raise RuntimeError(f"{provider} HTTP {resp.status_code}: {body}")
        data = resp.json()
        text = (data.get("choices") or [{}])[0].get("message", {}).get("content", "").strip()
        if not text:
            raise RuntimeError(f"{provider} empty response")
        for line in text.splitlines():
            if line.strip():
                run.emit(agent, "log", line)
        usage = data.get("usage", {})
        run.emit(agent, "log", f"── result ── ({usage.get('total_tokens', '?')} tokens)")
        return text
    return exec_provider


EXECUTORS = {
    "claude": exec_claude, "codex": exec_codex, "agy": exec_agy, "gemini": exec_gemini,
    "groq": _make_provider_exec("groq"), "nvidia": _make_provider_exec("nvidia"),
}


class LimitError(RuntimeError):
    """CLI hit a rate/usage limit — reroute."""


def _stream_proc(run: Run, agent: str, cmd: list[str], prompt: str,
                 stdin_prompt: bool, parser: str) -> str:
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE if stdin_prompt else subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=CREATE_NO_WINDOW,
    )
    run.procs.append(proc)
    if stdin_prompt:
        proc.stdin.write(prompt)
        proc.stdin.close()

    timed_out = threading.Event()

    def _kill():
        timed_out.set()
        proc.kill()

    killer = threading.Timer(AGENT_TIMEOUT_SECS, _kill)
    killer.start()
    collected: list[str] = []
    raw: list[str] = []
    try:
        for line in proc.stdout:
            line = line.rstrip("\n")
            if not line.strip():
                continue
            raw.append(line)
            if parser == "claude":
                for out, is_text in parse_claude_event(line):
                    if is_text:
                        collected.append(out)
                    run.emit(agent, "log", out)
            else:
                collected.append(line)
                run.emit(agent, "log", line)
    finally:
        killer.cancel()
    rc = proc.wait()
    full_out = "\n".join(raw)
    if run.cancelled:
        return "\n".join(collected)
    if timed_out.is_set() or rc == -9:
        raise TimeoutError(f"agent exceeded {AGENT_TIMEOUT_SECS}s")
    text = "\n".join(collected).strip()
    # Successful run with substantial content wins — never scan healthy output
    # for limit words (agent content may legitimately discuss rate limits).
    if rc == 0 and len(text) >= 40:
        return text
    # Failure path: classify limit vs generic error
    if LIMIT_PATTERNS.search(full_out):
        raise LimitError(f"limit detected (rc={rc}): {full_out[-200:]}")
    if rc != 0:
        raise RuntimeError(f"exit code {rc}: {full_out[-300:]}")
    raise RuntimeError(f"empty/short output: {full_out[-200:]!r}")


def parse_claude_event(line: str) -> list[tuple[str, bool]]:
    try:
        event = json.loads(line)
    except json.JSONDecodeError:
        return [(line, False)]
    etype = event.get("type")
    if etype == "system" and event.get("subtype") == "init":
        return [(f"· session {event.get('session_id', '')[:8]} ({event.get('model', '')})", False)]
    if etype == "assistant":
        out: list[tuple[str, bool]] = []
        for block in event.get("message", {}).get("content", []):
            if block.get("type") == "text" and block.get("text", "").strip():
                out.append((block["text"].strip(), True))
            elif block.get("type") == "tool_use":
                hint = str(block.get("input", {}))[:60]
                out.append((f"⚙ {block.get('name', '?')} {hint}", False))
        return out
    if etype == "result":
        cost = event.get("total_cost_usd") or 0
        return [(f"── result ── (${cost:.4f})", False)]
    return []


# ---- agent worker with failover --------------------------------------------

def run_agent(run: Run, agent_id: str) -> None:
    spec = AGENTS[agent_id]
    prompt = build_prompt(run, spec["prompt"].format(task=run.task))
    run.set_status(agent_id, "running")

    chain = list(spec["chain"])
    forced = run.route_overrides.get(agent_id)
    if forced in EXECUTORS:
        chain = [forced] + [c for c in chain if c != forced]
        run.emit(agent_id, "log", f"· route override: {forced} first")
    chain = [c for c in chain if REGISTRY.installed(c) or MOCK]
    if not chain:
        chain = ["claude"]
    last_exc: Exception | None = None
    for cli in chain:
        if run.cancelled:
            run.set_status(agent_id, "cancelled")
            break
        if not REGISTRY.available(cli):
            run.emit(agent_id, "log", f"↪ {cli} unavailable/benched — trying next")
            continue
        run.routed[agent_id] = cli
        run.emit(agent_id, "route", cli)
        try:
            if MOCK:
                text = mock_exec(run, agent_id, cli)
            else:
                text = EXECUTORS[cli](run, agent_id, prompt, spec["claude_tools"], run.model)
            run.results[agent_id] = text
            (run.dir / f"{agent_id}.md").write_text(text, encoding="utf-8")
            run.set_status(agent_id, "cancelled" if run.cancelled else "done")
            logger.info("agent %s done via %s chars=%d", agent_id, cli, len(text))
            break
        except LimitError as exc:
            REGISTRY.bench(cli, str(exc))
            run.emit(agent_id, "log", f"✖ {cli} out of limit — rerouting")
            last_exc = exc
        except Exception as exc:
            run.emit(agent_id, "log", f"✖ {cli} failed: {exc}")
            logger.exception("agent %s via %s failed", agent_id, cli)
            last_exc = exc
    else:
        run.results[agent_id] = f"(all CLIs failed: {last_exc})"
        run.set_status(agent_id, "error")


def mock_exec(run: Run, agent_id: str, cli: str) -> str:
    for i in range(4):
        if run.cancelled:
            raise RuntimeError("cancelled")
        time.sleep(0.5)
        run.emit(agent_id, "log", f"[{cli}] mock step {i + 1}/4")
    return f"mock findings from {agent_id} via {cli}"


def run_orchestration(run: Run) -> None:
    (run.dir / "task.txt").write_text(run.task, encoding="utf-8")
    meta = {
        "task": run.task, "model": run.model, "model_mode": run.model_mode,
        "caveman": run.caveman, "gsd": run.gsd, "agents": run.agents,
        "route_overrides": run.route_overrides, "started": run.started,
    }
    (run.dir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    logger.info("run %s start: %s", run.id, meta)

    threads = [
        threading.Thread(target=run_agent, args=(run, a), daemon=True, name=f"{run.id}-{a}")
        for a in run.agents
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # synthesis — Claude as agent (orchestrator delegating to itself)
    if not run.cancelled and len(run.agents) > 1:
        run.status["synth"] = "running"
        run.emit("synth", "status", "running")
        def cap(t: str, n: int = 6000) -> str:
            return t if len(t) <= n else t[:n] + "\n…(truncated)"
        reports = "\n\n".join(
            f"=== {AGENTS[a]['title'].upper()} (via {run.routed.get(a, '?')}) ===\n{cap(run.results.get(a, '(missing)'))}"
            for a in run.agents
        )
        prompt = build_prompt(run, SYNTH_PROMPT.format(task=run.task, reports=reports))
        try:
            if MOCK:
                time.sleep(1)
                text = "mock unified answer"
                run.emit("synth", "log", text)
            else:
                run.emit("synth", "route", "claude")
                text = exec_claude(run, "synth", prompt, "", run.model)
            run.results["synth"] = text
            (run.dir / "synthesis.md").write_text(text, encoding="utf-8")
            run.status["synth"] = "done"
            run.emit("synth", "status", "done")
        except Exception as exc:
            run.emit("synth", "log", f"✖ synthesis failed: {exc}")
            run.status["synth"] = "error"
            run.emit("synth", "status", "error")
            logger.exception("synthesis failed")

    run.done = True
    run.emit("_run", "done", run.id)
    meta["finished"] = time.time()
    meta["status"] = run.status
    meta["routed"] = run.routed
    (run.dir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    logger.info("run %s finished status=%s routed=%s", run.id, run.status, run.routed)


# --------------------------------------------------------------------------
# Flask app
# --------------------------------------------------------------------------

app = Flask(__name__)


@app.post("/api/run")
def api_run():
    data = request.get_json(force=True)
    task = (data.get("task") or "").strip()
    if not task:
        return jsonify({"error": "task required"}), 400
    agents = [a for a in (data.get("agents") or list(AGENTS)) if a in AGENTS]
    if not agents:
        return jsonify({"error": "no valid agents"}), 400
    routes = {k: v for k, v in (data.get("routes") or {}).items()
              if k in AGENTS and v in EXECUTORS}
    run = Run(
        task=task,
        model=data.get("model", "auto"),
        caveman=bool(data.get("caveman", True)),
        gsd=bool(data.get("gsd", False)),
        agents=agents,
        routes=routes,
    )
    with RUNS_LOCK:
        RUNS[run.id] = run
    threading.Thread(target=run_orchestration, args=(run,), daemon=True, name=run.id).start()
    return jsonify({"run_id": run.id, "model": run.model, "model_mode": run.model_mode})


@app.get("/api/stream/<run_id>")
def api_stream(run_id: str):
    run = RUNS.get(run_id)
    if run is None:
        return jsonify({"error": "unknown run"}), 404

    def gen():
        idx = 0
        idle = 0.0
        while True:
            hist = run.history
            if idx < len(hist):
                while idx < len(hist):
                    ev = hist[idx]
                    idx += 1
                    yield f"data: {json.dumps(ev)}\n\n"
                    if ev["kind"] == "done":
                        return
                idle = 0.0
                continue
            if run.done:
                yield f"data: {json.dumps({'agent': '_run', 'kind': 'done'})}\n\n"
                return
            time.sleep(0.4)
            idle += 0.4
            if idle >= 15:
                idle = 0.0
                yield ": keepalive\n\n"

    return Response(gen(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/api/cancel/<run_id>")
def api_cancel(run_id: str):
    run = RUNS.get(run_id)
    if run is None:
        return jsonify({"error": "unknown run"}), 404
    run.cancelled = True
    for p in run.procs:
        if p.poll() is None:
            p.kill()
    logger.info("run %s cancelled", run_id)
    return jsonify({"ok": True})


@app.get("/api/active")
def api_active():
    with RUNS_LOCK:
        active = [{"run_id": r.id, "task": r.task, "agents": r.agents, "model": r.model}
                  for r in RUNS.values() if not r.done]
    return jsonify(active)


@app.get("/api/status")
def api_status():
    return jsonify({"clis": REGISTRY.status(), "mock": MOCK,
                    "backends": list(EXECUTORS),
                    "agents": {
                        k: {"title": v["title"], "chain": v["chain"]} for k, v in AGENTS.items()
                    }})


@app.get("/api/keys")
def api_keys_get():
    out = {}
    for prov, cfg in PROVIDERS.items():
        val = ENV.get(cfg["key_env"], "")
        out[prov] = {
            "env": cfg["key_env"],
            "model": cfg["model"],
            "set": bool(val),
            "masked": (val[:4] + "…" + val[-4:]) if len(val) > 12 else ("set" if val else ""),
        }
    return jsonify(out)


@app.post("/api/keys")
def api_keys_set():
    data = request.get_json(force=True)
    prov = data.get("provider")
    key = (data.get("key") or "").strip()
    if prov not in PROVIDERS:
        return jsonify({"error": "unknown provider"}), 400
    if not key or len(key) < 8:
        return jsonify({"error": "key too short"}), 400
    env_name = PROVIDERS[prov]["key_env"]
    save_env_key(env_name, key)
    ENV[env_name] = key
    # fresh key clears any cooldown
    with REGISTRY._lock:
        REGISTRY.cooldown_until.pop(prov, None)
        REGISTRY.last_error.pop(prov, None)
    logger.info("api key updated for %s", prov)
    return jsonify({"ok": True})


@app.get("/api/runs")
def api_runs():
    out = []
    for d in sorted(RUNS_DIR.iterdir(), reverse=True):
        meta_f = d / "meta.json"
        if d.is_dir() and meta_f.exists():
            try:
                meta = json.loads(meta_f.read_text(encoding="utf-8"))
                out.append({"id": d.name, **{k: meta.get(k) for k in
                            ("task", "model", "caveman", "gsd", "status", "routed")}})
            except (json.JSONDecodeError, OSError):
                continue
        if len(out) >= 25:
            break
    return jsonify(out)


@app.get("/api/result/<run_id>")
def api_result(run_id: str):
    d = RUNS_DIR / run_id
    if not d.is_dir():
        return jsonify({"error": "unknown run"}), 404
    out = {}
    for f in d.glob("*.md"):
        out[f.stem] = f.read_text(encoding="utf-8")
    return jsonify(out)


@app.get("/")
def index():
    return Response(INDEX_HTML, mimetype="text/html")


INDEX_HTML = r"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Nexus Orchestrator</title>
<style>
:root{--bg:#0d1117;--panel:#161b22;--border:#30363d;--text:#e6edf3;--dim:#8b949e;
--accent:#d85a30;--green:#3fb950;--yellow:#d29922;--red:#f85149;--purple:#bc8cff;--cyan:#56d4dd}
*{box-sizing:border-box;margin:0}
body{background:var(--bg);color:var(--text);font:14px/1.5 system-ui,Segoe UI,sans-serif;padding:16px}
h1{font-size:18px;letter-spacing:.04em}
h1 span{color:var(--accent)}
.top{display:flex;justify-content:space-between;align-items:center;margin-bottom:14px}
.clis{display:flex;gap:8px;font-size:12px}
.cli{padding:3px 10px;border-radius:12px;border:1px solid var(--border);color:var(--dim)}
.cli.ok{border-color:var(--green);color:var(--green)}
.cli.bench{border-color:var(--yellow);color:var(--yellow)}
.cli.off{border-color:var(--red);color:var(--red)}
.grid{display:grid;grid-template-columns:300px 1fr;gap:14px}
.panel{background:var(--panel);border:1px solid var(--border);border-radius:8px;padding:14px}
label{display:block;font-size:11px;text-transform:uppercase;letter-spacing:.07em;color:var(--dim);margin:12px 0 4px}
textarea,select{width:100%;background:var(--bg);border:1px solid var(--border);border-radius:6px;
color:var(--text);padding:8px;font:inherit}
textarea{height:90px;resize:vertical}
.toggle{display:flex;align-items:center;gap:8px;margin:8px 0;font-size:13px;cursor:pointer}
.toggle input{accent-color:var(--accent)}
.toggle .hint{color:var(--dim);font-size:11px}
button{background:var(--accent);border:0;border-radius:6px;color:#fff;padding:9px 18px;
font:inherit;font-weight:600;cursor:pointer;width:100%;margin-top:14px}
button:hover{filter:brightness(1.1)}
button:disabled{opacity:.4;cursor:default}
#cancel{background:transparent;border:1px solid var(--red);color:var(--red);display:none}
.agents{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:12px}
.card{background:var(--panel);border:1px solid var(--border);border-radius:8px;padding:10px;
display:flex;flex-direction:column;min-height:220px}
.card h3{font-size:13px;display:flex;justify-content:space-between;align-items:center}
.chip{font-size:11px;padding:1px 8px;border-radius:10px;border:1px solid var(--border);color:var(--dim)}
.chip.running{border-color:var(--yellow);color:var(--yellow)}
.chip.done{border-color:var(--green);color:var(--green)}
.chip.error,.chip.cancelled{border-color:var(--red);color:var(--red)}
.via{font-size:11px;color:var(--cyan);margin:2px 0 6px;min-height:14px}
.log{flex:1;background:var(--bg);border-radius:6px;padding:8px;font:12px/1.5 ui-monospace,Consolas,monospace;
overflow-y:auto;max-height:260px;white-space:pre-wrap;word-break:break-word}
.synth{grid-column:1/-1;border-color:var(--green)}
.hist{margin-top:14px}
.hist h3{font-size:12px;color:var(--dim);text-transform:uppercase;letter-spacing:.07em;margin-bottom:6px}
.hitem{font-size:12px;padding:6px 8px;border-radius:6px;cursor:pointer;color:var(--dim);
overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.hitem:hover{background:var(--bg);color:var(--text)}
.meta{font-size:12px;color:var(--dim);margin-top:8px;min-height:16px}
.agentpick{display:flex;gap:10px;flex-wrap:wrap;font-size:13px}
.agrow{display:flex;align-items:center;gap:8px;margin:5px 0;font-size:13px}
.agrow select{width:auto;flex:1;padding:4px 6px;font-size:12px}
.keyrow{display:flex;align-items:center;gap:6px;margin:5px 0}
.keyrow input{flex:1;background:var(--bg);border:1px solid var(--border);border-radius:6px;
color:var(--text);padding:5px 8px;font:12px ui-monospace,Consolas,monospace}
.keyrow .kbtn{width:auto;margin:0;padding:5px 12px;font-size:12px}
.keystate{font-size:11px;color:var(--dim);min-width:70px}
.keystate.set{color:var(--green)}
</style></head><body>
<div class="top">
  <h1>NEXUS <span>ORCHESTRATOR</span></h1>
  <div class="clis" id="clis"></div>
</div>
<div class="grid">
  <div class="panel">
    <label>Task</label>
    <textarea id="task" placeholder="Describe your task…"></textarea>
    <label>Model</label>
    <select id="model">
      <option value="auto">auto — orchestrator picks</option>
      <option value="haiku">haiku — fast / cheap</option>
      <option value="sonnet">sonnet — balanced</option>
      <option value="opus">opus — deep reasoning</option>
    </select>
    <label>Agents &amp; routing</label>
    <div id="agentpick"></div>
    <label>API keys</label>
    <div id="keys"></div>
    <label>Options</label>
    <label class="toggle"><input type="checkbox" id="caveman" checked>
      Caveman compression <span class="hint">save tokens</span></label>
    <label class="toggle"><input type="checkbox" id="gsd">
      GSD skills <span class="hint">claude agents use /gsd workflow</span></label>
    <button id="runbtn" onclick="startRun()">▶ Run orchestration</button>
    <button id="cancel" onclick="cancelRun()">■ Cancel</button>
    <div class="meta" id="meta"></div>
    <div class="hist"><h3>History</h3><div id="hist"></div></div>
  </div>
  <div>
    <div class="agents" id="cards"></div>
  </div>
</div>
<script>
const AGENT_IDS=["research","code","local"];
const TITLES={research:"🌐 Research (web)",code:"🔧 Code analysis",local:"📁 Local context",synth:"🧠 Synthesis"};
let runId=null,es=null;

function el(id){return document.getElementById(id)}
function chip(s){return `<span class="chip ${s}" id="chip-${s}">${s}</span>`}

function buildCards(agents){
  let html="";
  for(const a of [...agents,"synth"]){
    html+=`<div class="card ${a==='synth'?'synth':''}" id="card-${a}">
      <h3>${TITLES[a]} <span class="chip" id="chip-${a}">idle</span></h3>
      <div class="via" id="via-${a}"></div>
      <div class="log" id="log-${a}"></div></div>`;
  }
  el("cards").innerHTML=html;
}
let BACKENDS=["claude","codex","agy","gemini","groq","nvidia"];
function buildPicker(){
  el("agentpick").innerHTML=AGENT_IDS.map(a=>
    `<div class="agrow"><input type="checkbox" class="agpick" value="${a}" checked>
     <span style="min-width:120px">${TITLES[a]}</span>
     <select class="agroute" data-agent="${a}">
       <option value="">auto (failover chain)</option>
       ${BACKENDS.map(b=>`<option value="${b}">force ${b}</option>`).join("")}
     </select></div>`).join("");
}
async function refreshKeys(){
  const r=await fetch("/api/keys");const d=await r.json();
  el("keys").innerHTML=Object.entries(d).map(([p,v])=>
    `<div class="keyrow"><span style="min-width:50px;font-size:12px">${p}</span>
     <input type="password" id="key-${p}" placeholder="${v.env}">
     <span class="keystate ${v.set?'set':''}">${v.set?'✓ '+v.masked:'not set'}</span>
     <button class="kbtn" onclick="saveKey('${p}')">Save</button></div>`).join("");
}
async function saveKey(p){
  const key=el("key-"+p).value.trim();if(!key)return;
  const r=await fetch("/api/keys",{method:"POST",headers:{"Content-Type":"application/json"},
    body:JSON.stringify({provider:p,key})});
  const d=await r.json();
  el("meta").textContent=d.ok?`${p} key saved`:(d.error||"error");
  refreshKeys();refreshStatus();
}
async function refreshStatus(){
  const r=await fetch("/api/status");const d=await r.json();
  el("clis").innerHTML=Object.entries(d.clis).map(([k,v])=>{
    const cls=!v.installed?"off":v.cooldown_secs>0?"bench":"ok";
    const extra=v.cooldown_secs>0?` ⏱${v.cooldown_secs}s`:"";
    return `<span class="cli ${cls}" title="${v.last_error||''}">${k}${extra}</span>`;}).join("");
}
async function refreshHist(){
  const r=await fetch("/api/runs");const d=await r.json();
  el("hist").innerHTML=d.map(h=>
    `<div class="hitem" onclick="loadRun('${h.id}')" title="${h.task||''}">${h.id.slice(0,15)} · ${(h.task||'').slice(0,40)}</div>`).join("");
}
async function loadRun(id){
  const r=await fetch("/api/result/"+id);const d=await r.json();
  buildCards(AGENT_IDS.filter(a=>d[a]!==undefined));
  for(const[k,v]of Object.entries(d)){
    const lg=el("log-"+(k==="synthesis"?"synth":k));
    if(lg){lg.textContent=v;setChip(k==="synthesis"?"synth":k,"done");}
  }
  el("meta").textContent="Loaded archived run "+id;
}
function setChip(a,s){const c=el("chip-"+a);if(c){c.textContent=s;c.className="chip "+s;}}
function append(a,t){const lg=el("log-"+a);if(lg){lg.textContent+=t+"\n";lg.scrollTop=lg.scrollHeight;}}

async function startRun(){
  const task=el("task").value.trim();if(!task)return;
  const agents=[...document.querySelectorAll(".agpick:checked")].map(x=>x.value);
  if(!agents.length)return;
  const routes={};
  document.querySelectorAll(".agroute").forEach(s=>{if(s.value)routes[s.dataset.agent]=s.value;});
  buildCards(agents);
  el("runbtn").disabled=true;el("cancel").style.display="block";
  const r=await fetch("/api/run",{method:"POST",headers:{"Content-Type":"application/json"},
    body:JSON.stringify({task,model:el("model").value,caveman:el("caveman").checked,
      gsd:el("gsd").checked,agents,routes})});
  const d=await r.json();
  if(d.error){el("meta").textContent=d.error;el("runbtn").disabled=false;return;}
  runId=d.run_id;
  el("meta").textContent=`run ${d.run_id} · model: ${d.model} (${d.model_mode})`;
  for(const a of agents)setChip(a,"queued");
  attach(runId);
}
function attach(id){
  runId=id;
  el("runbtn").disabled=true;el("cancel").style.display="block";
  if(es)es.close();
  es=new EventSource("/api/stream/"+id);
  es.onmessage=e=>{
    const ev=JSON.parse(e.data);
    if(ev.kind==="done"){es.close();el("runbtn").disabled=false;
      el("cancel").style.display="none";refreshHist();refreshStatus();return;}
    if(ev.kind==="status")setChip(ev.agent,ev.text);
    else if(ev.kind==="route"){const v=el("via-"+ev.agent);if(v)v.textContent="via "+ev.text;}
    else if(ev.kind==="log")append(ev.agent,ev.text);
  };
  es.onerror=()=>{};
}
async function reattachActive(){
  const r=await fetch("/api/active");const d=await r.json();
  if(d.length){
    const run=d[0];
    buildCards(run.agents);
    el("meta").textContent=`reattached to live run ${run.run_id} · ${run.task.slice(0,50)}`;
    attach(run.run_id);
  }
}
async function cancelRun(){
  if(runId)await fetch("/api/cancel/"+runId,{method:"POST"});
}
buildPicker();buildCards(AGENT_IDS);refreshStatus();refreshHist();refreshKeys();reattachActive();
setInterval(refreshStatus,10000);
</script></body></html>"""


if __name__ == "__main__":
    print(f"Nexus Orchestrator web UI -> http://127.0.0.1:{PORT}  (mock={MOCK})")
    app.run(host="127.0.0.1", port=PORT, threaded=True, debug=False)
