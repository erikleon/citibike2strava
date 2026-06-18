// Persist the backend endpoint and auth token in extension-local storage.

const endpointEl = document.getElementById("endpoint");
const tokenEl = document.getElementById("token");
const statusEl = document.getElementById("status");

async function restore() {
  const { endpoint, token } = await chrome.storage.local.get(["endpoint", "token"]);
  if (endpoint) endpointEl.value = endpoint;
  if (token) tokenEl.value = token;
}

document.getElementById("save").addEventListener("click", async () => {
  await chrome.storage.local.set({
    endpoint: endpointEl.value.trim().replace(/\/$/, ""),
    token: tokenEl.value.trim(),
  });
  statusEl.textContent = "Saved.";
  setTimeout(() => (statusEl.textContent = ""), 1500);
});

restore();
