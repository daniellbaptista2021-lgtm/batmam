// Clow Copilot — popup with auth
document.addEventListener("DOMContentLoaded", () => {
  const secLogin = document.getElementById("secLogin");
  const secConn = document.getElementById("secConnected");
  const loginMsg = document.getElementById("loginMsg");

  // Check if already connected
  chrome.storage.local.get(["clow_token", "clow_email", "clow_api_url"], (r) => {
    if (r.clow_token) {
      // Verify token
      const url = (r.clow_api_url || "https://clow.pvcorretor01.com.br") + "/api/v1/auth/verify";
      fetch(url, {headers: {"Authorization": "Bearer " + r.clow_token}})
        .then(res => res.json())
        .then(data => {
          if (data.valid) {
            showConnected(r.clow_email, r.clow_api_url);
          } else {
            showLogin(r.clow_api_url);
          }
        })
        .catch(() => showLogin(r.clow_api_url));
    } else {
      showLogin();
    }
  });

  function showLogin(savedUrl) {
    secLogin.classList.add("active");
    secConn.classList.remove("active");
    if (savedUrl) document.getElementById("apiUrl").value = savedUrl;
  }

  function showConnected(email, url) {
    secLogin.classList.remove("active");
    secConn.classList.add("active");
    document.getElementById("connEmail").textContent = email || "conectado";
    document.getElementById("apiUrlConn").value = url || "";
  }

  // Login
  document.getElementById("loginBtn").onclick = async () => {
    const baseUrl = document.getElementById("apiUrl").value.trim() || "https://clow.pvcorretor01.com.br";
    const email = document.getElementById("email").value.trim();
    const password = document.getElementById("password").value;

    if (!email || !password) {
      loginMsg.textContent = "preencha email e senha";
      loginMsg.className = "msg err";
      return;
    }

    loginMsg.textContent = "conectando...";
    loginMsg.className = "msg";

    try {
      const res = await fetch(baseUrl + "/api/v1/auth/login", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({email, password})
      });
      const data = await res.json();

      if (res.ok && data.token) {
        chrome.storage.local.set({
          clow_token: data.token,
          clow_email: data.email,
          clow_api_url: baseUrl
        }, () => {
          loginMsg.textContent = "";
          showConnected(data.email, baseUrl);
        });
      } else {
        loginMsg.textContent = data.error || "erro no login";
        loginMsg.className = "msg err";
      }
    } catch (e) {
      loginMsg.textContent = "erro de conexao";
      loginMsg.className = "msg err";
    }
  };

  // Logout
  document.getElementById("logoutBtn").onclick = () => {
    chrome.storage.local.remove(["clow_token", "clow_email"], () => {
      showLogin();
    });
  };
});
