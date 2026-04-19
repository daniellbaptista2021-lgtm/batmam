/* Clean start - unregister old service workers */
if("serviceWorker" in navigator){navigator.serviceWorker.getRegistrations().then(function(regs){regs.forEach(function(r){r.unregister()})});caches.keys().then(function(names){names.forEach(function(name){caches.delete(name)})})}

/* CLOW branding: injeta CSS inline + esconde emails + esconde Captain pra nao-admin */
(function(){
  var ADMIN_EMAIL = 'daniellbaptista2021@gmail.com';
  /* Descobre email do usuario logado via config ou JWT no localStorage */
  function currentUserEmail(){
    try{
      var k = Object.keys(localStorage).filter(function(k){return k.indexOf('access_token')>=0 || k==='cw_d_user' || k==='userData';})[0];
      if(!k) return '';
      var d = localStorage.getItem(k);
      try{ d = JSON.parse(d); }catch(e){}
      return (d && d.email) || '';
    }catch(e){ return ''; }
  }
  var isAdmin = false;
  try{
    /* heuristica: se o email do user logado e ADMIN_EMAIL, e admin. Fallback pros dados vindos via API /api/v1/profile */
    fetch('/api/v1/profile', {credentials:'same-origin'}).then(function(r){return r.ok?r.json():null;}).then(function(p){
      if(p && p.email === ADMIN_EMAIL){ isAdmin = true; document.documentElement.classList.add('cw-is-admin'); }
      else { document.documentElement.classList.add('cw-is-client'); }
    }).catch(function(){});
  }catch(e){}

  /* CSS inline \u2014 garante que carrega */
  var css = [
    '/* Esconde email no rodape da sidebar */',
    '.current-user--meta,.current-user--email,.user-thumbnail-box~*>small,.text-xxs,.sidebar small:not([class*=badge]){ display:none !important; }',
    '/* Esconde qualquer span com conteudo de email dentro da sidebar */',
    '.sidebar [class*=profile] small, .sidebar [class*=profile] .text-xs{ display:none !important; }',
    '/* Esconde botao Captain/Capitao pra NAO admins */',
    'html.cw-is-client a[href*="/captain"], html.cw-is-client [data-route*=captain], html.cw-is-client .sidebar-nav a[title*="Capit"], html.cw-is-client .sidebar-nav a[title*="Captain"]{ display:none !important; }',
    '/* Badge CLOW no rodape */',
    '.sidebar-profile__info::after{ content:"Powered by CLOW"; display:block; font-size:11px; color:#8B5CF6; font-weight:600; letter-spacing:.3px; margin-top:2px; }'
  ].join('\n');
  var st = document.getElementById('clow-brand-css');
  if(!st){
    st = document.createElement('style');
    st.id = 'clow-brand-css';
    st.textContent = css;
    (document.head||document.documentElement).appendChild(st);
  }

  /* MutationObserver + interval: remove qualquer elemento com email visivel */
  function maskEmails(){
    try{
      var emailRe=/[\w._%+-]+@[\w.-]+\.[a-z]{2,}/i;
      /* sidebar / profile blocks */
      document.querySelectorAll('aside .current-user, .sidebar-profile__info, .user-thumbnail-box, [class*="profile"] [class*="meta"]').forEach(function(root){
        root.querySelectorAll('p,span,small,div').forEach(function(el){
          if(el.children.length===0 && emailRe.test(el.textContent||'') && el.offsetHeight>0){
            el.style.display='none';
            el.setAttribute('data-clow-masked','1');
          }
        });
      });
      /* Esconder botao Captain pra nao-admin (fallback JS) */
      if(document.documentElement.classList.contains('cw-is-client')){
        document.querySelectorAll('a[href*="captain"],button[title*="Capit"],button[title*="Captain"]').forEach(function(el){
          el.style.display='none';
        });
        /* sidebar items com texto Capitao */
        document.querySelectorAll('.sidebar-nav a, .sidebar-nav button, nav a, nav button').forEach(function(el){
          if(/capit\u00e3o|captain/i.test(el.textContent||'')) el.style.display='none';
        });
      }
    }catch(e){}
  }
  maskEmails();
  setInterval(maskEmails, 800);
  try{
    var obs=new MutationObserver(function(){ maskEmails(); });
    obs.observe(document.body || document.documentElement, {childList:true,subtree:true});
  }catch(e){}

  /* Troca titulo Chatwoot -> CRM CLOW */
  try{
    var tobs=new MutationObserver(function(){
      if(document.title.indexOf('Chatwoot')>=0) document.title=document.title.replace(/Chatwoot/g,'CRM CLOW');
    });
    var titleEl=document.querySelector('title');
    if(titleEl) tobs.observe(titleEl,{childList:true,characterData:true,subtree:true});
    if(document.title.indexOf('Chatwoot')>=0) document.title=document.title.replace(/Chatwoot/g,'CRM CLOW');
  }catch(e){}
})();
