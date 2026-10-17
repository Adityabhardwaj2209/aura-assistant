/* Offline Canvas renderer for an articulated 3D-coordinate virtual body.
   Projection/animation only: no physics engine, human mesh or hardware model. */
(function(root){
const rad=x=>x*Math.PI/180,add=(a,b)=>a.map((v,i)=>v+b[i]);
function rx(v,a){a=rad(a);return [v[0],v[1]*Math.cos(a)-v[2]*Math.sin(a),v[1]*Math.sin(a)+v[2]*Math.cos(a)]}
function rz(v,a){a=rad(a);return [v[0]*Math.cos(a)-v[1]*Math.sin(a),v[0]*Math.sin(a)+v[1]*Math.cos(a),v[2]]}
function ry(v,a){return [v[0]*Math.cos(a)+v[2]*Math.sin(a),v[1],-v[0]*Math.sin(a)+v[2]*Math.cos(a)]}
function skeleton(state){
 const j=state.joints||{},p=state.position||{x:0,z:0,yaw:0},points={},segments=[];
 const world=v=>{const q=ry(v,p.yaw||0);return [q[0]+p.x,q[1]+(p.bounce||0),q[2]+p.z]};
 const set=(name,v)=>(points[name]=world(v),v),seg=(a,b,r,c)=>segments.push({a:points[a],b:points[b],r,c});
 set('pelvis',[0,.94,0]);
 for(const [side,sign] of [['left',-1],['right',1]]){
  const hip=set(side+'hip',[sign*.15,.94,0]),hp=j[side+'_hip']||0,knee=set(side+'knee',add(hip,rx([0,-.43,0],hp)));
  const ankle=set(side+'ankle',add(knee,rx([0,-.43,0],hp-(j[side+'_knee']||0))));
  set(side+'toe',add(ankle,rx([0,-.04,.18],hp-(j[side+'_knee']||0)+(j[side+'_ankle']||0))));
  seg(side+'hip',side+'knee',.095,'#8aaec1');seg(side+'knee',side+'ankle',.073,'#acc8d7');seg(side+'ankle',side+'toe',.075,'#3b627d');
 }
 const upper=v=>add([0,.94,0],ry(rz(v,j.torso_roll||0),rad(j.torso_yaw||0)));
 for(const [side,sign] of [['left',-1],['right',1]]){
  const shoulder=upper([sign*.32,.52,0]);set(side+'shoulder',shoulder);
  const dir=(length,pitch)=>ry(rz(rx([0,-length,0],pitch),-(j[side+'_arm_roll']||0)),rad(j.torso_yaw||0));
  const elbow=set(side+'elbow',add(shoulder,dir(.31,j[side+'_shoulder']||0)));
  set(side+'hand',add(elbow,dir(.29,(j[side+'_shoulder']||0)-(j[side+'_elbow']||0))));
  seg(side+'shoulder',side+'elbow',.065,'#bdd5df');seg(side+'elbow',side+'hand',.055,'#7facc6');
 }
 const torso=[upper([-.23,.08,0]),upper([.23,.08,0]),upper([.29,.46,0]),upper([-.29,.46,0])].map(world);
 set('neck',upper([0,.62,0]));set('head',upper([0,.79,0]));
 return {points,segments,torso,headFacing:(p.yaw||0)+rad((j.torso_yaw||0)+(j.head_yaw||0)),headPitch:j.head_pitch||0};
}
function draw(canvas,state,options={}){
 const ctx=canvas.getContext('2d'),w=canvas.width,h=canvas.height;
 if(!state){ctx.fillStyle='#111f30';ctx.fillRect(0,0,w,h);return}
 const project=v=>{const q=ry(v,-.28),s=Math.min(w,h)*2.15/(q[2]+8.5);return [w*.5+q[0]*s,h*.70-q[1]*s+q[2]*s*.20,s,q[2]]};
 const bg=ctx.createLinearGradient(0,0,0,h);bg.addColorStop(0,'#101e32');bg.addColorStop(1,'#09111e');ctx.fillStyle=bg;ctx.fillRect(0,0,w,h);
 function line(a,b,width,color){ctx.beginPath();ctx.moveTo(a[0],a[1]);ctx.lineTo(b[0],b[1]);ctx.lineWidth=width;ctx.lineCap='round';ctx.strokeStyle=color;ctx.stroke()}
 for(let n=-3;n<=3;n+=.5){line(project([n,0,-3]),project([n,0,3]),1,'#21364a');line(project([-3,0,n]),project([3,0,n]),1,'#21364a')}
 const origin=project([0,0,0]);ctx.fillStyle='#759bb6';ctx.font=Math.max(10,w*.017)+'px system-ui';ctx.fillText('HOME',origin[0]+8,origin[1]+18);
 const active=state.active;
 if(active&&active.path&&active.path.length){ctx.setLineDash([5,5]);let previous=project([state.position.x,.015,state.position.z]);for(const p of active.path){const next=project([p[0],.015,p[1]]);line(previous,next,2,'#7cd8c3');previous=next}ctx.setLineDash([])}
 const objects=[...(state.world?.obstacles||[]).map(o=>({...o,obstacle:true})),...(state.world?.targets||[])].sort((a,b)=>b.z-a.z);
 for(const o of objects){const p=project([o.x,0,o.z]),r=(o.radius||.13)*p[2],top=project([o.x,o.obstacle?.4:.2,o.z]);ctx.fillStyle=o.obstacle?'#385264':o.colour==='red'?'#dc6571':'#6ca7eb';ctx.beginPath();ctx.ellipse(p[0],p[1],r,r*.3,0,0,Math.PI*2);ctx.fill();ctx.fillRect(top[0]-r,top[1],r*2,p[1]-top[1]);ctx.fillStyle=o.obstacle?'#607d91':o.colour==='red'?'#f39da4':'#9ac7ff';ctx.beginPath();ctx.ellipse(top[0],top[1],r,r*.3,0,0,Math.PI*2);ctx.fill();ctx.fillStyle='#b0c5d4';ctx.font='10px system-ui';ctx.fillText(o.id,p[0]-r,p[1]+16)}
 const model=skeleton(state),rootp=project([state.position.x,0,state.position.z]);ctx.fillStyle='#03081088';ctx.beginPath();ctx.ellipse(rootp[0],rootp[1],rootp[2]*.37,rootp[2]*.09,0,0,Math.PI*2);ctx.fill();
 function sphere(v,r,color){const p=project(v),radius=r*p[2],grad=ctx.createRadialGradient(p[0]-radius*.3,p[1]-radius*.3,1,p[0],p[1],radius);grad.addColorStop(0,'#e4f2f6');grad.addColorStop(.35,color);grad.addColorStop(1,'#253f55');ctx.fillStyle=grad;ctx.beginPath();ctx.arc(p[0],p[1],radius,0,Math.PI*2);ctx.fill()}
 const segs=model.segments.sort((a,b)=>(b.a[2]+b.b[2])-(a.a[2]+a.b[2]));
 const limb=s=>{const a=project(s.a),b=project(s.b),width=s.r*(a[2]+b[2]);line(a,b,width+3,'#0b1421');line(a,b,width,s.c);line([a[0]-width*.17,a[1]],[b[0]-width*.17,b[1]],Math.max(1,width*.13),'#d9f1f088');sphere(s.a,s.r*.9,'#83afc8');sphere(s.b,s.r*.85,'#a8c7d8')};
 for(const s of segs.filter(s=>!s.c.includes('bdd')&&!s.c.includes('7fa')))limb(s);
 const torso=model.torso.map(project);ctx.beginPath();torso.forEach((p,i)=>i?ctx.lineTo(p[0],p[1]):ctx.moveTo(p[0],p[1]));ctx.closePath();const gradient=ctx.createLinearGradient(torso[0][0],0,torso[1][0],0);gradient.addColorStop(0,'#3a637f');gradient.addColorStop(.5,'#c6dfe9');gradient.addColorStop(1,'#3a637f');ctx.fillStyle=gradient;ctx.fill();ctx.strokeStyle='#c3e9f0';ctx.lineWidth=1.2;ctx.stroke();
 const chest=model.points.neck.slice();chest[1]-=.20;sphere(chest,.045,state.estop?'#ed697c':'#6de3d7');
 for(const s of segs.filter(s=>s.c.includes('bdd')||s.c.includes('7fa')))limb(s);
 sphere(model.points.neck,.085,'#7ca3b9');sphere(model.points.head,.18,'#bed7e2');
 const hp=project(model.points.head),facing=model.headFacing-.28,front=Math.cos(facing),eyeY=hp[1]-hp[2]*.025;
 if(front>-.3){const shift=Math.sin(facing)*hp[2]*.065;for(const sign of [-1,1]){ctx.fillStyle=state.estop?'#ff8997':'#7df7ef';ctx.beginPath();ctx.ellipse(hp[0]+shift+sign*.065*hp[2]*Math.max(.25,front),eyeY,.033*hp[2],.012*hp[2],0,0,Math.PI*2);ctx.fill()}
  const level=Math.max(0,Math.min(1,options.speech||0));ctx.fillStyle='#182f43';ctx.beginPath();ctx.ellipse(hp[0]+shift,hp[1]+hp[2]*(.07+model.headPitch*.0005),hp[2]*.043,hp[2]*(.008+.035*level),0,0,Math.PI*2);ctx.fill();}
 ctx.fillStyle='#9ab5c8';ctx.font='11px system-ui';ctx.fillText('X '+state.position.x.toFixed(2)+'   Z '+state.position.z.toFixed(2)+'   '+(active?active.kind:'idle'),14,h-16);
}
const api={skeleton,draw};root.AuraBodyRender=api;if(typeof module!=='undefined')module.exports=api;
})(globalThis);
