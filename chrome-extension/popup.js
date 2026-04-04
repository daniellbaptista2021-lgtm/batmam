// Popup settings
document.addEventListener("DOMContentLoaded", () => {
  chrome.storage.sync.get(["clow_api_url", "clow_api_key"], (r) => {
    if (r.clow_api_url) document.getElementById("apiUrl").value = r.clow_api_url;
    if (r.clow_api_key) document.getElementById("apiKey").value = r.clow_api_key;
  });

  document.getElementById("saveBtn").onclick = () => {
    const url = document.getElementById("apiUrl").value.trim();
    const key = document.getElementById("apiKey").value.trim();
    chrome.storage.sync.set({
      clow_api_url: url || "https://clow.pvcorretor01.com.br/api/v1/chat",
      clow_api_key: key
    }, () => {
      const msg = document.getElementById("savedMsg");
      msg.style.display = "block";
      setTimeout(() => msg.style.display = "none", 2000);
    });
  };
});
