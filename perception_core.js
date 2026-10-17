/* Pure helpers, shared by the browser UI and offline Node tests. */
(function(root){
function normalise(predictions,width,height){
 if(!Number.isFinite(width)||!Number.isFinite(height)||width<=0||height<=0||!Array.isArray(predictions))throw Error('Invalid detector input');
 const out=[];
 for(const p of predictions.slice(0,20)){
  if(typeof p.class!=='string'||!Number.isFinite(p.score)||p.score<.6||p.score>1||!Array.isArray(p.bbox)||p.bbox.length!==4||!p.bbox.every(Number.isFinite))continue;
  const [x,y,w,h]=p.bbox;if(w<=0||h<=0)continue;
  const left=Math.max(0,Math.min(1,x/width)),top=Math.max(0,Math.min(1,y/height));
  const right=Math.max(0,Math.min(1,(x+w)/width)),bottom=Math.max(0,Math.min(1,(y+h)/height));
  if(right-left<.005||bottom-top<.005)continue;
  out.push({label:p.class,score:p.score,box:[left,top,right-left,bottom-top]});
 }
 return out;
}
function fitRect(width,height,videoWidth,videoHeight){
 if([width,height,videoWidth,videoHeight].some(v=>!Number.isFinite(v)||v<=0))return null;
 const s=Math.min(width/videoWidth,height/videoHeight),w=videoWidth*s,h=videoHeight*s;
 return {x:(width-w)/2,y:(height-h)/2,width:w,height:h};
}
function drawOverlay(ctx,width,height,videoWidth,videoHeight,scene){
 ctx.clearRect(0,0,width,height);const rect=fitRect(width,height,videoWidth,videoHeight);if(!rect)return;
 for(const o of scene?.objects||[]){if(!o.visible)continue;const [x,y,w,h]=o.box;
  ctx.strokeStyle=o.id===scene.selected_id?'#ffd37f':'#73e8cb';ctx.lineWidth=2;ctx.strokeRect(rect.x+x*rect.width,rect.y+y*rect.height,w*rect.width,h*rect.height);
  const label='#'+o.id+' '+o.label+' '+Math.round(o.score*100)+'%';ctx.font='12px system-ui';
  const tx=rect.x+x*rect.width,ty=Math.max(14,rect.y+y*rect.height-5);ctx.fillStyle='#06131ee8';ctx.fillRect(tx-2,ty-13,ctx.measureText(label).width+6,17);ctx.fillStyle=ctx.strokeStyle;ctx.fillText(label,tx,ty);
 }
}
const api={normalise,fitRect,drawOverlay};root.AuraPerceptionCore=api;if(typeof module!=='undefined')module.exports=api;
})(globalThis);
