/* Optional Node-only pure-JS tests. No browser, camera or dependencies needed. */
const assert=require('node:assert/strict'),V=require('./body_vision.js'),R=require('./body_render.js');
let passed=0;function test(name,fn){fn();passed++;console.log('PASS '+name)}
const w=32,h=24;
function image(){const data=new Uint8ClampedArray(w*h*4);for(let i=3;i<data.length;i+=4)data[i]=255;return data}
function rectangle(data,x,y,width,height,colour){for(let yy=y;yy<y+height;yy++)for(let xx=x;xx<x+width;xx++){const i=(yy*w+xx)*4;data.set([...colour,255],i)}}
test('red component centroid',()=>{const d=image();rectangle(d,4,6,8,6,[220,20,15]);const r=V.detectColour(d,w,h,'red');assert.equal(r.visible,true);assert.equal(r.x,8/w);assert.equal(r.y,9/h)});
test('largest component wins',()=>{const d=image();rectangle(d,1,1,3,4,[255,0,0]);rectangle(d,20,10,8,8,[255,0,0]);assert.ok(V.detectColour(d,w,h,'red').x>.6)});
test('different colour rejected',()=>{const d=image();rectangle(d,2,2,8,8,[0,0,255]);assert.equal(V.detectColour(d,w,h,'red').visible,false)});
test('blue and green supported',()=>{for(const [name,rgb]of [['blue',[5,10,230]],['green',[5,180,10]]]){const d=image();rectangle(d,4,4,7,7,rgb);assert.equal(V.detectColour(d,w,h,name).visible,true)}});
test('transparent pixels ignored',()=>{const d=image();rectangle(d,2,2,8,8,[255,0,0]);for(let i=3;i<d.length;i+=4)d[i]=0;assert.equal(V.detectColour(d,w,h,'red').visible,false)});
test('single pixel noise rejected',()=>{const d=image();rectangle(d,5,5,1,1,[255,0,0]);assert.equal(V.detectColour(d,w,h,'red').visible,false)});
test('invalid tracker input rejected',()=>{assert.throws(()=>V.detectColour(new Uint8Array(3),32,24,'red'));assert.throws(()=>V.detectColour(image(),32,24,'purple'))});
test('neutral articulated skeleton finite',()=>{const s=R.skeleton({position:{x:0,z:0,yaw:0},joints:{}});assert.equal(s.segments.length,10);for(const v of Object.values(s.points))assert.ok(v.every(Number.isFinite))});
test('shoulder motion changes hand position',()=>{const a=R.skeleton({position:{x:0,z:0,yaw:0},joints:{}}),b=R.skeleton({position:{x:0,z:0,yaw:0},joints:{right_arm_roll:-60,right_elbow:90}});assert.notDeepEqual(a.points.righthand,b.points.righthand)});
test('root transform reaches every segment',()=>{const a=R.skeleton({position:{x:0,z:0,yaw:0},joints:{}}),b=R.skeleton({position:{x:1,z:2,yaw:0},joints:{}});assert.equal(b.points.head[0]-a.points.head[0],1);assert.equal(b.points.head[2]-a.points.head[2],2)});
console.log(passed+' pure-JS checks passed.');
