/* Browser-local detector. Dependencies/model download remotely; pixels stay local. */
'use strict';
let perceptionMode=false,perceptionGeneration=0,detector=null,detectorPromise=null,perceptionSession=null,perceptionProfile=null,perceptionSeq=0,inferenceBusy=false,sceneBusy=false,sceneView=null,geometry=null;
const pc=AuraPerceptionCore,overlay=document.getElementById('objectoverlay'),objectStatus=document.getElementById('objectstatus'),objectList=document.getElementById('objectlist');
const detectorCanvas=document.createElement('canvas');
function objectMessage(text){objectStatus.textContent=text}
function script(url,name){
 if(window[name])return Promise.resolve();
 return new Promise((resolve,reject)=>{const element=document.createElement('script'),timer=setTimeout(()=>{element.remove();reject(Error('Detector library download timed out. Check internet and retry.'))},30000);element.src=url;element.onload=()=>{clearTimeout(timer);resolve()};element.onerror=()=>{clearTimeout(timer);element.remove();reject(Error('Detector library unavailable. Check CDN access and retry.'))};document.head.append(element)})
}
function loadDetector(){
 if(detector)return Promise.resolve(detector);
 if(!detectorPromise)detectorPromise=(async()=>{await script('https://cdn.jsdelivr.net/npm/@tensorflow/tfjs@4.22.0/dist/tf.min.js','tf');await tf.ready();await script('https://cdn.jsdelivr.net/npm/@tensorflow-models/coco-ssd@2.2.3/dist/coco-ssd.min.js','cocoSsd');let expired=false,timer;try{const loading=cocoSsd.load({base:'lite_mobilenet_v2'}).then(m=>{if(expired){m.dispose();throw Error('Late model discarded')}return m});const m=await Promise.race([loading,new Promise((_,reject)=>{timer=setTimeout(()=>{expired=true;reject(Error('Model download timed out. Check model-host access and retry.'))},60000)})]);detector=m;return m}finally{clearTimeout(timer)}})().catch(e=>{detectorPromise=null;throw e});
 return detectorPromise;
}
async function cameraProfile(){
 const settings=camera?.getVideoTracks()[0]?.getSettings()||{};
 const raw=JSON.stringify({device:settings.deviceId||'default',width:video.videoWidth,height:video.videoHeight,zoom:settings.zoom||1,facing:settings.facingMode||'unknown'});
 const hash=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(raw));
 return {key:Array.from(new Uint8Array(hash)).map(v=>v.toString(16).padStart(2,'0')).join(''),geometry:raw};
}
async function stopPerception(){
 window.AuraEval?.onSessionEnd?.();
 perceptionGeneration++;perceptionMode=false;const session=perceptionSession;perceptionSession=null;sceneView=null;
 overlay.getContext('2d').clearRect(0,0,overlay.width,overlay.height);objectList.replaceChildren();objectMessage('Object detection stopped. Distance calibration cleared.');
 if(session)try{await api('/api/vision/end',{session})}catch{}
}
async function startPerception(){
 if(perceptionMode)return;
 if(!tracking||video.readyState<2){objectMessage('Start the camera first, then enable object detection.');return}
 const generation=++perceptionGeneration;const button=document.getElementById('objecton');button.disabled=true;
 objectMessage('Loading browser detector/model. First use needs internet; no frame upload.');
 try{await loadDetector();if(generation!==perceptionGeneration||!tracking)return;
  const profile=await cameraProfile();if(generation!==perceptionGeneration||!tracking)return;
  const session=crypto.randomUUID();await api('/api/vision/start',{session,profile:profile.key});
  if(generation!==perceptionGeneration||!tracking){await api('/api/vision/end',{session});return}
  perceptionSession=session;perceptionProfile=profile.key;geometry=profile.geometry;perceptionSeq=0;perceptionMode=true;
  await api('/api/body/observe',{visible:false});objectMessage('Detector ready. Select a visible track below or say “AURA look at the bottle”.');
 }catch(e){if(generation!==perceptionGeneration)return;await stopPerception();objectMessage('Object detector unavailable: '+e.message)}finally{button.disabled=false}
}
async function inferObjects(){
 if(!perceptionMode||!tracking||inferenceBusy||document.hidden||video.readyState<2)return;
 inferenceBusy=true;const generation=perceptionGeneration,session=perceptionSession;
 try{
  if(camera?.getVideoTracks()[0]?.readyState!=='live'){await stopCamera();objectMessage('Camera disconnected. Object tracking and head target released.');return}
  const profile=await cameraProfile();if(profile.geometry!==geometry){await stopPerception();objectMessage('Camera geometry changed. Enable object detection again and recalibrate.');return}
  detectorCanvas.width=320;detectorCanvas.height=Math.max(1,Math.round(320*video.videoHeight/video.videoWidth));
  detectorCanvas.getContext('2d').drawImage(video,0,0,detectorCanvas.width,detectorCanvas.height);
  const start=performance.now(),predictions=await detector.detect(detectorCanvas,20,.6),ms=performance.now()-start;
  if(generation!==perceptionGeneration||!perceptionMode||!tracking)return;
  try{window.AuraEval?.onInference?.(detectorCanvas,pc.normalise(predictions,detectorCanvas.width,detectorCanvas.height),ms)}catch(e){console.warn('Evaluation callback failed',e)}
  if(ms>800){objectMessage('Inference '+Math.round(ms)+' ms: result discarded as stale. Warming up or laptop too slow; no stale target following.');return}
  const detections=pc.normalise(predictions,detectorCanvas.width,detectorCanvas.height);
  const received=await api('/api/vision/frame',{session,profile:perceptionProfile,seq:++perceptionSeq,age_ms:ms,detections});
  if(generation!==perceptionGeneration)return;
  sceneView=received;
  objectMessage('Local detector · '+Math.round(ms)+' ms · '+detections.length+' reports · target '+sceneView.target_state+'. Confidence scores are not measured accuracy.');
  renderObjects();
 }catch(e){if(generation===perceptionGeneration&&perceptionMode)window.AuraEval?.onError?.();objectMessage('Detector/connection error: '+e.message+' Target expires automatically.')}finally{inferenceBusy=false}
}
function renderObjects(){
 objectList.replaceChildren();if(!sceneView)return;
 const fresh=sceneView.objects.filter(o=>o.visible);
 for(const o of fresh){const row=document.createElement('div');row.style.marginTop='5px';const button=document.createElement('button');button.textContent=(o.id===sceneView.selected_id?'Selected ':'Follow ')+'#'+o.id+' '+o.label+' · '+o.side+' · '+Math.round(o.score*100)+'%';button.onclick=async()=>{try{sceneView=await api('/api/vision/target',{selector:o.id});renderObjects()}catch(e){objectMessage(e.message)}};row.append(button);
  if(o.distance_estimate_m!==null){const note=document.createElement('span');note.textContent=' ≈ '+o.distance_estimate_m+' m (same-width assumption)';row.append(note)}objectList.append(row)
 }
 if(!fresh.length){const p=document.createElement('span');p.textContent='No fresh detections. Lost targets are not automatically replaced.';objectList.append(p)}
 if(sceneView.target_state==='lost'){const p=document.createElement('div');p.textContent='Selected track lost. Show the same target again or explicitly select a new ID.';objectList.append(p)}
}
async function pollScene(){
 if(sceneBusy||document.hidden)return;sceneBusy=true;
 const generation=perceptionGeneration;
 try{const received=await api('/api/vision/state');if(generation!==perceptionGeneration)return;sceneView=received;if(perceptionMode)renderObjects()}catch{}finally{sceneBusy=false}
}
function drawObjects(){
 requestAnimationFrame(drawObjects);const ratio=Math.min(devicePixelRatio||1,2),w=Math.round(overlay.clientWidth*ratio),h=Math.round(overlay.clientHeight*ratio);if(overlay.width!==w||overlay.height!==h){overlay.width=w;overlay.height=h}
 pc.drawOverlay(overlay.getContext('2d'),w,h,video.videoWidth,video.videoHeight,perceptionMode?sceneView:null);
}
document.getElementById('objecton').onclick=startPerception;document.getElementById('objectoff').onclick=stopPerception;
document.getElementById('objectrelease').onclick=async()=>{try{sceneView=await api('/api/vision/release',{});renderObjects()}catch(e){objectMessage(e.message)}};
document.getElementById('calibrateobject').onclick=async()=>{try{const width=Number(document.getElementById('knownwidth').value)/100,distance=Number(document.getElementById('knowndistance').value)/100;await api('/api/vision/calibrate',{known_width_m:width,known_distance_m:distance});objectMessage('Approximate calibration set for this track/session. Keep the same rigid object and facing width. Rotation, clipping or camera changes invalidate the estimate.');await pollScene()}catch(e){objectMessage(e.message)}};
document.addEventListener('visibilitychange',()=>{if(document.hidden)stopPerception()});
window.addEventListener('pagehide',()=>{perceptionGeneration++;perceptionMode=false;detector?.dispose();detector=null;detectorPromise=null;if(perceptionSession)fetch('/api/vision/end',{method:'POST',headers:{'X-Aura-Token':bodyToken,'Content-Type':'application/json'},body:JSON.stringify({session:perceptionSession}),keepalive:true}).catch(()=>{})});
setInterval(inferObjects,200);setInterval(pollScene,300);drawObjects();
