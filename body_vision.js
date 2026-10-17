/* Colour-component tracker. Local pixels only; not a trained object detector. */
(function(root){
function detectColour(rgba,width,height,colour){
 if(!['red','green','blue'].includes(colour)||!Number.isInteger(width)||!Number.isInteger(height)||width<1||height<1||width*height>40000||rgba.length!==width*height*4)throw Error('Invalid tracker input');
 const n=width*height,mask=new Uint8Array(n),seen=new Uint8Array(n),stack=new Int32Array(n);
 for(let i=0;i<n;i++){const r=rgba[i*4],g=rgba[i*4+1],b=rgba[i*4+2],a=rgba[i*4+3];let yes=false;
  if(a>100){if(colour==='red')yes=r>90&&r>g*1.4&&r>b*1.4;else if(colour==='green')yes=g>70&&g>r*1.3&&g>b*1.2;else yes=b>90&&b>r*1.4&&b>g*1.2}mask[i]=yes?1:0;
 }
 let best=null;
 for(let i=0;i<n;i++){if(!mask[i]||seen[i])continue;let count=0,sx=0,sy=0,minx=width,maxx=0,miny=height,maxy=0,top=0;stack[top++]=i;seen[i]=1;
  while(top){const j=stack[--top],x=j%width,y=(j/width)|0;count++;sx+=x;sy+=y;minx=Math.min(minx,x);maxx=Math.max(maxx,x);miny=Math.min(miny,y);maxy=Math.max(maxy,y);
   const neighbours=[];if(x>0)neighbours.push(j-1);if(x<width-1)neighbours.push(j+1);if(y>0)neighbours.push(j-width);if(y<height-1)neighbours.push(j+width);
   for(const k of neighbours)if(mask[k]&&!seen[k]){seen[k]=1;stack[top++]=k}
  }
  if(!best||count>best.count)best={count,x:(sx/count+.5)/width,y:(sy/count+.5)/height,box:[minx,miny,maxx,maxy]};
 }
 if(!best||best.count<Math.max(12,n*.003))return {visible:false};
 return {visible:true,x:best.x,y:best.y,coverage:best.count/n,colour,box:best.box};
}
const api={detectColour};root.AuraVision=api;if(typeof module!=='undefined')module.exports=api;
})(globalThis);
