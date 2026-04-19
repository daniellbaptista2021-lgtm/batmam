/* Clean start - unregister old service workers */
if("serviceWorker" in navigator){navigator.serviceWorker.getRegistrations().then(function(regs){regs.forEach(function(r){r.unregister()})});caches.keys().then(function(names){names.forEach(function(name){caches.delete(name)})})}

/* CLOW branding: injeta custom.css + esconde emails no rodape */
(function(){
  /* 1. Inject custom.css */
  if(!document.getElementById('clow-custom-css')){
    var l=document.createElement('link');
    l.id='clow-custom-css';
    l.rel='stylesheet';
    l.href='/pv-custom.css?v='+Date.now();
    document.head.appendChild(l);
  }

  /* 2. Periodicamente substitui texto de email por string limpa no rodape */
  function maskEmails(){
    try{
      var selectors=['.sidebar-profile__info','.current-user','.user-thumbnail + *','aside.sidebar .row','.sidebar footer','.sidebar-footer'];
      selectors.forEach(function(sel){
        document.querySelectorAll(sel).forEach(function(el){
          el.childNodes.forEach(function(n){
            if(n.nodeType===3 && n.textContent && /@[a-z0-9.-]+\.[a-z]{2,}/i.test(n.textContent)){
              n.textContent='';
            }
          });
          el.querySelectorAll('span,div,small').forEach(function(s){
            if(s.children.length===0 && /@[a-z0-9.-]+\.[a-z]{2,}/i.test(s.textContent||'')){
              s.style.display='none';
            }
          });
        });
      });
    }catch(e){}
  }
  maskEmails();
  setInterval(maskEmails, 2000);

  /* 3. Trocar titulo da aba se conter Chatwoot */
  try{
    var observer=new MutationObserver(function(){
      if(document.title.indexOf('Chatwoot')>=0){
        document.title=document.title.replace(/Chatwoot/g,'CRM CLOW');
      }
    });
    observer.observe(document.querySelector('title')||document.head,{childList:true,subtree:true,characterData:true});
    if(document.title.indexOf('Chatwoot')>=0){
      document.title=document.title.replace(/Chatwoot/g,'CRM CLOW');
    }
  }catch(e){}
})();
