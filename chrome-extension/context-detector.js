// Context detector — extracts info from known platforms
const ClowContext = {
  detect() {
    const host = location.hostname;
    const path = location.pathname;
    const ctx = {platform: null, details: {}};

    // GitHub
    if (host === "github.com") {
      ctx.platform = "github";
      const parts = path.split("/").filter(Boolean);
      if (parts.length >= 2) {
        ctx.details.owner = parts[0];
        ctx.details.repo = parts[1];
      }
      if (parts.length >= 4 && parts[2] === "blob") {
        ctx.details.branch = parts[3];
        ctx.details.file = parts.slice(4).join("/");
      }
      if (parts.length >= 4 && parts[2] === "tree") {
        ctx.details.branch = parts[3];
      }
      if (parts[2] === "pull") ctx.details.pr = parts[3];
      if (parts[2] === "issues") ctx.details.issue = parts[3];
      // Try to get file content from code view
      const codeEl = document.querySelector(".react-code-lines, .blob-code-content, [data-testid='raw-button']");
      if (codeEl) ctx.details.has_code = true;
    }

    // n8n
    else if (host.includes("n8n")) {
      ctx.platform = "n8n";
      const titleEl = document.querySelector(".workflow-name, [data-test-id='workflow-name']");
      if (titleEl) ctx.details.workflow = titleEl.textContent.trim();
      const nodes = document.querySelectorAll(".node-default, [data-test-id='canvas-node']");
      ctx.details.node_count = nodes.length;
      ctx.details.nodes = Array.from(nodes).slice(0, 10).map(n => {
        const name = n.querySelector(".node-name, .node-title");
        return name ? name.textContent.trim() : "";
      }).filter(Boolean);
    }

    // Chatwoot
    else if (host.includes("chatwoot") || document.querySelector("[data-app='chatwoot']")) {
      ctx.platform = "chatwoot";
      const contact = document.querySelector(".contact--name, .contact-name");
      if (contact) ctx.details.contact = contact.textContent.trim();
      const convId = path.match(/conversations\/(\d+)/);
      if (convId) ctx.details.conversation_id = convId[1];
      const msgs = document.querySelectorAll(".conversation-wrap .message-text__wrap");
      ctx.details.message_count = msgs.length;
      if (msgs.length > 0) {
        ctx.details.last_message = msgs[msgs.length - 1].textContent.trim().substring(0, 200);
      }
    }

    // Vercel
    else if (host.includes("vercel.com")) {
      ctx.platform = "vercel";
      const project = path.split("/").filter(Boolean);
      if (project.length >= 1) ctx.details.project = project[project.length - 1];
      const status = document.querySelector("[data-testid='deployment-state'], .deployment-state");
      if (status) ctx.details.deploy_status = status.textContent.trim();
      const domain = document.querySelector(".project-domain, [data-testid='project-domain']");
      if (domain) ctx.details.domain = domain.textContent.trim();
    }

    // Supabase
    else if (host.includes("supabase")) {
      ctx.platform = "supabase";
      const projMatch = path.match(/project\/([^/]+)/);
      if (projMatch) ctx.details.project_id = projMatch[1];
      const tables = document.querySelectorAll("[data-testid='table-name'], .table-name");
      ctx.details.tables = Array.from(tables).slice(0, 20).map(t => t.textContent.trim()).filter(Boolean);
      if (path.includes("/editor")) ctx.details.section = "sql-editor";
      if (path.includes("/table")) ctx.details.section = "table-editor";
      if (path.includes("/auth")) ctx.details.section = "auth";
    }

    // Generic — get page title and selected text
    ctx.details.page_title = document.title;
    ctx.details.url = location.href;
    const sel = window.getSelection().toString().trim();
    if (sel) ctx.details.selected_text = sel.substring(0, 1000);

    return ctx;
  },

  format(ctx) {
    if (!ctx.platform) return "";
    let lines = [`[Contexto: ${ctx.platform}]`];
    const d = ctx.details;

    if (ctx.platform === "github") {
      if (d.owner) lines.push(`Repo: ${d.owner}/${d.repo}`);
      if (d.branch) lines.push(`Branch: ${d.branch}`);
      if (d.file) lines.push(`Arquivo: ${d.file}`);
      if (d.pr) lines.push(`PR: #${d.pr}`);
      if (d.issue) lines.push(`Issue: #${d.issue}`);
    } else if (ctx.platform === "n8n") {
      if (d.workflow) lines.push(`Workflow: ${d.workflow}`);
      if (d.nodes && d.nodes.length) lines.push(`Nodes: ${d.nodes.join(", ")}`);
    } else if (ctx.platform === "chatwoot") {
      if (d.contact) lines.push(`Contato: ${d.contact}`);
      if (d.conversation_id) lines.push(`Conversa: #${d.conversation_id}`);
      if (d.last_message) lines.push(`Ultima msg: ${d.last_message}`);
    } else if (ctx.platform === "vercel") {
      if (d.project) lines.push(`Projeto: ${d.project}`);
      if (d.deploy_status) lines.push(`Deploy: ${d.deploy_status}`);
      if (d.domain) lines.push(`Dominio: ${d.domain}`);
    } else if (ctx.platform === "supabase") {
      if (d.project_id) lines.push(`Projeto: ${d.project_id}`);
      if (d.section) lines.push(`Secao: ${d.section}`);
      if (d.tables && d.tables.length) lines.push(`Tabelas: ${d.tables.join(", ")}`);
    }
    if (d.selected_text) lines.push(`Selecionado: ${d.selected_text}`);
    return lines.join("\n");
  }
};
