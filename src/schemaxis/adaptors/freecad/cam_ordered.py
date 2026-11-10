"""Host-only aggregate admission for actual ordered CAM stock motions."""
import math
from schemaxis.dispatch import remaining_timeout
from schemaxis.errors import fail
from .cam_mixed_budget import preflight
from .cam_pointed import ENDMILL_SHANK_OVERLAP


def reusable_vertical_rapid(motion,last_feed,top):
    """A connected previous feed union encloses this IN-STOCK cutting part.

    Same physical tool and exact fixed XY; no near-point merge. Cone radius is
    monotone above its apex, so raising the minimum tip stays in the old sweep.
    An upper extension is permitted only when the old maximum TIP is already
    above original stock. This never grants removal or guarded-part clearance.
    """
    if last_feed is None or motion['code']!=0 or last_feed['code']!=1:return False
    if (motion['tool']!=last_feed['tool'] or motion['from'][:2]!=motion['to'][:2]
            or last_feed['from'][:2]!=last_feed['to'][:2]
            or motion['from'][:2]!=last_feed['from'][:2]):return False
    lo,hi=sorted((motion['from'][2],motion['to'][2]))
    old_lo,old_hi=sorted((last_feed['from'][2],last_feed['to'][2]))
    return lo>=old_lo and (hi<=old_hi or old_hi>=top)


def cleared_column(motion,previous):
    """Exact connected TIP-interval union; the caller unions actual C bodies.

    No disconnected interval, changed tool or nearby XY can expand the domain.
    The native body is a union of already removed feed sweeps, never a sweep
    invented between disconnected visits. Return/assignment clears it outside
    this helper. This is solely a zero-credit rapid allocation optimisation.
    """
    lo,hi=sorted((motion['from'][2],motion['to'][2]))
    if (previous is None or motion['tool']!=previous['tool']
            or motion['from'][:2]!=motion['to'][:2]
            or motion['from'][:2]!=previous['from'][:2]):return motion,'replace'
    old_lo,old_hi=sorted((previous['from'][2],previous['to'][2]))
    if hi<old_lo or old_hi<lo:return motion,'replace'
    if old_lo<=lo and hi<=old_hi:return previous,'keep'
    return {'code':1,'tool':motion['tool'],'from':[*motion['from'][:2],max(hi,old_hi)],
            'to':[*motion['from'][:2],min(lo,old_lo)]},'merge'


def preflight_ordered(prepared,replay):
    """Count ALL expanded movements and transitions before native allocation.

    Primitive/interaction estimates reject oversized aggregate work up front.
    Result topology and cumulative actual operand face products are separately
    checked BEFORE EVERY kernel call; estimates never authorise exceeding them.
    """
    tools={t['id']:t for t in prepared['tools']};policy=prepared['setup']['toolClearance']
    if policy.get('kind')!='evolvingStock':raise ValueError('Expected evolving-stock clearance policy')
    gap=policy['minimumSeparation'];top=prepared['stockBounds'][5]
    events=replay.get('events')
    if not isinstance(events,list) or len(events)>20000:
        fail('RESOURCE_LIMIT','Ordered stock needs a bounded complete transition/motion inventory')
    pieces=faces=edges=calls=cut_faces=0;expected=0;changes=[];active=None;position=None;last_feed=None
    def add(n,planar=False):
        nonlocal pieces,faces,edges
        pieces+=n;faces+=n*(12 if planar else 3);edges+=n*(24 if planar else 6)
    # Complete fresh actual-bit partition/cutting subset and holder enclosure.
    for tool in tools.values():
        holders=len(tool.get('holder',{}).get('steps',[]));add(6+holders)
        calls+=12+2*holders
    for event in events:
        remaining_timeout()
        if not isinstance(event,dict) or len(event)!=1:
            fail('VERIFICATION_FAILED','Ordered stock event is not one finite transition or motion')
        if 'motion' in event:
            index=event['motion']
            if type(index) is not int or index!=expected or index>=len(replay['motions']):
                fail('VERIFICATION_FAILED','Ordered stock motion inventory is incomplete or reordered')
            expected+=1;motion=replay['motions'][index]
            if active!=motion['tool'] or position!=motion['from']:
                fail('VERIFICATION_FAILED','Ordered motion does not follow the active tool and known pose')
            position=motion['to'];code=motion['code']
            if type(code) is not int or code not in (0,1,2,3):
                fail('UNSUPPORTED_TOOLPATH','Ordered stock motion code is outside its finite sweep domain')
        elif 'toolChange' in event:
            last_feed=None #no previous-tool mask survives M6, even a return
            item=event['toolChange'];active=item['tool'];changes.append(active)
            if item['position']!=position:
                fail('VERIFICATION_FAILED','Tool transition loses the current programmed pose')
            if position is None:continue
            motion={'code':0,'tool':active,'from':position,'to':position};code=0
        elif 'positioned' in event:
            item=event['positioned']
            if position is not None or item['tool']!=active:
                fail('VERIFICATION_FAILED','First known programmed pose loses its active tool')
            position=item['position'];motion={'code':0,'tool':active,'from':position,'to':position};code=0
        else:fail('VERIFICATION_FAILED','Unknown ordered stock event')
        if active not in tools or not isinstance(position,list) or len(position)!=3 or any(
                type(v) not in (int,float) or not math.isfinite(v) for v in position):
            fail('VERIFICATION_FAILED','Ordered stock needs a complete declared tool and finite known pose')
        tool=tools[active];end=tool['cuttingReach'] if tool['kind']=='drill' else tool['cuttingLength']-ENDMILL_SHANK_OVERLAP
        low=min(motion['from'][2],motion['to'][2]);arc=code in (2,3)
        regions=1 if not arc or motion['from'][:2]==motion['to'][:2] else 3
        intersects_plane=math.nextafter(low,-math.inf)<math.nextafter(top,math.inf)
        if intersects_plane:
            if code==0 and reusable_vertical_rapid(motion,last_feed,top):
                calls+=1 #actual prefix common check remains; no new primitive
            else:
                n=2 if tool['kind']=='drill' and motion['from'][:2]==motion['to'][:2] else regions
                add(n,arc or motion['from'][:2]!=motion['to'][:2]);calls+=2 if n==2 and tool['kind']=='drill' else int(arc)
                if code==0:calls+=regions
                else:calls+=2*regions;cut_faces+=3*n if not arc else 12*n
        intervals=[end,*[s['start'] for s in tool.get('holder',{}).get('steps',[])]]
        checked=sum(math.nextafter(low+z,-math.inf)<math.nextafter(top+gap,math.inf) for z in intervals)
        add(checked*regions,arc or motion['from'][:2]!=motion['to'][:2]);calls+=2*checked*regions
        if (checked and code==1 and motion['from'][:2]==motion['to'][:2]
                and motion['to'][2]<motion['from'][2]):
            add(1);calls+=4 #contained finite temporal credit + one prefix copy
        if code:
            if intersects_plane and code==1 and motion['from'][:2]==motion['to'][:2]:
                last_feed,action=cleared_column(motion,last_feed)
                if action=='merge':calls+=2 #union of actually removed C bodies
            else:last_feed=None
    if expected!=len(replay['motions']) or changes!=[c['tool'] for c in replay['toolChanges']]:
        fail('VERIFICATION_FAILED','Ordered stock is missing a motion or active-tool transition')
    calls+=6 #final residual/gouge and conservation comparisons
    estimate=2*(6+cut_faces)**2+2*faces*(6+cut_faces)
    return preflight(pieces=pieces,faces=faces,edges=edges,booleans=calls,facePairs=estimate)
