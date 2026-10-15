(() => {
  "use strict";
  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => [...el.querySelectorAll(s)];
  const SHOW_CHIPS = [
    "Alexa, I got a new care plan from my clinic",
    "Alexa, approve my plan",
    "Alexa, let my brother Sam see my tasks and get updates for two weeks",
    "Alexa, do my check-in",
    "Alexa, my pain is 8 yesterday",
    "Alexa, my pain is 9",
    "Alexa, get me ready for my appointment",
    "Alexa, who has access to my care?",
    "Alexa, remove Sam",
    "Alexa, should I double my medication?",
    "Alexa, is my document ready?",
  ];
  const DOT_CHIPS = [
    "Alexa, any CareLoop updates?",
    "Alexa, mark it seen",
    "Alexa, what was Maya's pain score?",
    "Alexa, show Maya's tasks",
  ];

  // ---- API ------------------------------------------------------------------
  async function api(path, body) {
    const init = body === undefined ? {} : { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) };
    const res = await fetch(path, init);
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || "Request failed");
    return data;
  }

  // ---- device visuals ---------------------------------------------------------
  const devices = { show: $("#device-show"), dot: $("#device-dot") };
  function setState(id, state) {
    devices[id].dataset.state = state;
    $(`#${id}-state`).textContent = state;
  }
  function bubble(text, who = "assistant") {
    if (!text) return;
    $("#home").hidden = true;
    const convo = $("#convo"); convo.hidden = false;
    const b = document.createElement("div"); b.className = "bubble " + who; b.textContent = text;
    convo.append(b);
    while (convo.children.length > 6) convo.firstChild.remove();
    $("#screen").scrollTop = 0;
  }
  function tick() { $("#clock").textContent = new Date().toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }); }
  setInterval(tick, 15000); tick();

  // ---- voice engines: Kokoro/Whisper on the host when ready, browser speech otherwise ----
  let voiceCfg = { tts: "browser", stt: "browser" };
  const engineLabel = { kokoro: "Kokoro", whisper: "Whisper", browser: "browser", loading: "loading…" };
  async function loadVoice() {
    try { voiceCfg = await api("/api/voice"); } catch { /* keep browser defaults */ }
    $("#voice-engines").textContent = `Voice: ${engineLabel[voiceCfg.tts] || voiceCfg.tts} · Listening: ${engineLabel[voiceCfg.stt] || voiceCfg.stt}`;
    if (voiceCfg.tts === "loading" || voiceCfg.stt === "loading") setTimeout(loadVoice, 2000);
  }
  const useKokoro = () => voiceCfg.tts === "kokoro";
  const useWhisper = () => voiceCfg.stt === "whisper";
  const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  const status = (t) => { $("#voice-status").textContent = t; };

  // ---- speech output (TTS) with barge-in --------------------------------------------------
  let speakingDevice = null, speechToken = 0, currentAudio = null;
  // Resolves true when the reply finished without being interrupted.
  async function speak(id, text) {
    if (!text) return true;
    stopSpeaking();
    const token = ++speechToken;
    speakingDevice = id; setState(id, "speaking"); pauseInput();
    try {
      if (useKokoro()) await speakKokoro(text, token); else await speakBrowser(text);
    } catch {
      if (token === speechToken) await speakBrowser(text).catch(() => {});
    }
    const completed = token === speechToken;
    if (completed) { speakingDevice = null; setState(id, "idle"); }
    resumeInput();
    return completed;
  }
  function sentences(text) {
    return (text.match(/[^.!?]+[.!?]*/g) || [text]).map((s) => s.trim()).filter(Boolean);
  }
  async function speakKokoro(text, token) {
    // Request every sentence up front (the host renders them in order) and play the
    // first as soon as it is ready, so long replies start speaking quickly.
    const clips = sentences(text).map((part) => fetch("/api/tts", {
      method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ text: part }),
    }).then((r) => { if (!r.ok) throw new Error("tts unavailable"); return r.blob(); }));
    clips.forEach((clip) => clip.catch(() => {}));
    for (const clip of clips) {
      const blob = await clip;
      if (token !== speechToken) return;
      await playBlob(blob, token);
    }
  }
  function playBlob(blob, token) {
    return new Promise((resolve, reject) => {
      const url = URL.createObjectURL(blob), audio = new Audio(url);
      currentAudio = audio;
      const finish = (fn) => () => { URL.revokeObjectURL(url); fn(); };
      audio.onended = finish(resolve);
      audio.onerror = finish(() => reject(new Error("audio playback failed")));
      audio.onpause = () => { if (token !== speechToken) finish(resolve)(); };
      audio.play().catch(reject);
    });
  }
  function speakBrowser(text) {
    return new Promise((resolve) => {
      if (!window.speechSynthesis) return resolve();
      const u = new SpeechSynthesisUtterance(text);
      u.rate = 1.03; u.onend = u.onerror = () => resolve();
      speechSynthesis.speak(u);
    });
  }
  function stopSpeaking() {
    speechToken++;
    if (currentAudio) { currentAudio.pause(); currentAudio = null; }
    if (window.speechSynthesis?.speaking) speechSynthesis.cancel();
    if (speakingDevice) { setState(speakingDevice, "idle"); speakingDevice = null; }
  }

  // ---- turns --------------------------------------------------------------------------------
  async function say(id, text) {
    text = text.trim();
    if (!text) return;
    if (/^(alexa[, ]*)?(stop|quiet|cancel that)\b/i.test(text)) { stopSpeaking(); return; }
    if (activeListen && activeListen.id === id) activeListen.cancel();  // typed while the mic was open
    stopSpeaking();
    if (id === "show") bubble(text, "user"); else $("#dot-caption").textContent = "“" + text + "”";
    setState(id, "thinking");
    let out;
    try { out = await api("/api/utterance", { device_id: id, text }); }
    catch (e) { out = { reply: "Sorry, the simulator can't reach CareLoop right now.", screen: null }; }
    setState(id, "idle");
    if (id === "show") {
      bubble(out.reply);
      if (out.screen?.resource_uri) mountApp(out.screen).catch(() => bubble("The private view couldn't load.", "system"));
    } else {
      $("#dot-caption").textContent = out.reply || "";
    }
    refresh().catch(() => {});
    const completed = await speak(id, out.reply);
    // Like Alexa, keep the mic open after a question or a confirmation prompt.
    if (out.expects_reply && completed && !activeListen) listen(id);
  }

  $$(".composer").forEach((form) => form.addEventListener("submit", (e) => {
    e.preventDefault();
    const input = $("input", form); const text = input.value; input.value = "";
    say(form.dataset.device, text);
  }));
  function chips(container, list, id) {
    list.forEach((text) => {
      const b = document.createElement("button"); b.type = "button"; b.className = "chip"; b.textContent = text.replace(/^Alexa, /, "");
      b.addEventListener("click", () => say(id, text)); container.append(b);
    });
  }
  chips($("#show-chips"), SHOW_CHIPS, "show");
  chips($("#dot-chips"), DOT_CHIPS, "dot");

  // ---- microphone capture for Whisper: 16 kHz mono with simple energy VAD ------------------
  const mic = {
    ctx: null, stream: null, rate: 16000, noise: 0.004, paused: false, handler: null,
    async ensure() {
      if (this.ctx) { if (this.ctx.state === "suspended") await this.ctx.resume(); return; }
      this.stream = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true } });
      this.ctx = new AudioContext({ sampleRate: 16000 });
      this.rate = this.ctx.sampleRate;
      const source = this.ctx.createMediaStreamSource(this.stream);
      const node = this.ctx.createScriptProcessor(2048, 1, 1);
      node.onaudioprocess = (e) => { if (!this.paused && this.handler) this.handler.push(new Float32Array(e.inputBuffer.getChannelData(0))); };
      source.connect(node); node.connect(this.ctx.destination); // output buffer stays silent
    },
  };

  function segmenter({ onSegment, noSpeechMs = 0, silenceMs = 800, maxMs = 12000 }) {
    let chunks = [], preroll = [], speaking = false, silence = 0, elapsed = 0, closed = false;
    const emit = () => {
      const audio = speaking && chunks.length ? concat(chunks) : null;
      chunks = []; preroll = []; speaking = false; silence = 0; elapsed = 0;
      onSegment(audio);
    };
    return {
      push(frame) {
        if (closed) return;
        let sum = 0; for (const x of frame) sum += x * x;
        const rms = Math.sqrt(sum / frame.length), ms = frame.length / mic.rate * 1000;
        const threshold = Math.max(0.012, mic.noise * 3);
        elapsed += ms;
        if (!speaking) {
          if (rms < threshold) mic.noise = mic.noise * 0.95 + rms * 0.05;
          preroll.push(frame); if (preroll.length > 4) preroll.shift();
          if (rms >= threshold) { speaking = true; chunks = preroll.slice(); silence = 0; elapsed = 0; }
          else if (noSpeechMs && elapsed >= noSpeechMs) { closed = true; onSegment(null); }
          return;
        }
        chunks.push(frame);
        silence = rms >= threshold * 0.6 ? 0 : silence + ms;
        if (silence >= silenceMs || elapsed >= maxMs) emit();
      },
      flush() { if (!closed) { closed = true; emit(); } },
      close() { closed = true; },
    };
  }
  function concat(frames) {
    const out = new Float32Array(frames.reduce((n, f) => n + f.length, 0));
    let offset = 0; for (const f of frames) { out.set(f, offset); offset += f.length; }
    return out;
  }
  function toPcm16(samples) {
    // Resample to 16 kHz if the browser ignored the requested context rate.
    let data = samples;
    if (mic.rate !== 16000) {
      const ratio = mic.rate / 16000, length = Math.floor(samples.length / ratio);
      data = new Float32Array(length);
      for (let i = 0; i < length; i++) data[i] = samples[Math.floor(i * ratio)];
    }
    const pcm = new Int16Array(data.length);
    for (let i = 0; i < data.length; i++) pcm[i] = Math.max(-1, Math.min(1, data[i])) * 0x7fff;
    return pcm.buffer;
  }
  async function transcribe(samples) {
    const res = await fetch("/api/stt", { method: "POST", headers: { "content-type": "application/octet-stream" }, body: toPcm16(samples) });
    if (!res.ok) throw new Error("stt unavailable");
    return ((await res.json()).text || "").trim();
  }

  // ---- push-to-talk / follow-up listening ---------------------------------------------------
  let activeListen = null;
  async function listen(id) {
    if (activeListen) { activeListen.stop(); return; }   // second tap ends the utterance now
    stopSpeaking();
    if (!useWhisper()) return browserListen(id);
    try { await mic.ensure(); } catch { status("Microphone permission is needed for voice input."); return; }
    const button = $(`[data-mic="${id}"]`), input = $(`.composer[data-device="${id}"] input`);
    button.classList.add("live"); setState(id, "listening"); pauseWake();
    const previous = mic.handler;
    await new Promise((resolve) => {
      const done = async (audio) => {
        activeListen = null; mic.handler = wakeOn ? previous : null;
        button.classList.remove("live");
        if (!audio) { setState(id, "idle"); resumeWake(); return resolve(); }
        setState(id, "thinking"); input.placeholder = "Transcribing…";
        let text = "";
        try { text = await transcribe(audio); } catch { status("Whisper is unavailable; using typed input."); }
        input.placeholder = "";
        resumeWake();
        if (text) say(id, text); else setState(id, "idle");
        resolve();
      };
      const seg = segmenter({ onSegment: done, noSpeechMs: 7000 });
      mic.handler = seg;
      activeListen = { id, stop: () => seg.flush(), cancel: () => { seg.close(); done(null); } };
    });
  }
  function browserListen(id) {
    if (!Recognition) { status("Speech input isn't supported in this browser; type instead."); return; }
    pauseWake();
    const rec = new Recognition(); rec.lang = "en-US"; rec.interimResults = true; rec.maxAlternatives = 1;
    const button = $(`[data-mic="${id}"]`), input = $(`.composer[data-device="${id}"] input`);
    button.classList.add("live"); setState(id, "listening");
    let finalText = "";
    activeListen = { id, stop: () => rec.stop(), cancel: () => { finalText = ""; rec.abort(); } };
    rec.onresult = (e) => {
      const r = e.results[e.results.length - 1];
      input.value = r[0].transcript;
      if (r.isFinal) finalText = r[0].transcript;
    };
    rec.onerror = () => {};
    rec.onend = () => {
      activeListen = null; button.classList.remove("live"); input.value = "";
      if (finalText) say(id, finalText); else setState(id, "idle");
      resumeWake();
    };
    rec.start();
  }
  $$(".mic").forEach((b) => b.addEventListener("click", () => listen(b.dataset.mic)));

  // ---- hands-free wake word -------------------------------------------------------------------
  const WAKE = /\b(?:hey\s+)?(?:alexa|alexis|alexia|alexsa)\b[\s,.!?]*(.*)$/i;
  let wakeOn = false, wakePaused = false, armedUntil = 0, wakeRec = null;
  function heardPhrase(heard) {
    const target = $("#wake-target").value, match = heard.match(WAKE);
    if (match && match[1].trim()) { armedUntil = 0; say(target, match[1]); }
    else if (match) { armedUntil = Date.now() + 6000; setState(target, "listening"); }
    else if (Date.now() < armedUntil) { armedUntil = 0; say(target, heard); }
  }
  function whisperWakeHandler() {
    return segmenter({ silenceMs: 700, onSegment: async (audio) => {
      if (!audio || !wakeOn) return;
      try { const heard = await transcribe(audio); if (heard) heardPhrase(heard); } catch { /* keep listening */ }
    } });
  }
  async function startWake() {
    if (!wakeOn || wakePaused) return;
    if (useWhisper()) {
      try { await mic.ensure(); } catch { status("Microphone permission is needed for voice input."); return; }
      if (!mic.handler && !activeListen) mic.handler = whisperWakeHandler();
      status("Listening for “Alexa”… (Whisper)");
      return;
    }
    if (!Recognition || wakeRec) return;
    wakeRec = new Recognition(); wakeRec.lang = "en-US"; wakeRec.continuous = true; wakeRec.interimResults = false;
    wakeRec.onresult = (e) => heardPhrase(e.results[e.results.length - 1][0].transcript.trim());
    wakeRec.onend = () => { wakeRec = null; if (wakeOn && !wakePaused) setTimeout(startWake, 250); };
    wakeRec.onerror = () => {};
    try { wakeRec.start(); status("Listening for “Alexa”…"); } catch { wakeRec = null; }
  }
  function pauseWake() {
    wakePaused = true;
    if (wakeRec) { wakeRec.onend = null; wakeRec.abort(); wakeRec = null; }
  }
  function resumeWake() { wakePaused = false; setTimeout(startWake, 300); }
  // While the assistant talks, ignore the mic so it never hears itself.
  function pauseInput() { mic.paused = true; pauseWake(); }
  function resumeInput() { mic.paused = false; resumeWake(); }
  $("#wake").addEventListener("change", (e) => {
    wakeOn = e.target.checked;
    if (wakeOn) startWake();
    else { pauseWake(); wakePaused = false; if (!activeListen) mic.handler = null; status(""); }
  });

  // ---- MCP Apps host bridge -----------------------------------------------------------
  let activeApp = null;
  async function mountApp(screen) {
    const { html } = await api(`/api/apps/resource?device_id=show&uri=${encodeURIComponent(screen.resource_uri)}`);
    if (activeApp) { window.removeEventListener("message", activeApp.listener); activeApp.frame.remove(); }
    const frame = document.createElement("iframe");
    frame.className = "app-frame"; frame.title = "CareLoop private view";
    frame.setAttribute("sandbox", "allow-scripts"); // no same-origin: no cookies, storage, or parent DOM
    const post = (msg) => frame.contentWindow?.postMessage(msg, "*"); // sandboxed frame has an opaque origin
    const listener = async (event) => {
      if (event.source !== frame.contentWindow) return;
      const m = event.data;
      if (!m || m.jsonrpc !== "2.0") return;
      const reply = (result) => post({ jsonrpc: "2.0", id: m.id, result });
      const fail = (message) => post({ jsonrpc: "2.0", id: m.id, error: { code: -32000, message } });
      switch (m.method) {
        case "ui/initialize":
          reply({ protocolVersion: m.params?.protocolVersion || "2026-01-26",
            hostInfo: { name: "careloop-assistant-simulator", version: "1" },
            hostCapabilities: { serverTools: {} },
            hostContext: { theme: "light", displayMode: "inline", platform: "web",
              containerDimensions: { maxHeight: 560 } } });
          break;
        case "ui/notifications/initialized":
          post({ jsonrpc: "2.0", method: "ui/notifications/tool-result", params: screen.result });
          break;
        case "tools/call":
          try {
            const result = await api("/api/apps/call", { device_id: "show", name: m.params?.name, arguments: m.params?.arguments || {} });
            reply(result);
          } catch (e) { fail("CareLoop action unavailable"); }
          break;
        case "ui/notifications/size-changed":
          frame.style.height = Math.max(140, Math.min(560, Number(m.params?.height) || 260)) + "px";
          break;
        default:
          if (m.id !== undefined) fail("Method not supported by this host");
      }
    };
    window.addEventListener("message", listener);
    frame.srcdoc = html;
    $("#app-slot").replaceChildren(frame);
    activeApp = { frame, listener };
  }

  // ---- Alexa app panel, director, inspector -----------------------------------------
  async function refresh() {
    const s = await api("/api/state");
    for (const d of s.devices) {
      const row = $(`.account[data-account="${d.owner}"]`);
      row.classList.toggle("linked", !!d.account);
      $("button", row).textContent = d.account ? "Unlink" : "Enable CareLoop";
      if (d.id === "dot") devices.dot.classList.toggle("notify", !!d.notification);
    }
    $("#open-invite").disabled = !s.invitation_pending || !s.devices.find((d) => d.id === "dot").account;
    $("#planner").value = s.planner;
  }
  $$("[data-link]").forEach((b) => b.addEventListener("click", async () => {
    const account = b.dataset.link, linked = b.closest(".account").classList.contains("linked");
    try {
      if (linked) await api(`/api/unlink/${account}`, {});
      else { const out = await api("/api/link", { account }); traceLine({ type: "host", text: `${account} linked · ${out.tools.length} model-visible tools discovered` }); }
    } catch (e) { traceLine({ type: "error", text: e.message }); }
    refresh();
  }));
  $("#open-invite").addEventListener("click", async () => {
    try { const out = await api("/api/invite/open", {}); $("#dot-caption").textContent = out.reply || ""; speak("dot", out.reply); }
    catch (e) { traceLine({ type: "error", text: e.message }); }
    refresh();
  });
  $("#planner").addEventListener("change", (e) => api("/api/planner", { mode: e.target.value }).then(refresh));
  $("#reset").addEventListener("click", () => api("/api/conversation/reset", {}).then(() => { $("#convo").replaceChildren(); $("#app-slot").replaceChildren(); }));
  $("#show-inspector").addEventListener("change", (e) => { $("#inspector").hidden = !e.target.checked; });

  function traceLine(entry) {
    const li = document.createElement("li");
    let cls = "host", text;
    if (entry.method) {
      cls = entry.direction === "out" ? "out" : "in";
      const who = `[${entry.account}${entry.source && entry.source !== "model" ? " · " + entry.source : ""}]`;
      const detail = entry.direction === "out"
        ? (entry.name ? `${entry.name} ${JSON.stringify(entry.arguments || {})}` : entry.uri || "")
        : (entry.name ? JSON.stringify(entry.result) : entry.tools ? entry.tools.join(", ") : entry.uri ? `${entry.bytes} bytes` : "");
      text = `${entry.direction === "out" ? "→" : "←"} ${entry.method} ${who} ${detail}`;
      if (entry.result?.isError) cls = "err";
    } else if (entry.type === "turn") {
      text = `◆ turn [${entry.device_id} · ${entry.planner}] tools: ${entry.tools.join(" → ") || "none"} · “${entry.reply}”`;
    } else if (entry.type === "device") {
      return;
    } else {
      cls = entry.type === "error" || entry.type === "turn_error" ? "err" : "host";
      text = entry.text || JSON.stringify(entry);
    }
    li.className = cls; li.textContent = text;
    $("#trace").prepend(li);
    while ($("#trace").children.length > 150) $("#trace").lastChild.remove();
  }

  // ---- document sharing (the Alexa app's "share a file") ---------------------------------
  async function share(file, sample) {
    const account = $("#share-as").value, type = $("#share-type").value;
    const params = new URLSearchParams({ account, doc_type: type, title: type === "prescription" ? "Prescription" : "Discharge plan" });
    if (sample) params.set("sample", sample);
    $("#share-status").textContent = "Sending…";
    try {
      const res = await fetch("/api/documents/share?" + params, { method: "POST", body: file || null,
        headers: file ? { "content-type": file.type || "application/octet-stream" } : {} });
      const out = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(out.detail || "CareLoop couldn't take that document");
      $("#share-status").textContent = `Shared as ${account}. CareLoop is reading it…`;
    } catch (e) { $("#share-status").textContent = e.message; }
  }
  $("#share-upload").addEventListener("click", () => {
    const file = $("#share-file").files[0];
    if (!file) { $("#share-status").textContent = "Choose a PDF, PNG or JPEG first."; return; }
    share(file);
  });
  $("#share-sample-go").addEventListener("click", () => share(null, $("#share-sample").value));

  async function announced(msg) {
    if (msg.device_id === "show") {
      bubble(msg.reply);
      if (msg.screen?.resource_uri) mountApp(msg.screen).catch(() => bubble("The private view couldn't load.", "system"));
      $("#share-status").textContent = "Ready for Maya to review.";
    } else {
      $("#dot-caption").textContent = msg.reply || "";
    }
    refresh().catch(() => {});
    await speak(msg.device_id, msg.reply);
  }

  function connect() {
    const ws = new WebSocket((location.protocol === "https:" ? "wss" : "ws") + "://" + location.host + "/ws");
    ws.onmessage = (e) => {
      const msg = JSON.parse(e.data);
      if (msg.type === "trace") traceLine(msg.entry);
      else if (msg.type === "announce") announced(msg);
      else if (msg.type === "device") {
        if (msg.device_id === "dot") devices.dot.classList.toggle("notify", !!msg.notification);
        if (msg.state === "thinking" && speakingDevice !== msg.device_id) setState(msg.device_id, "thinking");
      }
    };
    ws.onclose = () => setTimeout(connect, 2000);
  }
  // Fallback when live updates are unavailable: keep device/notification state fresh.
  setInterval(() => refresh().catch(() => {}), 4000);
  connect();
  refresh();
  loadVoice();
})();
