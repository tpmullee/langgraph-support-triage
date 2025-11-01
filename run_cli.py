import uuid
from app import graph, GraphState

def run_once(text: str, thread_id=None, approval=None):
    thread_id = thread_id or uuid.uuid4().hex
    state: GraphState = {
        "messages":[{"role":"user","content":text}],
        "intent": None, "risk": None, "action_result": None,
        "approval": approval
    }
    try:
        out = graph.invoke(state, config={"configurable":{"thread_id":thread_id}})
        print("DONE", out["intent"], out["risk"], out["action_result"])
        return thread_id
    except Exception as e:
        if "interrupt" in str(e).lower():
            print("PAUSED_FOR_APPROVAL", thread_id)
            return thread_id
        raise

if __name__ == "__main__":
    tid = run_once("I want a refund of $42 please.")
    # Later…
    tid = run_once("resume", thread_id=tid, approval=True)
