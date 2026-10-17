/* Metrics and mocked annotation UI; these tests do not use a real camera. */
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),{webcrypto}=require('node:crypto'),C=require('./eval_core.js');
let passed=0;function test(name,fn){fn();passed++;console.log('PASS '+name)}
const gt=(label='bottle',box=[.1,.1,.2,.4])=>({label,box}),pred=(label='bottle',score=.9,box=[.1,.1,.2,.4])=>({label,score,box});
test('perfect matched box',()=>{const r=C.scoreFrame([pred()],[gt()]);assert.equal(r.tp,1);assert.equal(r.fp,0);assert.equal(r.fn,0);assert.equal(r.precision,1);assert.equal(r.recall,1);assert.equal(r.mean_matched_iou,1)});
test('duplicate predictions count as false positive',()=>{const r=C.scoreFrame([pred(),pred('bottle',.8)],[gt()]);assert.equal(r.tp,1);assert.equal(r.fp,1);assert.equal(r.precision,.5)});
test('missing object counted',()=>{const r=C.scoreFrame([],[gt()]);assert.equal(r.fn,1);assert.equal(r.recall,0);assert.equal(r.precision,null)});
test('wrong class is FP plus FN',()=>{const r=C.scoreFrame([pred('cup')],[gt()]);assert.equal(r.fp,1);assert.equal(r.fn,1)});
test('nonoverlapping boxes not matched',()=>{const r=C.scoreFrame([pred('bottle',.9,[.7,.1,.2,.4])],[gt()]);assert.equal(r.tp,0)});
test('matching is one-to-one',()=>{const r=C.scoreFrame([pred()],[gt(),gt()]);assert.equal(r.tp,1);assert.equal(r.fn,1)});
test('exact IoU 0.5 accepted',()=>{const r=C.scoreFrame([pred('bottle',.9,[0,0,.75,.25])],[gt('bottle',[.25,0,.75,.25])]);assert.equal(r.tp,1);assert.equal(r.mean_matched_iou,.5)});
test('low confidence excluded',()=>{const r=C.scoreFrame([pred('bottle',.59)],[gt()]);assert.equal(r.tp,0);assert.equal(r.fn,1);assert.equal(r.fp,0)});
test('score threshold boundary included',()=>assert.equal(C.scoreFrame([pred('bottle',.6)],[gt()]).tp,1));
test('empty scene not reported as 100 percent',()=>{const r=C.scoreFrame([],[]);assert.equal(r.precision,null);assert.equal(r.recall,null);assert.equal(r.f1,null)});
test('hallucination on empty scene counted',()=>{const r=C.scoreFrame([pred()],[]);assert.equal(r.precision,0);assert.equal(r.fp,1);assert.equal(r.recall,null)});
test('explicit scope ignores unannotated other categories',()=>{const r=C.scoreFrame([pred('person'),pred()],[gt()],{scope:['bottle']});assert.equal(r.tp,1);assert.equal(r.fp,0);assert.equal(r.matches[0].prediction,1)});
test('ground truth outside scope rejected',()=>assert.throws(()=>C.scoreFrame([],[gt('cup')],{scope:['bottle']})));
test('invalid numeric boxes and scores rejected',()=>{for(const p of [pred('bottle',NaN),pred('bottle',.9,[.9,.1,.2,.3]),pred('bottle',true)])assert.throws(()=>C.scoreFrame([p],[]))});
test('confidence order matching retains original indexes',()=>{const r=C.scoreFrame([pred('bottle',.7),pred('bottle',.95)],[gt()]);assert.equal(r.matches[0].prediction,1);assert.equal(r.false_positives[0].prediction,0)});
test('aggregate micro precision and recall',()=>{const r=C.aggregate([{predictions:[pred(),pred('bottle',.8)],truth:[gt()],scope:['bottle'],scenario:'normal_light'},{predictions:[],truth:[gt()],scope:['bottle'],scenario:'dim_light'}]);assert.equal(r.tp,1);assert.equal(r.fp,1);assert.equal(r.fn,1);assert.equal(r.precision,.5);assert.equal(r.recall,.5);assert.equal(r.by_scenario.dim_light.fn,1)});
test('latency window and stale count',()=>{const r=C.aggregate([],[10,20,1001,NaN,-1,Infinity],2);assert.equal(r.timing_window.completed_inferences,3);assert.equal(r.timing_window.stale_over_800_ms,1);assert.equal(r.inference_or_connection_errors,2)});
test('percentiles use stated interpolation',()=>assert.ok(Math.abs(C.percentile([10,20,30,100],.95)-89.5)<1e-10));
test('unsafe-looking scenario remains plain data',()=>{const r=C.aggregate([{predictions:[],truth:[],scenario:'__proto__'}]);assert.equal(r.by_scenario.__proto__.samples,1)});
function browser(){
 const elements={},timers=[],draws=[];
 const drawing={clearRect(){},drawImage(...args){draws.push(args)},strokeRect(){},fillText(){},setLineDash(){}};
 const element=id=>elements[id]||(elements[id]={id,value:'',checked:false,disabled:false,width:320,height:240,children:[],textContent:'',append(v){this.children.push(v)},getContext(){return drawing},getBoundingClientRect(){return {left:0,top:0,width:320,height:240}},click(){this.clicked=true}});
 for(const match of fs.readFileSync(__dirname+'/eval_panel.html','utf8').matchAll(/id="([^"]+)"/g))element(match[1]);
 const sandbox={console,structuredClone,crypto:webcrypto,performance:{now:()=>2000},perceptionMode:true,AuraEvalCore:C,
  window:{AuraEvalLabels:['bottle','cup','person']},document:{getElementById:element,createElement:type=>element(type+'-'+Math.random())},
  setTimeout(fn){timers.push(fn)},URL:{createObjectURL(){return 'blob:fixture'},revokeObjectURL(){}},Blob,
 };
 const context=vm.createContext(sandbox);vm.runInContext(fs.readFileSync(__dirname+'/eval_lab.js','utf8'),context);
 return {elements,timers,draws,api:context.window.AuraEval,input:{width:320,height:240,privateCameraPixels:'MUST_NOT_BE_EXPORTED'}};
}
test('annotation UI rejects unconfirmed truth',()=>{const b=browser();b.elements.evalcapture.onclick();b.api.onInference(b.input,[pred()],40);b.elements.evalsave.onclick();assert.equal(b.api.report().summary.annotated_samples,0)});
test('exact-frame capture and manual box score',()=>{const b=browser();b.elements.evalcapture.onclick();b.api.onInference(b.input,[pred()],40);assert.ok(b.draws.some(d=>d[0]===b.input));const c=b.elements.evalcanvas;c.onpointerdown({clientX:32,clientY:24,pointerId:1,preventDefault(){}});c.onpointerup({clientX:96,clientY:120});b.elements.evalconfirmed.checked=true;b.elements.evalsave.onclick();assert.equal(b.api.report().summary.tp,1)});
test('reports never contain frozen pixels',()=>{const b=browser();b.elements.evalcapture.onclick();b.api.onInference(b.input,[pred()],40);b.elements.evalconfirmed.checked=true;b.elements.evalsave.onclick();const r=b.api.report();assert.equal(r.raw_camera_frames_included,false);assert.equal(JSON.stringify(r).includes('MUST_NOT_BE_EXPORTED'),false);assert.equal(r.samples[0].truth.length,0);assert.equal(r.summary.fp,1)});
test('stale inference scored separately from tracking suitability',()=>{const b=browser();b.elements.evalcapture.onclick();b.api.onInference(b.input,[],1200);b.elements.evalconfirmed.checked=true;b.elements.evalsave.onclick();const r=b.api.report();assert.equal(r.samples[0].stale_for_live_tracking,true);assert.equal(r.summary.timing_window.stale_over_800_ms,1)});
test('stop cancels pending capture',()=>{const b=browser();b.elements.evalcapture.onclick();b.api.onSessionEnd();b.api.onInference(b.input,[pred()],40);b.elements.evalconfirmed.checked=true;b.elements.evalsave.onclick();assert.equal(b.api.report().samples.length,0)});
test('timing memory bounded',()=>{const b=browser();for(let i=0;i<1010;i++)b.api.onInference(b.input,[],i);assert.equal(b.api.report().summary.timing_window.completed_inferences,1000)});
test('clearing removes samples and frozen image state',()=>{const b=browser();b.elements.evalcapture.onclick();b.api.onInference(b.input,[pred()],40);b.elements.evalconfirmed.checked=true;b.elements.evalsave.onclick();b.elements.evalclear.onclick();assert.equal(b.api.report().samples.length,0);assert.equal(b.api.report().summary.timing_window.completed_inferences,0)});
console.log(passed+' evaluation JS checks passed.');
