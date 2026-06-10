"""Headless smoke test for orchestrator_tui (mock mode, no API calls)."""

import asyncio
import sys

sys.argv.append("--mock")  # force mock before module import reads sys.argv

import orchestrator_tui
from orchestrator_tui import AGENTS, AgentPanel, OrchestratorApp

assert orchestrator_tui.MOCK, "mock mode not active"


async def main() -> None:
    app = OrchestratorApp()
    async with app.run_test(size=(120, 40)) as pilot:
        task_input = app.query_one("#task-input")
        task_input.focus()
        task_input.value = "test task"
        await pilot.pause()
        await pilot.press("enter")

        panels = {p.agent["id"]: p for p in app.query(AgentPanel)}
        assert set(panels) == {"research", "code", "local", "synth"}, panels.keys()

        # workers running
        await pilot.pause(0.5)
        statuses = {k: p.status for k, p in panels.items() if k != "synth"}
        print("after launch:", statuses)
        assert all(s == "running" for s in statuses.values()), statuses

        # wait for agents + synthesis
        for _ in range(40):
            await pilot.pause(0.5)
            if panels["synth"].status == "done":
                break
        statuses = {k: p.status for k, p in panels.items()}
        print("final:", statuses)
        assert all(s == "done" for s in statuses.values()), statuses

        # logs populated
        for k, p in panels.items():
            assert len(p.query_one("RichLog").lines) > 0, f"{k} log empty"

        # persistence: run dir contains task + per-agent + synthesis files
        run_dir = app._run_dir
        assert run_dir is not None and run_dir.exists(), run_dir
        names = {f.name for f in run_dir.iterdir()}
        expected = {"task.txt", "synthesis.md"} | {f"{a['id']}.md" for a in AGENTS}
        assert expected <= names, f"missing {expected - names}"
        print("persisted:", sorted(names))
        print("PASS: agents + synthesis completed, outputs persisted")


asyncio.run(main())
