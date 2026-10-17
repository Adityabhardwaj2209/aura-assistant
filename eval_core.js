/* Detection evaluation at one fixed operating point, not COCO mAP. */
(function(root){
function validBox(box){return Array.isArray(box)&&box.length===4&&box.every(v=>typeof v==='number'&&Number.isFinite(v)&&v>=0&&v<=1)&&box[2]>0&&box[3]>0&&box[0]+box[2]<=1.001&&box[1]+box[3]<=1.001}
function overlap(a,b){const w=Math.max(0,Math.min(a[0]+a[2],b[0]+b[2])-Math.max(a[0],b[0])),h=Math.max(0,Math.min(a[1]+a[3],b[1]+b[3])-Math.max(a[1],b[1]));const intersection=w*h;return intersection/(a[2]*a[3]+b[2]*b[3]-intersection)}
function metrics(tp,fp,fn,sumIoU=0){return {tp,fp,fn,precision:tp+fp?tp/(tp+fp):null,recall:tp+fn?tp/(tp+fn):null,f1:2*tp+fp+fn?2*tp/(2*tp+fp+fn):null,mean_matched_iou:tp?sumIoU/tp:null}}
function scoreFrame(predictions,truth,{scope=null,iouThreshold=.5,scoreThreshold=.6}={}){
 if(!Array.isArray(predictions)||!Array.isArray(truth)||predictions.length>100||truth.length>100)throw Error('At most 100 predictions/annotations per sample');
 if(typeof iouThreshold!=='number'||!Number.isFinite(iouThreshold)||iouThreshold<=0||iouThreshold>1||typeof scoreThreshold!=='number'||!Number.isFinite(scoreThreshold)||scoreThreshold<0||scoreThreshold>1)throw Error('Invalid evaluation thresholds');
 if(scope!==null&&(!Array.isArray(scope)||!scope.length||scope.some(s=>typeof s!=='string'||!s.trim())))throw Error('Invalid class scope');
 const inside=o=>scope===null||scope.includes(o.label);
 for(const o of [...predictions,...truth])if(!o||typeof o.label!=='string'||!o.label.trim()||!validBox(o.box))throw Error('Invalid labelled box');
 for(const p of predictions)if(typeof p.score!=='number'||!Number.isFinite(p.score)||p.score<0||p.score>1)throw Error('Invalid score');
 if(truth.some(o=>!inside(o)))throw Error('Annotation lies outside the declared evaluation scope');
 const p=predictions.map((o,index)=>({...o,index})).filter(o=>inside(o)&&o.score>=scoreThreshold).sort((a,b)=>b.score-a.score);
 const used=new Set(),matches=[],falsePositives=[];
 for(const prediction of p){let best=-1,bestIoU=0;truth.forEach((target,i)=>{if(used.has(i)||target.label!==prediction.label)return;const value=overlap(prediction.box,target.box);if(value>bestIoU){bestIoU=value;best=i}});
  if(best>=0&&bestIoU>=iouThreshold){used.add(best);matches.push({prediction:prediction.index,truth:best,iou:bestIoU,label:prediction.label})}else falsePositives.push({prediction:prediction.index,label:prediction.label});
 }
 const falseNegatives=truth.map((target,i)=>({truth:i,label:target.label})).filter(o=>!used.has(o.truth));
 const sumIoU=matches.reduce((sum,m)=>sum+m.iou,0);
 return {...metrics(matches.length,falsePositives.length,falseNegatives.length,sumIoU),sum_iou:sumIoU,matches,false_positives:falsePositives,false_negatives:falseNegatives,predictions_in_scope:p.length,truth_in_scope:truth.length};
}
function percentile(values,q){if(!values.length)return null;const v=values.slice().sort((a,b)=>a-b),position=(v.length-1)*q,lo=Math.floor(position),hi=Math.ceil(position);return v[lo]+(v[hi]-v[lo])*(position-lo)}
function aggregate(samples,timings=[],errors=0){
 let tp=0,fp=0,fn=0,sum=0;const groups=Object.create(null);
 for(const sample of samples){const result=scoreFrame(sample.predictions,sample.truth,{scope:sample.scope});tp+=result.tp;fp+=result.fp;fn+=result.fn;sum+=result.sum_iou;
  const key=sample.scenario||'unspecified',g=groups[key]||(groups[key]={samples:0,tp:0,fp:0,fn:0,sum:0});g.samples++;g.tp+=result.tp;g.fp+=result.fp;g.fn+=result.fn;g.sum+=result.sum_iou;
 }
 const latency=timings.filter(v=>typeof v==='number'&&Number.isFinite(v)&&v>=0);
 return {annotated_samples:samples.length,...metrics(tp,fp,fn,sum),
  by_scenario:Object.fromEntries(Object.entries(groups).map(([key,g])=>[key,{samples:g.samples,...metrics(g.tp,g.fp,g.fn,g.sum)}])),
  timing_window:{completed_inferences:latency.length,mean_ms:latency.length?latency.reduce((a,b)=>a+b,0)/latency.length:null,median_ms:percentile(latency,.5),p95_ms:percentile(latency,.95),stale_over_800_ms:latency.filter(v=>v>800).length},
  inference_or_connection_errors:errors,score_threshold:.6,iou_threshold:.5,
  limitations:['Manually annotated selected samples; not a representative benchmark by default.','Metrics depend on complete/correct ground truth within each declared scope.','Not COCO mAP, tracking accuracy, physical safety or an improvement claim.','Timing covers inference calls only, not end-to-end speech or action latency.']};
}
const api={validBox,overlap,scoreFrame,aggregate,percentile};root.AuraEvalCore=api;if(typeof module!=='undefined')module.exports=api;
})(globalThis);
