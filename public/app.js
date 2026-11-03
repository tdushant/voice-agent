const log = document.querySelector("#log");
const chips = document.querySelector("#chips");
const mic = document.querySelector("#mic");
const hint = document.querySelector("#hint");
const form = document.querySelector("#form");
const text = document.querySelector("#text");
const hands = document.querySelector("#hands");
const phase = document.querySelector("#phase");
const latency = document.querySelector("#latency");
const customer = document.querySelector("#customer");
const accounts = document.querySelector("#accounts");
const card = document.querySelector("#card");
const txns = document.querySelector("#txns");
const pending = document.querySelector("#pending");
const reset = document.querySelector("#reset");
const keyhint = document.querySelector("#keyhint");

const USUAL = [
  "What's my balance?",
  "Recent charges",
  "Move 50 dollars to savings",
  "Freeze my card",
  "Why was I charged for Netflix?",
];

let listening = false;
let recognition = null;
let lastSpoken = "";
let turnId = 0;
let llmReady = false;

function setPhase(name, hot) {
  phase.textContent = name;
  phase.classList.toggle("hot", Boolean(hot));
}

function setLatency(label) {
  latency.textContent = label;
}

function render(state) {
  customer.textContent = state.name;
  accounts.replaceChildren();
  for (const acct of state.accounts) {
    const el = document.createElement("article");
    el.className = "acct";
    const label = document.createElement("span");
    label.textContent = `${acct.name} ····${acct.mask}`;
    const money = document.createElement("strong");
    money.textContent = acct.display;
    el.append(label, money);
    accounts.append(el);
  }
  const frozen = state.card === "frozen";
  card.textContent = frozen ? "Debit card frozen" : "Debit card active";
  card.className = frozen ? "pill frozen" : "pill live";
  txns.replaceChildren();
  for (const row of state.txns.slice(0, 5)) {
    const li = document.createElement("li");
    const name = document.createElement("span");
    name.textContent = `${row.account} · ${row.desc}`;
    const amt = document.createElement("b");
    amt.textContent = row.display;
    amt.className = row.cents < 0 ? "out" : "in";
    li.append(name, amt);
    txns.append(li);
  }
  pending.hidden = !state.pending;
  pending.textContent = state.pending || "";
  drawChips(state);
}

function drawChips(state) {
  const labels = state.pending && state.pending.startsWith("Say confirm")
    ? ["Confirm", "Cancel"]
    : USUAL;
  chips.replaceChildren();
  for (const label of labels) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = label;
    button.addEventListener("click", () => ask(label));
    chips.append(button);
  }
}

function setModel(on) {
  llmReady = on;
  keyhint.hidden = on;
  keyhint.textContent = on
    ? ""
    : "Open questions need a free Groq key in .env (GROQ_API_KEY). Refresh after saving. Scripted banking already works.";
}

function addLine(who, value) {
  const el = document.createElement("p");
  el.className = who;
  el.textContent = value;
  log.append(el);
  while (log.children.length > 10) log.firstChild.remove();
  log.scrollTop = log.scrollHeight;
  return el;
}

function pickVoice() {
  const voices = speechSynthesis.getVoices();
  return (
    voices.find((voice) => /natural/i.test(voice.name) && /en-US/i.test(voice.lang)) ||
    voices.find((voice) => /en-US/i.test(voice.lang)) ||
    null
  );
}

function isEcho(heard) {
  const said = heard.toLowerCase().replace(/[^a-z0-9 ]/g, "").trim();
  const spoken = lastSpoken.toLowerCase().replace(/[^a-z0-9 ]/g, "").trim();
  if (!said || !spoken) return false;
  if (said === spoken) return true;
  return said.length > 24 && spoken.includes(said) && said.length / spoken.length > 0.7;
}

function speak(value, after) {
  lastSpoken = value;
  if (!window.speechSynthesis) {
    after?.();
    return;
  }
  const gen = ++speak.gen;
  speechSynthesis.cancel();
  const utterance = new SpeechSynthesisUtterance(value);
  utterance.lang = "en-US";
  utterance.rate = 1.03;
  utterance.voice = pickVoice();
  utterance.onend = () => {
    if (gen !== speak.gen) return;
    setPhase("Ready", false);
    after?.();
  };
  setPhase("Speaking", false);
  setTimeout(() => {
    if (gen === speak.gen) speechSynthesis.speak(utterance);
  }, 40);
}
speak.gen = 0;

function stopSpeaking() {
  speak.gen += 1;
  speechSynthesis?.cancel();
}

async function ask(value) {
  const cleaned = value.trim();
  if (!cleaned) return;
  stopMic();
  stopSpeaking();
  const id = ++turnId;
  addLine("you", cleaned);
  const slot = addLine("agent", "…");
  setPhase("Checking", false);
  try {
    const res = await fetch("/api/turn", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      cache: "no-store",
      body: JSON.stringify({ text: cleaned }),
    });
    const data = await res.json();
    if (id !== turnId) return;
    slot.textContent = data.speech;
    render(data.state);
    setModel(data.llm);
    const via = data.source === "model" ? data.model : data.source === "fallback" ? "model off" : "ledger · 0 tokens";
    setLatency(`${data.ms} ms · ${via}`);
    log.scrollTop = log.scrollHeight;
    speak(data.speech, () => {
      if (hands.checked && id === turnId) startMic();
    });
  } catch {
    if (id !== turnId) return;
    slot.textContent = "The desk didn't answer. Try that again.";
    setPhase("Ready", false);
  }
}

function startMic() {
  const Rec = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!Rec) {
    hint.textContent = "This browser has no speech recognition. Type instead.";
    return;
  }
  stopSpeaking();
  recognition?.abort();
  const rec = new Rec();
  recognition = rec;
  rec.lang = "en-US";
  rec.interimResults = true;
  rec.continuous = false;
  listening = true;
  mic.setAttribute("aria-pressed", "true");
  mic.querySelector(".mic-label").textContent = "Stop";
  hint.textContent = "Listening…";
  setPhase("Listening", true);
  rec.onresult = (event) => {
    let finalText = "";
    let interim = "";
    for (const result of event.results) {
      if (result.isFinal) finalText += result[0].transcript;
      else interim += result[0].transcript;
    }
    hint.textContent = finalText || interim || "Listening…";
    if (!finalText) return;
    const heard = finalText.trim();
    if (!isEcho(heard)) ask(heard);
  };
  rec.onerror = (event) => {
    if (event.error === "not-allowed") hint.textContent = "Microphone blocked. Type the question instead.";
    else hint.textContent = "Tap or press Space";
  };
  rec.onend = () => {
    listening = false;
    mic.setAttribute("aria-pressed", "false");
    mic.querySelector(".mic-label").textContent = "Speak";
    if (hint.textContent === "Listening…") hint.textContent = "Tap or press Space";
    if (phase.textContent === "Listening") setPhase("Ready", false);
  };
  rec.start();
}

function stopMic() {
  listening = false;
  mic.setAttribute("aria-pressed", "false");
  mic.querySelector(".mic-label").textContent = "Speak";
  recognition?.abort();
  recognition = null;
}

mic.addEventListener("click", () => (listening ? stopMic() : startMic()));

form.addEventListener("submit", (event) => {
  event.preventDefault();
  const value = text.value;
  text.value = "";
  ask(value);
});

document.addEventListener("keydown", (event) => {
  if (event.code !== "Space" || event.repeat || event.target.closest("input, textarea, button, a")) return;
  event.preventDefault();
  listening ? stopMic() : startMic();
});

reset.addEventListener("click", async () => {
  stopMic();
  stopSpeaking();
  turnId += 1;
  const data = await fetch("/api/reset", { method: "POST" }).then((res) => res.json());
  log.replaceChildren();
  addLine("agent", "Hi Alex. I can check a balance, recent activity, move money between your accounts, or freeze your card.");
  render(data.state);
  setLatency("Ledger on device");
  setPhase("Ready", false);
  hint.textContent = "Tap or press Space";
});

speechSynthesis?.addEventListener?.("voiceschanged", pickVoice);

fetch("/api/state", { cache: "no-store" })
  .then((res) => res.json())
  .then((data) => {
    render(data.state);
    setModel(data.llm);
    setLatency(data.llm ? "Groq ready · ledger still answers first" : "Ledger only");
  })
  .catch(() => setLatency("Server not reachable"));
