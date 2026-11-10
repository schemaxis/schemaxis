"""Finite, independent LinuxCNC milling-program reader; no native CAM imports."""
import math
import re
from schemaxis.errors import fail

WORD=re.compile(r'([A-Z])([-+]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+))')
POSTED_ARC_RADIUS_TOLERANCE=1e-7
PERSISTED_ARC_RADIUS_TOLERANCE=2e-6


def parse(text,tool,safe=0,*,arc_radius_tolerance=POSTED_ARC_RADIUS_TOLERANCE):
    if not isinstance(text,str) or len(text)>4*1024*1024:fail('INVALID_NC','NC program exceeds the bounded text contract')
    position=[None,None,None];modal=None;feed=None;spindle=None;selected=None;units=False;absolute=False;plane=False;fixture=False;ended=False;offset=False;speed_set=False;arc_incremental=False;per_minute=False;resets=set();motions=[]
    for index,original in enumerate(text.splitlines(),1):
        line=re.sub(r'\([^()]*\)','',original).strip()
        if not line:continue
        if ended:fail('INVALID_NC','Executable content follows program end',str(index))
        words=WORD.findall(line)
        if WORD.sub('',line).strip():fail('INVALID_NC','Unsupported NC syntax',str(index))
        values={};gs=[];ms=[]
        for letter,raw in words:
            value=float(raw)
            if not math.isfinite(value):fail('INVALID_NC','Non-finite NC word',str(index))
            if letter=='G':gs.append(value)
            elif letter=='M':ms.append(value)
            elif letter in values:fail('INVALID_NC','Repeated NC word',str(index))
            else:values[letter]=value
        if set(values)-set('XYZIJFSTH'):fail('INVALID_NC','Unsupported NC word',str(index))
        groups={0:'motion',1:'motion',2:'motion',3:'motion',80:'motion',17:'plane',21:'units',90:'distance',91.1:'arc',94:'feed',40:'cutter',43:'length',49:'length',54:'fixture',61:'path',92.1:'temporary'}
        seen=set()
        for g in gs:
            group=groups.get(g)
            if group in seen:fail('INVALID_NC','Conflicting or repeated NC modal-group codes',str(index))
            if group is not None:seen.add(group)
        seen=set()
        for m in ms:
            group='spindle' if m in (3,5) else 'end' if m in (2,30) else 'tool' if m==6 else None
            if group in seen:fail('INVALID_NC','Conflicting or repeated machine-command group',str(index))
            if group is not None:seen.add(group)
        for g in gs:
            if g in (0,1,2,3):modal=int(g)
            elif g==21:units=True
            elif g==90:absolute=True
            elif g==17:plane=True
            elif g==54:fixture=True
            elif g==91.1:arc_incremental=True
            elif g==94:per_minute=True
            elif g in (40,61,80,92.1):
                resets.add(g)
                if g==80:modal=None
            elif g==43:
                if values.get('H')!=1:fail('INVALID_NC','Tool compensation requires declared H1 register',str(index))
                offset=True
            elif g==49:offset=False
            elif g not in (40,43,49,80,91.1):fail('INVALID_NC','Unsupported unit, frame, cycle or motion mode',str(index),nativeCode=g)
        for m in ms:
            if m==3:spindle=True
            elif m==5:spindle=False
            elif m==6:
                if spindle is not False:fail('INVALID_NC','Tool change requires an explicit spindle stop',str(index))
                if values.get('T')!=1:fail('INVALID_NC','Only the declared tool number is permitted',str(index))
                selected=1
            elif m in (2,30):ended=True
            else:fail('INVALID_NC','Unsupported machine command',str(index),nativeCode=m)
        if 'T' in values and values['T']!=1:fail('INVALID_NC','Undeclared tool',str(index))
        if 'H' in values and values['H']!=1:fail('INVALID_NC','Tool-length register differs from the declared tool',str(index))
        if 'S' in values:speed_set=True
        if 'S' in values and abs(values['S']-tool['rpm'])>1e-6:fail('INVALID_NC','Posted spindle speed differs from tool cutting data',str(index))
        if 'F' in values:
            feed=values['F']
            if feed<=0:fail('INVALID_NC','Cutting feed must be positive',str(index))
        if not any(k in values for k in 'XYZ') and modal not in (2,3):continue
        if not any(k in values for k in 'XYZIJ'):continue
        if not (units and absolute and plane and fixture) or modal is None:fail('INVALID_NC','Motion requires explicit mm, absolute XYZ, XY plane and G54 frame',str(index))
        if resets!={40,61,80,92.1}:fail('INVALID_NC','Motion requires explicit cutter/cycle cancellation, exact path mode and cleared temporary offsets',str(index))
        end=[values.get(k,position[i]) for i,k in enumerate('XYZ')]
        if modal==0:
            if end[2] is None:fail('INVALID_NC','Initial positioning must establish clearance Z',str(index))
            if position[2] is None and end[2]<safe-1e-6:fail('UNSAFE_RAPID','Initial positioning must establish the declared safe plane',str(index))
            horizontal=any(k in values for k in 'XY')
            downward=position[2] is not None and end[2]<position[2]-1e-6
            if horizontal and (position[2] is None or min(position[2],end[2])<safe-1e-6):fail('UNSAFE_RAPID','XY rapid requires known start and end above the declared safe plane',str(index))
            if downward and end[2]<safe-1e-6:fail('UNSAFE_RAPID','Rapid descent is below the declared safe plane',str(index))
        else:
            if None in position or None in end or not spindle or selected!=1 or feed is None or not offset or not speed_set or not per_minute:fail('INVALID_NC','Cutting needs known coordinates, running spindle, selected tool and feed',str(index))
            vertical=modal==1 and all(abs(end[i]-position[i])<2e-6 for i in (0,1))
            expected=tool['plunge'] if vertical else tool['feed']
            if abs(feed-expected)>6e-5:fail('INVALID_NC','Posted feed differs from the declared cutting data',str(index))
        if None not in position and None not in end:
            motion={'code':modal,'from':position,'to':end,'feed':feed if modal else None}
            if modal in (2,3):
                if not arc_incremental or not all(k in values for k in 'IJ') or abs(position[2]-end[2])>2e-6:fail('UNSUPPORTED_TOOLPATH','Only planar IJ-centre arcs are supported',str(index))
                centre=[position[0]+values['I'],position[1]+values['J']];r=math.dist(position[:2],centre)
                if r<1e-6 or abs(math.dist(end[:2],centre)-r)>arc_radius_tolerance:fail('INVALID_NC','Posted arc endpoints do not share a radius',str(index))
                if position[:2]!=end[:2] and math.dist(position[:2],end[:2])<=1e-6:fail('UNSUPPORTED_TOOLPATH','Near-coincident arc endpoints cannot distinguish a tiny arc from a complete circle at the native geometric scale',str(index))
                motion['centre']=centre
            elif 'I' in values or 'J' in values:fail('INVALID_NC','Arc centre on linear motion',str(index))
            if modal and not (all(abs(position[i]-end[i])<2e-6 for i in (0,1)) or abs(position[2]-end[2])<2e-6):fail('UNSUPPORTED_TOOLPATH','Ramped cutting needs an independently qualified cutter sweep',str(index))
            motions.append(motion)
        position=end
        if len(motions)>10000:fail('RESOURCE_LIMIT','NC motion count exceeds 10000')
    if not ended or not motions or spindle:fail('INVALID_NC','NC program must contain motion, stop the spindle and end explicitly')
    return {'units':'mm','fixture':'G54','absolute':True,'motions':motions}
