"""Organ-inspired control services, not a biological or medical simulation."""
from collections import deque
import math
import time

DESCRIPTIONS = {
    'brain':'Selects validated tasks and checks their progress.',
    'heart':'Tracks controller heartbeat and operator lease; missing feedback stops motion.',
    'lungs':'Tracks browser/body communication availability, not oxygen or real network quality.',
    'liver':'Validates typed requests and rejects malformed or excessive values; not a general security filter.',
    'kidneys':'Prunes bounded signal history; never deletes user documents.',
    'stomach':'Manages a virtual movement-energy budget; not the laptop battery.',
    'nerves':'Routes typed control and observation events.',
    'circulation':'Distributes virtual energy status to task and movement services; carries no real blood.',
    'muscles':'Applies joint speed and range limits in the kinematic simulator.',
    'eyes':'Receives explicit simulated targets or fresh camera colour-centroid observations.',
    'ears_voice':'Uses the existing microphone, speech recognition and Windows speech pipeline.',
    'immune':'Latches faults/Stop and requires explicit reset before movement resumes.',
}


class Organs:
    def __init__(self, clock=time.monotonic):
        self.clock=clock
        self.started=clock()
        self.beats=0
        self.energy=100.
        self.rejected=0
        self.cleaned=0
        self.events=deque(maxlen=120)
        self.sequence=0
        self.fault=None
        self.operator_seen=None
        self.visual_seen=None
        self.last_action='idle'
        self.mailboxes={name:deque(maxlen=32) for name in DESCRIPTIONS}

    def signal(self, kind, origin, target, outcome='ok'):
        if origin not in DESCRIPTIONS or target not in DESCRIPTIONS:
            raise ValueError('Unknown organ service.')
        if kind not in ('request','validated','rejected','heartbeat','started','completed','stopped','fault','recovered','observed','low_energy','cleaned'):
            raise ValueError('Unknown signal type.')
        self.sequence+=1
        if len(self.events)==self.events.maxlen:self.cleaned+=1
        # No user text, camera frames, API keys or model-generated instructions.
        event={'id':self.sequence,'time':round(self.clock()-self.started,3),
               'kind':kind,'from':origin,'to':target,'outcome':str(outcome)[:80]}
        self.events.append(event)
        self.mailboxes[target].append(dict(event))

    def drain(self,target):
        if target not in self.mailboxes:raise ValueError('Unknown signal recipient.')
        events=list(self.mailboxes[target]);self.mailboxes[target].clear()
        return events

    def validate(self, kind, values):
        self.signal('request','nerves','liver')
        allowed={'walk':{'x','z'},'dance':{'duration'},'wave':{'duration'},'look':{'yaw','pitch'},
                 'point':{'x','z'},'stop':set(),'reset':set(),'home':set(),'demo':set(),'rest':set()}
        try:
            if kind not in allowed or not isinstance(values,dict) or set(values)-allowed[kind]:
                raise ValueError('Unsupported body command or fields.')
            clean={}
            for key,value in values.items():
                if type(value) not in (int,float) or not math.isfinite(value):
                    raise ValueError('Body values must be finite numbers, not text or booleans.')
                clean[key]=float(value)
            if kind in ('walk','point'):
                if set(clean)!={'x','z'} or any(abs(clean[k])>2.7 for k in ('x','z')):
                    raise ValueError('Specify x and z between -2.7 and 2.7 virtual metres.')
            if kind in ('dance','wave'):
                clean.setdefault('duration',8. if kind=='dance' else 3.)
                if not 1<=clean['duration']<=30:raise ValueError('Duration must be 1 to 30 seconds.')
            if kind=='look':
                clean.setdefault('yaw',0.);clean.setdefault('pitch',0.)
                if abs(clean['yaw'])>70 or abs(clean['pitch'])>35:raise ValueError('Head angle outside virtual joint limits.')
            self.signal('validated','liver','brain')
            return clean
        except ValueError:
            self.rejected+=1
            self.signal('rejected','liver','immune','invalid_request')
            raise

    def tick(self,dt,moving):
        self.beats+=1
        before=self.energy
        self.energy=max(0.,min(100.,self.energy+dt*(-.7 if moving else .3)))
        if before>5>=self.energy:self.signal('low_energy','stomach','circulation')
        if self.beats%20==0:
            self.signal('heartbeat','heart','nerves')
            self.signal('heartbeat','circulation','muscles','virtual_energy_'+str(round(self.energy)))
        for event in self.drain('circulation'):
            if event['kind']=='low_energy':self.signal('low_energy','circulation','brain')
        if self.beats%100==0:self.signal('cleaned','kidneys','brain','bounded_signal_history')

    def summary(self):
        now=self.clock()
        def age(value):return None if value is None else round(max(0,now-value),2)
        statuses={name:{'function':desc,'status':'ready'} for name,desc in DESCRIPTIONS.items()}
        statuses['immune']['status']='latched: '+self.fault if self.fault else 'ready'
        statuses['stomach'].update(virtual_energy=round(self.energy,1),status='low' if self.energy<=5 else 'ready')
        statuses['heart'].update(beats=self.beats,operator_age=age(self.operator_seen))
        statuses['lungs']['status']='connected' if self.operator_seen is not None and now-self.operator_seen<1.5 else 'no fresh body-lab heartbeat'
        statuses['eyes']['status']='fresh camera target' if self.visual_seen is not None and now-self.visual_seen<1 else 'simulated scene / no fresh camera target'
        statuses['liver']['rejected_requests']=self.rejected
        statuses['kidneys'].update(retained_signals=len(self.events),pruned_signals=self.cleaned)
        return {'systems':statuses,'signals':list(self.events)[-25:],'simulation_only':True,'biological_model':False}
