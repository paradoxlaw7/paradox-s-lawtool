'use strict';
// A short, optional brand entrance. It never waits for or submits a model task.
(()=>{
 const key='agreement-entrance-v1-seen',app=document.querySelector('#app');
 const reduced=window.matchMedia('(prefers-reduced-motion: reduce)');
 if(reduced.matches||navigator.connection?.saveData||document.hidden)return;
 try{if(sessionStorage.getItem(key))return;sessionStorage.setItem(key,'1');}catch{}
 const previousFocus=document.activeElement;
 const overlay=document.createElement('section');
 overlay.className='entrance';overlay.setAttribute('role','dialog');
 overlay.setAttribute('aria-modal','true');overlay.setAttribute('aria-label','约定品牌入场动画');
 const video=document.createElement('video');
 video.className='entrance-video';video.muted=true;video.defaultMuted=true;
 video.playsInline=true;video.preload='auto';video.setAttribute('aria-hidden','true');
 video.poster='/assets/entrance-start.png';
 const skip=document.createElement('button');skip.type='button';skip.className='entrance-skip';
 skip.textContent='跳过动画';skip.setAttribute('aria-label','跳过动画，进入工作台');
 overlay.append(video,skip);document.body.append(overlay);
 const oldInert=app?.hasAttribute('inert'),oldHidden=app?.getAttribute('aria-hidden');
 if(app){app.setAttribute('inert','');app.setAttribute('aria-hidden','true');}
 let done=false,started=false,loadingTimer,limitTimer;
 const onKey=e=>{if(e.key==='Escape'){e.preventDefault();finish();}else if(e.key==='Tab'){e.preventDefault();skip.focus();}};
 const onVisibility=()=>{if(document.hidden)finish();};
 const onReduce=()=>{if(reduced.matches)finish();};
 function finish(){
  if(done)return;done=true;clearTimeout(loadingTimer);clearTimeout(limitTimer);
  document.removeEventListener('keydown',onKey,true);document.removeEventListener('visibilitychange',onVisibility);
  reduced.removeEventListener('change',onReduce);video.pause();video.removeAttribute('src');video.load();
  // Restore the application immediately, independently of the visual fade.
  if(app){if(!oldInert)app.removeAttribute('inert');if(oldHidden===null)app.removeAttribute('aria-hidden');else app.setAttribute('aria-hidden',oldHidden);}
  overlay.classList.add('leaving');overlay.setAttribute('aria-hidden','true');overlay.inert=true;
  setTimeout(()=>overlay.remove(),220);
  const target=previousFocus&&previousFocus!==document.body&&previousFocus.isConnected?previousFocus:document.querySelector('#password, #project-select');
  target?.focus({preventScroll:true});
 }
 skip.addEventListener('click',finish);video.addEventListener('ended',finish);video.addEventListener('error',finish);
 video.addEventListener('playing',()=>{started=true;clearTimeout(loadingTimer);},{once:true});
 document.addEventListener('keydown',onKey,true);document.addEventListener('visibilitychange',onVisibility);
 reduced.addEventListener('change',onReduce);skip.focus({preventScroll:true});
 loadingTimer=setTimeout(()=>{if(!started)finish();},1800);
 limitTimer=setTimeout(finish,6800);
 video.src='/assets/entrance-v1.mp4';
 video.play().catch(finish);
})();
