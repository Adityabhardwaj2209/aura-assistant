/* Explicit local frame annotation. Reports contain no camera images. */
(function(){
'use strict';
const get=id=>document.getElementById(id),core=AuraEvalCore,canvas=get('evalcanvas'),ctx=canvas.getContext('2d'),labels=window.AuraEvalLabels;
const run={started:new Date().toISOString(),samples:[],timings:[],errors:0},scope=get('evalscope'),label=get('evallabel');
let pending=null,held=null,drag=null,lastRender=0;
function status(text){get('evalstatus').textContent=text}
for(const select of [scope,label])for(const name of labels){const option=document.createElement('option');option.value=name;option.textContent=name;select.append(option)}
const all=document.createElement('option');all.value='__all__';all.textContent='All supported categories';scope.append(all);scope.value='bottle';label.value='bottle';label.disabled=true;
scope.onchange=()=>{if(scope.value!=='__all__')label.value=scope.value;label.disabled=scope.value!=='__all__'};
function controls(locked){scope.disabled=locked;get('evalscenario').disabled=locked}
function boxDraw(box,text,colour,dashed=false){const [x,y,w,h]=box;ctx.strokeStyle=colour;ctx.lineWidth=2;ctx.setLineDash(dashed?[5,3]:[]);ctx.strokeRect(x*canvas.width,y*canvas.height,w*canvas.width,h*canvas.height);ctx.fillStyle=colour;ctx.font='12px system-ui';ctx.fillText(text,x*canvas.width+2,Math.max(13,y*canvas.height-3));ctx.setLineDash([])}
function draw(){ctx.clearRect(0,0,canvas.width,canvas.height);if(!held)return;ctx.drawImage(held.image,0,0,canvas.width,canvas.height);for(const box of held.truth)boxDraw(box.box,'GT '+box.label,'#7affdf');if(drag)boxDraw(rect(drag.start,drag.end),'drawing…','#ffffff');if(held.saved)for(const p of held.predictions)if(held.scope===null||held.scope.includes(p.label))boxDraw(p.box,'AI '+p.label,'#ffd17a',true)}
function rect(a,b){return [Math.min(a.x,b.x),Math.min(a.y,b.y),Math.abs(a.x-b.x),Math.abs(a.y-b.y)]}
function point(event){const r=canvas.getBoundingClientRect();return {x:Math.max(0,Math.min(1,(event.clientX-r.left)/r.width)),y:Math.max(0,Math.min(1,(event.clientY-r.top)/r.height))}}
canvas.onpointerdown=event=>{if(!held||held.saved)return;event.preventDefault();const p=point(event);drag={start:p,end:p,label:label.value};canvas.setPointerCapture?.(event.pointerId)};
canvas.onpointermove=event=>{if(drag){drag.end=point(event);draw()}};
canvas.onpointerup=event=>{if(!drag)return;drag.end=point(event);const box=rect(drag.start,drag.end);if(box[2]>=.01&&box[3]>=.01){if(held.truth.length>=100)status('Maximum 100 annotation boxes per sample.');else held.truth.push({label:drag.label,box})}drag=null;get('evalconfirmed').checked=false;draw()};
canvas.onpointercancel=()=>{drag=null;draw()};
get('evalcapture').onclick=()=>{
 if(typeof perceptionMode==='undefined'||!perceptionMode){status('Enable camera and Object detection first.');return}
 if(held&&!held.saved){status('Save or discard the current frozen frame first.');return}
 pending={scope:scope.value==='__all__'?null:[scope.value],scenario:get('evalscenario').value};controls(true);status('Waiting for the next completed inference frame…');
 const request=pending;setTimeout(()=>{if(pending===request){pending=null;controls(false);status('Capture timed out. Check detector/camera and retry.')}},15000);
};
get('evalundo').onclick=()=>{if(held&&!held.saved){held.truth.pop();get('evalconfirmed').checked=false;draw()}};
function discard(){pending=null;held=null;drag=null;ctx.clearRect(0,0,canvas.width,canvas.height);controls(false);get('evalconfirmed').checked=false}
get('evaldiscard').onclick=()=>{discard();status('Frozen frame discarded. Saved samples remain.')};
function percent(value){return value===null?'N/A':(value*100).toFixed(1)+'%'}
function render(){
 const m=core.aggregate(run.samples,run.timings,run.errors),t=m.timing_window;
 get('evalmetrics').textContent='Annotated samples: '+m.annotated_samples+'\nTP '+m.tp+' · FP '+m.fp+' · FN '+m.fn+'\nPrecision '+percent(m.precision)+' · Recall '+percent(m.recall)+' · F1 '+percent(m.f1)+'\nMean matched IoU '+(m.mean_matched_iou===null?'N/A':m.mean_matched_iou.toFixed(3))+'\nInference samples (last ≤1000): '+t.completed_inferences+' · median '+(t.median_ms===null?'N/A':t.median_ms.toFixed(1)+' ms')+' · p95 '+(t.p95_ms===null?'N/A':t.p95_ms.toFixed(1)+' ms')+'\nOver 800 ms: '+t.stale_over_800_ms+' · inference/connection errors: '+m.inference_or_connection_errors+'\nSelected annotated frames only; no measured improvement claim.';
 return m;
}
get('evalsave').onclick=()=>{
 if(!held||held.saved){status('Freeze a new inference frame first.');return}
 if(drag){status('Finish the current annotation box first.');return}
 if(!get('evalconfirmed').checked){status('Confirm all visible objects in scope are annotated, including missed ones.');return}
 if(run.samples.length>=100){status('100 samples reached. Export, then clear to start another run.');return}
 try{const result=core.scoreFrame(held.predictions,held.truth,{scope:held.scope});const sample={id:crypto.randomUUID(),captured_at:held.captured,scenario:held.scenario,scope:held.scope,predictions:structuredClone(held.predictions),truth:structuredClone(held.truth),inference_ms:held.ms,stale_for_live_tracking:held.ms>800};run.samples.push(sample);held.saved=true;controls(false);draw();render();status('Sample saved: TP '+result.tp+', FP '+result.fp+', FN '+result.fn+'. Dashed AI boxes now shown; solid boxes are your ground truth.')}catch(e){status(e.message)}
};
get('evalexport').onclick=()=>{
 const report={schema:'aura-camera-evaluation-v1',created_at:new Date().toISOString(),started_at:run.started,
  model:{name:'COCO-SSD lite_mobilenet_v2',score_threshold:.6,input_width:320,backend:window.tf?.getBackend?.()||'not_loaded'},
  summary:render(),samples:structuredClone(run.samples),raw_camera_frames_included:false};
 const blob=new Blob([JSON.stringify(report,null,2)],{type:'application/json'}),url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download='aura_camera_evaluation_'+Date.now()+'.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);status('Metadata report exported. Camera images were not included.');
};
get('evalclear').onclick=()=>{discard();run.samples=[];run.timings=[];run.errors=0;run.started=new Date().toISOString();render();status('Evaluation run cleared. Export results before clearing next time.')};
window.AuraEval={
 onInference(input,predictions,ms){
  if(!Number.isFinite(ms)||ms<0)return;run.timings.push(ms);if(run.timings.length>1000)run.timings.shift();
  if(pending){const chosen=pending;pending=null;const image=document.createElement('canvas');image.width=input.width;image.height=input.height;image.getContext('2d').drawImage(input,0,0);
   held={...chosen,image,predictions:structuredClone(predictions),truth:[],saved:false,ms,captured:new Date().toISOString()};canvas.width=input.width;canvas.height=input.height;get('evalconfirmed').checked=false;label.disabled=chosen.scope!==null;if(chosen.scope)label.value=chosen.scope[0];draw();status('Frozen exact inference input. Draw every visible object in scope, then confirm and score. '+(ms>800?'This result was too stale for live tracking.':''));
  }
  if(performance.now()-lastRender>1000){lastRender=performance.now();render()}
 },
 onError(){run.errors++;render()},
 onSessionEnd(){if(pending){pending=null;controls(false);status('Pending capture cancelled because object detection stopped.')}},
 report(){return {summary:core.aggregate(run.samples,run.timings,run.errors),samples:structuredClone(run.samples),raw_camera_frames_included:false}}
};
render();
})();
