const fs=require('fs'),vm=require('vm'),assert=require('assert');let Capture;
const outputs=[];const ctx={Float32Array,AudioWorkletProcessor:class{constructor(){this.port={postMessage:a=>outputs.push(a)}}},registerProcessor:(name,cls)=>{assert.equal(name,'aura-capture');Capture=cls}};
vm.createContext(ctx);vm.runInContext(fs.readFileSync('worklet.js','utf8'),ctx);const p=new Capture;
assert.equal(p.process([]),true);assert.equal(outputs.length,0);console.log('PASS no input is harmless');
for(let i=0;i<16;i++)p.process([[new Float32Array(128).fill(.25),new Float32Array(128).fill(.75)]]);
assert.equal(outputs.length,1);assert.equal(outputs[0].length,2048);assert(outputs[0].every(v=>v===.5));console.log('PASS fixed-size mono chunks average channels');
for(let i=0;i<16;i++)p.process([[new Float32Array(128).fill(-.5)]]);
assert.equal(outputs.length,2);assert.notEqual(outputs[0],outputs[1]);assert(outputs[1].every(v=>v===-.5));assert(outputs[0].every(v=>v===.5));console.log('PASS chunks use independent buffers');
console.log('3 audio-worklet fixture checks passed.');
