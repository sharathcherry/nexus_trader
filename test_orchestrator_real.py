"""Real end-to-end test: spawns actual claude CLI agents headlessly."""

import asyncio

from orchestrator_tui import AGENTS, AgentPanel, OrchestratorApp


async def main() -> None:
    app = OrchestratorApp()
    async with app.run_test(size=(120, 40)) as pilot:
        task_input = app.query_one("#task-input")
        task_input.focus()
        task_input.value = "what does the dashboard server in this project do"
        await pilot.pause()
        await pilot.press("enter")

        panels = {p.agent["id"]: p for p in app.query(AgentPanel)}

        # wait up to 8 minutes for agents + synthesis
        for i in range(480):
            await pilot.pause(1.0)
            statuses = {k: p.status for k, p in panels.items()}
            if i % 15 == 0:
                print(f"[{i}s]", statuses, flush=True)
            if panels["synth"].status in ("done", "error"):
                break

        statuses = {k: p.status for k, p in panels.items()}
        print("final:", statuses)
        run_dir = app._run_dir
        if run_dir:
            print("run dir:", run_dir)
            for f in sorted(run_dir.iterdir()):
                print(f"  {f.name}: {f.stat().st_size} bytes")
        ok = all(s == "done" for s in statuses.values())
        print("PASS" if ok else "FAIL", statuses)
        raise SystemExit(0 if ok else 1)


asyncio.run(main())
