async function refresh() {
  try {
    const r = await fetch('/health');
    const d = await r.json();
    document.getElementById('lastUpdate').textContent = new Date().toLocaleTimeString('pt-BR', {hour:'2-digit',minute:'2-digit',second:'2-digit'});

    const c = d.components;
    document.getElementById('cards').innerHTML = `
      <div class="card">
        <div class="card-label">Tasks</div>
        <div class="card-value">${c.tasks.total}</div>
        <div class="card-detail">${Object.entries(c.tasks.by_status).map(([k,v])=>`<span class="badge ${k==='completed'?'ok':k==='failed'?'warn':'info'}">${k}: ${v}</span>`).join('')}</div>
      </div>
      <div class="card">
        <div class="card-label">Cron Jobs</div>
        <div class="card-value">${c.cron.active_jobs}<span class="unit"> / ${c.cron.total_jobs}</span></div>
        <div class="card-detail"><span class="badge purple">ativos</span></div>
      </div>
      <div class="card">
        <div class="card-label">Memoria</div>
        <div class="card-value">${c.memory.total}</div>
        <div class="card-detail">${Object.entries(c.memory.by_type).map(([k,v])=>`<span class="badge purple">${k}: ${v}</span>`).join('')}</div>
      </div>
      <div class="card">
        <div class="card-label">Triggers</div>
        <div class="card-value">${c.triggers.results_count}</div>
        <div class="card-detail">${c.triggers.running?'<span class="badge ok">online :'+c.triggers.port+'</span>':'<span class="badge warn">offline</span>'}</div>
      </div>`;

    const cronBody = document.getElementById('cronBody');
    if (c.cron.jobs.length === 0) {
      cronBody.innerHTML = '<tr><td colspan="6" class="s-muted">Nenhum cron job</td></tr>';
    } else {
      cronBody.innerHTML = c.cron.jobs.map(j => {
        const next = new Date(j.next_run * 1000).toLocaleTimeString('pt-BR',{hour:'2-digit',minute:'2-digit'});
        return `<tr>
          <td style="color:var(--purple)">${j.id}</td>
          <td>${j.prompt}</td>
          <td><span class="badge purple">${j.interval}</span></td>
          <td class="${j.active?'s-ok':'s-err'}">${j.active?'ativo':'pausado'}</td>
          <td>${j.run_count}x</td>
          <td class="s-muted">${next}</td>
        </tr>`;
      }).join('');
    }

    const actionsBody = document.getElementById('actionsBody');
    const actions = d.recent_actions || [];
    if (actions.length === 0) {
      actionsBody.innerHTML = '<tr><td colspan="4" class="s-muted">Nenhuma ação recente</td></tr>';
    } else {
      actionsBody.innerHTML = actions.reverse().map(a => {
        const t = new Date(a.timestamp * 1000).toLocaleTimeString('pt-BR',{hour:'2-digit',minute:'2-digit',second:'2-digit'});
        return `<tr>
          <td class="s-muted">${t}</td>
          <td>${a.action}</td>
          <td style="color:var(--text-secondary)">${a.details}</td>
          <td class="${a.status==='ok'?'s-ok':'s-err'}">${a.status}</td>
        </tr>`;
      }).join('');
    }
  } catch(e) {
    document.getElementById('cards').innerHTML = `<div class="card"><div class="card-label" style="color:var(--red)">Erro</div><div class="card-detail">${e.message}</div></div>`;
  }
}
refresh();
setInterval(refresh, 10000);
