// citibike2strava — Gmail content script (minimal stub).
//
// Detects an open Citi Bike "Ride Receipt" in Gmail and injects an
// "↑ Strava" button. Clicking it reads the message's legacy id (the same id the
// Gmail API uses) and POSTs it to the local backend (`citibike2strava serve`),
// which re-fetches and re-parses the receipt server-side and uploads the ride.
//
// This is intentionally small and DOM-heuristic; Gmail's markup is unofficial
// and can change. Treat it as a starting point.

const SENDER_MARKER = "updates.citibikenyc.com";
const BUTTON_CLASS = "cb2s-upload-btn";

async function getConfig() {
  const { endpoint, token } = await chrome.storage.local.get(["endpoint", "token"]);
  return {
    endpoint: endpoint || "http://127.0.0.1:8722",
    token: token || "",
  };
}

async function uploadRide(messageId, button) {
  const { endpoint, token } = await getConfig();
  if (!token) {
    button.textContent = "⚠ set token in options";
    return;
  }
  button.disabled = true;
  button.textContent = "↑ uploading…";
  try {
    const resp = await fetch(`${endpoint}/api/rides/upload`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Auth-Token": token },
      body: JSON.stringify({ message_id: messageId }),
    });
    const data = await resp.json();
    if (data.status === "uploaded" || data.status === "duplicate") {
      button.textContent = data.status === "uploaded" ? "✓ on Strava" : "= already up";
      if (data.activity_url) {
        button.title = data.activity_url;
        button.onclick = () => window.open(data.activity_url, "_blank");
        button.disabled = false;
      }
    } else {
      button.textContent = "✗ " + (data.detail || data.error || "failed");
      button.disabled = false;
    }
  } catch (err) {
    // Most common cause: the local backend isn't running (`citibike2strava serve`).
    button.textContent = "✗ backend offline?";
    button.disabled = false;
  }
}

function makeButton(messageId) {
  const btn = document.createElement("button");
  btn.className = BUTTON_CLASS;
  btn.textContent = "↑ Strava";
  btn.style.cssText =
    "margin:8px;padding:4px 10px;font-size:12px;cursor:pointer;" +
    "border:1px solid #fc4c02;color:#fc4c02;background:#fff;border-radius:4px;";
  btn.addEventListener("click", (e) => {
    e.stopPropagation();
    uploadRide(messageId, btn);
  });
  return btn;
}

function injectButtons() {
  // Each open message lives in a container carrying data-legacy-message-id.
  document.querySelectorAll("[data-legacy-message-id]").forEach((el) => {
    if (el.querySelector(`.${BUTTON_CLASS}`)) return; // already added
    const messageId = el.getAttribute("data-legacy-message-id");
    if (!messageId) return;
    // Only Citi Bike receipts: cheap check on the rendered message text.
    if (!el.innerHTML.includes(SENDER_MARKER)) return;
    el.prepend(makeButton(messageId));
  });
}

// Gmail is a single-page app; re-scan as the DOM mutates (debounced).
let pending = null;
const observer = new MutationObserver(() => {
  if (pending) return;
  pending = setTimeout(() => {
    pending = null;
    injectButtons();
  }, 400);
});
observer.observe(document.body, { childList: true, subtree: true });
injectButtons();
