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
