// Content script: grabs the article (Readability) or the selection, sends it to `lisn serve`,
// highlights the spoken sentence/word in the live DOM via the CSS Highlight API, and shows a
// floating control bar. Falls back to the browser's Web Speech API when the server is down.

(() => {
  if (window.__lisnLoaded) return;
  window.__lisnLoaded = true;

  const DEFAULTS = { port: 7391, token: "", speed: 1.0, voice: "" };
  const state = {
    settings: { ...DEFAULTS },
    session: null,
    sentences: [],
    ranges: [],
    events: null,
    mode: "server", // "server" | "browser"
    browser: null,
    bar: null,
  };

  // ---------------------------------------------------------------- messages
  chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
    if (message.action === "ping") {
      sendResponse({ ok: true });
      return false;
    }
    (async () => {
      await loadSettings();
      if (message.action === "readPage") await readPage();
      else if (message.action === "readSelection") await readSelection(message.text);
      else if (message.action === "control") await control(message.control, message.value);
      sendResponse({ ok: true });
    })().catch((error) => {
      notice(`lisn: ${error.message}`, true);
      sendResponse({ ok: false, error: error.message });
    });
    return true;
  });

  async function loadSettings() {
    const stored = await chrome.storage.local.get(DEFAULTS);
    state.settings = { ...DEFAULTS, ...stored };
  }

  // ---------------------------------------------------------------- extraction
  async function readPage() {
    const selection = window.getSelection();
    if (selection && selection.toString().trim().length > 40) {
      return readSelection(selection.toString());
    }
    if (location.hostname === "docs.google.com" && location.pathname.startsWith("/document/")) {
      return startSession({ url: location.href, title: document.title });
    }
    const article = extractArticle();
    if (!article.text.trim()) throw new Error("No readable text found on this page. Try selecting some text.");
    return startSession({ text: article.text, title: article.title || document.title, root: article.root });
  }

  async function readSelection(text) {
    const selection = window.getSelection();
    const selected = (text || (selection ? selection.toString() : "")).trim();
    if (!selected) throw new Error("Nothing is selected.");
    const root = selection && selection.rangeCount ? selection.getRangeAt(0).commonAncestorContainer : document.body;
    return startSession({ text: selected, title: document.title, root: root.nodeType === 1 ? root : root.parentElement });
  }

  function extractArticle() {
    let text = "";
    let title = document.title;
    try {
      const clone = document.cloneNode(true);
      const article = new Readability(clone, { keepClasses: false }).parse();
      if (article && article.textContent && article.textContent.trim().length > 200) {
        text = paragraphsOf(article.content);
        title = article.title || title;
      }
    } catch (_error) {
      // Readability can throw on odd pages; fall through to the heuristic.
    }
    const root = document.querySelector("article, main, [role=main]") || document.body;
    if (!text) text = root.innerText || "";
    return { text, title, root };
  }

  function paragraphsOf(html) {
    const container = document.createElement("div");
    container.innerHTML = html;
    const out = [];
    container.querySelectorAll("h1,h2,h3,h4,h5,h6,p,li,blockquote,pre,td,figcaption").forEach((el) => {
      if (el.querySelector("p,li")) return;
      const t = el.innerText.replace(/\s+/g, " ").trim();
      if (!t) return;
      out.push(/^H[1-6]$/.test(el.tagName) ? `${"#".repeat(Number(el.tagName[1]))} ${t}` : t);
    });
    return out.join("\n\n");
  }

  // ---------------------------------------------------------------- server session
  async function startSession({ text, url, title, root }) {
    stopEverything();
    mountBar();
    setStatus("connecting…");
    const alive = await serverAlive();
    if (!alive) {
      state.mode = "browser";
      notice("lisn serve is not running — using the browser voice instead (no word timing).", true);
      if (!text) throw new Error("Browser fallback needs the page text; select text and try again.");
      prepareHighlights(text, root || document.body);
      return browserSpeak();
    }
    state.mode = "server";
    const body = { title: title || document.title, speed: state.settings.speed || undefined, voice: state.settings.voice || undefined };
    if (text) body.text = text;
    else body.url = url;
    const info = await api("POST", "/session", body);
    state.session = info.id;
    state.sentences = info.sentences;
    if (text) prepareHighlights(text, root || document.body);
    subscribe();
    setStatus("playing");
  }

  async function serverAlive() {
    try {
      const response = await fetch(`${base()}/health`, { cache: "no-store" });
      return response.ok;
    } catch (_error) {
      return false;
    }
  }

  function base() {
    return `http://127.0.0.1:${state.settings.port || 7391}`;
  }

  async function api(method, path, body) {
    const response = await fetch(base() + path, {
      method,
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${state.settings.token}` },
      body: body ? JSON.stringify(body) : undefined,
    });
    if (response.status === 401) throw new Error("Wrong token. Run `lisn serve --show-token` and paste it in the popup.");
    if (!response.ok) {
      let detail = response.statusText;
      try {
        detail = (await response.json()).detail || detail;
      } catch (_ignored) {
        // keep statusText
      }
      throw new Error(detail);
    }
    return response.json();
  }

  function subscribe() {
    if (state.events) state.events.close();
    const url = `${base()}/session/${state.session}/events?token=${encodeURIComponent(state.settings.token)}`;
    state.events = new EventSource(url);
    state.events.onmessage = (event) => {
      const payload = JSON.parse(event.data);
      applyState(payload);
      if (payload.kind === "finished") {
        state.events.close();
        state.events = null;
      }
    };
    state.events.onerror = () => setStatus("connection lost");
  }

  function applyState(payload) {
    setStatus(`${payload.status} · ${payload.index + 1}/${state.sentences.length || "?"} · ${payload.speed.toFixed(1)}x`);
    if (payload.kind === "sentence" || payload.kind === "word" || payload.kind === "state") {
      highlightSentence(payload.index, payload.kind === "sentence");
      if (payload.word_index >= 0) highlightWord(payload.index, payload.word_index);
    }
    if (payload.status === "finished" || payload.status === "stopped") clearHighlights();
  }

  async function control(action, value) {
    if (state.mode === "browser") return browserControl(action, value);
    if (!state.session) return;
    await api("POST", `/session/${state.session}/control`, { action, value });
  }

  // ---------------------------------------------------------------- highlighting
  function prepareHighlights(text, root) {
    state.rawText = text;
    state.ranges = [];
    const nodes = textNodes(root);
    const pieces = [];
    const map = [];
    nodes.forEach((node, nodeIndex) => {
      const value = node.nodeValue;
      for (let i = 0; i < value.length; i++) {
        pieces.push(value[i]);
        map.push([nodeIndex, i]);
      }
      pieces.push(" ");
      map.push([nodeIndex, value.length]);
    });
    const haystack = normalize(pieces.join(""));
    state.haystack = haystack.text;
    state.haystackMap = haystack.map.map((i) => map[i]);
    state.nodes = nodes;
    state.cursor = 0;
  }

  function textNodes(root) {
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
      acceptNode(node) {
        const parent = node.parentElement;
        if (!parent) return NodeFilter.FILTER_REJECT;
        const tag = parent.tagName;
        if (["SCRIPT", "STYLE", "NOSCRIPT", "TEMPLATE"].includes(tag)) return NodeFilter.FILTER_REJECT;
        if (parent.closest("#lisn-bar")) return NodeFilter.FILTER_REJECT;
        return node.nodeValue.trim() ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT;
      },
    });
    const out = [];
    let node;
    while ((node = walker.nextNode())) out.push(node);
    return out;
  }

  function normalize(text) {
    // Collapse whitespace and unify quotes/dashes so server sentences match page text; keep an index map.
    const out = [];
    const map = [];
    let lastSpace = true;
    for (let i = 0; i < text.length; i++) {
      let ch = text[i];
      if (/\s/.test(ch)) {
        if (lastSpace) continue;
        ch = " ";
        lastSpace = true;
      } else {
        lastSpace = false;
        ch = ch.replace(/[‘’‚]/g, "'").replace(/[“”„]/g, '"').replace(/[‐-‒]/g, "-");
        ch = ch.toLowerCase();
      }
      out.push(ch);
      map.push(i);
    }
    return { text: out.join(""), map };
  }

  function findSentenceRange(index) {
    if (state.ranges[index] !== undefined) return state.ranges[index];
    const sentence = state.sentences[index];
    let range = null;
    if (sentence && state.haystack) {
      const needle = normalize(sentence.text).text.trim();
      let at = needle ? state.haystack.indexOf(needle, state.cursor) : -1;
      if (at < 0 && needle) at = state.haystack.indexOf(needle);
      if (at >= 0) {
        state.cursor = at + needle.length;
        range = rangeFor(at, at + needle.length);
      }
    }
    state.ranges[index] = range;
    return range;
  }

  function rangeFor(start, end) {
    const [n0, o0] = state.haystackMap[start];
    const [n1, o1] = state.haystackMap[Math.max(start, end - 1)];
    const range = document.createRange();
    range.setStart(state.nodes[n0], o0);
    range.setEnd(state.nodes[n1], Math.min(o1 + 1, state.nodes[n1].nodeValue.length));
    return range;
  }

  function highlightSentence(index, scroll) {
    if (!("highlights" in CSS)) return;
    const range = findSentenceRange(index);
    if (!range) {
      CSS.highlights.delete("lisn-sentence");
      return;
    }
    CSS.highlights.set("lisn-sentence", new Highlight(range));
    if (scroll) {
      const rect = range.getBoundingClientRect();
      if (rect.top < 80 || rect.bottom > window.innerHeight - 120) {
        window.scrollBy({ top: rect.top - window.innerHeight / 3, behavior: "smooth" });
      }
    }
  }

  function highlightWord(index, wordIndex) {
    if (!("highlights" in CSS)) return;
    const range = findSentenceRange(index);
    const sentence = state.sentences[index];
    if (!range || !sentence) return;
    const words = sentence.text.split(/\s+/);
    const word = words[wordIndex];
    if (!word) return;
    const text = normalize(range.toString());
    const needle = normalize(word).text;
    let offset = 0;
    let at = -1;
    for (let i = 0; i <= wordIndex; i++) {
      at = text.text.indexOf(normalize(words[i]).text, offset);
      if (at < 0) return;
      offset = at + 1;
    }
    const start = state.haystack.indexOf(text.text, Math.max(0, state.cursor - text.text.length - 5));
    if (start < 0) return;
    const wordRange = rangeFor(start + at, start + at + needle.length);
    CSS.highlights.set("lisn-word", new Highlight(wordRange));
  }

  function clearHighlights() {
    if ("highlights" in CSS) {
      CSS.highlights.delete("lisn-sentence");
      CSS.highlights.delete("lisn-word");
    }
  }

  // ---------------------------------------------------------------- browser fallback (Web Speech API)
  function browserSpeak() {
    const synth = window.speechSynthesis;
    if (!synth) throw new Error("This browser has no speech synthesis.");
    const sentences = splitSentences(state.rawText || "");
    state.sentences = sentences.map((t, i) => ({ index: i, text: t }));
    state.browser = { index: 0, paused: false, rate: state.settings.speed || 1 };
    speakFrom(0);
  }

  function speakFrom(index) {
    const synth = window.speechSynthesis;
    synth.cancel();
    if (index >= state.sentences.length) {
      setStatus("finished");
      clearHighlights();
      return;
    }
    state.browser.index = index;
    const sentence = state.sentences[index];
    const utterance = new SpeechSynthesisUtterance(sentence.text);
    utterance.rate = state.browser.rate;
    utterance.onstart = () => {
      highlightSentence(index, true);
      setStatus(`browser voice · ${index + 1}/${state.sentences.length} · ${state.browser.rate.toFixed(1)}x`);
    };
    utterance.onboundary = (event) => {
      if (event.name !== "word") return;
      const before = sentence.text.slice(0, event.charIndex).trim();
      const wordIndex = before ? before.split(/\s+/).length : 0;
      highlightWord(index, wordIndex);
    };
    utterance.onend = () => {
      if (state.browser && state.browser.index === index && !state.browser.paused) speakFrom(index + 1);
    };
    synth.speak(utterance);
  }

  function browserControl(action, value) {
    const synth = window.speechSynthesis;
    if (!state.browser) return;
    if (action === "toggle") {
      if (synth.paused) {
        synth.resume();
        state.browser.paused = false;
      } else {
        synth.pause();
        state.browser.paused = true;
      }
    } else if (action === "play") synth.resume();
    else if (action === "pause") synth.pause();
    else if (action === "stop") stopEverything();
    else if (action === "next") speakFrom(state.browser.index + 1);
    else if (action === "prev") speakFrom(Math.max(0, state.browser.index - 1));
    else if (action === "speed") {
      state.browser.rate = Math.max(0.5, Math.min(3, Number(value)));
      speakFrom(state.browser.index);
    }
  }

  function splitSentences(text) {
    return text
      .replace(/\s+/g, " ")
      .split(/(?<=[.!?])\s+(?=[A-Z"'(\[])/)
      .map((s) => s.trim())
      .filter(Boolean);
  }

  // ---------------------------------------------------------------- control bar UI
  function mountBar() {
    if (state.bar) return;
    const host = document.createElement("div");
    host.id = "lisn-bar";
    host.style.cssText = "position:fixed;right:16px;bottom:16px;z-index:2147483647;";
    const shadow = host.attachShadow({ mode: "open" });
    shadow.innerHTML = `
      <style>
        .bar{font:13px system-ui,sans-serif;background:#1e1e24;color:#eee;border-radius:10px;padding:8px 10px;
             box-shadow:0 4px 18px rgba(0,0,0,.35);display:flex;gap:6px;align-items:center;flex-wrap:wrap;max-width:420px}
        button{background:#2f2f38;color:#eee;border:0;border-radius:6px;padding:5px 9px;cursor:pointer;font-size:13px}
        button:hover{background:#44445a}
        .status{opacity:.8;min-width:90px}
        .notice{color:#ffd166}
      </style>
      <div class="bar">
        <button data-c="prev" title="Previous sentence (←)">⏮</button>
        <button data-c="toggle" title="Play / pause (space)">⏯</button>
        <button data-c="next" title="Next sentence (→)">⏭</button>
        <button data-c="slower" title="Slower">−</button>
        <button data-c="faster" title="Faster">+</button>
        <button data-c="stop" title="Stop and close">✕</button>
        <span class="status">…</span>
        <span class="notice"></span>
      </div>`;
    shadow.querySelectorAll("button").forEach((button) => {
      button.addEventListener("click", () => barAction(button.dataset.c));
    });
    document.documentElement.appendChild(host);
    const style = document.createElement("style");
    style.id = "lisn-highlight-style";
    style.textContent = `::highlight(lisn-sentence){background:rgba(255,214,102,.35)} ::highlight(lisn-word){background:rgba(255,160,0,.9);color:#000}`;
    document.head.appendChild(style);
    state.bar = shadow;
    state.speedValue = state.settings.speed || 1;
    document.addEventListener("keydown", onKey, true);
  }

  async function barAction(name) {
    try {
      if (name === "stop") return stopEverything();
      if (name === "slower" || name === "faster") {
        state.speedValue = Math.max(0.5, Math.min(3, (state.speedValue || 1) + (name === "faster" ? 0.1 : -0.1)));
        return control("speed", Math.round(state.speedValue * 10) / 10);
      }
      return control(name);
    } catch (error) {
      notice(error.message, true);
    }
  }

  function onKey(event) {
    if (!state.bar || event.target.closest?.("input, textarea, [contenteditable]")) return;
    const map = { " ": "toggle", ArrowRight: "next", ArrowLeft: "prev", "+": "faster", "=": "faster", "-": "slower", Escape: "stop" };
    const action = map[event.key];
    if (!action) return;
    event.preventDefault();
    barAction(action);
  }

  function setStatus(text) {
    if (state.bar) state.bar.querySelector(".status").textContent = text;
  }

  function notice(text, warn) {
    if (!state.bar) mountBar();
    const element = state.bar.querySelector(".notice");
    element.textContent = text;
    element.style.color = warn ? "#ffd166" : "#9be37f";
  }

  function stopEverything() {
    if (state.events) {
      state.events.close();
      state.events = null;
    }
    if (state.session) {
      const id = state.session;
      state.session = null;
      api("DELETE", `/session/${id}`).catch(() => {});
    }
    if (window.speechSynthesis) window.speechSynthesis.cancel();
    state.browser = null;
    clearHighlights();
    if (state.bar) {
      document.getElementById("lisn-bar")?.remove();
      document.getElementById("lisn-highlight-style")?.remove();
      document.removeEventListener("keydown", onKey, true);
      state.bar = null;
    }
  }
})();
