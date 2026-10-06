// Service worker: context menu, toolbar command and on-demand injection of the content script.

const MENU_SELECTION = "lisn-read-selection";
const MENU_PAGE = "lisn-read-page";

chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({ id: MENU_SELECTION, title: "Read selection with lisn", contexts: ["selection"] });
  chrome.contextMenus.create({ id: MENU_PAGE, title: "Read this page with lisn", contexts: ["page"] });
});

chrome.contextMenus.onClicked.addListener(async (info, tab) => {
  if (!tab?.id) return;
  if (info.menuItemId === MENU_SELECTION) {
    await send(tab.id, { action: "readSelection", text: info.selectionText || "" });
  } else if (info.menuItemId === MENU_PAGE) {
    await send(tab.id, { action: "readPage" });
  }
});

chrome.commands.onCommand.addListener(async (command, tab) => {
  if (!tab?.id) return;
  if (command === "read-page") await send(tab.id, { action: "readPage" });
  if (command === "toggle-play") await send(tab.id, { action: "control", control: "toggle" });
});

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message?.action === "readActiveTab") {
    chrome.tabs.query({ active: true, currentWindow: true }).then(async ([tab]) => {
      if (tab?.id) await send(tab.id, { action: message.what === "selection" ? "readSelection" : "readPage" });
      sendResponse({ ok: true });
    });
    return true;
  }
  return false;
});

async function send(tabId, message) {
  try {
    await ensureInjected(tabId);
    await chrome.tabs.sendMessage(tabId, message);
  } catch (error) {
    console.warn("lisn: could not reach the page", error);
  }
}

async function ensureInjected(tabId) {
  try {
    const pong = await chrome.tabs.sendMessage(tabId, { action: "ping" });
    if (pong?.ok) return;
  } catch (_ignored) {
    // not injected yet
  }
  await chrome.scripting.executeScript({ target: { tabId }, files: ["lib/Readability.js", "content.js"] });
}
