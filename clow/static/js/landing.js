/**
 * Clow Landing Page — animations, checkout, sticky CTA
 * External JS (CSP-safe)
 */
(function(){
'use strict';

// 3D tilt on cards
document.querySelectorAll('.feat,.uc-card').forEach(function(c){
  c.addEventListener('mousemove',function(e){
    var r=c.getBoundingClientRect(),x=(e.clientX-r.left)/r.width,y=(e.clientY-r.top)/r.height;
    c.style.setProperty('--rx',(y-.5)*-10+'deg');
    c.style.setProperty('--ry',(x-.5)*10+'deg');
    c.style.setProperty('--mx',x*100+'%');
    c.style.setProperty('--my',y*100+'%');
  });
  c.addEventListener('mouseleave',function(){
    c.style.setProperty('--rx','0deg');
    c.style.setProperty('--ry','0deg');
  });
});

// Scroll-in animation
var obs=new IntersectionObserver(function(es){
  es.forEach(function(e){
    if(e.isIntersecting){e.target.style.opacity='1';e.target.style.transform='translateY(0)';}
  });
},{threshold:.1});
document.querySelectorAll('.feat,.step,.uc-card,.flow-card,.price-wrap,.niche-item,.faq-item,.wf-item').forEach(function(el){
  el.style.opacity='0';el.style.transform='translateY(30px)';el.style.transition='all .6s cubic-bezier(.25,.8,.25,1)';obs.observe(el);
});

// Checkout Stripe — event delegation (CSP-safe, no inline onclick)
document.addEventListener('click',function(e){
  var btn=e.target.closest('[data-plan]');
  if(!btn)return;
  e.preventDefault();
  var planId=btn.getAttribute('data-plan');
  if(!planId)return;

  // Abre nova aba IMEDIATAMENTE no click (evita popup blocker)
  var newTab=window.open('about:blank','_blank');
  if(newTab){
    newTab.document.write('<html><body style="background:#0a0a1a;color:#e8e8f0;display:flex;align-items:center;justify-content:center;height:100vh;font-family:sans-serif;flex-direction:column;gap:16px"><div style="width:40px;height:40px;border:3px solid #9B59FC;border-top-color:transparent;border-radius:50%;animation:spin 1s linear infinite"></div><h2>Redirecionando para o checkout...</h2><style>@keyframes spin{to{transform:rotate(360deg)}}</style></body></html>');
  }

  fetch('/api/v1/billing/checkout',{
    method:'POST',
    headers:{'Content-Type':'application/json'},
    credentials:'same-origin',
    body:JSON.stringify({plan_id:planId})
  })
  .then(function(r){
    if(r.status===401){
      if(newTab)newTab.close();
      window.location='/onboarding?plan='+planId;
      return null;
    }
    return r.json();
  })
  .then(function(d){
    if(!d)return;
    if(d.url){
      if(newTab)newTab.location.href=d.url;
      else window.location.href=d.url;
    }else{
      if(newTab)newTab.close();
      if(d.error)alert(d.error);
      else window.location='/onboarding?plan='+planId;
    }
  })
  .catch(function(){
    if(newTab)newTab.close();
    window.location='/onboarding?plan='+planId;
  });
});

// Sticky CTA mobile
var sticky=document.getElementById('stickyCta');
var priceSection=document.querySelector('.price-wrap');
if(sticky&&window.innerWidth<769){
  window.addEventListener('scroll',function(){
    var show=window.scrollY>500;
    var priceVisible=priceSection&&priceSection.getBoundingClientRect().top<window.innerHeight;
    sticky.classList.toggle('show',show&&!priceVisible);
  },{passive:true});
}

// Analytics pageview
fetch('/api/v1/analytics/pageview',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({page:location.pathname,ref:document.referrer}),credentials:'same-origin'}).catch(function(){});

})();
