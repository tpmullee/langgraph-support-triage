const logEl = document.getElementById("log");
const form = document.getElementById("chat-form");
const input = document.getElementById("message");
const approvalEl = document.getElementById("approval");
const approveBtn = document.getElementById("approve");
const denyBtn = document.getElementById("deny");
const approvalText = document.getElementById("approval-text");

let threadId = null;
let paused = false;

function addMsg(role, content){
  const div = document.createElement("div");
  div.className = `msg ${role}`;
  div.innerHTML = `<strong>${role}:</strong> ${content}`;
  logEl.appendChild(div);
  logEl.scrollTop = logEl.scrollHeight;
}

async function postChat(body){
  const res = await fetch("/chat", {
    method: "POST",
    headers: {"Content-Type":"application/json"},
    body: JSON.stringify(body),
  });
  if(!res.ok){
    const text = await res.text();
    throw new Error(text || `HTTP ${res.status}`);
  }
  return res.json();
}

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  const msg = input.value.trim();
  if(!msg) return;
  addMsg("user", msg);
  input.value = "";
  approvalEl.classList.add("hidden");

  try {
    const payload = { message: msg };
    if (threadId) payload.thread_id = threadId;

    const out = await postChat(payload);
    threadId = out.thread_id;

    if (out.status === "PAUSED_FOR_APPROVAL") {
      paused = true;
      approvalEl.classList.remove("hidden");
      approvalText.textContent = (out.interrupt && out.interrupt.message) ? out.interrupt.message : "Approval required.";
      addMsg("system", "⏸ Awaiting reviewer decision…");
    } else {
      paused = false;
      const last = out.action_result || (out.messages?.slice(-1)[0]?.content ?? "");
      if (last) addMsg("assistant", last);
    }
  } catch (err) {
    addMsg("system", `Error: ${err.message}`);
    console.error(err);
  }
});

approveBtn?.addEventListener("click", () => handleDecision(true));
denyBtn?.addEventListener("click", () => handleDecision(false));

async function handleDecision(approval){
  if (!paused || !threadId) return;
  approvalEl.classList.add("hidden");
  addMsg("system", approval ? "✅ Reviewer approved" : "❌ Reviewer denied");
  try {
    const out = await postChat({
      thread_id: threadId,
      message: "resume",
      approval
    });
    paused = false;
    const last = out.action_result || (out.messages?.slice(-1)[0]?.content ?? "");
    if (last) addMsg("assistant", last);
  } catch (err) {
    addMsg("system", `Error resuming: ${err.message}`);
    console.error(err);
  }
}
