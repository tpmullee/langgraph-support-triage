# Support Triage Autopilot (LangGraph 1.0)

A tiny but real **LangGraph** app that demonstrates stateful control-flow, a **human approval gate** (interrupt → resume), and persisted state via a SQLite checkpointer. Product managers can use this as a pattern for “stop-before-money/legal” workflows.

## Why LangGraph (not just one LLM call)?
- **Declarative graph**: route by intent (`faq` / `issue` / `refund`) with explicit nodes.
- **Human-in-the-loop**: `interrupt()` pauses at risky steps; resume with a decision.
- **Persistence**: SQLite checkpointer for durable threads and resumability.

## Quickstart (Python 3.12)
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m uvicorn app:app --reload --port 8000
# UI → http://127.0.0.1:8000/ui/
