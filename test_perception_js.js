/* Pure helper + mocked browser-lifecycle tests. No real neural inference/camera. */
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),{webcrypto}=require('node:crypto');
const P=require('./perception_core.js');let passed=0;
async function test(name,fn){await fn();passed++;console.log('PASS '+name)}
const flush=()=>new Promise(resolve=>setImmediate(resolve));
function deferred(){let resolve;const promise=new Promise(r=>resolve=r);return {promise,resolve}}
function browser({loading,detecting}={}){
 const requests=[],elements={},ctx2d={clearRect(){},drawImage(){},strokeRect(){},fillRect(){},fillText(){},measureText(){return {width:20}}};
 function el(id){return elements[id]||(elements[id]={width:320,height:240,clientWidth:320,clientHeight:240,disabled:false,textContent:'',value:'',children:[],append(...v){this.children.push(...v)},replaceChildren(){this.children=[]},getContext(){return ctx2d},addEventListener(){}})}
 const model={detect:()=>detecting?detecting.promise:Promise.resolve([{class:'bottle',score:.9,bbox:[32,24,64,96]}]),dispose(){}};
 const sandbox={console,TextEncoder,crypto:webcrypto,structuredClone,performance:{now:()=>10},devicePixelRatio:1,AbortController,
  setTimeout,clearTimeout,setInterval(){},requestAnimationFrame(){},AuraPerceptionCore:P,
  tracking:true,camera:{getVideoTracks:()=>[{readyState:'live',getSettings:()=>({deviceId:'fixture',zoom:1})}]},video:{readyState:2,videoWidth:640,videoHeight:480},bodyToken:'FAKE_TOKEN',
  document:{getElementById:el,createElement:()=>el('new-'+Math.random()),addEventListener(){},hidden:false,head:{append(){throw Error('Unexpected dependency download in mocked test')}}},
  window:{addEventListener(){}},fetch:async()=>({}),tf:{ready:async()=>{}},cocoSsd:{load:()=>loading?loading.promise:Promise.resolve(model)},
  api:async(path,data)=>{requests.push({path,data});return {objects:[],selected_id:null,target_state:'none'}}};
 sandbox.window.tf=sandbox.tf;sandbox.window.cocoSsd=sandbox.cocoSsd;
 const context=vm.createContext(sandbox);context.stopCamera=async()=>{context.tracking=false;await vm.runInContext('stopPerception()',context)};
 vm.runInContext(fs.readFileSync(__dirname+'/perception_lab.js','utf8'),context);
 return {context,requests,model,run:code=>vm.runInContext(code,context)};
}
(async()=>{
await test('pixel boxes normalised',()=>{const d=P.normalise([{class:'bottle',score:.9,bbox:[10,20,40,60]}],100,200);assert.deepEqual(d[0].box,[.1,.1,.4,.30000000000000004])});
await test('low confidence ignored',()=>assert.equal(P.normalise([{class:'bottle',score:.2,bbox:[1,1,20,20]}],100,100).length,0));
await test('nonfinite predictions ignored',()=>assert.equal(P.normalise([{class:'bottle',score:.9,bbox:[NaN,1,20,20]}],100,100).length,0));
await test('clipped boxes bounded',()=>{const o=P.normalise([{class:'person',score:.9,bbox:[-5,-5,30,30]}],100,100)[0];assert.deepEqual(o.box,[0,0,.25,.25])});
await test('letterbox overlay mapping',()=>assert.deepEqual(P.fitRect(400,400,640,480),{x:0,y:50,width:400,height:300}));
await test('invalid overlay geometry skipped',()=>assert.equal(P.fitRect(0,100,640,480),null));
await test('prediction count bounded',()=>assert.equal(P.normalise(Array.from({length:50},()=>({class:'cup',score:.9,bbox:[1,1,20,20]})),100,100).length,20));
await test('stop during model load prevents session start',async()=>{const loading=deferred(),b=browser({loading});const p=b.run('startPerception()');await flush();await b.run('stopPerception()');loading.resolve(b.model);await p;assert.equal(b.run('perceptionMode'),false);assert.equal(b.requests.filter(r=>r.path==='/api/vision/start').length,0)});
await test('late inference cannot publish after stop',async()=>{const detecting=deferred(),b=browser({detecting});await b.run('startPerception()');const p=b.run('inferObjects()');await flush();await b.run('stopPerception()');detecting.resolve([{class:'bottle',score:.9,bbox:[1,2,30,40]}]);await p;assert.equal(b.requests.filter(r=>r.path==='/api/vision/frame').length,0)});
await test('valid inference sends metadata only',async()=>{const b=browser();await b.run('startPerception()');await b.run('inferObjects()');const packet=b.requests.find(r=>r.path==='/api/vision/frame').data;assert.equal(packet.detections[0].label,'bottle');assert.deepEqual(Object.keys(packet).sort(),['age_ms','detections','profile','seq','session']);assert.equal(JSON.stringify(packet).includes('data:image'),false)});
await test('camera disconnect ends object session',async()=>{const b=browser();await b.run('startPerception()');b.context.camera={getVideoTracks:()=>[{readyState:'ended'}]};await b.run('inferObjects()');assert.equal(b.run('perceptionMode'),false);assert.ok(b.requests.some(r=>r.path==='/api/vision/end'))});
console.log(passed+' perception JS checks passed.');
})().catch(error=>{console.error(error);process.exitCode=1});
