const DEFAULTS = { port: 7391, token: "", speed: 1.0, voice: "" };
const $ = (id) => document.getElementById(id);

async function load() {
  const settings = { ...DEFAULTS, ...(await chrome.storage.local.get(DEFAULTS)) };
  $("port").value = settings.port;
  $("token").value = settings.token;
  $("speed").value = settings.speed;
  await checkServer(settings);
}

async function checkServer(settings) {
  const status = $("status");
  const base = `http://127.0.0.1:${settings.port}`;
  try {
    const health = await (await fetch(`${base}/health`, { cache: "no-store" })).json();
    const voices = await fetch(`${base}/voices`, { headers: { Authorization: `Bearer ${settings.token}` } });
    if (voices.status === 401) {
      status.className = "bad";
      status.textContent = `server v${health.version} found, but the token is wrong`;
      return;
    }
    const list = await voices.json();
    const select = $("voice");
    select.innerHTML = '<option value="">(server default: ' + health.voice + ")</option>";
    for (const voice of list) {
      const option = document.createElement("option");
      option.value = voice.id;
      option.textContent = `${voice.id} — ${voice.description || voice.language}`;
      if (voice.id === settings.voice) option.selected = true;
      select.appendChild(option);
    }
    status.className = "ok";
    status.textContent = `connected · ${health.engine} · ${list.length} voices`;
  } catch (_error) {
    status.className = "bad";
    status.textContent = "lisn serve is not running — browser voice will be used";
  }
}

async function save() {
  const settings = {
    port: Number($("port").value) || DEFAULTS.port,
    token: $("token").value.trim(),
    speed: Math.max(0.5, Math.min(3, Number($("speed").value) || 1)),
    voice: $("voice").value,
  };
  await chrome.storage.local.set(settings);
  await checkServer(settings);
}

$("save").addEventListener("click", save);
$("read-page").addEventListener("click", async () => {
  await save();
  await chrome.runtime.sendMessage({ action: "readActiveTab", what: "page" });
  window.close();
});
$("read-selection").addEventListener("click", async () => {
  await save();
  await chrome.runtime.sendMessage({ action: "readActiveTab", what: "selection" });
  window.close();
});
load();
