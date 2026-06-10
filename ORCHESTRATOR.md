# Nexus Orchestrator

Two interfaces over the same multi-CLI agent orchestration engine:

| Interface | File | Use |
|---|---|---|
| **Web control panel** (recommended) | `orchestrator_web.py` | Full control: model select, toggles, failover view, history |
| TUI | `orchestrator_tui.py` | Quick terminal use |
| Bash script | `orchestrate.sh` | Called by Claude Code's Bash tool per CLAUDE.md |

## Web control panel

```bash
python orchestrator_web.py          # real agents → http://127.0.0.1:8765
python orchestrator_web.py --mock   # demo mode, zero API calls
python orchestrator_web.py 9000     # custom port
```

### Agent roster + failover chains

| Agent | Primary CLI | Failover chain | Job |
|---|---|---|---|
| research | agy | agy → gemini → claude | 5 key findings with source URLs |
| code | codex | codex → claude → gemini | 3 code-level recommendations |
| local | claude | claude → gemini → codex | local project context |
| synthesis | claude | (always claude — orchestrator as agent) | unified final answer |

**Failover ("out of limit" rerouting):** when a CLI hits a rate/usage limit
(429, quota, insufficient_quota, …) it is benched for 5 minutes
(`COOLDOWN_SECS`) and the task immediately reroutes to the next CLI in the
chain. Benched CLIs show a countdown in the header. Limit words inside
healthy agent *content* never trigger a false bench — classification only
runs on failed executions (non-zero exit or empty output).

### API-key providers (Groq, NVIDIA)

OpenAI-compatible HTTP backends alongside the CLIs:

| Provider | Endpoint | Key env | Default model |
|---|---|---|---|
| groq | api.groq.com/openai/v1 | `GROQ_API_KEY` | llama-3.3-70b-versatile |
| nvidia | integrate.api.nvidia.com/v1 | `NVIDIA_API_KEY` | meta/llama-3.3-70b-instruct |

- Keys managed in UI ("API keys" panel) — saved to `.env` (gitignored),
  masked in API responses, never logged.
- Override models via `GROQ_MODEL` / `NVIDIA_MODEL` in `.env`.
- Providers participate in failover chains and can be **force-assigned per
  agent** via the routing dropdown ("force groq" etc.). Saving a fresh key
  clears the provider's cooldown.
- HTTP 429/402 → benched + rerouted like any CLI.

### Controls

- **Model**: `auto` (orchestrator picks haiku/sonnet/opus by task complexity
  heuristic) or manual haiku / sonnet / opus. Applied to claude executions.
- **Caveman compression** (default ON): deterministic prompt compressor —
  strips articles/filler, demands terse replies. ~30-40% prompt token savings,
  zero API cost (no LLM round-trip to compress).
- **GSD skills** (toggle, default OFF): claude agents get instructed to use
  GSD workflow skills (`/gsd:quick`, `/gsd:debug`) for any file-changing work.
- **Agent picker**: run any subset of the three agents.
- **Cancel**: kills all child CLI processes mid-run.
- **History**: last 25 runs clickable, archived results reload into cards.

### API

| Endpoint | Method | Purpose |
|---|---|---|
| `/api/run` | POST | `{task, model, caveman, gsd, agents[]}` → `{run_id, model}` |
| `/api/stream/<id>` | GET | SSE: `{agent, kind: status\|route\|log, text}` |
| `/api/cancel/<id>` | POST | kill run |
| `/api/status` | GET | CLI availability + cooldowns |
| `/api/runs` | GET | history |
| `/api/result/<id>` | GET | archived outputs |

### Production behavior

- Per-agent hard timeout 300 s
- Every run persisted: `.orch_runs/<run_id>/` (task.txt, meta.json with
  routing + status, per-agent .md, synthesis.md)
- Diagnostics: `.orch_runs/orchestrator.log`
- Failure isolation: one agent failing never blocks others; synthesis runs
  on whatever results exist
- Windows: children spawn with `CREATE_NO_WINDOW`

### Verified (2026-06-10)

Real run `20260610_134531_1b1b63`: agy produced no output → research agent
auto-rerouted to gemini → done. code via codex done, local via claude done,
synthesis via claude done. Auto model picked haiku for a simple question,
opus for an architecture task. All artifacts persisted.

## TUI

```bash
python orchestrator_tui.py          # 3 claude agents + synthesis, live panels
python orchestrator_tui.py --mock
```

## Tests

```bash
python test_orchestrator_tui.py     # headless TUI mock test
python test_orchestrator_real.py    # live TUI end-to-end
```

## Requirements

Python 3.11+, `flask`, `textual` (TUI only). CLIs on PATH: `claude`
(required), `codex` / `agy` / `gemini` (optional — chains skip missing ones).
