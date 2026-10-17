"""Deterministic, non-physical articulated-body simulator. No hardware drivers."""
import heapq
import math
import re
import threading
import time
from collections import deque
from copy import deepcopy
from aura_organs import Organs

LIMITS={'head_yaw':(-70,70),'head_pitch':(-35,35),'torso_yaw':(-25,25),'torso_roll':(-12,12),
        'left_shoulder':(-90,90),'right_shoulder':(-90,90),'left_arm_roll':(-75,75),'right_arm_roll':(-75,75),
        'left_elbow':(0,130),'right_elbow':(0,130),'left_hip':(-45,45),'right_hip':(-45,45),
        'left_knee':(0,90),'right_knee':(0,90),'left_ankle':(-25,25),'right_ankle':(-25,25)}
SPEED=160.  # degrees/s; a virtual constraint, not a safe physical motor rating
GRID=.25
RADIUS=.23


def finite(value):return type(value) in (int,float) and math.isfinite(value)


def blocked(x,z,obstacles):
    return abs(x)>2.75 or abs(z)>2.75 or any(math.hypot(x-o['x'],z-o['z'])<RADIUS+o['radius']+.04 for o in obstacles)


def path_to(start,goal,obstacles):
    """Bounded A* on a 2D floor with conservative root-circle obstacle checks."""
    if blocked(*goal,obstacles):raise ValueError('Target is blocked or outside the virtual floor.')
    source=tuple(round(v/GRID) for v in start);target=tuple(round(v/GRID) for v in goal)
    frontier=[(0.,source)];cost={source:0};parent={}
    for _ in range(700):
        if not frontier:break
        _,node=heapq.heappop(frontier)
        if node==target:
            route=[]
            while node!=source:
                route.append((node[0]*GRID,node[1]*GRID));node=parent[node]
            route.reverse()
            route.append(tuple(goal))
            return route
        for dx,dz in ((1,0),(-1,0),(0,1),(0,-1)):
            nxt=(node[0]+dx,node[1]+dz)
            if blocked(nxt[0]*GRID,nxt[1]*GRID,obstacles):continue
            value=cost[node]+1
            if value<cost.get(nxt,math.inf):
                cost[nxt]=value;parent[nxt]=node
                heapq.heappush(frontier,(value+abs(nxt[0]-target[0])+abs(nxt[1]-target[1]),nxt))
    raise ValueError('No bounded path found around the virtual obstacles.')


class Body:
    def __init__(self,clock=time.monotonic):
        self.clock=clock;self.lock=threading.RLock();self.last=clock();self.phase=0.
        self.organs=Organs(clock);self.x=0.;self.z=0.;self.yaw=0.
        self.joints={k:0. for k in LIMITS};self.queue=deque();self.active=None
        self.history=deque(maxlen=30);self.next_id=1;self.estop=False;self.reason='idle'
        self.obstacles=[{'id':'block-A','x':.75,'z':1.25,'radius':.35},
                        {'id':'block-B','x':-1.4,'z':-.9,'radius':.3}]
        self.targets=[{'id':'red-cube','x':1.8,'z':-.8,'colour':'red'},
                      {'id':'blue-cube','x':-1.8,'z':1.7,'colour':'blue'}]
        self.camera=None;self.camera_tracking=False;self.last_scene=None
        self.root_height=0.
        self.recorder=None;self.memory_status='session-only until Body Lab launcher attaches persistent storage'

    def _remember(self,kind,data):
        if self.recorder is None:return
        try:self.recorder(kind,data);self.memory_status='structured simulation events saved locally'
        except Exception:self.memory_status='body history unavailable; no database repair attempted'

    def heartbeat(self):
        with self.lock:
            before=self.organs.operator_seen;self.organs.operator_seen=self.clock()
            if before is None or self.clock()-before>.8:self.organs.signal('heartbeat','lungs','heart','operator_connected')

    def _fault(self,reason):
        self.estop=True;self.reason=reason;self.organs.fault=reason
        self._cancel(reason)
        self.organs.signal('fault','immune','muscles',reason)
        self._remember('fault',{'reason':reason,'simulation_only':True})

    def _cancel(self,reason):
        if self.active:self.history.append({'id':self.active['id'],'action':self.active['kind'],'status':'cancelled','reason':reason})
        for item in self.queue:self.history.append({'id':item['id'],'action':item['kind'],'status':'cancelled','reason':reason})
        self.active=None;self.queue.clear()

    def command(self,kind,params=None):
        with self.lock:
            clean=self.organs.validate(kind,params if params is not None else {})
            if kind=='stop':
                self._fault('operator_stop');return {'accepted':True,'status':'stopped','simulation_only':True}
            if kind=='reset':
                if blocked(self.x,self.z,self.obstacles):raise ValueError('Current virtual position is blocked.')
                self.estop=False;self.reason='reset';self.organs.fault=None
                self.organs.signal('recovered','immune','brain')
                return {'accepted':True,'status':'reset','simulation_only':True}
            if kind=='rest':
                self._cancel('rest');self.reason='resting'
                return {'accepted':True,'status':'resting','simulation_only':True}
            if self.estop:raise ValueError('Body stopped: '+self.reason+'. Use Reset before new movement.')
            if self.organs.operator_seen is None or self.clock()-self.organs.operator_seen>1.5:
                raise ValueError('Open the Body Lab first. A fresh browser heartbeat is required for virtual movement.')
            if self.organs.energy<=5:raise ValueError('Virtual energy is low. Rest before a new movement.')
            if len(self.queue)+(1 if self.active else 0)>=8:raise ValueError('Task queue is full. Stop or wait.')
            tasks=[(kind,clean)]
            if kind=='home':tasks=[('walk',{'x':0.,'z':0.})]
            if kind=='demo':tasks=[('wave',{'duration':2.}),('walk',{'x':.5,'z':-.5}),('dance',{'duration':5.}),('walk',{'x':0.,'z':0.})]
            if len(self.queue)+len(tasks)+(1 if self.active else 0)>8:raise ValueError('Not enough room for the complete plan.')
            # Validate walk targets before adding anything. Replan from actual position at execution.
            for action,values in tasks:
                if action=='walk':path_to((self.x,self.z),(values['x'],values['z']),self.obstacles)
            ids=[]
            for action,values in tasks:
                ident=self.next_id;self.next_id+=1;ids.append(ident)
                self.queue.append({'id':ident,'kind':action,'params':values,'elapsed':0.})
            self.organs.signal('validated','brain','muscles',kind)
            return {'accepted':True,'status':'queued','task_ids':ids,'simulation_only':True}

    def observe(self,data):
        with self.lock:
            if not isinstance(data,dict) or set(data)-{'visible','x','y','coverage','colour'}:
                raise ValueError('Invalid camera observation fields.')
            if type(data.get('visible')) is not bool:raise ValueError('visible must be a boolean.')
            if not data['visible']:
                self.camera=None;self.camera_tracking=False;self.organs.visual_seen=None
                return
            if data.get('colour') not in ('red','green','blue'):raise ValueError('Choose red, green or blue.')
            if any(not finite(data.get(k)) or not 0<=data[k]<=1 for k in ('x','y','coverage')):
                raise ValueError('Camera coordinates must be normalised finite values.')
            self.camera={k:data[k] for k in ('x','y','coverage','colour')}
            self.camera['seen']=self.clock();self.organs.visual_seen=self.clock();self.camera_tracking=True
            if self.organs.beats%5==0:self.organs.signal('observed','eyes','brain','colour_centroid')

    def scene(self,obstacles):
        with self.lock:
            if not isinstance(obstacles,list) or len(obstacles)>12:raise ValueError('Up to 12 virtual obstacles allowed.')
            clean=[]
            for i,o in enumerate(obstacles):
                if not isinstance(o,dict) or set(o)-{'x','z','radius'}:raise ValueError('Invalid obstacle.')
                if any(not finite(o.get(k)) for k in ('x','z','radius')):raise ValueError('Obstacle values must be finite.')
                if abs(o['x'])>2.7 or abs(o['z'])>2.7 or not .1<=o['radius']<=.6:raise ValueError('Obstacle outside supported bounds.')
                clean.append(dict(o,id='obstacle-'+str(i)))
            self.obstacles=clean;self.last_scene=self.clock()
            self._remember('scene_updated',{'obstacles':deepcopy(clean),'simulation_only':True})
            if blocked(self.x,self.z,clean):self._fault('obstacle_at_body')
            elif self.active and self.active['kind']=='walk':
                try:
                    p=self.active['params'];self.active['path']=path_to((self.x,self.z),(p['x'],p['z']),self.obstacles)
                except ValueError:self._fault('path_blocked')

    def _complete(self):
        action=self.active
        if action['kind']=='walk':
            p=action['params']
            if math.hypot(self.x-p['x'],self.z-p['z'])>.04:
                self._fault('goal_not_verified');return
        self.history.append({'id':action['id'],'action':action['kind'],'status':'verified_in_simulation'})
        self._remember('completed_task',{'action':action['kind'],'params':action['params'],
                                       'position':{'x':self.x,'z':self.z},'verification':'kinematic_simulation_only'})
        self.organs.signal('completed','muscles','brain',action['kind'])
        self.active=None;self.reason='completed'

    def update(self,dt=None):
        with self.lock:
            now=self.clock()
            elapsed=now-self.last if dt is None else dt
            if not finite(elapsed) or elapsed<0:raise ValueError('Invalid simulation time step.')
            # No movement catch-up after a hung tab/controller. Stop and require reset.
            if elapsed>.5 and (self.active or self.queue):self._fault('controller_delay')
            dt=min(elapsed,.1);self.last=now
            if (self.active or self.queue) and (self.organs.operator_seen is None or now-self.organs.operator_seen>1.5):
                self._fault('browser_heartbeat_lost')
            self.organs.tick(dt,bool(self.active or self.queue))
            for event in self.organs.drain('brain'):
                if event['kind']=='low_energy' and (self.active or self.queue):self._fault('virtual_energy_low')
            if self.organs.energy<=5 and (self.active or self.queue):self._fault('virtual_energy_low')
            if self.estop:return
            if not self.active and self.queue:
                self.active=self.queue.popleft();self.reason='running';self.active['started']=now
                if self.active['kind']=='walk':
                    p=self.active['params']
                    try:self.active['path']=path_to((self.x,self.z),(p['x'],p['z']),self.obstacles)
                    except ValueError:self._fault('path_blocked');return
                self.organs.signal('started','brain','muscles',self.active['kind'])
            target={k:0. for k in LIMITS};moving=False;self.root_height=0.
            if self.active:
                action=self.active;action['elapsed']+=dt;kind=action['kind'];p=action['params'];t=action['elapsed']
                if kind=='walk':
                    if t>90:self._fault('task_deadline');return
                    path=action['path']
                    while path and math.hypot(self.x-path[0][0],self.z-path[0][1])<.015:path.pop(0)
                    if not path:self._complete()
                    else:
                        gx,gz=path[0];dx=gx-self.x;dz=gz-self.z;distance=math.hypot(dx,dz)
                        angle=math.atan2(dx,dz);delta=(angle-self.yaw+math.pi)%(2*math.pi)-math.pi
                        self.yaw+=max(-1.8*dt,min(1.8*dt,delta))
                        if abs(delta)<.2 and distance>0:
                            step=min(.55*dt,distance);nx=self.x+dx/distance*step;nz=self.z+dz/distance*step
                            if blocked(nx,nz,self.obstacles):self._fault('collision_guard');return
                            self.x,self.z=nx,nz;moving=True;self.phase+=dt*7
                        q=math.sin(self.phase)
                        target.update(left_hip=24*q,right_hip=-24*q,left_knee=max(0,-q)*38,right_knee=max(0,q)*38,
                                      left_shoulder=-20*q,right_shoulder=20*q,left_elbow=14,right_elbow=14)
                        self.root_height=.02*abs(math.sin(self.phase)) if moving else 0.
                elif kind=='dance':
                    s=math.sin(t*4.5)
                    target.update(torso_roll=8*s,torso_yaw=16*math.sin(t*2.2),head_yaw=18*s,
                                  left_arm_roll=45+20*s,right_arm_roll=-45+20*s,
                                  left_elbow=55+25*s,right_elbow=55-25*s,
                                  left_hip=16*s,right_hip=-16*s,left_knee=12+10*s,right_knee=12-10*s)
                    self.root_height=.025*math.sin(t*9)
                    if t>=p['duration']:self._complete()
                elif kind=='wave':
                    target.update(right_arm_roll=-70,right_elbow=80+30*math.sin(t*7),head_yaw=-8)
                    if t>=p['duration']:self._complete()
                elif kind=='look':
                    target.update(head_yaw=p['yaw'],head_pitch=p['pitch'])
                    if t>=1.2:self._complete()
                elif kind=='point':
                    direction=math.atan2(p['x']-self.x,p['z']-self.z)
                    delta=(direction-self.yaw+math.pi)%(2*math.pi)-math.pi
                    self.yaw+=max(-1.8*dt,min(1.8*dt,delta))
                    distance=math.hypot(p['x']-self.x,p['z']-self.z)
                    arm_angle=-math.degrees(math.atan2(distance,1.25))
                    target.update(head_yaw=max(-70,min(70,math.degrees(delta))),head_pitch=25,
                                  right_shoulder=arm_angle,right_elbow=0)
                    if t>=3 and abs(delta)<.08:self._complete()
                    elif t>10:self._fault('point_orientation_not_verified');return
            if self.camera_tracking and self.camera:
                if now-self.camera['seen']>1.0:
                    self.camera_tracking=False;self.camera=None;self.organs.visual_seen=None
                else:
                    target['head_yaw']=(.5-self.camera['x'])*100
                    target['head_pitch']=(self.camera['y']-.5)*60
            for joint,value in target.items():
                lo,hi=LIMITS[joint];value=max(lo,min(hi,value))
                self.joints[joint]+=max(-SPEED*dt,min(SPEED*dt,value-self.joints[joint]))

    def snapshot(self):
        with self.lock:
            now=self.clock()
            return {'simulation_only':True,'physics_engine':False,'hardware_connected':False,
                    'position':{'x':round(self.x,4),'z':round(self.z,4),'yaw':self.yaw,'bounce':self.root_height},
                    'joints':dict(self.joints),'joint_limits':dict(LIMITS),'joint_speed_limit':SPEED,
                    'estop':self.estop,'reason':self.reason,'active':deepcopy(self.active),
                    'queue':list(deepcopy(self.queue)),'history':list(self.history),
                    'world':{'obstacles':deepcopy(self.obstacles),'targets':deepcopy(self.targets),
                             'camera':deepcopy(self.camera),'camera_fresh':bool(self.camera and now-self.camera['seen']<1.)},
                    'organs':self.organs.summary(),'memory_status':self.memory_status}


BODY=Body()


def parse_body_command(text):
    text=text.strip().casefold()
    if text in ('/body','/organs'):return ('status',{})
    # Exact, explicit movement requests only. Mentions/quoted text are not commands.
    match=re.fullmatch(r'(?:aura[, ]+)?(?:please )?(?:dance|dance karo|naacho)(?: for (\d+(?:\.\d+)?) seconds?)?[.!]?',text)
    if match:return 'dance',{'duration':float(match[1] or 8)}
    exact={'walk':('walk',{'x':0.,'z':1.}), 'walk karo':('walk',{'x':0.,'z':1.}),
           'wave':('wave',{}),'wave karo':('wave',{}),'stop':('stop',{}),'stop moving':('stop',{}),'ruk jao':('stop',{})}
    stripped=re.sub(r'^aura[, ]+','',text).rstrip('.!')
    if stripped in ('walk and dance','walk then dance','demo dikhao'):return ('demo',{})
    if stripped in exact:return exact[stripped]
    match=re.fullmatch(r'/body\s+(walk|dance|wave|look|point|stop|reset|home|demo|rest)(?:\s+(.*))?',text)
    if not match:
        if text.startswith('/body '):raise ValueError('Unknown body action. Use /body demo, dance, walk x z, wave, stop, reset, home or rest.')
        return None
    kind=match[1];rest=(match[2] or '').split()
    keys={'walk':['x','z'],'point':['x','z'],'look':['yaw','pitch'],'dance':['duration'],'wave':['duration']}.get(kind,[])
    if len(rest)>len(keys) or kind in ('walk','point') and len(rest)!=2:
        raise ValueError('Use /body walk x z, dance [seconds], wave [seconds], look [yaw pitch], point x z, stop, reset, home, demo or rest.')
    try:return kind,dict(zip(keys,[float(v) for v in rest]))
    except ValueError:raise ValueError('Use numbers for body command values.') from None


def command_reply(text):
    parsed=parse_body_command(text)
    if parsed is None:return None
    kind,params=parsed
    if kind=='status':
        state=BODY.snapshot()
        reply='Virtual body only. Open /body on this AURA server. Status: '+state['reason']+'. No biological organs or physical motors are connected.'
        if text.strip().casefold()=='/organs':
            reply+='\n'+'\n'.join(name+': '+data['function'] for name,data in state['organs']['systems'].items())
        return reply
    result=BODY.command(kind,params)
    return 'Virtual body: '+result['status']+'. '+('Task queued; completion is checked in the simulation, not the real world.' if result['status']=='queued' else 'No physical hardware action performed.')
