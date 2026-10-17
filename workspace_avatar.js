/* Procedural full-body scene-graph rig, no downloaded character asset. */
export async function createAvatar(container,status){
 const THREE=await import('https://cdn.jsdelivr.net/npm/three@0.170.0/build/three.module.js');
 const renderer=new THREE.WebGLRenderer({antialias:true,alpha:true});renderer.setPixelRatio(Math.min(devicePixelRatio,2));container.append(renderer.domElement);renderer.setClearColor(0x101c25,0);
 const scene=new THREE.Scene(),camera=new THREE.PerspectiveCamera(34,1,.1,100);camera.position.set(3.8,2.3,6.8);camera.lookAt(0,1.15,0);scene.add(new THREE.HemisphereLight(0xc7ffef,0x233343,2.5));const light=new THREE.DirectionalLight(0xffffff,3);light.position.set(4,6,3);scene.add(light);
 const bodyMat=new THREE.MeshStandardMaterial({color:0x72c9bc,metalness:.35,roughness:.4}),jointMat=new THREE.MeshStandardMaterial({color:0x253e4a,roughness:.5}),darkMat=new THREE.MeshStandardMaterial({color:0x101923}),eyeMat=new THREE.MeshStandardMaterial({color:0xafffe8,emissive:0x4da38b,emissiveIntensity:1});
 function box(parent,w,h,d,x,y,z,mat=bodyMat){const m=new THREE.Mesh(new THREE.BoxGeometry(w,h,d),mat);m.position.set(x,y,z);parent.add(m);return m}
 function joint(parent,x,y,z){const g=new THREE.Group();g.position.set(x,y,z);parent.add(g);const m=new THREE.Mesh(new THREE.SphereGeometry(.085,12,8),jointMat);g.add(m);return g}
 const root=new THREE.Group();scene.add(root);const hips=joint(root,0,.98,0);box(hips,.47,.23,.28,0,.02,0);const spine=joint(hips,0,.19,0);box(spine,.55,.5,.3,0,.22,0);box(spine,.18,.1,.02,0,.27,.16,eyeMat);const neck=joint(spine,0,.53,0);const head=joint(neck,0,.12,0);box(head,.41,.39,.33,0,.08,0);box(head,.34,.12,.02,0,.13,.18,darkMat);[-1,1].forEach(s=>box(head,.075,.045,.025,s*.105,.14,.2,eyeMat));
 const mouth=box(head,.14,.018,.035,0,-.035,.19,darkMat),jaw=joint(head,0,-.06,0);box(jaw,.31,.08,.28,0,-.045,0);const leftShoulder=joint(spine,-.36,.39,0),rightShoulder=joint(spine,.36,.39,0);
 function arm(j){box(j,.15,.32,.16,0,-.19,0);const e=joint(j,0,-.39,0);box(e,.13,.3,.14,0,-.18,0);box(e,.16,.16,.12,0,-.4,0);return e}const leftElbow=arm(leftShoulder),rightElbow=arm(rightShoulder);
 const leftHip=joint(hips,-.16,-.1,0),rightHip=joint(hips,.16,-.1,0);
 function leg(j){box(j,.19,.35,.2,0,-.21,0);const k=joint(j,0,-.43,0);box(k,.16,.32,.18,0,-.18,0);box(k,.21,.12,.37,0,-.4,.07,jointMat);return k}const leftKnee=leg(leftHip),rightKnee=leg(rightHip);
 const floor=new THREE.Mesh(new THREE.CircleGeometry(1.2,48),new THREE.MeshStandardMaterial({color:0x1c3940,roughness:.9}));floor.rotation.x=-Math.PI/2;floor.position.y=.005;scene.add(floor);
 let mode='idle',v=0,amp=0,dead=false,raf=0;const start=performance.now();
 const resize=()=>{const w=container.clientWidth,h=container.clientHeight;if(w&&h){renderer.setSize(w,h,false);camera.aspect=w/h;camera.updateProjectionMatrix()}};const observer=new ResizeObserver(resize);observer.observe(container);resize();status.textContent='Full-body joint rig · virtual animation';
 const joints=[spine,neck,head,leftShoulder,rightShoulder,leftElbow,rightElbow,leftHip,rightHip,leftKnee,rightKnee];
 function frame(){if(dead)return;const t=(performance.now()-start)/1000;joints.forEach(j=>j.rotation.set(0,0,0));hips.position.y=.98+Math.sin(t*2)*.012;root.rotation.y=Math.sin(t*.4)*.08;
 if(mode==='wave'){rightShoulder.rotation.z=-2.25;rightShoulder.rotation.x=-.2;rightElbow.rotation.z=Math.sin(t*6)*.45-.5;head.rotation.z=-.1}
 if(mode==='walk'){const s=Math.sin(t*5);leftHip.rotation.x=s*.43;rightHip.rotation.x=-s*.43;leftKnee.rotation.x=Math.max(0,-s)*.5;rightKnee.rotation.x=Math.max(0,s)*.5;leftShoulder.rotation.x=-s*.35;rightShoulder.rotation.x=s*.35;hips.position.y+=Math.abs(Math.sin(t*5))*.025}
 if(mode==='dance'){spine.rotation.z=Math.sin(t*4)*.18;hips.position.y+=Math.abs(Math.sin(t*4))*.08;leftShoulder.rotation.z=.9+Math.sin(t*4)*.6;rightShoulder.rotation.z=-.9+Math.sin(t*4)*.6;leftElbow.rotation.x=-.7;rightElbow.rotation.x=-.7;leftHip.rotation.z=Math.sin(t*4)*.12;rightHip.rotation.z=Math.sin(t*4)*.12;root.rotation.y=Math.sin(t*2)*.4}
 // Windows viseme groups approximate visible mouth shapes, not audio-derived phoneme guesses.
 const closed=[0,21].includes(v),round=[7,8,9,10,11].includes(v),open=closed?0:amp*(round?.65:1);mouth.scale.set(round?.6:1,1+open*5,1);jaw.rotation.x=open*.2;renderer.render(scene,camera);raf=requestAnimationFrame(frame)}frame();
 return {motion(value){if(['idle','wave','walk','dance'].includes(value))mode=value},mouth(viseme,amplitude){v=viseme;amp=amplitude},dispose(){dead=true;cancelAnimationFrame(raf);observer.disconnect();scene.traverse(o=>{o.geometry?.dispose()});[bodyMat,jointMat,darkMat,eyeMat,floor.material].forEach(m=>m.dispose());renderer.dispose();renderer.domElement.remove()}};
}
