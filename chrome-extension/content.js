// Clow Copilot — content script
(function() {
  if (document.getElementById("clow-overlay")) return;

  const DEFAULT_API = "https://clow.pvcorretor01.com.br/api/v1/chat";
  let apiUrl = DEFAULT_API;
  let apiKey = "";
  let pinned = false;
  let sessionId = "";

  // Load settings
  chrome.storage.sync.get(["clow_api_url", "clow_api_key"], (r) => {
    if (r.clow_api_url) apiUrl = r.clow_api_url;
    if (r.clow_api_key) apiKey = r.clow_api_key;
  });

  // Create overlay
  const ov = document.createElement("div");
  ov.id = "clow-overlay";
  ov.innerHTML = `
    <div class="clow-bar" id="clowBar">
      <span class="clow-bar-title">clow copilot</span>
      <span class="clow-bar-ctx" id="clowCtx"></span>
      <button class="clow-bar-pin" id="clowPin" title="pin">&#x1F4CC;</button>
      <button class="clow-bar-close" id="clowClose" title="fechar">&times;</button>
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

  // Toggle
  function toggle() {
    ov.classList.toggle("open");
    if (ov.classList.contains("open")) {
      inp.focus();
      updateCtx();
    }
  }

  function close() {
    if (!pinned) ov.classList.remove("open");
  }

  document.getElementById("clowClose").onclick = () => { ov.classList.remove("open"); };
  document.getElementById("clowPin").onclick = (e) => {
    pinned = !pinned;
    e.target.classList.toggle("pinned", pinned);
  };

  // Listen for toggle command from background
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

  // Auto-resize textarea
  inp.addEventListener("input", () => {
    inp.style.height = "auto";
    inp.style.height = Math.min(inp.scrollHeight, 80) + "px";
  });

  // Send message
  async function send() {
    const text = inp.value.trim();
    if (!text) return;

    // Show user message
    const userDiv = document.createElement("div");
    userDiv.className = "clow-msg-user";
    userDiv.textContent = text;
    out.appendChild(userDiv);

    inp.value = "";
    inp.style.height = "auto";

    // Build prompt with context
    const ctx = ClowContext.detect();
    const ctxStr = ClowContext.format(ctx);
    const fullPrompt = ctxStr ? ctxStr + "\n\n" + text : text;

    // Show thinking
    const thinkDiv = document.createElement("div");
    thinkDiv.className = "clow-thinking";
    thinkDiv.innerHTML = '<span class="clow-thinking-dot"></span> pensando...';
    out.appendChild(thinkDiv);
    out.scrollTop = out.scrollHeight;

    // Call API
    try {
      const headers = {"Content-Type": "application/json"};
      if (apiKey) headers["Authorization"] = "Bearer " + apiKey;

      const res = await fetch(apiUrl, {
        method: "POST",
        headers: headers,
        body: JSON.stringify({
          content: fullPrompt,
          session_id: sessionId,
          model: "sonnet"
        })
      });

      thinkDiv.remove();

      if (!res.ok) {
        const err = await res.json().catch(() => ({error: "Erro " + res.status}));
        showError(err.error || "Erro na API");
        return;
      }

      const data = await res.json();
      sessionId = data.session_id || sessionId;

      // Show tool calls
      if (data.tools && data.tools.length) {
        data.tools.forEach(t => showTool(t.name, t.status, t.output));
      }

      // Show response
      if (data.response) {
        const asstDiv = document.createElement("div");
        asstDiv.className = "clow-msg-asst";
        // Simple markdown rendering
        let html = data.response
          .replace(/```(\w*)\n([\s\S]*?)```/g, '<pre><code>$2</code></pre>')
          .replace(/`([^`]+)`/g, '<code>$1</code>')
          .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
          .replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank">$1</a>')
          .replace(/\n/g, '<br>');
        asstDiv.innerHTML = html;
        out.appendChild(asstDiv);
      }

      // Show file
      if (data.file) {
        const fDiv = document.createElement("div");
        fDiv.className = "clow-msg-asst";
        fDiv.innerHTML = `<a href="${data.file.url}" target="_blank">${data.file.name}</a> (${data.file.size})`;
        out.appendChild(fDiv);
      }

    } catch (e) {
      thinkDiv.remove();
      showError("Erro de conexao: " + e.message);
    }

    out.scrollTop = out.scrollHeight;
  }

  function showTool(name, status, output) {
    const div = document.createElement("div");
    div.className = "clow-tool";
    const dotClass = status === "error" ? "error" : status === "running" ? "running" : "";
    div.innerHTML = `<span class="clow-tool-dot ${dotClass}"></span><span class="clow-tool-name">${esc(name)}</span>`;
    if (output) {
      div.innerHTML += `<div class="clow-tool-out">${esc(output).substring(0, 300)}</div>`;
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
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  });
  document.getElementById("clowSend").onclick = send;

  // Draggable
  let isDragging = false, dragX = 0, dragY = 0;
  const bar = document.getElementById("clowBar");
  bar.addEventListener("mousedown", (e) => {
    if (e.target.tagName === "BUTTON") return;
    isDragging = true;
    dragX = e.clientX - ov.offsetLeft;
    dragY = e.clientY - ov.offsetTop;
    document.addEventListener("mousemove", onDrag);
    document.addEventListener("mouseup", () => {
      isDragging = false;
      document.removeEventListener("mousemove", onDrag);
    }, {once: true});
  });
  function onDrag(e) {
    if (!isDragging) return;
    ov.style.left = (e.clientX - dragX) + "px";
    ov.style.top = (e.clientY - dragY) + "px";
    ov.style.right = "auto";
    ov.style.bottom = "auto";
  }

  // Close on click outside (if not pinned)
  document.addEventListener("click", (e) => {
    if (ov.classList.contains("open") && !pinned && !ov.contains(e.target)) {
      ov.classList.remove("open");
    }
  });

  // Keyboard shortcut fallback
  document.addEventListener("keydown", (e) => {
    if (e.ctrlKey && e.shiftKey && e.key === "K") {
      e.preventDefault();
      toggle();
    }
  });
})();
