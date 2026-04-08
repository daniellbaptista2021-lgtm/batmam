
// -- Drag & Drop --
(function(){
  const ov=document.getElementById('dragOverlay');
  let dragC=0;
  document.addEventListener('dragenter',function(e){e.preventDefault();dragC++;ov.classList.add('active')});
  document.addEventListener('dragleave',function(e){e.preventDefault();dragC--;if(dragC<=0){dragC=0;ov.classList.remove('active')}});
  document.addEventListener('dragover',function(e){e.preventDefault()});
  document.addEventListener('drop',function(e){
    e.preventDefault();dragC=0;ov.classList.remove('active');
    const f=e.dataTransfer.files[0];
    if(f){const dt=new DataTransfer();dt.items.add(f);document.getElementById('fileInput').files=dt.files;handleFileSelect(document.getElementById('fileInput'))}
  });
})();
