/* Local Body Lab controller. No arbitrary model output is interpreted as motion. */
'use strict';
const $=id=>document.getElementById(id),bodyToken=document.body.dataset.token;
let state=null,display=null,speech=0,speechSeen=0,stoppedLocally=false,camera=null,tracking=false,observationBusy=false,commandEpoch=0,cameraEpoch=0;
const canvas=$('bodycanvas'),chat=$('chat'),video=$('video'),pixels=document.createElement('canvas');pixels.width=128;pixels.height=96;
function message(text){$('message').textContent=text}
async function api(path,data,timeout=2500){
 const abort=new AbortController(),timer=setTimeout(()=>abort.abort(),timeout);
 try{const r=await fetch(path,{method:data===undefined?'GET':'POST',headers:{'X-Aura-Token':bodyToken,'Content-Type':'application/json'},body:data===undefined?undefined:JSON.stringify(data),cache:'no-store',signal:abort.signal});const value=await r.json();if(!r.ok)throw Error(value.detail||'Body request failed');return value}
 finally{clearTimeout(timer)}
}
async function command(action,params={}){
 if(action==='stop'||action==='reset')commandEpoch++;
 if(action==='stop'){stoppedLocally=true;if(display)display.estop=true;message('Stopping virtual body…')}
 try{if(!document.hidden)await api('/api/body/heartbeat',{});const r=await api('/api/body/command',{action,params});message('Virtual body: '+r.status);if(action==='reset')stoppedLocally=false;await poll()}
 catch(e){message(e.name==='AbortError'?'Body server timeout. Virtual motion stops when its heartbeat expires.':e.message)}
}
for(const button of document.querySelectorAll('[data-action]'))button.onclick=()=>command(button.dataset.action);
$('estop').onclick=()=>{command('stop');chat.contentWindow?.postMessage({type:'aura-body-stop-speech'},location.origin)};
$('walk').onclick=()=>command('walk',{x:Number($('goalx').value),z:Number($('goalz').value)});
$('lookred').onclick=()=>command('point',{x:1.8,z:-.8});
$('blockpath').onclick=async()=>{if(!state)return;const p=state.position;let x=p.x+Math.sin(p.yaw)*.8,z=p.z+Math.cos(p.yaw)*.8;x=Math.max(-2.6,Math.min(2.6,x));z=Math.max(-2.6,Math.min(2.6,z));try{await api('/api/body/scene',{obstacles:[{x,z,radius:.35}]});message('Virtual obstacle added; current path replans or stops.')}catch(e){message(e.message)}};
$('clearscene').onclick=async()=>{try{await api('/api/body/scene',{obstacles:[]});message('Virtual obstacles cleared. Reset if Stop is latched.')}catch(e){message(e.message)}};
$('history').onclick=async()=>{try{const r=await api('/api/body/history');$('savedhistory').textContent=r.events.map(e=>e.recorded+' · '+e.kind+' · '+(e.data.action||e.data.reason||'scene update')+' [simulation]').join('\n')||'No saved body events yet.'}catch(e){message(e.message)}};
let polling=false;
async function poll(){
 if(polling||document.hidden)return;polling=true;
 const generation=commandEpoch;
 try{const received=await api('/api/body/state');if(generation!==commandEpoch)return;state=received;if(!display)display=structuredClone(state);if(state.estop)stoppedLocally=true;
 $('motionstatus').textContent=state.estop?'STOPPED · '+state.reason:'VIRTUAL · '+(state.active?.kind||state.reason);
 $('energy').textContent='Virtual energy: '+state.organs.systems.stomach.virtual_energy.toFixed(1)+'%';
 $('tasklist').textContent='Active: '+(state.active?.kind||'none')+' · Queued: '+state.queue.map(t=>t.kind).join(' → ')+'\nLast result: '+(state.history.at(-1)?.status||'none');
 const container=$('organs');container.replaceChildren();for(const [name,o]of Object.entries(state.organs.systems)){const item=document.createElement('div');item.className='organ';item.title=o.function;const title=document.createElement('b');title.textContent=name.replaceAll('_',' / ');const status=document.createElement('span');status.textContent=o.status+(name==='heart'?' · '+o.beats+' ticks':'');item.append(title,status);container.append(item)}
 $('signals').textContent=state.organs.signals.slice(-12).reverse().map(e=>e.id+' '+e.from+' → '+e.to+' : '+e.kind+' ['+e.outcome+']').join('\n');
 }catch(e){$('motionstatus').textContent='Connection lost · controller watchdog will stop motion';stoppedLocally=true;message(e.message)}finally{polling=false}
}
let leaseBusy=false;
async function lease(){if(document.hidden||leaseBusy)return;leaseBusy=true;try{await api('/api/body/heartbeat',{},800)}catch(e){stoppedLocally=true}finally{leaseBusy=false}}
window.addEventListener('message',e=>{if(e.origin!==location.origin||e.source!==chat.contentWindow)return;const d=e.data;if(d?.type==='aura-body-voice'&&Number.isFinite(d.level)){speech=Math.max(0,Math.min(1,d.level));speechSeen=performance.now()}if(d?.type==='aura-body-stop')command('stop')});
function frame(){
 requestAnimationFrame(frame);const ratio=Math.min(devicePixelRatio||1,2),w=Math.round(canvas.clientWidth*ratio),h=Math.round(canvas.clientHeight*ratio);if(canvas.width!==w||canvas.height!==h){canvas.width=w;canvas.height=h}
 if(state&&display){if(!stoppedLocally){for(const k of Object.keys(state.joints))display.joints[k]+=(state.joints[k]-display.joints[k])*.28;for(const k of ['x','z','bounce'])display.position[k]+=(state.position[k]-display.position[k])*.3;let d=(state.position.yaw-display.position.yaw+Math.PI)%(2*Math.PI);if(d<0)d+=2*Math.PI;d-=Math.PI;display.position.yaw+=d*.3}display.estop=state.estop||stoppedLocally;display.active=state.active;display.world=state.world;}
 if(performance.now()-speechSeen>300)speech*=.8;
 AuraBodyRender.draw(canvas,display,{speech});
}
async function observe(){
 if(!tracking||observationBusy||video.readyState<2||document.hidden||(typeof perceptionMode!=='undefined'&&perceptionMode))return;observationBusy=true;
 try{const c=pixels.getContext('2d',{willReadFrequently:true});c.drawImage(video,0,0,pixels.width,pixels.height);const found=AuraVision.detectColour(c.getImageData(0,0,pixels.width,pixels.height).data,pixels.width,pixels.height,$('colour').value);const {box,...payload}=found;await api('/api/body/observe',payload);$('camstatus').textContent=found.visible?'Tracking '+found.colour+' region · x '+found.x.toFixed(2)+' y '+found.y.toFixed(2)+'. Colour only; no depth.':'Selected colour not visible; head tracking released.'}catch(e){$('camstatus').textContent='Tracking unavailable: '+e.message}finally{observationBusy=false}
}
async function stopCamera(){if(typeof stopPerception==='function')stopPerception();cameraEpoch++;tracking=false;camera?.getTracks().forEach(t=>t.stop());camera=null;video.srcObject=null;$('camstatus').textContent='Camera stopped. No camera frames were uploaded.';try{await api('/api/body/observe',{visible:false})}catch{}}
$('cameraon').onclick=async()=>{if(tracking)return;$('cameraon').disabled=true;const generation=++cameraEpoch;try{const stream=await navigator.mediaDevices.getUserMedia({video:{width:{ideal:640},height:{ideal:480}},audio:false});if(generation!==cameraEpoch){stream.getTracks().forEach(t=>t.stop());return}camera=stream;video.srcObject=camera;await video.play();if(generation!==cameraEpoch){stream.getTracks().forEach(t=>t.stop());return}tracking=true;message('Camera is local. Show one clearly coloured object.')}catch(e){await stopCamera();message('Camera unavailable: '+e.message)}finally{$('cameraon').disabled=false}};
$('cameraoff').onclick=stopCamera;
function leaving(){commandEpoch++;cameraEpoch++;stoppedLocally=true;tracking=false;camera?.getTracks().forEach(t=>t.stop());fetch('/api/body/command',{method:'POST',headers:{'X-Aura-Token':bodyToken,'Content-Type':'application/json'},body:JSON.stringify({action:'stop',params:{}}),keepalive:true}).catch(()=>{});chat.contentWindow?.postMessage({type:'aura-body-stop-speech'},location.origin)}
document.addEventListener('visibilitychange',()=>{if(document.hidden){leaving();stopCamera()}else{lease();poll();message('Body may be stopped after tab switch. Use Reset before moving.')}});
window.addEventListener('pagehide',leaving);setInterval(lease,400);setInterval(poll,120);setInterval(observe,200);lease();poll();frame();
