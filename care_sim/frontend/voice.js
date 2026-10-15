(() => {
  const $ = selector => document.querySelector(selector);
  const state = { persona: "patient", busy: false };
  const voiceButton = $("#voice-button"), stream = $("#stream"), transcript = $("#transcript"), history = $("#history");
  const escape = text => text.replace(/[&<>]/g, char => ({"&":"&amp;","<":"&lt;",">":"&gt;"}[char]));
  const setState = (label, help) => { $("#voice-label").textContent = label; $("#voice-help").textContent = help; };
  const addTurn = (speaker, text, trace = "") => history.insertAdjacentHTML("afterbegin", `<div class="turn"><b>${escape(speaker)}</b><p>${escape(text)}</p>${trace ? `<div class="trace">${escape(trace)}</div>` : ""}</div>`);
  const setStreaming = (text, active = false) => { stream.innerHTML = `${escape(text)}${active ? '<span class="cursor" aria-hidden="true"></span>' : ""}`; };
  const audioState = name => { voiceButton.classList.toggle("speaking", name === "speaking"); voiceButton.classList.toggle("listening", name === "listening"); };
  const sentenceParts = text => text.match(/[^.!?]+[.!?]+|[^.!?]+$/g) || [text];
  async function say(text) {
    audioState("speaking");
    try {
      const response = await fetch("/api/tts", { method: "POST", headers: {"content-type":"application/json"}, body: JSON.stringify({text}) });
      if (response.ok) {
        const url = URL.createObjectURL(await response.blob()), audio = new Audio(url);
        await new Promise(resolve => { audio.onended = () => { URL.revokeObjectURL(url); resolve(); }; audio.onerror = resolve; audio.play().catch(resolve); });
        return;
      }
    } catch (_) { /* Browser speech is the intended fallback. */ }
    if ("speechSynthesis" in window) {
      for (const part of sentenceParts(text)) await new Promise(resolve => { const utterance = new SpeechSynthesisUtterance(part); utterance.rate = .98; utterance.onend = utterance.onerror = resolve; speechSynthesis.speak(utterance); });
    }
  }
  function parseEventBlock(block) { const data = block.split("\n").find(line => line.startsWith("data: ")); return data ? JSON.parse(data.slice(6)) : null; }
  async function send(text = $("#text").value) {
    text = text.trim(); if (!text || state.busy) return;
    state.busy = true; $("#text").value = ""; $("#send").disabled = true; voiceButton.disabled = true;
    transcript.textContent = text; addTurn("You", text); setStreaming("", true); setState("Thinking…", "CareLoop is preparing a private response.");
    let responseText = "", buffer = "";
    try {
      const response = await fetch("/api/chat/stream", {method:"POST",headers:{"content-type":"application/json"},body:JSON.stringify({persona:state.persona,text})});
      if (!response.ok || !response.body) throw new Error("stream unavailable");
      const reader = response.body.getReader(), decoder = new TextDecoder();
      for (;;) {
        const { value, done } = await reader.read(); buffer += decoder.decode(value || new Uint8Array(), {stream:!done});
        const blocks = buffer.split("\n\n"); buffer = blocks.pop();
        for (const block of blocks) {
          const event = parseEventBlock(block); if (!event) continue;
          if (event.type === "assistant_delta") { responseText += event.text; setStreaming(responseText, true); }
          if (event.type === "tool") addTurn("CareLoop", "Private action checked.", `${event.tool.tool} · ${event.tool.ok ? "available" : "unavailable"}`);
          if (event.type === "error") throw new Error(event.message);
        }
        if (done) break;
      }
      setStreaming(responseText); addTurn("CareLoop", responseText); setState("Here’s what I found", "You can continue talking or type another request."); await say(responseText);
    } catch (error) {
      const message = error.message || "The private CareLoop connection is unavailable. Check that the service and simulator are running.";
      setStreaming(message); addTurn("CareLoop", message); setState("Connection needed", "Check the local CareLoop services and try again."); await say(message);
    } finally { state.busy = false; $("#send").disabled = false; voiceButton.disabled = false; audioState(""); }
  }
  function listen() {
    if (state.busy) return;
    const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!Recognition) { setState("Voice capture isn’t available", "Type a request below; spoken output will still work."); return; }
    const recognition = new Recognition(); recognition.lang = "en-US"; recognition.interimResults = true; recognition.continuous = false;
    setState("Listening…", "Speak naturally. I’ll show the words as you speak."); audioState("listening"); transcript.innerHTML = "<span>Listening…</span>";
    recognition.onresult = event => { const words = Array.from(event.results).map(result => result[0].transcript).join(""); transcript.textContent = words; if (event.results[event.results.length - 1].isFinal) { recognition.stop(); send(words); } };
    recognition.onerror = () => setState("I didn’t catch that", "Tap the voice button to try again, or type below.");
    recognition.onend = () => { if (!state.busy) audioState(""); }; recognition.start();
  }
  document.querySelectorAll("[data-persona]").forEach(button => button.addEventListener("click", () => {
    state.persona = button.dataset.persona; document.body.classList.toggle("caregiver", state.persona === "caregiver"); document.querySelectorAll("[data-persona]").forEach(item => item.setAttribute("aria-pressed", item === button));
    const message = state.persona === "caregiver" ? "Caregiver session active. Only generic status is visible here." : "Patient session active. Your private CareLoop view is ready.";
    transcript.innerHTML = `<span>${escape(message)}</span>`; setStreaming(""); addTurn("CareLoop", message);
  }));
  $("#composer").addEventListener("submit", event => { event.preventDefault(); send(); }); voiceButton.addEventListener("click", listen); document.querySelectorAll(".quick button").forEach(button => button.addEventListener("click", () => send(button.textContent)));
  fetch("/api/config").then(response => response.json()).then(config => { $("#connection").innerHTML = `<span class="status-dot"></span>Private CareLoop ready`; $("#connection-copy").textContent = `Model: ${config.llm} · Voice: ${config.voice} · Listening: ${config.stt}`; $("#state").textContent = "Private CareLoop connection ready"; }).catch(() => { $("#connection").textContent = "Waiting for local services"; $("#connection-copy").textContent = "Start CareLoop and the voice simulator, then refresh."; });
  addTurn("CareLoop", "Welcome. Choose a private session and ask about a planned demo task.");
})();
