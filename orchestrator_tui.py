#!/usr/bin/env python3
"""Nexus Orchestrator TUI.

Claude-app style terminal interface that fans a task out to three parallel
`claude -p` agents (web research / code analysis / local context), streams
each agent's live progress into its own panel, then synthesizes a final
answer from all three outputs.

Usage:
    python orchestrator_tui.py            # real agents (claude CLI)
    python orchestrator_tui.py --mock     # simulated agents (no API calls)

Keys:
    Enter   submit task
    Escape  cancel running task
    q       quit (kills child agents)

Outputs of every run are persisted under .orch_runs/<timestamp>/.
Diagnostics are logged to .orch_runs/orchestrator.log.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

from textual import on
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.widgets import Footer, Header, Input, Label, RichLog, Static

MOCK = "--mock" in sys.argv
AGENT_TIMEOUT_SECS = 300  # hard cap per agent
RUNS_DIR = Path(__file__).parent / ".orch_runs"

AGENTS = [
    {
        "id": "research",
        "title": "🌐 Research (web)",
        "tools": "WebSearch,WebFetch",
        "prompt": "Research this topic thoroughly: {task}. Return 5 key findings with source URLs.",
    },
    {
        "id": "code",
        "title": "🔧 Code analysis",
        "tools": "Read,Grep,Glob",
        "prompt": "Technical analysis for: {task}. Scan relevant code in current project. Give 3 concrete code-level recommendations.",
    },
    {
        "id": "local",
        "title": "📁 Local context",
        "tools": "Read,WebFetch",
        "prompt": "Scan local project files for context on: {task}. Summarize what you find.",
    },
]

SYNTH_PROMPT = (
    "You are a synthesis agent. Combine the three agent reports below into one "
    "concise final answer for the task: {task}\n\n"
    "=== WEB RESEARCH ===\n{research}\n\n"
    "=== CODE ANALYSIS ===\n{code}\n\n"
    "=== LOCAL CONTEXT ===\n{local}\n\n"
    "Produce a single unified answer. Resolve contradictions, drop duplication."
)

STATUS_STYLE = {
    "idle": ("dim", "● idle"),
    "running": ("yellow", "◐ running"),
    "done": ("green", "● done"),
    "error": ("red", "✖ error"),
    "timeout": ("red", "⏱ timeout"),
    "cancelled": ("magenta", "■ cancelled"),
}

# ---- logging ---------------------------------------------------------------

RUNS_DIR.mkdir(exist_ok=True)
logging.basicConfig(
    filename=RUNS_DIR / "orchestrator.log",
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(threadName)s %(message)s",
)
logger = logging.getLogger("orchestrator")

# Hide child console windows on Windows
CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


def find_claude() -> str | None:
    for name in ("claude.exe", "claude.cmd", "claude"):
        path = shutil.which(name)
        if path:
            return path
    return None


class AgentPanel(Vertical):
    """One agent: status bar + streaming log."""

    status: reactive[str] = reactive("idle")
    started_at: float | None = None
    elapsed: reactive[float] = reactive(0.0)

    def __init__(self, agent: dict) -> None:
        super().__init__(id=f"panel-{agent['id']}", classes="agent-panel")
        self.agent = agent

    def compose(self) -> ComposeResult:
        yield Label(self.agent["title"], classes="agent-title")
        yield Static("", classes="agent-status")
        yield RichLog(wrap=True, markup=True, classes="agent-log")

    def on_mount(self) -> None:
        self.set_interval(0.5, self._tick)
        self._render_status()

    def _tick(self) -> None:
        if self.status == "running" and self.started_at:
            self.elapsed = time.monotonic() - self.started_at
        self._render_status()

    def _render_status(self) -> None:
        color, text = STATUS_STYLE[self.status]
        bar = self.query_one(".agent-status", Static)
        bar.update(f"[{color}]{text}[/]  [dim]{self.elapsed:5.1f}s[/]")

    def log_line(self, line: str) -> None:
        self.query_one(RichLog).write(line)

    def clear_log(self) -> None:
        self.query_one(RichLog).clear()

    def set_status(self, status: str) -> None:
        self.status = status
        if status == "running":
            self.started_at = time.monotonic()
        self._render_status()


class OrchestratorApp(App):
    """Claude-app style multi-agent orchestrator."""

    TITLE = "NEXUS ORCHESTRATOR"
    SUB_TITLE = "parallel claude agents — live progress"

    CSS = """
    Screen { layout: vertical; }
    #agents { height: 2fr; }
    .agent-panel {
        width: 1fr;
        border: round $primary;
        padding: 0 1;
    }
    .agent-title { text-style: bold; color: $accent; }
    .agent-status { height: 1; }
    .agent-log { height: 1fr; background: $surface; }
    #panel-synth { height: 1fr; border: round $success; }
    #task-input { dock: bottom; border: tall $accent; }
    #summary { dock: bottom; height: 1; color: $text-muted; padding: 0 1; }
    """

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("ctrl+c", "quit", "Quit"),
        ("escape", "cancel", "Cancel run"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._procs: list[subprocess.Popen] = []
        self._active_agents = 0
        self._lock = threading.Lock()
        self._cancelled = False
        self._results: dict[str, str] = {}
        self._run_dir: Path | None = None
        self._task: str = ""

    def on_mount(self) -> None:
        self.query_one("#task-input", Input).focus()
        if not MOCK and find_claude() is None:
            self.query_one("#summary", Static).update(
                "[red bold]claude CLI not found on PATH — install Claude Code or run with --mock[/]"
            )

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="agents"):
            for agent in AGENTS:
                yield AgentPanel(agent)
        yield AgentPanel(
            {"id": "synth", "title": "🧠 Synthesis", "tools": "", "prompt": ""}
        )
        yield Static("Type a task and press Enter to launch 3 parallel agents.", id="summary")
        yield Input(placeholder="Describe your task… (Enter to run)", id="task-input")
        yield Footer()

    # ---- launch ----------------------------------------------------------

    @on(Input.Submitted, "#task-input")
    def launch(self, event: Input.Submitted) -> None:
        task = event.value.strip()
        if not task:
            return
        if self._active_agents:
            self.query_one("#summary", Static).update(
                "[yellow]Run in progress — press Escape to cancel first.[/]"
            )
            return
        if not MOCK and find_claude() is None:
            self.query_one("#summary", Static).update(
                "[red bold]claude CLI not found — cannot launch agents.[/]"
            )
            return
        event.input.value = ""
        self._task = task
        self._cancelled = False
        self._results.clear()
        self._procs.clear()
        self._run_dir = RUNS_DIR / datetime.now().strftime("%Y%m%d_%H%M%S")
        self._run_dir.mkdir(parents=True, exist_ok=True)
        (self._run_dir / "task.txt").write_text(task, encoding="utf-8")
        logger.info("run start task=%r dir=%s", task, self._run_dir)

        self.query_one("#summary", Static).update(f"[bold]Task:[/] {task}")
        self.query_one("#panel-synth", AgentPanel).clear_log()
        self.query_one("#panel-synth", AgentPanel).set_status("idle")
        self._active_agents = len(AGENTS)
        for agent in AGENTS:
            panel = self.query_one(f"#panel-{agent['id']}", AgentPanel)
            panel.clear_log()
            panel.set_status("running")
            threading.Thread(
                target=self._run_agent,
                args=(agent, task, panel),
                daemon=True,
                name=f"agent-{agent['id']}",
            ).start()

    # ---- agent worker (background thread) --------------------------------

    def _run_agent(self, agent: dict, task: str, panel: AgentPanel) -> None:
        prompt = agent["prompt"].format(task=task)
        try:
            if MOCK:
                text = self._run_mock(agent, panel)
            else:
                text = self._run_claude(agent["tools"], prompt, panel)
            self._results[agent["id"]] = text
            self._persist(agent["id"], text)
            status = "cancelled" if self._cancelled else "done"
            self.call_from_thread(panel.set_status, status)
            logger.info("agent %s finished status=%s chars=%d", agent["id"], status, len(text))
        except TimeoutError:
            self.call_from_thread(panel.log_line, f"[red]agent exceeded {AGENT_TIMEOUT_SECS}s — killed[/]")
            self.call_from_thread(panel.set_status, "timeout")
            self._results[agent["id"]] = "(timed out)"
            logger.warning("agent %s timeout", agent["id"])
        except Exception as exc:  # surface failures in the panel, never crash TUI
            if self._cancelled:
                self.call_from_thread(panel.set_status, "cancelled")
            else:
                self.call_from_thread(panel.log_line, f"[red]{exc}[/]")
                self.call_from_thread(panel.set_status, "error")
            self._results[agent["id"]] = f"(error: {exc})"
            logger.exception("agent %s failed", agent["id"])
        finally:
            with self._lock:
                self._active_agents -= 1
                last = self._active_agents == 0
            if last:
                self.call_from_thread(self._agents_done)

    def _run_claude(self, tools: str, prompt: str, panel: AgentPanel | None) -> str:
        cmd = [find_claude(), "-p", "--output-format", "stream-json", "--verbose"]
        if tools:
            cmd += ["--allowedTools", tools]
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=CREATE_NO_WINDOW,
        )
        self._procs.append(proc)
        proc.stdin.write(prompt)
        proc.stdin.close()

        killer = threading.Timer(AGENT_TIMEOUT_SECS, proc.kill)
        killer.start()
        timed_out = True  # assume worst; cleared when stream ends before timer fires
        collected: list[str] = []
        try:
            for line in proc.stdout:
                line = line.strip()
                if not line:
                    continue
                for out, is_text in self._format_event(line):
                    if is_text:
                        collected.append(out)
                    if panel is not None:
                        self.call_from_thread(panel.log_line, out)
            timed_out = not killer.is_alive() and proc.returncode is None
        finally:
            killer.cancel()
        rc = proc.wait()
        if self._cancelled:
            return "\n".join(collected)
        if timed_out or rc == -9:
            raise TimeoutError
        if rc != 0:
            raise RuntimeError(f"claude exited with code {rc}")
        return "\n".join(collected)

    @staticmethod
    def _format_event(line: str) -> list[tuple[str, bool]]:
        """Turn one stream-json event into (display_line, is_result_text) pairs."""
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            return [(line, False)]
        etype = event.get("type")
        if etype == "system" and event.get("subtype") == "init":
            return [(f"[dim]session {event.get('session_id', '')[:8]} started[/]", False)]
        if etype == "assistant":
            out: list[tuple[str, bool]] = []
            for block in event.get("message", {}).get("content", []):
                if block.get("type") == "text" and block.get("text", "").strip():
                    out.append((block["text"].strip(), True))
                elif block.get("type") == "tool_use":
                    name = block.get("name", "?")
                    hint = str(block.get("input", {}))[:60]
                    out.append((f"[cyan]⚙ {name}[/] [dim]{hint}[/]", False))
            return out
        if etype == "result":
            cost = event.get("total_cost_usd") or 0
            return [(f"[green]── result ──[/] [dim](${cost:.4f})[/]", False)]
        return []

    def _run_mock(self, agent: dict, panel: AgentPanel) -> str:
        steps = [
            f"[dim]session mock-{agent['id']} started[/]",
            f"[cyan]⚙ {'WebSearch' if 'Web' in agent['tools'] else 'Grep'}[/] [dim]querying…[/]",
            "Found 3 relevant items.",
            f"[cyan]⚙ {'WebFetch' if 'WebFetch' in agent['tools'] else 'Read'}[/] [dim]fetching detail…[/]",
            f"Synthesized findings for agent '{agent['id']}'.",
            "[green]── result ──[/] [dim]($0.0000)[/]",
        ]
        for step in steps:
            if self._cancelled:
                raise RuntimeError("cancelled")
            time.sleep(0.6)
            self.call_from_thread(panel.log_line, step)
        return f"mock findings from {agent['id']}"

    # ---- synthesis stage ---------------------------------------------------

    def _agents_done(self) -> None:
        if self._cancelled:
            self.query_one("#summary", Static).update("[magenta]Run cancelled.[/]")
            return
        self.query_one("#summary", Static).update(
            "[bold]Agents done — synthesizing…[/]"
        )
        panel = self.query_one("#panel-synth", AgentPanel)
        panel.set_status("running")
        threading.Thread(
            target=self._run_synthesis, daemon=True, name="agent-synth"
        ).start()

    def _run_synthesis(self) -> None:
        panel = self.query_one("#panel-synth", AgentPanel)
        try:
            if MOCK:
                time.sleep(1)
                text = "mock unified answer"
                self.call_from_thread(panel.log_line, text)
            else:
                prompt = SYNTH_PROMPT.format(
                    task=self._task,
                    research=self._results.get("research", "(missing)"),
                    code=self._results.get("code", "(missing)"),
                    local=self._results.get("local", "(missing)"),
                )
                text = self._run_claude("", prompt, panel)
            self._persist("synthesis", text)
            self.call_from_thread(panel.set_status, "done")
            self.call_from_thread(
                self.query_one("#summary", Static).update,
                f"[green bold]Done.[/] Saved to [u]{self._run_dir}[/] — type new task to run again.",
            )
            logger.info("synthesis done chars=%d", len(text))
        except Exception as exc:
            self.call_from_thread(panel.log_line, f"[red]{exc}[/]")
            self.call_from_thread(panel.set_status, "error")
            logger.exception("synthesis failed")

    # ---- persistence / lifecycle -------------------------------------------

    def _persist(self, name: str, text: str) -> None:
        if self._run_dir is None:
            return
        try:
            (self._run_dir / f"{name}.md").write_text(text, encoding="utf-8")
        except OSError:
            logger.exception("failed to persist %s", name)

    def action_cancel(self) -> None:
        if not self._active_agents:
            return
        self._cancelled = True
        for proc in self._procs:
            if proc.poll() is None:
                proc.kill()
        logger.info("run cancelled by user")

    def action_quit(self) -> None:
        self._cancelled = True
        for proc in self._procs:
            if proc.poll() is None:
                proc.kill()
        self.exit()


if __name__ == "__main__":
    OrchestratorApp().run()
