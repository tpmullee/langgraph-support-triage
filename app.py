from __future__ import annotations
import json, os, uuid
from typing import TypedDict, Literal, List, Optional

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

# LangGraph 1.0 core
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.sqlite import SqliteSaver  # from langgraph-checkpoint-sqlite
from langgraph.types import interrupt, Command       # interrupt + Command(resume=...) pattern

# ---------- Domain "state" ----------
class Message(TypedDict):
    role: Literal["user", "system", "assistant"]
    content: str

class GraphState(TypedDict):
    messages: List[Message]
    intent: Optional[Literal["faq", "issue", "refund", "unknown"]]
    risk: Optional[Literal["low", "high"]]
    action_result: Optional[str]
    approval: Optional[bool]  # set by human approval gate on resume

# ---------- Tiny tools ----------
def load_kb():
    with open("kb.json", "r") as f:
        return json.load(f)

KB = load_kb()

def tool_kb_search(query: str) -> str:
    q = query.lower()
    for row in KB:
        if row["q"] in q:
            return f"FAQ: {row['a']}"
    return "No FAQ match."

def tool_create_ticket(text: str) -> str:
    ticket_id = "T-" + uuid.uuid4().hex[:8]
    return f"Created ticket {ticket_id} for: {text}"

def tool_issue_refund(amount: float) -> str:
    return f"Refund issued: ${amount:.2f}"

# ---------- Classifier (mock model) ----------
def classify_intent(message: str) -> tuple[str, str]:
    """
    Returns (intent, risk)
    - 'refund' intents are 'high' risk (require human approval)
    - 'faq' and 'issue' are 'low' risk
    """
    m = message.lower()
    if any(k in m for k in ["refund", "chargeback", "money back"]):
        return "refund", "high"
    if any(k in m for k in ["hours", "policy", "contact"]):
        return "faq", "low"
    if any(k in m for k in ["bug", "error", "issue", "broken"]):
        return "issue", "low"
    return "unknown", "low"

# ---------- Graph nodes ----------
def _last_user(state: GraphState) -> str:
    return next((m["content"] for m in reversed(state["messages"]) if m["role"] == "user"), "")

def node_classify(state: GraphState) -> GraphState:
    user_msg = _last_user(state)
    intent, risk = classify_intent(user_msg)
    state["intent"] = intent  # type: ignore
    state["risk"] = risk      # type: ignore
    return state

def node_handle_faq(state: GraphState) -> GraphState:
    ans = tool_kb_search(_last_user(state))
    state["action_result"] = ans
    state["messages"].append({"role": "assistant", "content": ans})
    return state

def node_handle_issue(state: GraphState) -> GraphState:
    res = tool_create_ticket(_last_user(state))
    state["action_result"] = res
    state["messages"].append({"role": "assistant", "content": res})
    return state

def node_human_gate(state: GraphState) -> GraphState:
    """
    Pause and surface a decision to the client. In LangGraph 1.0, interrupt()
    returns a value when resumed via Command(resume=...) (e.g., True/False). :contentReference[oaicite:2]{index=2}
    """
    if state.get("approval") is None:
        approved = interrupt({"message": "Approval required for refund. Resume with true/false."})
        state["approval"] = bool(approved)
    return state

def node_handle_refund(state: GraphState) -> GraphState:
    approved = bool(state.get("approval"))
    if not approved:
        msg = "Refund request denied by reviewer."
        state["action_result"] = msg
        state["messages"].append({"role": "assistant", "content": msg})
        return state

    # naive amount parse
    user_msg = _last_user(state)
    amount = 0.0
    for tok in user_msg.replace("$", " ").split():
        try:
            amount = float(tok)
            break
        except:
            pass
    if amount <= 0:
        amount = 20.00  # default demo

    res = tool_issue_refund(amount)
    state["action_result"] = res
    state["messages"].append({"role": "assistant", "content": res})
    return state

def node_fallback(state: GraphState) -> GraphState:
    msg = "I couldn’t classify that. I created a ticket to follow up."
    t = tool_create_ticket(_last_user(state))
    state["action_result"] = f"{msg} {t}"
    state["messages"].append({"role": "assistant", "content": state["action_result"]})
    return state

# ---------- Build graph ----------
builder = StateGraph(GraphState)

builder.add_node("classify", node_classify)
builder.add_node("faq", node_handle_faq)
builder.add_node("issue", node_handle_issue)
builder.add_node("human_gate", node_human_gate)
builder.add_node("refund", node_handle_refund)
builder.add_node("fallback", node_fallback)

def router(state: GraphState):
    intent = state.get("intent")
    risk = state.get("risk")
    if intent == "faq":
        return "faq"
    if intent == "issue":
        return "issue"
    if intent == "refund":
        return "human_gate" if risk == "high" else "refund"
    return "fallback"

builder.add_edge(START, "classify")
builder.add_conditional_edges(
    "classify",
    router,
    {
        "faq": "faq",
        "issue": "issue",
        "human_gate": "human_gate",
        "refund": "refund",
        "fallback": "fallback",
    },
)
builder.add_edge("human_gate", "refund")
builder.add_edge("faq", END)
builder.add_edge("issue", END)
builder.add_edge("refund", END)
builder.add_edge("fallback", END)

# ---------- Persistence (SQLite checkpointer) ----------
# Checkpoints enable pause/resume & durable state per thread. :contentReference[oaicite:3]{index=3}
os.makedirs(".checkpoints", exist_ok=True)
checkpointer = SqliteSaver.from_conn_string(".checkpoints/state.sqlite3")
graph = builder.compile(checkpointer=checkpointer)

# ---------- FastAPI ----------
app = FastAPI(title="LangGraph Support Triage Demo (LG 1.0)")

# Serve the UI (ui/index.html, ui/app.js, ui/styles.css)
# StaticFiles pattern per FastAPI docs. :contentReference[oaicite:4]{index=4}
app.mount("/ui", StaticFiles(directory="ui", html=True), name="ui")

@app.get("/")
def root():
    return RedirectResponse(url="/ui/")

class Inbound(BaseModel):
    thread_id: Optional[str] = None
    message: str
    approval: Optional[bool] = None  # set when resuming after pause

@app.post("/chat")
def chat(inp: Inbound):
    """
    - Fresh call: POST {message} → graph may PAUSE via interrupt()
    - Resume call: POST {thread_id, approval: true/false} → we pass Command(resume=...)
      back into the node that interrupted. :contentReference[oaicite:5]{index=5}
    """
    thread_id = inp.thread_id or uuid.uuid4().hex
    config = {"configurable": {"thread_id": thread_id}}

    if inp.approval is not None:
        # Resume the node that called interrupt(), with the provided boolean
        result = graph.invoke(Command(resume=bool(inp.approval)), config=config)
    else:
        # Start/continue normal turn with a user message
        state_in: GraphState = {
            "messages": [{"role": "user", "content": inp.message}],
            "intent": None,
            "risk": None,
            "action_result": None,
            "approval": None,
        }
        result = graph.invoke(state_in, config=config)

    # If a node called interrupt(), LangGraph returns an interrupt payload to the caller
    if isinstance(result, dict) and "__interrupt__" in result:
        return {
            "thread_id": thread_id,
            "status": "PAUSED_FOR_APPROVAL",
            "message": "Approval required. POST again with the same thread_id and approval=true/false.",
            "interrupt": result["__interrupt__"],
        }

    # Otherwise, finished
    return {
        "thread_id": thread_id,
        "status": "DONE",
        "intent": result.get("intent"),
        "risk": result.get("risk"),
        "action_result": result.get("action_result"),
        "messages": result.get("messages"),
    }
