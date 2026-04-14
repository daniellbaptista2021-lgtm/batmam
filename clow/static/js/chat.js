const INF='<svg viewBox="0 0 32 32" style="width:16px;height:16px"><path d="M8 16c0-3 2-6 5-6s5 3 8 6c3 3 5 6 8 6s5-3 5-6-2-6-5-6-5 3-8 6c-3 3-5 6-8 6s-5-3-5-6z" transform="translate(-5,0) scale(.95)" fill="none" stroke="var(--p)" stroke-width="3" stroke-linecap="round"/></svg>';
const T=document.getElementById('term'),I=document.getElementById('inp'),SB=document.getElementById('sBtn');
let ws=null,proc=false,curMsg=null,curBody=null,curTool=null,tStart=0,tTimer=null,rA=0,http=false,hSid='',raw='',me=null,cid='',selMod='deepseek-chat';
async function init(){
  try{const r=await fetch('/api/v1/me');me=await r.json();
    document.getElementById('sbAv').textContent=me.email[0].toUpperCase();
    document.getElementById('sbEm').textContent=me.email;
    document.getElementById('sbPl').textContent=me.plan;
    if(me.is_admin)document.getElementById('admSec').style.display='block';
    var _scP=['starter','pro','business','unlimited','admin'];if(_scP.indexOf(me.plan)>=0||me.is_admin){var _scb=document.getElementById('systemCodeBtn');if(_scb)_scb.style.display='block';}
    initMod(me.plan,me.is_admin);
    _loadPlanBadge();
  }catch(e){}
  loadConvs();connectWS();_setupMobileViewport();
}
async function _loadPlanBadge(){
  try{
    const r=await fetch('/api/v1/user/usage');const u=await r.json();
    const b=document.getElementById('planBadge');if(!b)return;
    b.style.display='block';
    const names={'byok_free':'BYOK Gratuito','lite':'Lite','starter':'Starter','pro':'Pro','business':'Business','free':'Gratuito','unlimited':'Admin'};
    document.getElementById('planName').textContent=names[u.plan_id]||u.plan_name||u.plan_id;
    document.getElementById('planModel').textContent=u.model&&u.model.includes('reasoner')?'DeepSeek Reasoner':'DeepSeek Chat';
    if(u.limits.daily_input>0){
      const used=u.today.input+u.today.output;
      const limit=u.limits.daily_input+u.limits.daily_output;
      const pct=Math.min(100,Math.round(used/limit*100));
      document.getElementById('planBar').style.width=pct+'%';
      if(pct>=90)document.getElementById('planBar').style.background='#F87171';
      else if(pct>=70)document.getElementById('planBar').style.background='#FBBF24';
      const fmt=n=>n>=1e6?(n/1e6).toFixed(1)+'M':n>=1e3?Math.round(n/1e3)+'K':n;
      document.getElementById('planUsage').textContent=fmt(used)+' usados';
      document.getElementById('planLimit').textContent=fmt(limit)+' diario';
    }else{
      document.getElementById('planBar').style.width='100%';
      document.getElementById('planUsage').textContent='Uso livre';
      document.getElementById('planLimit').textContent='Sem limite';
    }
    // Header bar
    const hp=document.getElementById('hdrPlan'),hb=document.getElementById('hdrBar'),hpct=document.getElementById('hdrPct');
    if(hp){
      const names2={'byok_free':'BYOK','lite':'Lite','starter':'Starter','pro':'Pro','business':'Business','free':'Free','unlimited':'Admin'};
      hp.textContent=names2[u.plan_id]||u.plan_id;
      if(u.limits.daily_input>0){
        const used2=u.today.input+u.today.output,limit2=u.limits.daily_input+u.limits.daily_output;
        const p2=Math.min(100,Math.round(used2/limit2*100));
        if(hb){hb.style.width=p2+'%';if(p2>=90)hb.style.background='#F87171';else if(p2>=70)hb.style.background='#FBBF24'}
        if(hpct)hpct.textContent=p2+'%';
      }else{if(hb)hb.style.width='100%';if(hpct)hpct.textContent='ilimitado'}
    }
  }catch(e){}
}
function initMod(plan,adm){const s=document.getElementById('modSel');selMod='deepseek-chat';if(s)s.style.display='none'}
function onMod(){}
function toggleSB(){document.getElementById('sb').classList.toggle('open');document.getElementById('sbOv').classList.toggle('show')}
function togDrop(){document.getElementById('hdrDrop').classList.toggle('show')}
function clsDrop(){document.getElementById('hdrDrop').classList.remove('show')}
document.addEventListener('click',e=>{if(!e.target.closest('.hdr-menu'))clsDrop()});
let pinnedConvs=JSON.parse(localStorage.getItem('clow_pinned')||'[]');
let allConvsCache=[];
let showAllPast=false;
let activeCtxMenu=null;

function closeCtxMenu(){if(activeCtxMenu){activeCtxMenu.remove();activeCtxMenu=null}}
document.addEventListener('click',e=>{if(activeCtxMenu&&!e.target.closest('.conv-ctx-menu')&&!e.target.closest('.ca-btn'))closeCtxMenu()});
document.addEventListener('keydown',e=>{if(e.key==='Escape')closeCtxMenu()});

function getDateGroup(ts){
  const d=new Date(ts*1000);const now=new Date();
  const today=new Date(now.getFullYear(),now.getMonth(),now.getDate());
  const yesterday=new Date(today);yesterday.setDate(today.getDate()-1);
  const week=new Date(today);week.setDate(today.getDate()-7);
  const convDay=new Date(d.getFullYear(),d.getMonth(),d.getDate());
  if(convDay>=today)return'Hoje';
  if(convDay>=yesterday)return'Ontem';
  if(convDay>=week)return'Ultimos 7 dias';
  return'Anteriores';
}

function smartTitle(t){
  if(!t||t==='Nova conversa')return'Nova conversa';
  const generic=['oi','ola','bom dia','boa tarde','boa noite','hey','hello','hi','e ai','fala'];
  const w=t.trim().toLowerCase();
  if(generic.includes(w))return'Nova conversa';
  if(t.length>28)return t.substring(0,28)+'...';
  return t;
}

async function loadConvs(){try{
  const r=await fetch('/api/v1/conversations');const d=await r.json();
  const el=document.getElementById('convList');
  allConvsCache=d.conversations||[];
  const pinned=allConvsCache.filter(c=>pinnedConvs.includes(c.id));
  const unpinned=allConvsCache.filter(c=>!pinnedConvs.includes(c.id));
  // Show search icon if 3+ conversations
  document.getElementById('convSearchWrap').style.display=allConvsCache.length>=3?'block':'none';
  let h='';
  // PINNED
  if(pinned.length){
    h+='<div class="sb-grp-label">FIXADAS</div>';
    pinned.forEach(c=>{h+=convBtn(c,true)});
  }
  // GROUP BY DATE
  const groups={};
  const maxShow=showAllPast?unpinned.length:10;
  unpinned.slice(0,maxShow).forEach(c=>{
    const g=getDateGroup(c.updated_at||c.created_at);
    if(!groups[g])groups[g]=[];
    groups[g].push(c);
  });
  const order=['Hoje','Ontem','Ultimos 7 dias','Anteriores'];
  order.forEach(g=>{
    if(groups[g]&&groups[g].length){
      h+='<div class="sb-grp-label">'+g+'</div>';
      groups[g].forEach(c=>{h+=convBtn(c,false)});
    }
  });
  if(!showAllPast&&unpinned.length>10){
    h+='<button class="sb-conv-more" onclick="showAllPast=true;loadConvs()">Ver anteriores ('+unpinned.length+')</button>';
  }
  el.innerHTML=h||'<div style="padding:12px 8px;color:var(--tm);font-size:12px;text-align:center">Nenhuma conversa</div>';
  bindConvEvents();
}catch(e){}}

function convBtn(c,isPinned){
  const t=smartTitle(c.title);
  const isAct=c.id===cid;
  return '<div class="sb-conv-item'+(isAct?' act':'')+'" data-id="'+c.id+'" data-title="'+esc(c.title)+'">'
    +'<span class="conv-icon">'+(isPinned?'':'&#x1F4AC;')+'</span>'
    +(isPinned?'<span class="conv-pin-static">&#x1F4CC;</span>':'')
    +'<span class="conv-title">'+esc(t)+'</span>'
    +'<span class="conv-actions">'
    +'<button class="ca-btn ca-pin" data-cid="'+c.id+'" data-pinned="'+(isPinned?'1':'0')+'" title="'+(isPinned?'Desafixar':'Fixar')+'" aria-label="'+(isPinned?'Desafixar conversa':'Fixar conversa')+'">&#x1F4CC;</button>'
    +'<button class="ca-btn ca-menu" data-cid="'+c.id+'" data-pinned="'+(isPinned?'1':'0')+'" title="Menu" aria-label="Opções da conversa">\u22EF</button>'
    +'</span></div>';
}
function bindConvEvents(){
  // Bind click on conv items (load conversation)
  document.querySelectorAll('.sb-conv-item').forEach(function(el){
    el.addEventListener('click',function(e){
      if(e.target.closest('.ca-btn'))return; // Don't load if clicking action buttons
      loadConv(el.getAttribute('data-id'));
    });
  });
  // Bind pin buttons
  document.querySelectorAll('.ca-pin').forEach(function(btn){
    btn.addEventListener('click',function(e){
      e.stopPropagation();
      togglePin(btn.getAttribute('data-cid'));
    });
  });
  // Bind menu buttons
  document.querySelectorAll('.ca-menu').forEach(function(btn){
    btn.addEventListener('click',function(e){
      e.stopPropagation();
      showCtxMenu(e,btn.getAttribute('data-cid'),btn.getAttribute('data-pinned')==='1');
    });
  });
}

function showCtxMenu(e,id,isPinned){
  e.preventDefault();e.stopPropagation();
  closeCtxMenu();
  const menu=document.createElement('div');
  menu.className='conv-ctx-menu';
  // Block ALL clicks inside menu from bubbling to document
  menu.addEventListener('click',function(ev){ev.stopPropagation()});
  menu.addEventListener('mousedown',function(ev){ev.stopPropagation()});
  // Build menu items with addEventListener (not inline onclick)
  const items=[
    {icon:'\u270F\uFE0F',label:'Renomear',action:function(){closeCtxMenu();startRename(id)}},
    {icon:'\uD83D\uDCCC',label:isPinned?'Desafixar':'Fixar conversa',action:function(){closeCtxMenu();togglePin(id)}},
    {icon:'\uD83D\uDCCB',label:'Copiar conversa',action:function(){closeCtxMenu();copyConv(id)}},
    {sep:true},
    {icon:'\uD83D\uDDD1\uFE0F',label:'Deletar conversa',danger:true,action:function(ev){confirmDel(id,ev.currentTarget,menu)}}
  ];
  items.forEach(function(item){
    if(item.sep){const s=document.createElement('div');s.className='conv-ctx-sep';menu.appendChild(s);return}
    const btn=document.createElement('button');
    btn.className='ctx-item'+(item.danger?' danger':'');
    btn.innerHTML='<span class="ctx-icon">'+item.icon+'</span>'+item.label;
    btn.addEventListener('click',item.action);
    menu.appendChild(btn);
  });
  document.body.appendChild(menu);
  // Position near click
  const x=Math.min(e.clientX,window.innerWidth-200);
  const y=Math.min(e.clientY,window.innerHeight-menu.offsetHeight-10);
  menu.style.left=x+'px';menu.style.top=y+'px';
  activeCtxMenu=menu;
}

function confirmDel(id,btn,menu){
  const confirm=document.createElement('div');
  confirm.className='conv-del-confirm';
  const span=document.createElement('span');span.textContent='Tem certeza?';
  const yes=document.createElement('button');yes.className='del-yes';yes.textContent='Sim';
  yes.addEventListener('click',function(ev){ev.stopPropagation();delConv(id)});
  const no=document.createElement('button');no.className='del-no';no.textContent='Nao';
  no.addEventListener('click',function(ev){ev.stopPropagation();closeCtxMenu()});
  confirm.appendChild(span);confirm.appendChild(yes);confirm.appendChild(no);
  btn.replaceWith(confirm);
}

async function delConv(id){
  closeCtxMenu();
  const el=document.querySelector('.sb-conv-item[data-id="'+id+'"]');
  if(el){el.classList.add('leaving');await new Promise(r=>setTimeout(r,200))}
  try{await fetch('/api/v1/conversations/'+id,{method:'DELETE'});
    if(id===cid){cid=null;hSid='';T.innerHTML='';showWelc();document.getElementById('hdrT').textContent='Nova conversa'}
    pinnedConvs=pinnedConvs.filter(x=>x!==id);localStorage.setItem('clow_pinned',JSON.stringify(pinnedConvs));
    loadConvs();
  }catch(e){}
}

function startRename(id){
  closeCtxMenu();
  const el=document.querySelector('.sb-conv-item[data-id="'+id+'"]');
  if(!el)return;
  const titleEl=el.querySelector('.conv-title');
  const oldTitle=el.getAttribute('data-title')||titleEl.textContent;
  const inp=document.createElement('input');
  inp.className='conv-rename-input';inp.value=oldTitle;inp.maxLength=50;
  titleEl.replaceWith(inp);inp.focus();inp.select();
  const save=async()=>{
    const v=inp.value.trim()||oldTitle;
    try{await fetch('/api/v1/conversations/'+id+'/title',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({title:v})});
      if(id===cid)document.getElementById('hdrT').textContent=v;
      loadConvs();
    }catch(e){loadConvs()}
  };
  inp.addEventListener('keydown',e=>{if(e.key==='Enter'){e.preventDefault();save()}if(e.key==='Escape'){loadConvs()}});
  inp.addEventListener('blur',save);
  inp.addEventListener('click',e=>e.stopPropagation());
}

async function copyConv(id){
  try{const r=await fetch('/api/v1/conversations/'+id+'/messages');const d=await r.json();
    let txt='';d.messages.forEach(m=>{txt+=(m.role==='user'?'Voce':'Clow')+': '+m.content+'\\n\\n'});
    await navigator.clipboard.writeText(txt);
  }catch(e){try{
    const ta=document.createElement('textarea');ta.value='Conversa copiada';document.body.appendChild(ta);ta.select();document.execCommand('copy');ta.remove();
  }catch(e2){}}
}

function togglePin(id){
  if(pinnedConvs.includes(id)){pinnedConvs=pinnedConvs.filter(x=>x!==id)}
  else{if(pinnedConvs.length>=3)return;pinnedConvs.push(id)}
  localStorage.setItem('clow_pinned',JSON.stringify(pinnedConvs));
  loadConvs();
  // Pin bounce animation
  setTimeout(()=>{const el=document.querySelector('.sb-conv-item[data-id="'+id+'"] .conv-pin-static');if(el)el.classList.add('pin-bounce')},50);
}

function filterConvs(q){
  const el=document.getElementById('convList');
  if(!q.trim()){loadConvs();return}
  const ql=q.toLowerCase();
  const filtered=allConvsCache.filter(c=>(c.title||'').toLowerCase().includes(ql));
  let h='';
  if(!filtered.length){h='<div style="padding:12px 8px;color:var(--tm);font-size:12px;text-align:center">Nenhum resultado</div>'}
  else{filtered.forEach(c=>{h+=convBtn(c,pinnedConvs.includes(c.id))})}
  el.innerHTML=h;
  bindConvEvents();
}

function closeConvSearch(){
  document.getElementById('convSearchInp').value='';
  loadConvs();
}

async function showAllConvs(){showAllPast=true;loadConvs()}

async function ensureConv(){if(cid)return cid;try{const r=await fetch('/api/v1/conversations',{method:'POST'});const d=await r.json();cid=d.id;hSid='';convMsgCount=0;loadConvs();return cid}catch(e){return ''}}

async function newConv(){try{const r=await fetch('/api/v1/conversations',{method:'POST'});const d=await r.json();cid=d.id;hSid='';convMsgCount=0;T.innerHTML='';showWelc();document.getElementById('hdrT').textContent='Nova conversa';loadConvs();if(window.innerWidth<769)toggleSB()}catch(e){}}
async function loadConv(id){cid=id;hSid='';T.innerHTML='';try{const r=await fetch(`/api/v1/conversations/${id}/messages`);const d=await r.json();d.messages.forEach(m=>{if(m.role==='user')addUser(m.content,false);else{curMsg=null;curBody=null;appendTxt(m.content);finishTxt();curMsg=null;curBody=null}});const cs=await(await fetch('/api/v1/conversations')).json();const c=cs.conversations.find(x=>x.id===id);if(c)document.getElementById('hdrT').textContent=c.title;loadConvs();if(window.innerWidth<769)toggleSB()}catch(e){}}
function connectWS(){const pr=location.protocol==='https:'?'wss:':'ws:';try{ws=new WebSocket(`${pr}//${location.host}/ws`)}catch(e){http=true;setOn('http');return}const to=setTimeout(()=>{if(!ws||ws.readyState!==1){try{ws.close()}catch(e){}http=true;setOn('http')}},10000);ws.onopen=()=>{clearTimeout(to);http=false;setOn('online');rA=0};ws.onmessage=e=>hMsg(JSON.parse(e.data));ws.onclose=()=>{clearTimeout(to);if(rA>=3){http=true;setOn('http');return}setOn('offline');setTimeout(()=>{rA++;connectWS()},Math.min(1000*rA,5000))};ws.onerror=()=>setOn('offline')}
function setOn(s){const b=document.getElementById('onBdg'),l=document.getElementById('onLbl');b.style.color=s==='offline'?'var(--r)':'var(--g)';l.textContent=s}
function hMsg(m){switch(m.type){case'thinking_start':showThink();break;case'thinking_end':hideThink();break;case'text_delta':appendTxt(m.content);break;case'text_done':finishTxt();break;case'tool_call':showTool(m.name,m.args);break;case'tool_result':showToolR(m.name,m.status,m.output);break;case'turn_complete':finishTurn();break;case'error':showErr(m.content);break}}
async function sendMessage(){const t=I.value.trim();if(!t||proc)return;if(!cid)await ensureConv();if(http){addUser(t,false);sendHTTP(t);return}if(!ws||ws.readyState!==1)return;addUser(t,false);ws.send(JSON.stringify({type:'message',content:t,model:selMod,conversation_id:cid}));I.value='';I.style.height='auto';proc=true;SB.disabled=true;document.getElementById('stopBtn').classList.add('vis')}
async function sendHTTP(t){I.value='';I.style.height='auto';proc=true;SB.disabled=true;showThink();try{const r=await fetch('/api/v1/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({content:t,session_id:hSid,conversation_id:cid,model:selMod})});hideThink();if(!r.ok){const e=await r.json().catch(()=>({error:'Erro'}));showErr(e.error||e.response||'Erro');finishTurn();return}const d=await r.json();hSid=d.session_id||hSid;if(d.tools&&d.tools.length)d.tools.forEach(x=>{showTool(x.name,x.args);showToolR(x.name,x.status,x.output||'')});if(d.response){appendTxt(d.response);finishTxt()}if(d.file)showFile(d.file);if(d.mission)startPoll(d.mission);finishTurn()}catch(e){hideThink();showErr('Erro: '+e.message);finishTurn()}}
function sendCmd(c){I.value=c;sendMessage()}
function qa(t){const w=document.getElementById('welc');if(w)w.remove();I.value=t;I.focus();if(window.innerWidth<769)toggleSB()}
function now(){return new Date().toLocaleTimeString('pt-BR',{hour:'2-digit',minute:'2-digit'})}
let convMsgCount=0;
function addUser(t,save=true){const w=document.getElementById('welc');if(w)w.remove();const wm=document.getElementById('wmark');if(wm)wm.classList.remove('empty');const d=document.createElement('div');d.className='ml user';d.innerHTML=`<div class="mh"><span class="mt">${now()}</span><span class="mn">você</span><div class="mav">${me?me.email[0].toUpperCase():'?'}</div></div><div class="mb-wrap"><div class="mb">${esc(t)}</div></div>`;T.appendChild(d);scrl();convMsgCount++;if(!cid&&save){fetch('/api/v1/conversations',{method:'POST'}).then(r=>r.json()).then(d=>{cid=d.id;autoTitle(t);loadConvs()})}else if(convMsgCount===1&&cid){autoTitle(t)}else if(convMsgCount===2&&cid){const hdr=document.getElementById('hdrT');if(!hdr.textContent||hdr.textContent==='Nova conversa')autoTitle(t)}}
function autoTitle(t){
  const generic=['oi','ola','bom dia','boa tarde','boa noite','hey','hello','hi','e ai','fala','oi!','ola!'];
  const w=t.trim().toLowerCase().replace(/[!?.]/g,'');
  if(generic.includes(w))return;
  const words=t.trim().split(/\s+/).slice(0,6).join(' ');
  const title=words.length>28?words.substring(0,28)+'...':words;
  document.getElementById('hdrT').textContent=title;
  fetch(`/api/v1/conversations/${cid}/title`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({title})}).then(()=>loadConvs());
}
function showThink(){hideThink();const d=document.createElement('div');d.className='think';d.id='thinkEl';const st=Date.now();d.innerHTML='<div class="think-in"><div class="think-logo"></div><span class="think-t">Working\u2026</span></div>';T.appendChild(d);d._thinkTimer=setInterval(()=>{const el=d.querySelector('.think-t');if(el){const s=((Date.now()-st)/1000);if(s<60)el.textContent='Working\u2026 ('+s.toFixed(0)+'s)';else el.textContent='Working\u2026 ('+Math.floor(s/60)+'m '+Math.floor(s%60)+'s)'}},1000);scrl()}
function hideThink(){const e=document.getElementById('thinkEl');if(e){if(e._thinkTimer)clearInterval(e._thinkTimer);e.remove()}}
let hadTools=false;
function ensureMsg(){if(!curMsg){hideThink();curMsg=document.createElement('div');curMsg.className='ml assistant';curBody=document.createElement('div');curBody.className='mb';const wrap=document.createElement('div');wrap.className='mb-wrap';wrap.appendChild(curBody);curMsg.appendChild(wrap);T.appendChild(curMsg);raw='';hadTools=false}}
function appendTxt(t){ensureMsg();
  // If tools were shown, create a NEW body element AFTER the tools
  if(hadTools&&curBody&&!curBody._afterTools){
    const newBody=document.createElement('div');newBody.className='mb';newBody._afterTools=true;
    curMsg.querySelector('.mb-wrap').appendChild(newBody);
    curBody=newBody;raw='';
  }
  raw+=t;const c=curBody.querySelector('.scur');if(c)c.remove();curBody.insertAdjacentText('beforeend',t);const s=document.createElement('span');s.className='scur';curBody.appendChild(s);scrl()}
function finishTxt(){if(curBody){const c=curBody.querySelector('.scur');if(c)c.remove();if(raw&&typeof marked!=='undefined'){marked.setOptions({breaks:true,gfm:true});curBody.innerHTML=marked.parse(raw);curBody.querySelectorAll('a').forEach(a=>{a.target='_blank';a.rel='noopener'})}raw=''}}
function showTool(n,a){ensureMsg();hadTools=true;const b=document.createElement('div');b.className='tblk act';const as=typeof a==='string'?a:JSON.stringify(a);const short=as.length>80?as.substring(0,80)+'\u2026':as;b.innerHTML=`<div class="thd" onclick="this.parentElement.classList.toggle('open')"><div class="tdot"></div><span class="tlb"><span class="tn">${esc(n)}</span>(<span class="ta">${esc(short)}</span>)</span><span class="tdr">0.0s</span></div><div class="tout"></div>`;curMsg.querySelector('.mb-wrap').appendChild(b);curTool=b;tStart=Date.now();if(tTimer)clearInterval(tTimer);tTimer=setInterval(()=>{if(!curTool){clearInterval(tTimer);return}const d=curTool.querySelector('.tdr');if(d){const s=(Date.now()-tStart)/1000;if(s<60)d.textContent=s.toFixed(1)+'s';else d.textContent=Math.floor(s/60)+'m '+Math.floor(s%60)+'s'}},100);scrl()}
function showToolR(n,s,o){if(tTimer){clearInterval(tTimer);tTimer=null}if(curTool){curTool.classList.remove('act');curTool.classList.add(s==='success'?'done':'err');if(o){const b=curTool.querySelector('.tout');if(b){const lines=o.split('\n').slice(0,4);const rest=o.split('\n').length-4;let h='';lines.forEach(l=>{h+='<div class="tline">'+esc(l)+'</div>'});if(rest>0)h+='<div class="tmore" onclick="this.parentElement.style.maxHeight=\'none\';this.remove()">\u2026 +'+rest+' lines (click to expand)</div>';b.innerHTML=h;b.style.display='block'}}const d=curTool.querySelector('.tdr');if(d){const s2=(Date.now()-tStart)/1000;if(s2<60)d.textContent=s2.toFixed(1)+'s';else d.textContent=Math.floor(s2/60)+'m '+Math.floor(s2%60)+'s'}curTool=null}scrl()}
function showFile(f){ensureMsg();const ic={'landing_page':'\ud83c\udf10','app':'\u26a1','xlsx':'\ud83d\udcca','docx':'\ud83d\udcc4','pptx':'\ud83c\udfac'};const i=ic[f.type]||'\ud83d\udcc1';const wb=f.type==='landing_page'||f.type==='app';const c=document.createElement('div');c.className='fcard';c.innerHTML=`<div class="ficon">${i}</div><div class="finfo"><div class="fname">${esc(f.name)}</div><div class="fmeta">${esc(f.size)}</div></div><div style="display:flex;gap:6px">${wb?`<a href="${esc(f.url)}" target="_blank" class="fbtn pr">Abrir</a>`:''}<a href="${esc(f.url)}" download class="fbtn ${wb?'sc':'pr'}">Download</a></div>`;curMsg.querySelector('.mb-wrap').appendChild(c);scrl()}
function showErr(t){ensureMsg();const e=document.createElement('div');e.className='eline';e.textContent='\u2717 '+t;curMsg.querySelector('.mb-wrap').appendChild(e);scrl()}
function finishTurn(){finishTxt();
  // Indicador visual de conclusao
  if(curMsg){const done=document.createElement('div');done.className='turn-done';done.textContent='\u2500\u2500 concluido';curMsg.querySelector('.mb-wrap').appendChild(done)}
  proc=false;SB.disabled=false;curMsg=null;curBody=null;hadTools=false;I.focus();loadConvs();document.getElementById('stopBtn').classList.remove('vis');toggleInputBtns();scrl()}
function stopGeneration(){if(ws&&ws.readyState===1){ws.send(JSON.stringify({type:'stop'}))}finishTurn()}
function scrl(){T.scrollTop=T.scrollHeight}
function esc(t){const d=document.createElement('div');d.textContent=t;return d.innerHTML}
let mPolls={};
function startPoll(m){const mid=m.id;let lt=0;const card=document.createElement('div');card.className='mission-card';card.id='mc-'+mid;card.innerHTML=`<div class="mctitle">\ud83d\ude80 ${esc(m.title)}</div><div class="mission-bar"><div class="mission-fill" id="mf-${mid}" style="width:0%"></div></div><div id="ms-${mid}"></div>`;ensureMsg();curMsg.querySelector('.mb-wrap').appendChild(card);scrl();const poll=async()=>{try{const r=await fetch(`/api/v1/missions/${mid}/progress?after=${lt}`);const d=await r.json();d.events.forEach(e=>{lt=Math.max(lt,e.time);const sl=document.getElementById('ms-'+mid);const fl=document.getElementById('mf-'+mid);if(e.type==='step_start'){const p=((e.data.step+1)/e.data.total*100).toFixed(0);if(fl)fl.style.width=p+'%';sl.innerHTML+=`<div class="mission-step running" id="mss-${mid}-${e.data.step}"><span class="ms-icon">\u23f3</span>${esc(e.data.title)}</div>`;scrl()}else if(e.type==='step_done'){const el=document.getElementById(`mss-${mid}-${e.data.step}`);if(el){el.className='mission-step done';el.querySelector('.ms-icon').textContent='\u2705'}if(e.data.file)showFile(e.data.file);scrl()}else if(e.type==='step_retry'){const el=document.getElementById(`mss-${mid}-${e.data.step}`);if(el)el.querySelector('.ms-icon').textContent='\ud83d\udd04'}else if(e.type==='step_failed'){const el=document.getElementById(`mss-${mid}-${e.data.step}`);if(el){el.className='mission-step failed';el.querySelector('.ms-icon').textContent='\u274c'}}else if(e.type==='completed'){const c=document.getElementById('mc-'+mid);if(c)c.className='mission-done';const tt=c?.querySelector('.mctitle');if(tt)tt.innerHTML='\ud83c\udf89 '+esc(e.data.title)+' — Concluida!';if(fl)fl.style.width='100%';if(e.data.summary){appendTxt(e.data.summary);finishTxt()}clearInterval(mPolls[mid]);scrl()}});if(d.status==='completed'||d.status==='failed')clearInterval(mPolls[mid])}catch(e){}};mPolls[mid]=setInterval(poll,2000);setTimeout(poll,500)}
async function showAdmUsers(){const r=await fetch('/api/v1/admin/users');const d=await r.json();let h='<h3>Usuários</h3><table class="adm-tbl"><tr><th>Email</th><th>Plano</th><th>Status</th><th></th></tr>';d.users.forEach(u=>{const st=u.active?'<span style="color:var(--g)">ativo</span>':'<span style="color:var(--r)">inativo</span>';h+=`<tr><td>${u.email}</td><td><select onchange="setPlan('${u.id}',this.value)">${['free','basic','pro','unlimited'].map(p=>`<option ${u.plan===p?'selected':''}>${p}</option>`).join('')}</select></td><td>${st}</td><td><button onclick="togUsr('${u.id}',${u.active?0:1})">${u.active?'Off':'On'}</button></td></tr>`});h+='</table>';document.getElementById('modalC').innerHTML=h;document.getElementById('modalBg').classList.add('show')}
async function showAdmStats(){const r=await fetch('/api/v1/admin/stats');const d=await r.json();let h=`<h3>Consumo</h3><div class="adm-cards"><div class="adm-card"><div class="al">Usuários</div><div class="av">${d.total_users}</div></div><div class="adm-card"><div class="al">Custo Hoje</div><div class="av">$${d.cost_today.toFixed(3)}</div></div><div class="adm-card"><div class="al">Custo Semana</div><div class="av">$${d.cost_week.toFixed(3)}</div></div><div class="adm-card"><div class="al">Tokens Hoje</div><div class="av">${(d.tokens_today/1000).toFixed(0)}k</div></div></div>`;document.getElementById('modalC').innerHTML=h;document.getElementById('modalBg').classList.add('show')}
function showCreateUsr(){document.getElementById('modalC').innerHTML='<h3>Cadastrar Usuario</h3><label>Email</label><input id="nuE" type="email" placeholder="email@exemplo.com"><label>Senha</label><input id="nuP" type="password" placeholder="minimo 6 chars"><label>Nome</label><input id="nuN" placeholder="opcional"><label>Plano</label><select id="nuPl"><option>free</option><option>basic</option><option>pro</option><option>unlimited</option></select><button class="mbtn" onclick="createUsr()">Cadastrar</button><div id="nuM" style="margin-top:8px;font-size:12px"></div>';document.getElementById('modalBg').classList.add('show')}
async function createUsr(){const e=document.getElementById('nuE').value,p=document.getElementById('nuP').value,n=document.getElementById('nuN').value,pl=document.getElementById('nuPl').value;const r=await fetch('/api/v1/admin/create-user',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({email:e,password:p,name:n,plan:pl})});const d=await r.json();document.getElementById('nuM').innerHTML=d.ok?'<span style="color:var(--g)">Criado!</span>':`<span style="color:var(--r)">${d.error}</span>`}
async function setPlan(id,p){await fetch(`/api/v1/admin/users/${id}`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({plan:p})});showAdmUsers()}
async function togUsr(id,a){await fetch(`/api/v1/admin/users/${id}`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({active:a})});showAdmUsers()}
function clsModal(){document.getElementById('modalBg').classList.remove('show')}
I.addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();sendMessage()}});
I.addEventListener('input',()=>{I.style.height='auto';I.style.height=Math.min(I.scrollHeight,120)+'px';toggleInputBtns()});
let lte=0;document.addEventListener('touchend',e=>{const n=Date.now();if(n-lte<=300)e.preventDefault();lte=n},false);

// ── AUDIO SUPPORT ──────────────────────────────────────
const MIC=document.getElementById('micBtn'),FP=document.getElementById('filePreview');
let mediaRec=null,audioChunks=[],recStart=0,recTimer=null,audioBlob=null,audioUrl=null;
let speechRec=null,audioTranscript='';
const hasSpeechRec=!!(window.SpeechRecognition||window.webkitSpeechRecognition);

function toggleInputBtns(){
  const has=I.value.trim().length>0||audioBlob;
  SB.classList.toggle('vis',has);
  MIC.classList.toggle('hid',has);
  MIC.classList.toggle('vis',!has);
}

// ── Audio Recording ──
function toggleRec(){
  if(mediaRec&&mediaRec.state==='recording'){stopRec();return}
  startRec();
}

async function startRec(){
  if(!hasSpeechRec){showToast('Seu navegador não suporta transcrição de áudio. Digite sua mensagem.','error');return}
  try{
    const stream=await navigator.mediaDevices.getUserMedia({audio:true});
    const mimeTypes=['audio/webm;codecs=opus','audio/webm','audio/mp4','audio/ogg'];
    const mime=mimeTypes.find(m=>MediaRecorder.isTypeSupported(m))||'';
    mediaRec=new MediaRecorder(stream,mime?{mimeType:mime}:{});
    audioChunks=[];audioTranscript='';
    mediaRec.ondataavailable=e=>{if(e.data.size>0)audioChunks.push(e.data)};
    mediaRec.onstop=()=>{stream.getTracks().forEach(t=>t.stop());audioBlob=new Blob(audioChunks,{type:mediaRec.mimeType||'audio/webm'});audioUrl=URL.createObjectURL(audioBlob);showAudioPreview()};
    mediaRec.start();
    // Web Speech API — transcricao em tempo real
    const SR=window.SpeechRecognition||window.webkitSpeechRecognition;
    speechRec=new SR();
    speechRec.lang='pt-BR';
    speechRec.continuous=true;
    speechRec.interimResults=false;
    speechRec.onresult=(ev)=>{audioTranscript=Array.from(ev.results).map(r=>r[0].transcript).join(' ')};
    speechRec.onerror=()=>{};
    speechRec.start();
    MIC.classList.add('recording');
    recStart=Date.now();
    recTimer=setInterval(()=>{
      const s=Math.floor((Date.now()-recStart)/1000);
      const mm=Math.floor(s/60),ss=s%60;
      MIC.title=mm+':'+(ss<10?'0':'')+ss;
    },500);
    setTimeout(()=>{if(mediaRec&&mediaRec.state==='recording')stopRec()},300000);
  }catch(e){showToast('Não foi possível acessar o microfone','error')}
}

function stopRec(){
  if(mediaRec&&mediaRec.state==='recording'){
    mediaRec.stop();
    if(speechRec){try{speechRec.stop()}catch(e){}}
    MIC.classList.remove('recording');
    clearInterval(recTimer);
    MIC.title='Gravar audio';
  }
}

function showAudioPreview(){
  const dur=Math.floor((Date.now()-recStart)/1000);
  const mm=Math.floor(dur/60),ss=dur%60;
  const ts=mm+':'+(ss<10?'0':'')+ss;
  let html='<div class="audio-preview"><button class="ap-play" id="apPlay" onclick="playPreviewAudio()">&#x25B6;</button><div class="ap-bar"><div class="ap-fill" id="apFill"></div></div><span class="ap-dur">'+ts+'</span><button class="ap-del" onclick="clearAudio()">&#x1F5D1;</button></div>';
  if(audioTranscript)html+='<div class="ap-transcript">&#x1F3A4; '+esc(audioTranscript)+'</div>';
  FP.innerHTML=html;
  toggleInputBtns();
}

let previewAudio=null;
function playPreviewAudio(){
  if(!audioUrl)return;
  if(previewAudio){previewAudio.pause();previewAudio=null;document.getElementById('apPlay').innerHTML='&#x25B6;';return}
  previewAudio=new Audio(audioUrl);
  document.getElementById('apPlay').innerHTML='&#x23F8;';
  previewAudio.ontimeupdate=()=>{const p=(previewAudio.currentTime/previewAudio.duration*100)||0;document.getElementById('apFill').style.width=p+'%'};
  previewAudio.onended=()=>{document.getElementById('apPlay').innerHTML='&#x25B6;';document.getElementById('apFill').style.width='0%';previewAudio=null};
  previewAudio.play();
}

function clearAudio(){audioBlob=null;audioUrl=null;audioTranscript='';speechRec=null;FP.innerHTML='';if(previewAudio){previewAudio.pause();previewAudio=null}toggleInputBtns()}

// Override sendMessage to handle audio
const _origSendMessage=sendMessage;
sendMessage=async function(){
  if(proc)return;
  // Audio pending?
  if(audioBlob){
    const text=I.value.trim();
    const localAudioUrl=audioUrl;
    const trans=audioTranscript;
    const msgText=text||(trans?trans:'[Audio enviado]');
    addUserWithAttachment(msgText,'audio','&#x1F3A4;','Audio',null,localAudioUrl,trans);
    I.value='';I.style.height='auto';proc=true;SB.disabled=true;
    clearAudio();
    // Envia como file_data com transcricao para o agente processar
    const audioFileData={type:'audio',file_name:'audio.webm',transcription:trans||''};
    showThink();
    if(http){
      try{
        const body={content:msgText,session_id:hSid,conversation_id:cid,model:selMod,file_data:audioFileData};
        const r=await fetch('/api/v1/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
        hideThink();
        if(!r.ok){const e=await r.json().catch(()=>({error:'Erro'}));showErr(e.error||'Erro');finishTurn();return}
        const d=await r.json();
        hSid=d.session_id||hSid;
        if(!cid&&d.conversation_id)cid=d.conversation_id;
        if(d.response){appendTxt(d.response);finishTxt()}
        finishTurn();
      }catch(e){hideThink();showErr('Erro: '+e.message);finishTurn()}
    }else if(ws&&ws.readyState===1){
      hideThink();
      ws.send(JSON.stringify({type:'message',content:msgText,model:selMod,conversation_id:cid,file_data:audioFileData}));
      proc=true;SB.disabled=true;
    }else{hideThink();finishTurn()}
    return;
  }
  // Normal text
  _origSendMessage();
};

function addUserWithAttachment(text,type,icon,name,imgUrl,audUrl,transcript){
  const w=document.getElementById('welc');if(w)w.remove();
  const wm=document.getElementById('wmark');if(wm)wm.classList.remove('empty');
  const d=document.createElement('div');d.className='ml user';
  let attachHtml='';
  if(type==='image'&&imgUrl){
    attachHtml='<img class="chat-img" src="'+imgUrl+'" onclick="openLightbox(this.src)" alt="imagem">';
  }else if(type==='audio'){
    attachHtml='<div class="chat-audio"><button class="ca-play" onclick="playChatAudio(this,\''+esc(audUrl||'')+'\')">&#x25B6;</button><div class="ca-bar"><div class="ca-fill"></div></div><span class="ca-dur">0:00</span></div>';
    if(transcript)attachHtml+='<div class="chat-transcription">&#x1F3A4; '+esc(transcript)+'</div>';
  }else{
    const sz='';
    attachHtml='<div class="chat-file-card"><span class="cfc-icon">'+icon+'</span><div class="cfc-info"><div class="cfc-name">'+esc(name)+'</div><div class="cfc-meta">'+sz+'</div></div></div>';
  }
  d.innerHTML='<div class="mh"><span class="mt">'+now()+'</span><span class="mn">você</span><div class="mav">'+(me?me.email[0].toUpperCase():'?')+'</div></div><div class="mb-wrap">'+attachHtml+(text?'<div class="mb">'+esc(text)+'</div>':'')+'</div>';
  T.appendChild(d);scrl();
  convMsgCount++;
  if(!cid){fetch('/api/v1/conversations',{method:'POST'}).then(r=>r.json()).then(d=>{cid=d.id;autoTitle(text||name);loadConvs()})}
}


// ── Lightbox ──
function openLightbox(src){const lb=document.getElementById('lightbox');document.getElementById('lbImg').src=src;lb.classList.add('show')}
function closeLightbox(){document.getElementById('lightbox').classList.remove('show')}
document.addEventListener('keydown',e=>{if(e.key==='Escape')closeLightbox()});

// ── Chat audio player ──
function playChatAudio(btn,url){
  const wrap=btn.closest('.chat-audio');
  const fill=wrap.querySelector('.ca-fill');
  const durEl=wrap.querySelector('.ca-dur');
  if(btn._audio){btn._audio.pause();btn._audio=null;btn.innerHTML='&#x25B6;';fill.style.width='0%';return}
  const a=new Audio(url);btn._audio=a;btn.innerHTML='&#x23F8;';
  a.ontimeupdate=()=>{const p=(a.currentTime/a.duration*100)||0;fill.style.width=p+'%';const s=Math.floor(a.currentTime);durEl.textContent=Math.floor(s/60)+':'+(s%60<10?'0':'')+(s%60)};
  a.onended=()=>{btn.innerHTML='&#x25B6;';fill.style.width='0%';btn._audio=null;durEl.textContent='0:00'};
  a.play();
}

// ── Toast ──
function showToast(msg,type){
  const t=document.createElement('div');t.className='toast'+(type==='error'?' error':'');t.textContent=msg;
  document.body.appendChild(t);setTimeout(()=>t.remove(),3500);
}

toggleInputBtns();
init();
// ── Particles ──
(function(){
  const isMobile=window.innerWidth<769;
  const count=isMobile?8:20;
  const colors=['#9B59FC','#4A9EFF'];
  for(let i=0;i<count;i++){
    const p=document.createElement('div');
    p.className='particle';
    const s=Math.random()*2+2;
    p.style.width=s+'px';p.style.height=s+'px';
    p.style.top=Math.random()*100+'%';
    p.style.left=Math.random()*100+'%';
    p.style.backgroundColor=colors[i%2];
    p.style.animation='floatParticle '+(15+Math.random()*25)+'s ease-in-out '+(Math.random()*10)+'s infinite';
    document.body.appendChild(p);
  }
})();

/* ── Mobile Viewport & Keyboard Handling ────────────────── */
function _setupMobileViewport(){
  var mc=document.querySelector(".main");
  var term=document.getElementById('term');
  var inp=document.getElementById('inp');
  if(!mc)return;
  var fullH=window.innerHeight;

  function applyHeight(h){
    mc.style.height=h+"px";
    // Scroll to bottom when keyboard opens
    if(term)setTimeout(function(){term.scrollTop=term.scrollHeight},50);
  }

  // Use visualViewport API (best for mobile keyboards)
  if(window.visualViewport){
    var vv=window.visualViewport;
    var lastH=vv.height;
    vv.addEventListener("resize",function(){
      var h=vv.height;
      applyHeight(h);
      // Detect keyboard open/close
      var kbOpen=h<fullH*0.75;
      document.body.classList.toggle("kb-open",kbOpen);
      // Prevent page scroll when keyboard opens
      if(kbOpen){
        window.scrollTo(0,0);
        document.documentElement.scrollTop=0;
      }
      lastH=h;
    });
    vv.addEventListener("scroll",function(e){
      e.preventDefault();
      window.scrollTo(0,0);
    });
  }

  // Fallback for browsers without visualViewport
  window.addEventListener("resize",function(){
    if(!window.visualViewport){
      var h=window.innerHeight;
      applyHeight(h);
      document.body.classList.toggle("kb-open",h<fullH*0.75);
    }
  });

  // Focus/blur on input — smooth scroll
  if(inp){
    inp.addEventListener("focus",function(){
      setTimeout(function(){
        if(term)term.scrollTop=term.scrollHeight;
        window.scrollTo(0,0);
      },300);
    });
    inp.addEventListener("blur",function(){
      setTimeout(function(){
        document.body.classList.remove("kb-open");
        if(window.visualViewport)applyHeight(window.visualViewport.height);
        else applyHeight(window.innerHeight);
      },100);
    });
  }

  // Prevent iOS bounce/overscroll
  document.body.addEventListener("touchmove",function(e){
    if(e.target===document.body||e.target===document.documentElement){
      e.preventDefault();
    }
  },{passive:false});

  // Initial size
  if(window.visualViewport)applyHeight(window.visualViewport.height);
  else applyHeight(window.innerHeight);
}

/* ── MOBILE UX ENHANCEMENTS ─────────────────────────── */

// Haptic feedback on send
(function(){
  var sb=document.getElementById('sBtn');
  if(sb&&navigator.vibrate){sb.addEventListener('click',function(){navigator.vibrate(10)})}
})();

// Smart auto-scroll (skip if user scrolled up)
(function(){
  var term=document.getElementById('term');
  if(!term)return;
  var userScrolled=false;
  term.addEventListener('scroll',function(){userScrolled=(term.scrollHeight-term.scrollTop-term.clientHeight)>100});
  var origScrl=window.scrl;
  if(typeof origScrl==='function'){window.scrl=function(){if(!userScrolled)origScrl()}}
})();

// Pull-to-refresh
(function(){
  var term=document.getElementById('term');
  if(!term||!('ontouchstart' in window))return;
  var startY=0,pulling=false,indicator=null;
  function mkInd(){if(indicator)return;indicator=document.createElement('div');indicator.className='pull-indicator';indicator.textContent='\u21BB';term.style.position='relative';term.insertBefore(indicator,term.firstChild)}
  term.addEventListener('touchstart',function(e){if(term.scrollTop<=0){startY=e.touches[0].clientY;pulling=true;mkInd()}},{passive:true});
  term.addEventListener('touchmove',function(e){if(!pulling||!indicator)return;var dy=e.touches[0].clientY-startY;if(dy>0&&dy<120){indicator.classList.add('show');indicator.style.top=Math.min(dy-40,20)+'px'}},{passive:true});
  term.addEventListener('touchend',function(){if(!pulling||!indicator)return;if((parseInt(indicator.style.top)||0)>10){indicator.classList.add('refreshing');if(typeof loadConvs==='function')loadConvs();setTimeout(function(){indicator.classList.remove('show','refreshing');indicator.style.top='-50px'},800)}else{indicator.classList.remove('show');indicator.style.top='-50px'}pulling=false},{passive:true});
})();

// Double-tap to copy message
(function(){
  var term=document.getElementById('term');
  if(!term)return;
  var lastTap=0;
  term.addEventListener('touchend',function(e){var now=Date.now();if(now-lastTap<300){var wrap=e.target.closest('.mb-wrap');if(wrap){var body=wrap.querySelector('.mb-body');if(body&&navigator.clipboard){navigator.clipboard.writeText(body.textContent).then(function(){showToast();if(navigator.vibrate)navigator.vibrate(5)})}}}lastTap=now});
  function showToast(){var t=document.querySelector('.copy-toast');if(!t){t=document.createElement('div');t.className='copy-toast';t.textContent='Copiado!';document.body.appendChild(t)}t.classList.add('show');setTimeout(function(){t.classList.remove('show')},1500)}
})();

// Swipe to open/close sidebar
(function(){
  if(!('ontouchstart' in window))return;
  var startX=0,startY=0,swiping=false;
  document.addEventListener('touchstart',function(e){var x=e.touches[0].clientX,y=e.touches[0].clientY;var sb=document.getElementById('sb');if(x<30||(sb&&sb.classList.contains('open'))){swiping=true;startX=x;startY=y}},{passive:true});
  document.addEventListener('touchmove',function(e){if(!swiping)return;if(Math.abs(e.touches[0].clientY-startY)>Math.abs(e.touches[0].clientX-startX))swiping=false},{passive:true});
  document.addEventListener('touchend',function(e){if(!swiping)return;var dx=e.changedTouches[0].clientX-startX;var sb=document.getElementById('sb');if(sb){if(dx>60&&!sb.classList.contains('open'))toggleSB();if(dx<-60&&sb.classList.contains('open'))toggleSB()}swiping=false},{passive:true});
})();
