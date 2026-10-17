"""Validated browser detections, short-lived spatial tracks and explicit targeting.
No frame upload, identity recognition, physical movement or model inference here.
"""
from copy import deepcopy
import math
import re
import threading
import time

LABELS=set(('person|bicycle|car|motorcycle|airplane|bus|train|truck|boat|traffic light|fire hydrant|stop sign|parking meter|bench|bird|cat|dog|horse|sheep|cow|elephant|bear|zebra|giraffe|backpack|umbrella|handbag|tie|suitcase|frisbee|skis|snowboard|sports ball|kite|baseball bat|baseball glove|skateboard|surfboard|tennis racket|bottle|wine glass|cup|fork|knife|spoon|bowl|banana|apple|sandwich|orange|broccoli|carrot|hot dog|pizza|donut|cake|chair|couch|potted plant|bed|dining table|toilet|tv|laptop|mouse|remote|keyboard|cell phone|microwave|oven|toaster|sink|refrigerator|book|clock|vase|scissors|teddy bear|hair drier|toothbrush').split('|'))
FRESH=.9
RETAIN=2.
def number(v):return type(v) in (int,float) and math.isfinite(v)
def iou(a,b):
    x=max(a[0],b[0]);y=max(a[1],b[1]);r=min(a[0]+a[2],b[0]+b[2]);bottom=min(a[1]+a[3],b[1]+b[3])
    overlap=max(0,r-x)*max(0,bottom-y)
    return overlap/(a[2]*a[3]+b[2]*b[3]-overlap) if overlap else 0.


class Scene:
    def __init__(self,clock=time.monotonic):
        self.clock=clock;self.lock=threading.RLock();self.session=None;self.profile=None
        self.last_seq=-1;self.last_capture=None;self.tracks={};self.next_id=1
        self.selected=None;self.calibration=None;self.frames=0;self.started=None;self.last_ms=None
    def start(self,session,profile):
        if not isinstance(session,str) or not re.fullmatch('[a-zA-Z0-9-]{12,80}',session):raise ValueError('Invalid camera session.')
        if not isinstance(profile,str) or not re.fullmatch('[a-f0-9]{64}',profile):raise ValueError('Invalid camera profile hash.')
        with self.lock:
            self.session=session;self.profile=profile;self.last_seq=-1;self.last_capture=None
            self.tracks.clear();self.selected=None;self.calibration=None;self.frames=0;self.started=self.clock()
    def end(self,session):
        with self.lock:
            if session!=self.session:return False
            self.session=None;self.tracks.clear();self.selected=None;self.calibration=None;self.last_capture=None
            return True
    def ingest(self,data):
        if not isinstance(data,dict) or set(data)!={'session','profile','seq','age_ms','detections'}:
            raise ValueError('Invalid detection packet fields.')
        if type(data['seq']) is not int or not 0<=data['seq']<=1_000_000_000:raise ValueError('Invalid frame sequence.')
        if not number(data['age_ms']) or not 0<=data['age_ms']<=800:raise ValueError('Inference result too old; fresh result required within 800 ms.')
        raw=data['detections']
        if not isinstance(raw,list) or len(raw)>20:raise ValueError('Send at most 20 detections.')
        clean=[]
        for detection in raw:
            if not isinstance(detection,dict) or set(detection)!={'label','score','box'}:raise ValueError('Invalid detection fields.')
            label=detection['label'];score=detection['score'];box=detection['box']
            if not isinstance(label,str) or label not in LABELS:raise ValueError('Unsupported detector category.')
            if not number(score) or not 0<=score<=1:raise ValueError('Invalid detector confidence.')
            if not isinstance(box,list) or len(box)!=4 or any(not number(v) or not 0<=v<=1 for v in box):raise ValueError('Use normalised bounding boxes.')
            if box[2]<.005 or box[3]<.005 or box[0]+box[2]>1.001 or box[1]+box[3]>1.001:raise ValueError('Bounding box is empty or outside the image.')
            if score>=.6:clean.append({'label':label,'score':score,'box':list(box)})
        with self.lock:
            if self.session is None or data['session']!=self.session:raise ValueError('Camera session is inactive or replaced.')
            if data['profile']!=self.profile:raise ValueError('Camera geometry changed. Restart object mode and recalibrate.')
            if data['seq']<=self.last_seq:raise ValueError('Old/replayed frame rejected.')
            now=self.clock();capture=now-data['age_ms']/1000
            if self.last_capture is not None and capture<self.last_capture:raise ValueError('Out-of-order capture rejected.')
            self.last_seq=data['seq'];self.last_capture=capture;self.frames+=1;self.last_ms=data['age_ms']
            self.tracks={k:t for k,t in self.tracks.items() if now-t['seen']<=RETAIN}
            candidates=[]
            for di,d in enumerate(clean):
                for ident,t in self.tracks.items():
                    if d['label']!=t['label']:continue
                    overlap=iou(d['box'],t['box'])
                    ax,ay,aw,ah=d['box'];bx,by,bw,bh=t['box']
                    distance=math.hypot(ax+aw/2-bx-bw/2,ay+ah/2-by-bh/2)
                    ratio=max(aw*ah,bw*bh)/max(.00001,min(aw*ah,bw*bh))
                    if overlap>=.15 or distance<.12 and ratio<2.5:
                        candidates.append((overlap-distance*.3,di,ident))
            used_d=set();used_t=set();matches={}
            for _,di,ident in sorted(candidates,reverse=True):
                if di not in used_d and ident not in used_t:matches[di]=ident;used_d.add(di);used_t.add(ident)
            for t in self.tracks.values():t['visible']=False
            for di,d in enumerate(clean):
                ident=matches.get(di)
                if ident is None:ident=self.next_id;self.next_id+=1
                self.tracks[ident]=dict(d,id=ident,seen=capture,visible=True,source='browser_coco_ssd')
            return self.snapshot()
    def _fresh(self,t):return bool(self.session and t['visible'] and self.clock()-t['seen']<=FRESH)
    def select(self,selector):
        with self.lock:
            fresh=[t for t in self.tracks.values() if self._fresh(t)]
            if type(selector) is int:
                matches=[t for t in fresh if t['id']==selector]
            elif isinstance(selector,str):matches=[t for t in fresh if t['label']==selector]
            else:raise ValueError('Choose a detected object category or numeric track ID.')
            if not matches:raise ValueError('Target not currently visible. Start object detection and show the object again.')
            if len(matches)>1:raise ValueError('Multiple '+str(selector)+' objects are visible. Choose track ID '+', '.join(str(t['id']) for t in matches)+'.')
            self.selected=matches[0]['id'];return self.snapshot()
    def release(self):
        with self.lock:self.selected=None
    def calibrate(self,known_width_m,known_distance_m):
        if not number(known_width_m) or not .02<=known_width_m<=2:raise ValueError('Known object width must be 0.02 to 2 metres.')
        if not number(known_distance_m) or not .1<=known_distance_m<=10:raise ValueError('Measured distance must be 0.1 to 10 metres.')
        with self.lock:
            t=self.tracks.get(self.selected)
            if t is None or not self._fresh(t):raise ValueError('Select one currently visible track before calibration.')
            x,y,w,h=t['box']
            if x<.01 or x+w>.99 or y<.01 or y+h>.99 or w<.02:raise ValueError('Use an unclipped, clearly visible object for calibration.')
            focal=w*known_distance_m/known_width_m
            if not .05<=focal<=10:raise ValueError('Calibration outside supported range; check measured dimensions.')
            self.calibration={'id':t['id'],'profile':self.profile,'width_m':known_width_m,'focal_norm':focal,'aspect':h/w}
            return {'approximate':True,'assumption':'same rigid object, same facing width and unchanged camera geometry','track_id':t['id']}
    def snapshot(self):
        with self.lock:
            objects=[]
            for t in self.tracks.values():
                age=max(0,self.clock()-t['seen'])
                if age>RETAIN:continue
                item=deepcopy(t);item.pop('seen');item['age_seconds']=round(age,3);item['visible']=self._fresh(t)
                x,y,w,h=t['box'];item.update(image_x=x+w/2,image_y=y+h/2,
                    side='left' if x+w/2<.4 else 'right' if x+w/2>.6 else 'centre',distance_estimate_m=None)
                cal=self.calibration
                if cal and cal['id']==t['id'] and cal['profile']==self.profile and item['visible'] and x>=.01 and x+w<=.99 and y>=.01 and y+h<=.99 and abs((h/w)/cal['aspect']-1)<.2:
                    estimate=cal['focal_norm']*cal['width_m']/w
                    if .1<=estimate<=10:item['distance_estimate_m']=round(estimate,2)
                objects.append(item)
            selected=next((t for t in objects if t['id']==self.selected),None)
            return {'active':self.session is not None,'objects':objects,'selected_id':self.selected,
                    'target_state':'none' if self.selected is None else 'visible' if selected and selected['visible'] else 'lost',
                    'frames':self.frames,'last_inference_ms':self.last_ms,
                    'freshness_limit_seconds':FRESH,'source':'browser_detector_reports','physical_identity':False,
                    'calibrated':self.calibration is not None,'distance_warning':'Approximate same-object size estimate; not metric 3D reconstruction.'}


SCENE=Scene()


def sync_head(scene=SCENE,body=None):
    if body is None:
        from aura_body import BODY
        body=BODY
    snapshot=scene.snapshot()
    target=next((o for o in snapshot['objects'] if o['id']==snapshot['selected_id'] and o['visible']),None)
    with body.lock:
        if target:
            body.camera={'x':target['image_x'],'y':target['image_y'],'seen':body.clock()-target['age_seconds'],
                         'source':'object_detection','track_id':target['id'],'label':target['label']}
            body.camera_tracking=True;body.organs.visual_seen=body.camera['seen']
        elif body.camera and body.camera.get('source')=='object_detection':
            body.camera=None;body.camera_tracking=False;body.organs.visual_seen=None
    return snapshot


ALIASES={'phone':'cell phone','mobile':'cell phone','sofa':'couch','plant':'potted plant','table':'dining table'}
def perception_reply(user):
    text=user.strip().lower().rstrip('.!?')
    location=re.fullmatch(r'(?:aura[, ]+)?where is (?:the )?([a-z ]+)',text)
    if location:
        label=ALIASES.get(location[1],location[1])
        if label not in LABELS:return None
        objects=[o for o in SCENE.snapshot()['objects'] if o['visible'] and o['label']==label]
        if not objects:return 'No fresh detector report for '+label+'. Show it to the camera with Object detection enabled.'
        return '; '.join('#'+str(o['id'])+' '+o['label']+' is at image '+o['side']+' (normalised centre '+str(round(o['image_x'],2))+', '+str(round(o['image_y'],2))+')' for o in objects)+'. This is an image location, not a physical room coordinate.'
    if text in ('/vision','/vision list','aura what do you see','what do you see','aura kya dikh raha hai'):
        snapshot=SCENE.snapshot();fresh=[o for o in snapshot['objects'] if o['visible']]
        if not fresh:return 'No fresh object detections are available. Open Body Lab, start the camera, and enable Object detection.'
        return 'Detector currently reports: '+'; '.join('#'+str(o['id'])+' '+o['label']+' ('+o['side']+', confidence '+str(round(o['score'],2))+')' for o in fresh)+'. Image positions only; labels and track IDs can be wrong.'
    if text=='/vision stop':SCENE.release();sync_head();return 'Object target released. Virtual head following stopped.'
    match=re.fullmatch(r'/vision (?:look|target) (.+)',text)
    if not match:
        match=re.fullmatch(r'(?:aura[, ]+)?look at (?:the )?([a-z ]+)',text)
    if not match:match=re.fullmatch(r'(?:aura[, ]+)?([a-z ]+?) (?:ko )?dekho',text)
    if not match:
        if text.startswith('/vision '):raise ValueError('Use /vision list, /vision look category, /vision target ID, or /vision stop.')
        return None
    selector=match[1].strip();selector=int(selector) if selector.isdigit() else ALIASES.get(selector,selector)
    if isinstance(selector,str) and selector not in LABELS:
        if not text.startswith('/vision '):return None
        raise ValueError('Unsupported detector category. Use /vision list and select a reported track ID.')
    SCENE.select(selector);snapshot=sync_head()
    return 'Following detector track #'+str(snapshot['selected_id'])+' with the virtual head. Tracking releases on missing/stale observations; no physical movement.'
