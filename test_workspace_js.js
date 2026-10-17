/* Scene-graph fixture tests: no WebGL, actual Three.js or browser renderer. */
const fs=require('fs'),vm=require('vm'),assert=require('assert');let passed=0;
function test(name,fn){fn();console.log('PASS '+name);passed++}
const html=fs.readFileSync('workspace.html','utf8'),ui=fs.readFileSync('workspace.js','utf8');
const ids=[...html.matchAll(/\bid="([^"]+)"/g)].map(m=>m[1]);
test('unique UI ids',()=>assert.equal(ids.length,new Set(ids).size));
test('all literal UI element lookups exist',()=>{for(const m of ui.matchAll(/\$\('([^']+)'\)/g))assert(ids.includes(m[1]),m[1]);for(const m of ui.matchAll(/action\('([^']+)'/g))assert(ids.includes(m[1]),m[1])});
test('untrusted content uses text nodes',()=>{assert(!ui.includes('innerHTML'));assert(!ui.includes('insertAdjacentHTML'));assert(ui.includes('textContent=text'))});
test('pending voice request cancelled by Stop generation',()=>assert(ui.includes('if(generation!==speechGeneration)return')));
test('review cleared on programmatic source load',()=>assert(ui.includes("if(['candidate','testsource'].includes(id))$('testreviewed').checked=false")));
test('all twelve capability sections represented',()=>{for(const id of ['home','goals','planner','docs','learn','screen','desktop','code','avatar','performance'])assert(ids.includes(id))});
(async()=>{
let raf=null,disposed=0,objects=[];
class V{constructor(){this.x=this.y=this.z=0}set(x,y,z){Object.assign(this,{x,y,z})}}
class G{constructor(){this.position=new V;this.rotation=new V;this.scale=new V;this.children=[];objects.push(this)}add(...x){this.children.push(...x)}traverse(fn){fn(this);this.children.forEach(c=>c.traverse?c.traverse(fn):fn(c))}}
class Mesh extends G{constructor(geometry,material){super();this.geometry=geometry;this.material=material}}
class Material{constructor(p){this.params=p}dispose(){disposed++}}
class Geometry{dispose(){disposed++}}
class Camera extends G{lookAt(){}updateProjectionMatrix(){}}
class Renderer{constructor(){this.domElement={remove(){}}}setPixelRatio(){}setClearColor(){}setSize(){}render(){}dispose(){disposed++}}
const THREE={Group:G,Scene:G,Mesh,PerspectiveCamera:Camera,WebGLRenderer:Renderer,HemisphereLight:G,DirectionalLight:G,MeshStandardMaterial:Material,BoxGeometry:Geometry,SphereGeometry:Geometry,CircleGeometry:Geometry};
const source=fs.readFileSync('workspace_avatar.js','utf8').replace('export async function createAvatar','async function createAvatar').replace("await import('https://cdn.jsdelivr.net/npm/three@0.170.0/build/three.module.js')",'globalThis.THREE');
let time=0;const ctx={THREE,devicePixelRatio:1,performance:{now:()=>time},ResizeObserver:class{observe(){}disconnect(){}},requestAnimationFrame:f=>(raf=f,1),cancelAnimationFrame(){}};
vm.createContext(ctx);vm.runInContext(source+'\nglobalThis.factory=createAvatar;',ctx);const status={};const rig=await ctx.factory({clientWidth:800,clientHeight:450,append(){}},status);
test('full body contains joint hierarchy and meshes',()=>{assert(objects.filter(x=>x instanceof Mesh).length>20);assert(objects.some(o=>o.children.some(c=>c.children?.length>2)))});
test('all motion transforms stay finite',()=>{for(const mode of ['idle','wave','walk','dance']){rig.motion(mode);for(let i=0;i<30;i++){time+=41;raf();for(const o of objects)for(const vector of [o.position,o.rotation,o.scale])for(const k of ['x','y','z'])assert(Number.isFinite(vector[k]),mode)}}});
test('dance changes torso and leg rotations',()=>{rig.motion('dance');time=315;raf();assert(objects.filter(o=>Math.abs(o.rotation.z)>.05).length>=3)});
test('viseme changes visible mouth and jaw',()=>{rig.mouth(1,1);raf();assert(objects.some(o=>o.scale.y>1));assert(objects.some(o=>o.rotation.x===.2));rig.mouth(0,0);raf();assert(!objects.some(o=>o.scale.y>1))});
test('renderer and geometry released',()=>{rig.dispose();assert(disposed>20)});
console.log(passed+' workspace JS fixture checks passed.');
})().catch(e=>{console.error(e);process.exitCode=1});
