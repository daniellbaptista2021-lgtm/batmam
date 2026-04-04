// Clow Copilot — content script with auth
(function() {
  if (document.getElementById("clow-overlay")) return;

  let apiUrl = "https://clow.pvcorretor01.com.br";
  let token = "";
  let email = "";
  let pinned = false;
  let sessionId = "";

  // Load auth
  chrome.storage.local.get(["clow_token", "clow_email", "clow_api_url"], (r) => {
    token = r.clow_token || "";
    email = r.clow_email || "";
    apiUrl = r.clow_api_url || "https://clow.pvcorretor01.com.br";
    updateStatus();
  });

  // Listen for auth changes
  chrome.storage.onChanged.addListener((changes) => {
    if (changes.clow_token) token = changes.clow_token.newValue || "";
    if (changes.clow_email) email = changes.clow_email.newValue || "";
    if (changes.clow_api_url) apiUrl = changes.clow_api_url.newValue || apiUrl;
    updateStatus();
  });

  // Create overlay
  const ov = document.createElement("div");
  ov.id = "clow-overlay";
  ov.innerHTML = `
    <div class="clow-bar" id="clowBar">
      <span class="clow-bar-title">clow</span>
      <span class="clow-bar-ctx" id="clowCtx"></span>
      <span class="clow-bar-status" id="clowStatus"></span>
      <button class="clow-bar-pin" id="clowPin" title="pin">&#x1F4CC;</button>
      <button class="clow-bar-close" id="clowClose">&times;</button>
    </div>
    <div class="clow-out" id="clowOut"></div>
    <div class="clow-prompt">
      <span class="clow-prompt-char">&#x276F;</span>
      <textarea id="clowInp" rows="1" placeholder=""></textarea>
      <button class="clow-prompt-send" id="clowSend">&#x21B5;</button>
    </div>
  `;
  document.body.appendChild(ov);

  const out = document.getElementById("clowOut");
  const inp = document.getElementById("clowInp");
  const ctxEl = document.getElementById("clowCtx");
  const statusEl = document.getElementById("clowStatus");

  function updateStatus() {
    if (token) {
      statusEl.textContent = "on";
      statusEl.style.color = "#4ade80";
      statusEl.title = email;
    } else {
      statusEl.textContent = "off";
      statusEl.style.color = "#f87171";
      statusEl.title = "nao autenticado — configure no popup da extensao";
    }
  }

  // Toggle
  function toggle() {
    if (!token) {
      // Not authenticated — don't open overlay, flash status
      statusEl.style.color = "#fbbf24";
      setTimeout(() => updateStatus(), 1000);
      return;
    }
    ov.classList.toggle("open");
    if (ov.classList.contains("open")) {
      inp.focus();
      updateCtx();
    }
  }

  document.getElementById("clowClose").onclick = () => ov.classList.remove("open");
  document.getElementById("clowPin").onclick = (e) => {
    pinned = !pinned;
    e.target.classList.toggle("pinned", pinned);
  };

  // Listen for toggle command
  chrome.runtime.onMessage.addListener((msg) => {
    if (msg.action === "toggle") toggle();
  });

  // Context
  function updateCtx() {
    const ctx = ClowContext.detect();
    if (ctx.platform) {
      ctxEl.textContent = ctx.platform;
      ctxEl.title = ClowContext.format(ctx);
    } else {
      ctxEl.textContent = "";
    }
  }

  // Auto-resize
  inp.addEventListener("input", () => {
    inp.style.height = "auto";
    inp.style.height = Math.min(inp.scrollHeight, 80) + "px";
  });

  // Send
  async function send() {
    const text = inp.value.trim();
    if (!text) return;
    if (!token) {
      showError("nao autenticado — configure no popup da extensao");
      return;
    }

    // User message
    const userDiv = document.createElement("div");
    userDiv.className = "clow-msg-user";
    userDiv.textContent = text;
    out.appendChild(userDiv);
    inp.value = "";
    inp.style.height = "auto";

    // Context
    const ctx = ClowContext.detect();
    const ctxStr = ClowContext.format(ctx);
    const fullPrompt = ctxStr ? ctxStr + "\n\n" + text : text;

    // Thinking
    const thinkDiv = document.createElement("div");
    thinkDiv.className = "clow-thinking";
    thinkDiv.innerHTML = '<span class="clow-thinking-dot"></span> pensando...';
    out.appendChild(thinkDiv);
    out.scrollTop = out.scrollHeight;

    try {
      const res = await fetch(apiUrl + "/api/v1/chat", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Authorization": "Bearer " + token
        },
        body: JSON.stringify({content: fullPrompt, session_id: sessionId, model: "sonnet"})
      });

      thinkDiv.remove();

      // Token expired
      if (res.status === 401) {
        token = "";
        chrome.storage.local.remove(["clow_token"]);
        updateStatus();
        showError("sessao expirada — reconecte no popup da extensao");
        return;
      }

      if (!res.ok) {
        const err = await res.json().catch(() => ({error: "Erro " + res.status}));
        showError(err.error || "Erro na API");
        return;
      }

      const data = await res.json();
      sessionId = data.session_id || sessionId;

      if (data.tools && data.tools.length) {
        data.tools.forEach(t => showTool(t.name, t.status, t.output));
      }

      if (data.response) {
        const asstDiv = document.createElement("div");
        asstDiv.className = "clow-msg-asst";
        let html = data.response
          .replace(/```(\w*)\n([\s\S]*?)```/g, '<pre><code>$2</code></pre>')
          .replace(/`([^`]+)`/g, '<code>$1</code>')
          .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
          .replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank">$1</a>')
          .replace(/\n/g, '<br>');
        asstDiv.innerHTML = html;
        out.appendChild(asstDiv);
      }

      if (data.file) {
        const fDiv = document.createElement("div");
        fDiv.className = "clow-msg-asst";
        fDiv.innerHTML = '<a href="' + esc(data.file.url) + '" target="_blank">' + esc(data.file.name) + '</a>';
        out.appendChild(fDiv);
      }
    } catch (e) {
      thinkDiv.remove();
      showError("erro de conexao: " + e.message);
    }

    out.scrollTop = out.scrollHeight;
  }

  function showTool(name, status, output) {
    const div = document.createElement("div");
    div.className = "clow-tool";
    const dc = status === "error" ? "error" : status === "running" ? "running" : "";
    div.innerHTML = '<span class="clow-tool-dot ' + dc + '"></span><span class="clow-tool-name">' + esc(name) + '</span>';
    if (output) {
      div.innerHTML += '<div class="clow-tool-out">' + esc(output).substring(0, 300) + '</div>';
      div.onclick = () => div.classList.toggle("open");
    }
    out.appendChild(div);
  }

  function showError(msg) {
    const div = document.createElement("div");
    div.className = "clow-msg-asst";
    div.style.color = "#f87171";
    div.textContent = msg;
    out.appendChild(div);
  }

  function esc(t) {
    const d = document.createElement("div");
    d.textContent = t;
    return d.innerHTML;
  }

  // Enter to send
  inp.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); }
  });
  document.getElementById("clowSend").onclick = send;

  // Draggable
  let isDragging = false, dragX = 0, dragY = 0;
  document.getElementById("clowBar").addEventListener("mousedown", (e) => {
    if (e.target.tagName === "BUTTON" || e.target.tagName === "SPAN") return;
    isDragging = true;
    dragX = e.clientX - ov.offsetLeft;
    dragY = e.clientY - ov.offsetTop;
    const onMove = (e) => {
      if (!isDragging) return;
      ov.style.left = (e.clientX - dragX) + "px";
      ov.style.top = (e.clientY - dragY) + "px";
      ov.style.right = "auto";
      ov.style.bottom = "auto";
    };
    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseup", () => {
      isDragging = false;
      document.removeEventListener("mousemove", onMove);
    }, {once: true});
  });

  // Close on click outside
  document.addEventListener("click", (e) => {
    if (ov.classList.contains("open") && !pinned && !ov.contains(e.target)) {
      ov.classList.remove("open");
    }
  });

  // Keyboard shortcut
  document.addEventListener("keydown", (e) => {
    if (e.ctrlKey && e.shiftKey && e.key === "K") { e.preventDefault(); toggle(); }
  });
})();
