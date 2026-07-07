# Legacy — previous iteration (pre-harness)

This directory quarantines the **previous iteration** of Proximity Swarm: the terminal TUI
(`terminal_dashboard.py`, launched via `cli.py`), the one-shot research-report mode
(`run_swarm_research.py`, `research_report.md`), and the tests that are hard-wired to the TUI
(`legacy/tests/`).

**Do not develop, test, or fix against anything in here.** The current product is the headless
logic-research harness described in `designs/implementation_plan.md` (entry point:
`supervisor.py --run-spec <spec.json>`; optional observability UI: `web_dashboard.py`). The test
suite is `python3 -m unittest discover -s tests`, which intentionally does not discover
`legacy/tests/`.

The quarantined tests cover pruning/hierarchy/personality flows *through the old TUI module*; if
that coverage is wanted back, re-point those tests at the supervisor/monitor APIs rather than
resurrecting the TUI.
