"""Independent finite multi-tool LinuxCNC reader for compiled CAM2 programs.

Controller policy: unremapped LinuxCNC2.9.4, millimetres, default canned cycles.
G83/G73 backoff is .010 inch (.254 mm). This is programmed motion, not a claim
about a machine's tool table, acceleration, spindle or measured cycle duration.
No native CAM classes, producer path interpretation or authored code is used.
"""
import math
import re
from schemaxis.errors import fail
from .cam_code import WORD,POSTED_ARC_RADIUS_TOLERANCE
from .cam_drilling import CYCLES,DIALECT,RAPID_BACKOFF

GROUPS={0:'motion',1:'motion',2:'motion',3:'motion',80:'motion',
        **{c:'motion' for c in CYCLES.values()},17:'plane',21:'units',
        90:'distance',91.1:'arc',94:'feed',40:'cutter',43:'length',49:'length',
        54:'fixture',61:'path',92.1:'temporary',98:'return',99:'return'}


def _words(original,index):
    line=re.sub(r'\([^()]*\)','',original).strip()
    words=WORD.findall(line)
    if WORD.sub('',line).strip():fail('INVALID_NC','Unsupported NC syntax',str(index))
    values={};gs=[];ms=[];groups=set()
    for letter,raw in words:
        value=float(raw)
        if not math.isfinite(value):fail('INVALID_NC','Non-finite NC word',str(index))
        if letter in ('G','M'):
            if letter=='G':group=GROUPS.get(value)
            else:group={3:'spindle',5:'spindle',6:'tool',2:'end',30:'end'}.get(value)
            if group is None:fail('INVALID_NC','Unsupported NC mode or machine command',str(index),nativeCode=value)
            group=letter+group
            if group in groups:fail('INVALID_NC','Conflicting or repeated NC modal-group codes',str(index))
            groups.add(group);(gs if letter=='G' else ms).append(value)
        elif letter in values:fail('INVALID_NC','Repeated NC word',str(index))
        else:values[letter]=value
    if set(values)-set('XYZIJFSTHRPQ'):fail('INVALID_NC','Unsupported NC word',str(index))
    # Typed source coordinates are bounded by +/-100000 mm; centred work
    # coordinates and IJ displacements need at most twice that range. Refuse
    # oversized finite words before derived distances or native geometry.
    if any(abs(values[k])>200000 for k in set(values)&set('XYZIJR')):
        fail('INVALID_NC','NC coordinates exceed the compiled geometric range',str(index))
    return values,gs,ms


def parse(text,tools,safe,*,arc_radius_tolerance=POSTED_ARC_RADIUS_TOLERANCE,ordered=False):
    if type(ordered) is not bool:raise ValueError('Ordered replay mode must be boolean')
    if not isinstance(text,str) or len(text)>4*1024*1024:fail('INVALID_NC','NC program exceeds the bounded text contract')
    if (not isinstance(tools,list) or not 1<=len(tools)<=8
            or any(type(t.get('number')) is not int or t['number']!=i+1 for i,t in enumerate(tools))):
        fail('INVALID_NC','Replay requires the compiled contiguous named-tool table')
    by_number={t['number']:t for t in tools}
    if len({t['id'] for t in tools})!=len(tools):fail('INVALID_NC','Replay tool identities must be unique')
    position=[None,None,None];modal=None;feed=None;selected=None;offset=None;speed=None
    spindle=None;ended=False;modes=set();resets=set();return_mode=None;initial=None
    motions=[];cycles=[];changes=[];events=[]

    def bad(message,index,code='INVALID_NC'):fail(code,message,str(index))
    def emit(code,end,index,*,cycle=None,centre=None):
        nonlocal position
        if None not in position and None not in end:
            item={'code':code,'from':list(position),'to':list(end),'feed':feed if code else None,
                  'tool':by_number[selected]['id'] if selected is not None else None}
            if cycle is not None:item['cycle']=cycle
            if centre is not None:item['centre']=centre
            motions.append(item)
            if len(motions)>10000:bad('Expanded NC motion count exceeds 10000',index,'RESOURCE_LIMIT')
            if ordered:events.append({'motion':len(motions)-1})
        elif ordered and None not in end:
            if selected is None:bad('First known programmed pose needs its declared active tool',index)
            events.append({'positioned':{'tool':by_number[selected]['id'],'position':list(end)}})
        position=list(end)
    def ready(index):
        if modes!={17,21,54,90,91.1,94} or resets!={40,61,80,92.1}:
            bad('Motion requires explicit mm, absolute XYZ, XY/IJ, G54, feed/minute and cancellation modes',index)
    def cutting(index):
        if (selected is None or offset!=selected or speed is None or not spindle
                or feed is None or None in position):
            bad('Cutting requires known coordinates, selected tool, matching length register, spindle and feed',index)

    for index,original in enumerate(text.splitlines(),1):
        if index%128==0:
            from schemaxis.dispatch import remaining_timeout
            remaining_timeout()
        values,gs,ms=_words(original,index)
        if not values and not gs and not ms:continue
        if ended:bad('Executable content follows program end',index)
        motion_codes=[g for g in gs if GROUPS[g]=='motion']
        explicit=motion_codes[0] if motion_codes else None
        if ('T' in values)!=(6 in ms):bad('Tool selection requires one explicit stopped-spindle M6 T block',index)
        if ('H' in values)!=(43 in gs):bad('Length register must accompany G43',index)
        if 6 in ms:
            if (gs or set(values)!={'T'} or ms!=[6] or spindle is not False
                    or values['T'] not in by_number or int(values['T'])!=values['T']):
                bad('Tool change requires a declared integral T number and a separate spindle stop',index)
            if modal in CYCLES.values():bad('Cancel the drilling cycle before changing tools',index)
            if selected is not None and (position[2] is None or position[2]<safe-1e-6):
                bad('Tool changes require a known safe traverse plane',index,'UNSAFE_RAPID')
            selected=int(values['T']);offset=None;speed=None;feed=None;modal=None;initial=None;return_mode=None
            changes.append({'number':selected,'tool':by_number[selected]['id']})
            if ordered:events.append({'toolChange':{'tool':by_number[selected]['id'],
                                                   'position':list(position) if None not in position else None}})
            continue
        for g in gs:
            if GROUPS[g]=='motion':
                modal=None if g==80 else int(g)
                if g not in CYCLES.values():initial=None
                if g==80:resets.add(80)
            elif g in (17,21,54,90,91.1,94):modes.add(g)
            elif g in (40,61,92.1):resets.add(g)
            elif g==43:
                if selected is None or values['H']!=selected:bad('Length register differs from the selected tool',index)
                offset=selected
            elif g==49:offset=None
            elif g in (98,99):return_mode=int(g)
        if 'S' in values:
            if selected is None or abs(values['S']-by_number[selected]['rpm'])>1e-6:
                bad('Posted spindle speed differs from the selected tool cutting data',index)
            speed=values['S']
        for m in ms:
            if m==3:
                if selected is None or speed is None:bad('Spindle start requires selected tool and explicit speed',index)
                spindle=True
            elif m==5:spindle=False
            else:
                if spindle is not False or set(values) or gs or len(ms)!=1:bad('Program end requires a separate explicit spindle stop',index)
                if modal in CYCLES.values():bad('Cancel the drilling cycle before program end',index)
                ended=True
        if 'F' in values:
            feed=values['F']
            if feed<=0:bad('Cutting feed must be positive',index)
        is_cycle=modal in CYCLES.values()
        if set(values)&set('RPQ') and not is_cycle:bad('Cycle parameters outside an explicit cycle',index)
        if not set(values)&set('XYZIJRPQ'):continue
        ready(index)
        if modal is None:bad('Coordinates require an explicit admitted motion mode',index)
        if is_cycle:
            cutting(index)
            if explicit!=modal or return_mode is None or set(values)-set('XYZFRPQ'):
                bad('Every hole requires an explicit cycle and return mode; sticky cycles are not admitted',index)
            required=set('XYZRF')|({'P'} if modal==82 else {'Q'} if modal in (73,83) else set())
            if set(values)!=required:bad('Cycle words differ from the complete finite drilling form',index)
            if abs(feed-by_number[selected]['plunge'])>6e-5:bad('Drilling feed differs from selected tool plunge data',index)
            r=values['R'];bottom=values['Z']
            if r<safe-1e-6 or position[2]<safe-1e-6 or bottom>=r:
                bad('Cycle positioning and R plane must be safe, with bottom below R',index,'UNSAFE_RAPID')
            if modal==82 and not .001<=values['P']<=3600:bad('Dwell must be positive bounded seconds',index)
            if modal in (73,83) and not .001<=values['Q']<=1000:bad('Peck must be positive bounded millimetres',index)
            if initial is None:initial=position[2]
            clear=r if return_mode==99 else max(initial,r)
            identity=len(cycles)
            cycle={'code':modal,'tool':by_number[selected]['id'],'centre':[values['X'],values['Y']],
                   'initial':initial,'retract':r,'bottom':bottom,'return':return_mode,'returnZ':clear,
                   'dwell':values.get('P',0),'peck':values.get('Q',0)}
            cycles.append(cycle)
            if len(cycles)>4096:bad('NC cycle count exceeds 4096',index,'RESOURCE_LIMIT')
            # Default LinuxCNC cycle: first raise to R if needed, position XY
            # at the current safe plane, then descend vertically to R.
            if position[2]<r:emit(0,[*position[:2],r],index,cycle=identity)
            emit(0,[values['X'],values['Y'],position[2]],index,cycle=identity)
            if position[2]>r:emit(0,[*position[:2],r],index,cycle=identity)
            if modal in (73,83):
                q=values['Q'];count=math.ceil((r-bottom)/q)
                if count>1000:bad('One drilling cycle exceeds 1000 pecks',index,'RESOURCE_LIMIT')
                for n in range(1,count):
                    depth=r-n*q
                    if depth<=bottom:break
                    emit(1,[*position[:2],depth],index,cycle=identity)
                    emit(0,[*position[:2],r if modal==83 else depth+RAPID_BACKOFF],index,cycle=identity)
                    if modal==83:emit(0,[*position[:2],depth+RAPID_BACKOFF],index,cycle=identity)
            emit(1,[*position[:2],bottom],index,cycle=identity)
            if modal==85:emit(1,[*position[:2],r],index,cycle=identity)
            emit(0,[*position[:2],clear],index,cycle=identity)
            continue
        if set(values)&set('RPQ'):bad('Cycle parameters on ordinary motion',index)
        end=[values.get(k,position[i]) for i,k in enumerate('XYZ')]
        if modal==0:
            if end[2] is None or position[2] is None and end[2]<safe-1e-6:
                bad('Initial positioning must establish clearance Z',index,'UNSAFE_RAPID')
            if (any(k in values for k in 'XY') and (position[2] is None or min(position[2],end[2])<safe-1e-6)
                    or position[2] is not None and end[2]<position[2]-1e-6 and end[2]<safe-1e-6):
                # Only ordered physical replay can admit lower known-pose
                # rapids. Every emitted Q_rapid and complete H sweep must then
                # pass the actual prefix-stock checks; parsing grants no cut
                # credit or clearance success. Unknown positioning must never
                # disappear before the first complete-pose event.
                if not ordered or None in position or None in end:
                    bad('Ordinary XY rapid and descent require the declared safe plane',index,'UNSAFE_RAPID')
        else:
            cutting(index)
            if None in end:bad('Cutting coordinates are incomplete',index)
            vertical=modal==1 and all(abs(end[i]-position[i])<2e-6 for i in (0,1))
            expected=by_number[selected]['plunge' if vertical else 'feed']
            if abs(feed-expected)>6e-5:bad('Posted feed differs from selected tool cutting data',index)
        centre=None
        if modal in (2,3):
            if not all(k in values for k in 'IJ') or abs(position[2]-end[2])>2e-6:
                bad('Only planar IJ-centre arcs are supported',index,'UNSUPPORTED_TOOLPATH')
            centre=[position[0]+values['I'],position[1]+values['J']];radius=math.dist(position[:2],centre)
            if radius<1e-6 or abs(math.dist(end[:2],centre)-radius)>arc_radius_tolerance:
                bad('Posted arc endpoints do not share a radius',index)
            if position[:2]!=end[:2] and math.dist(position[:2],end[:2])<=1e-6:
                bad('Near-coincident arc endpoints cannot distinguish a tiny arc from a full circle',index,'UNSUPPORTED_TOOLPATH')
        elif set(values)&set('IJ'):bad('Arc centre on linear motion',index)
        if modal and not (all(abs(position[i]-end[i])<2e-6 for i in (0,1)) or abs(position[2]-end[2])<2e-6):
            bad('Ramped cutting needs an independently qualified cutter sweep',index,'UNSUPPORTED_TOOLPATH')
        emit(modal,end,index,centre=centre)
    if not ended or not motions or spindle:fail('INVALID_NC','NC program must contain motion, stop the spindle and end explicitly')
    result={'units':'mm','fixture':'G54','absolute':True,'dialect':DIALECT,
            'toolChanges':changes,'cycles':cycles,'motions':motions}
    if ordered:result['events']=events
    return result
