// Clow Copilot — Side Panel with auth
(function() {
  if (document.getElementById("clow-panel")) return;

  let apiUrl = "https://clow.pvcorretor01.com.br";
  let token = "";
  let email = "";
  let sessionId = "";

  chrome.storage.local.get(["clow_token", "clow_email", "clow_api_url"], (r) => {
    token = r.clow_token || "";
    email = r.clow_email || "";
    apiUrl = r.clow_api_url || "https://clow.pvcorretor01.com.br";
    updateStatus();
  });

  chrome.storage.onChanged.addListener((c) => {
    if (c.clow_token) token = c.clow_token.newValue || "";
    if (c.clow_email) email = c.clow_email.newValue || "";
    if (c.clow_api_url) apiUrl = c.clow_api_url.newValue || apiUrl;
    updateStatus();
  });

  // Backdrop
  const bd = document.createElement("div");
  bd.id = "clow-backdrop";
  bd.onclick = () => close();
  document.body.appendChild(bd);

  // Panel
  const panel = document.createElement("div");
  panel.id = "clow-panel";
  panel.innerHTML = `
    <div class="cp-hdr">
      <span class="cp-title">Clow Copilot</span>
      <span class="cp-model">sonnet</span>
      <span class="cp-status"><span class="cp-dot off" id="cpDot"></span><span id="cpStatusTxt">off</span></span>
      <button class="cp-close" id="cpClose">&times;</button>
    </div>
    <div class="cp-ctx" id="cpCtx"><span class="cp-ctx-icon"></span><span id="cpCtxTxt"></span></div>
    <div class="cp-chat" id="cpChat"></div>
    <div class="cp-input">
      <div class="cp-input-box">
        <textarea id="cpInp" rows="1" placeholder="Mensagem para o Clow..."></textarea>
        <button class="cp-send" id="cpSend">&#x2191;</button>
      </div>
    </div>
  `;
  document.body.appendChild(panel);

  const chat = document.getElementById("cpChat");
  const inp = document.getElementById("cpInp");
  const ctxBar = document.getElementById("cpCtx");
  const ctxTxt = document.getElementById("cpCtxTxt");
  const dot = document.getElementById("cpDot");
  const statusTxt = document.getElementById("cpStatusTxt");

  function updateStatus() {
    if (token) {
      dot.className = "cp-dot on";
      statusTxt.textContent = "on";
    } else {
      dot.className = "cp-dot off";
      statusTxt.textContent = "off";
    }
  }

  function open() {
    if (!token) return;
    panel.classList.add("open");
    bd.classList.add("show");
    inp.focus();
    updateCtx();
  }

  function close() {
    panel.classList.remove("open");
    bd.classList.remove("show");
  }

  function toggle() {
    if (!token) {
      // Flash to indicate not authenticated
      dot.className = "cp-dot off";
      statusTxt.textContent = "login";
      setTimeout(updateStatus, 1500);
      return;
    }
    panel.classList.contains("open") ? close() : open();
  }

  document.getElementById("cpClose").onclick = close;

  chrome.runtime.onMessage.addListener((msg) => {
    if (msg.action === "toggle") toggle();
  });

  // Context detection
  function updateCtx() {
    const ctx = ClowContext.detect();
    if (ctx.platform) {
      ctxBar.classList.add("show");
      const d = ctx.details;
      let label = ctx.platform;
      if (ctx.platform === "github" && d.owner) label = `GitHub: ${d.owner}/${d.repo}` + (d.branch ? `/${d.branch}` : "");
      else if (ctx.platform === "n8n" && d.workflow) label = `n8n: ${d.workflow}`;
      else if (ctx.platform === "vercel" && d.project) label = `Vercel: ${d.project}`;
      else if (ctx.platform === "supabase" && d.project_id) label = `Supabase: ${d.project_id}`;
      else if (ctx.platform === "chatwoot" && d.contact) label = `Chatwoot: ${d.contact}`;
      ctxTxt.textContent = label;
      ctxBar.querySelector(".cp-ctx-icon").textContent = ctx.platform === "github" ? "GH" : ctx.platform.substring(0, 2).toUpperCase();
    } else {
      ctxBar.classList.remove("show");
    }
  }

  // Auto-resize
  inp.addEventListener("input", () => {
    inp.style.height = "auto";
    inp.style.height = Math.min(inp.scrollHeight, 120) + "px";
  });

  // Send
  async function send() {
    const text = inp.value.trim();
    if (!text || !token) return;

    // User msg
    const uDiv = document.createElement("div");
    uDiv.className = "cp-msg cp-msg-user";
    uDiv.textContent = text;
    chat.appendChild(uDiv);

    inp.value = "";
    inp.style.height = "auto";

    // Context injection
    const ctx = ClowContext.detect();
    const ctxStr = ClowContext.format(ctx);
    const prompt = ctxStr ? ctxStr + "\n\n" + text : text;

    // Thinking
    const think = document.createElement("div");
    think.className = "cp-think";
    think.innerHTML = '<span class="cp-think-dot"></span> pensando...';
    chat.appendChild(think);
    chat.scrollTop = chat.scrollHeight;

    try {
      const res = await fetch(apiUrl + "/api/v1/chat", {
        method: "POST",
        headers: {"Content-Type": "application/json", "Authorization": "Bearer " + token},
        body: JSON.stringify({content: prompt, session_id: sessionId, model: "sonnet"})
      });

      think.remove();

      if (res.status === 401) {
        token = "";
        chrome.storage.local.remove(["clow_token"]);
        updateStatus();
        addErr("sessao expirada — reconecte no popup");
        return;
      }

      if (!res.ok) {
        const e = await res.json().catch(() => ({}));
        addErr(e.error || "Erro " + res.status);
        return;
      }

      const data = await res.json();
      sessionId = data.session_id || sessionId;

      // Tools
      if (data.tools && data.tools.length) {
        data.tools.forEach(t => addTool(t.name, t.status, t.output));
      }

      // Response
      if (data.response) {
        const aDiv = document.createElement("div");
        aDiv.className = "cp-msg cp-msg-asst";
        aDiv.innerHTML = renderMd(data.response);
        chat.appendChild(aDiv);
      }
    } catch (e) {
      think.remove();
      addErr("erro: " + e.message);
    }

    chat.scrollTop = chat.scrollHeight;
  }

  function addTool(name, status, output) {
    const div = document.createElement("div");
    div.className = "cp-tool";
    const dc = status === "error" ? "err" : status === "running" ? "run" : "";
    div.innerHTML = `<span class="cp-tool-dot ${dc}"></span><span class="cp-tool-name">${esc(name)}</span>`;
    if (output) {
      div.innerHTML += `<div class="cp-tool-out">${esc(output).substring(0, 500)}</div>`;
      div.onclick = () => div.classList.toggle("open");
    }
    chat.appendChild(div);
  }

  function addErr(msg) {
    const div = document.createElement("div");
    div.className = "cp-err";
    div.textContent = msg;
    chat.appendChild(div);
  }

  function renderMd(text) {
    return text
      .replace(/```(\w*)\n([\s\S]*?)```/g, '<pre><code>$2</code></pre>')
      .replace(/`([^`]+)`/g, '<code>$1</code>')
      .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
      .replace(/^### (.+)$/gm, '<h3>$1</h3>')
      .replace(/^## (.+)$/gm, '<h2>$1</h2>')
      .replace(/^# (.+)$/gm, '<h1>$1</h1>')
      .replace(/^\- (.+)$/gm, '<li>$1</li>')
      .replace(/(<li>.*<\/li>)/s, '<ul>$1</ul>')
      .replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank">$1</a>')
      .replace(/^---$/gm, '<hr>')
      .replace(/\n/g, '<br>');
  }

  function esc(t) { const d = document.createElement("div"); d.textContent = t; return d.innerHTML; }

  // Keys
  inp.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); }
  });
  document.getElementById("cpSend").onclick = send;

  document.addEventListener("keydown", (e) => {
    if (e.ctrlKey && e.shiftKey && e.key === "K") { e.preventDefault(); toggle(); }
    if (e.key === "Escape" && panel.classList.contains("open")) close();
  });
})();
