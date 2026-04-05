/**
 * Clow Onboarding — signup, API key validation, redirect
 * External JS (CSP-safe)
 */
(function(){
'use strict';

var token='';
var userEmail='';

function $(id){return document.getElementById(id)}

function showStep(n){
  document.querySelectorAll('.step').forEach(function(s){s.classList.remove('active')});
  $('step'+n).classList.add('active');
  for(var i=1;i<=3;i++){
    $(('d'+i)).className=i<n?'dot done':i===n?'dot active':'dot';
  }
}

function showMsg(id,text,type){
  var el=$(id);
  el.className='msg '+type;
  el.textContent=text;
}

// Step 1: Signup
function signup(){
  var name=$('name').value.trim();
  var email=$('email').value.trim();
  var password=$('password').value;

  if(!$('terms').checked) return showMsg('msg1','Aceite os Termos de Uso e Politica de Privacidade','error');
  if(!name) return showMsg('msg1','Informe seu nome completo','error');
  if(name.split(/\s+/).length<2) return showMsg('msg1','Informe nome e sobrenome','error');
  if(!email) return showMsg('msg1','Informe seu email','error');
  if(!email.includes('@')||!email.split('@')[1].includes('.')) return showMsg('msg1','Email invalido','error');
  if(!password) return showMsg('msg1','Crie uma senha','error');
  if(password.length<6) return showMsg('msg1','Senha deve ter pelo menos 6 caracteres','error');

  fetch('/api/v1/auth/signup',{
    method:'POST',
    headers:{'Content-Type':'application/json'},
    credentials:'same-origin',
    body:JSON.stringify({name:name,email:email,password:password,accepted_terms:true})
  })
  .then(function(r){return r.json()})
  .then(function(d){
    if(d.error){
      if(d.action==='login'){
        $('msg1').className='msg error';
        $('msg1').innerHTML=d.error+' <a href="/login" style="color:var(--p);text-decoration:underline">Ir para o login</a>';
        return;
      }
      return showMsg('msg1',d.error,'error');
    }
    token=d.token;
    userEmail=email;

    // Se veio com ?plan= na URL, vai direto pro checkout Stripe
    var urlPlan=new URLSearchParams(window.location.search).get('plan');
    if(urlPlan&&['lite','starter','pro','business'].indexOf(urlPlan)!==-1){
      fetch('/api/v1/billing/checkout',{
        method:'POST',
        headers:{'Content-Type':'application/json'},
        credentials:'same-origin',
        body:JSON.stringify({plan_id:urlPlan})
      })
      .then(function(cr){return cr.json()})
      .then(function(cd){
        if(cd.url){window.location.href=cd.url;return;}
        showStep(3);
      })
      .catch(function(){showStep(3)});
    } else {
      showStep(2);
    }
  })
  .catch(function(){showMsg('msg1','Erro de rede. Tente novamente.','error')});
}

// Step 2: API Key
function saveKey(){
  var key=$('apikey').value.trim();
  if(!key) return showMsg('msg2','Cole sua API key','error');
  if(!key.startsWith('sk-ant-')) return showMsg('msg2','Key deve comecar com sk-ant-','error');

  $('btn-key').disabled=true;
  $('btn-key').innerHTML='<span class="spinner"></span> Validando...';
  showMsg('msg2','Validando key com a Anthropic...','info');

  fetch('/api/v1/me/api-key',{
    method:'POST',
    headers:{'Content-Type':'application/json'},
    credentials:'same-origin',
    body:JSON.stringify({api_key:key})
  })
  .then(function(r){return r.json()})
  .then(function(d){
    if(d.error){
      showMsg('msg2',d.error,'error');
      $('btn-key').disabled=false;
      $('btn-key').textContent='Validar e Salvar';
      return;
    }
    var un=$('userName');
    if(un) un.textContent=userEmail.split('@')[0];
    showStep(3);
  })
  .catch(function(){
    showMsg('msg2','Erro de rede','error');
    $('btn-key').disabled=false;
    $('btn-key').textContent='Validar e Salvar';
  });
}

// Step 3: Go to Clow
function goToClow(){
  fetch('/api/v1/me',{credentials:'same-origin'})
  .then(function(r){return r.json()})
  .then(function(d){
    if(d.error||!d.email){window.location='/login';return;}
    window.location='/';
  })
  .catch(function(){window.location='/login'});
}

// Wire up buttons via event delegation (CSP-safe, no onclick needed)
document.addEventListener('click',function(e){
  var btn=e.target.closest('button');
  if(!btn) return;
  var text=btn.textContent.trim();

  if(text==='Criar Conta') {e.preventDefault(); signup();}
  else if(btn.id==='btn-key') {e.preventDefault(); saveKey();}
  else if(text==='Abrir Clow Web') {e.preventDefault(); goToClow();}
});

// Also handle Enter key in form fields
document.addEventListener('keydown',function(e){
  if(e.key!=='Enter') return;
  var step1=$('step1');
  var step2=$('step2');
  if(step1&&step1.classList.contains('active')) signup();
  else if(step2&&step2.classList.contains('active')) saveKey();
});

})();
