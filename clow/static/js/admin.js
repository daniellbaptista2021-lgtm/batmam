async function load(){
  const [sr,ur]=await Promise.all([fetch('/api/v1/admin/stats').then(r=>r.json()),fetch('/api/v1/admin/users').then(r=>r.json())]);
  document.getElementById('stats').innerHTML=`
    <div class="stat"><div class="stat-label">Usuários</div><div class="stat-val">${sr.total_users}</div><div class="stat-sub">${sr.active_users} ativos</div></div>
    <div class="stat"><div class="stat-label">Custo Hoje</div><div class="stat-val">$${sr.cost_today.toFixed(3)}</div></div>
    <div class="stat"><div class="stat-label">Custo Semana</div><div class="stat-val">$${sr.cost_week.toFixed(3)}</div></div>
    <div class="stat"><div class="stat-label">Custo Mes</div><div class="stat-val">$${sr.cost_month.toFixed(3)}</div></div>
    <div class="stat"><div class="stat-label">Tokens Hoje</div><div class="stat-val">${(sr.tokens_today/1000).toFixed(0)}k</div></div>`;
  const ub=document.getElementById('usersBody');
  ub.innerHTML=ur.users.map(u=>{
    const dt=new Date(u.created_at*1000).toLocaleDateString('pt-BR');
    const st=u.active?'<span class="badge g">ativo</span>':'<span class="badge r">inativo</span>';
    const sc=u.has_system_clow?'<span class="badge g">ativo</span>':'<span class="badge r">off</span>';
    const scBtn=u.has_system_clow?'Desativar':'Ativar';
    return `<tr><td>${u.email}</td><td><select onchange="setPlan('${u.id}',this.value)">${['free','basic','pro','unlimited'].map(p=>`<option ${u.plan===p?'selected':''}>${p}</option>`).join('')}</select></td><td>${st}</td><td>${sc} <button onclick="toggleSysClow('${u.id}',${u.has_system_clow?0:1})" style="margin-left:6px;font-size:11px">${scBtn}</button></td><td style="color:var(--tm)">${dt}</td><td><button onclick="toggle('${u.id}',${u.active?0:1})">${u.active?'Desativar':'Ativar'}</button></td></tr>`;
  }).join('');
  const tb=document.getElementById('topBody');
  tb.innerHTML=(sr.top_users_today||[]).map(u=>`<tr><td>${u.email}</td><td><span class="badge p">${u.plan}</span></td><td>${(u.tokens/1000).toFixed(0)}k</td><td>$${u.cost.toFixed(4)}</td></tr>`).join('')||'<tr><td colspan="4" style="color:var(--tm)">Sem dados</td></tr>';
}
async function setPlan(id,plan){await fetch(`/api/v1/admin/users/${id}`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({plan})});load();}
async function toggle(id,active){await fetch(`/api/v1/admin/users/${id}`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({active})});load();}
async function toggleSysClow(id,val){await fetch(`/api/v1/admin/users/${id}`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({has_system_clow:val})});load();}
load();setInterval(load,30000);
