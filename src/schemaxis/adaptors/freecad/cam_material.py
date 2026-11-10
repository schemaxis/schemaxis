"""Independent posted-NC cutter replay against captured target and declared stock.

Flat, centre-cutting straight endmills only. Exact line capsules, vertical
cylinders and planar circular-arc sectors/end discs model programmed tool tips.
No producer Path, saved CAM shapes or CAM operation algorithm is used here.
"""
import hashlib
import json
import math
import os
from pathlib import Path
from schemaxis.artifacts import atomic_json
from schemaxis.errors import fail
from .cam_names import operation_names
from .cam_code import parse
from . import cam_sections as sections


def _disc(point,r):
    import FreeCAD as App,Part
    return Part.Face(Part.Wire([Part.makeCircle(r,App.Vector(*point))]))


def _capsule(a,b,r):
    import FreeCAD as App,Part
    a=App.Vector(*a);b=App.Vector(*b);delta=b-a
    if delta.Length<1e-8:return _disc([a.x,a.y,a.z],r)
    tangent=App.Vector(delta);tangent.normalize();normal=App.Vector(-tangent.y,tangent.x,0)*r;tangent*=r
    aa=a+normal;bb=b+normal;cc=b-normal;dd=a-normal
    return Part.Face(Part.Wire([Part.makeLine(aa,bb),Part.Arc(bb,b+tangent,cc).toShape(),Part.makeLine(cc,dd),Part.Arc(dd,a-tangent,aa).toShape()]))


def _arc_faces(motion,z,r):
    import FreeCAD as App,Part
    a=motion['from'];b=motion['to'];c=motion['centre'];radius=math.dist(a[:2],c);start=math.atan2(a[1]-c[1],a[0]-c[0]);end=math.atan2(b[1]-c[1],b[0]-c[0]);sign=1 if motion['code']==3 else -1
    span=(sign*(end-start))%(2*math.pi)
    full=a[:2]==b[:2]
    if full:span=2*math.pi
    elif span<=0:fail('UNSUPPORTED_TOOLPATH','Arc sweep is unresolved at floating-point precision')
    finish=start+sign*span;middle=(start+finish)/2;outer=radius+r;inner=max(0,radius-r)
    def point(rho,theta):return App.Vector(c[0]+rho*math.cos(theta),c[1]+rho*math.sin(theta),z)
    if full:
        face=_disc([*c,z],outer)
        if inner:face=face.cut(_disc([*c,z],inner))
        return [face]
    edges=[Part.Arc(point(outer,start),point(outer,middle),point(outer,finish)).toShape(),Part.makeLine(point(outer,finish),point(inner,finish))]
    if inner:edges.append(Part.Arc(point(inner,finish),point(inner,middle),point(inner,start)).toShape())
    edges.append(Part.makeLine(point(inner,start),point(outer,start)))
    sector=Part.Face(Part.Wire(edges))
    return [sector,_disc([a[0],a[1],z],r),_disc([b[0],b[1],z],r)]


def material(directory,output_directory=None):
    import FreeCAD as App,Part
    from .adaptor import close
    directory=Path(directory);output=Path(output_directory) if output_directory else directory;output.mkdir(parents=True,exist_ok=True);p=json.loads((directory/'plan.json').read_text())
    multiple=p.get('version')=='schemaxis.freecad.cam.plan/2';checked_native=None
    if multiple:
        from .cam_evidence2 import text
        program=text(directory/'program.ngc')
    else:program=(directory/'program.ngc').read_text()
    if multiple:
        from .cam_code2 import parse as parse2
        from .cam_state2 import verify as verify_state
        from .cam_cycles2 import validate
        replay=parse2(program,p['tools'],p['setup']['safe']);validate(p,replay)
        checked_native=verify_state(directory,p)
        tools={t['id']:t for t in p['tools']}
    else:
        replay=parse(program,p['tool'],p['setup']['safe'])
        from .cam_tool_native import verify as verify_tool
        verify_tool(directory,p)
    atomic_json(output/'replay.json',replay)
    source=Part.Shape();source.read(str(directory/('source.brep' if p['source']['format']=='FCStd' else 'source.step')))
    b=source.BoundBox
    if not source.isValid() or len(source.Solids)!=1 or not close(source.Volume,p['source']['volume']) or not close([b.XMin,b.XMax,b.YMin,b.YMax,b.ZMin,b.ZMax],p['source']['bounds']) or not close([source.Solids[0].CenterOfMass.x,source.Solids[0].CenterOfMass.y,source.Solids[0].CenterOfMass.z],p['source']['centreOfMass']):fail('EXPECTATION_FAILED','Independent replay source differs from declared solid geometry')
    source.translate(App.Vector(*[-v for v in p['origin']]));box=p['stockBounds'];stock=Part.makeBox(box[1]-box[0],box[3]-box[2],-box[4],App.Vector(box[0],box[2],box[4]));remaining=stock.copy();paths={};vertical={}
    for motion in ([] if multiple else replay['motions']):
        if motion['code']==0:continue
        a=motion['from'];b=motion['to'];z=min(a[2],b[2])
        if z>=0:continue
        if motion['code']==1 and all(abs(a[i]-b[i])<2e-6 for i in (0,1)):
            key=tuple(a[:2]);vertical[key]=min(z,vertical.get(key,z));continue
        key=(motion['code'] if motion['code'] in (2,3) else 1,tuple(a[:2]),tuple(b[:2]),tuple(motion.get('centre',[])))
        if key[0]==1:key=(1,*sorted((key[1],key[2])),())
        if key not in paths or z<paths[key][0]:paths[key]=(z,motion)
    if multiple:
        from .cam_tracks2 import tracks
        paths,vertical=tracks(replay,p['tools'])
    if len(paths)+len(vertical)>1000:fail('RESOURCE_LIMIT','Independent material replay exceeds 1000 distinct cutter tracks; use fewer passes or smaller jobs')
    # Read saved shapes as bounded geometry only, never restore a document or
    # its Python proxies. This independent process checks producer persistence
    # against the captured target and independently constructed stock.
    from .document_xml import Document,read_member
    from zipfile import ZipFile
    saved=Document(directory/'machining.FCStd');geometry={};saved_shapes={}
    with ZipFile(directory/'machining.FCStd') as archive:
        for identity,expected in (('Source',source),('Clone',source),('Stock',stock)):
            member=saved.properties[identity]['Shape'].find('Part').get('file');payload=read_member(archive,member,32*1024*1024);path=output/('saved-'+identity+'.brep');path.write_bytes(payload);shape=Part.Shape();shape.read(str(path));path.unlink()
            if not shape.isValid() or len(shape.Solids)!=1 or abs(shape.Volume-expected.Volume)>1e-5 or shape.cut(expected).Volume>1e-5 or expected.cut(shape).Volume>1e-5:fail('VERIFICATION_FAILED','Saved '+identity+' geometry differs from independent captured target or declared blank')
            placement=[shape.Placement.Base.x,shape.Placement.Base.y,shape.Placement.Base.z,*shape.Placement.Rotation.Q]
            saved_shapes[identity]=shape
            geometry[identity]={'member':member,'sha256':hashlib.sha256(payload).hexdigest(),'placement':placement}
    from .cam_native import face_at
    selected={}
    for spec in p['operations']:
        identity='Stock' if spec['operation']=='faceStock' else 'Clone'
        if spec['operation']=='drill':
            from .cam_holes_native import select
            edges=select(saved_shapes[identity],spec,tools[spec['tool']])
            selected[spec['id']]=[[identity,e] for e in edges]
            refs=saved.child(operation_names(p)[spec['id']],'Base','LinkSubList','App::PropertyLinkSubListGlobal')
            if [(r.get('obj'),r.get('sub')) for r in refs]!=[(identity,e) for e in edges]:
                fail('VERIFICATION_FAILED','Saved drill targets differ from every independently resolved source hole',spec['id'])
            continue
        point=[0,0,0] if identity=='Stock' else [spec['floor'][i]-p['origin'][i] for i in range(3)]
        selected[spec['id']]=[identity,face_at(saved_shapes[identity],point)]
        refs=saved.child(operation_names(p)[spec['id']],'Base','LinkSubList','App::PropertyLinkSubListGlobal')
        if [(r.get('obj'),r.get('sub')) for r in refs]!=[tuple(selected[spec['id']])]:fail('VERIFICATION_FAILED','Saved operation reference differs from independent geometric selection',spec['id'])
    radius=None if multiple else p['tool']['diameter']/2;count=0;slabs=[];pieces=[];residual_pieces=[];gouge_pieces=[];balance_error=0;target_volume=0;target_moment=[0,0,0]
    # Every admitted cutting move is horizontal or vertical. The cutting edge
    # spans the complete blank. Thus its exact occupancy changes only at a
    # posted tip depth. Splitting there gives non-overlapping constant-XY slabs;
    # this is continuous material coverage, without path/depth sampling.
    levels=sorted(set([box[4],0]+[z for z,m in paths.values()]+list(vertical.values())+sections.levels(source)))
    if levels[0]<box[4]-1e-6:fail('UNSUPPORTED_TOOLPATH','Cutter travels below the declared clamping base')
    if len(levels)>128:fail('RESOURCE_LIMIT','Independent replay exceeds 128 distinct tip depths')
    empty=Part.makeBox(1,1,1).cut(Part.makeBox(1,1,1))
    for bottom,top in zip(levels,levels[1:]):
        if top-bottom<1e-9:
            balance_error+=(box[1]-box[0])*(box[3]-box[2])*(top-bottom);continue
        face=Part.Face(Part.makePolygon([App.Vector(box[0],box[2],bottom),App.Vector(box[1],box[2],bottom),App.Vector(box[1],box[3],bottom),App.Vector(box[0],box[3],bottom),App.Vector(box[0],box[2],bottom)]))
        cutters=[]
        for z,motion in paths.values():
            if z>bottom:continue
            current_radius=tools[motion['tool']]['diameter']/2 if multiple else radius
            if motion['code']==1:cutters.append(_capsule([*motion['from'][:2],bottom],[*motion['to'][:2],bottom],current_radius))
            else:cutters.extend(_arc_faces(motion,bottom,current_radius))
        if multiple:cutters.extend(_disc([*key[1:],bottom],tools[key[0]]['diameter']/2) for key,z in vertical.items() if z<=bottom)
        else:cutters.extend(_disc([*xy,bottom],radius) for xy,z in vertical.items() if z<=bottom)
        for cutter in cutters:
            from schemaxis.dispatch import remaining_timeout
            remaining_timeout()
            if not cutter.isValid() or cutter.Area<=0:fail('MATERIAL_REPLAY_FAILED','Invalid continuous planar cutter footprint')
            try:
                previous=face.Area;overlap=face.common(cutter).Area;candidate=face.cut(cutter).removeSplitter();removed=previous-candidate.Area
                balance_error+=abs(removed-overlap)*(top-bottom)
                if not all(math.isfinite(value) for value in (previous,overlap,removed,candidate.Area)) or not candidate.isValid() or abs(removed-overlap)>1e-4 or removed < -1e-6 or removed>cutter.Area+1e-5:fail('MATERIAL_REPLAY_FAILED','Planar cutter subtraction violates independent area balance',slab=len(slabs),track=count,removed=removed,intersection=overlap)
                face=candidate
            except ValueError:fail('MATERIAL_REPLAY_FAILED','Planar cutter subtraction failed',slab=len(slabs),track=count)
            count+=1
        area=face.Area
        if area>1e-10:
            piece=face.extrude(App.Vector(0,0,top-bottom))
            balance_error+=abs(piece.Volume-area*(top-bottom))
            if not piece.isValid() or abs(piece.Volume-area*(top-bottom))>1e-3:fail('MATERIAL_REPLAY_FAILED','Extruded slab volume differs from continuous planar coverage',actual=piece.Volume,expected=area*(top-bottom),slab=len(slabs))
            pieces.append(piece)
        midpoint=(bottom+top)/2;target=sections.face(source,midpoint,empty);target.translate(App.Vector(0,0,bottom-midpoint))
        target_volume+=target.Area*(top-bottom)
        for region in target.Faces:
            for i,value in enumerate((region.CenterOfMass.x,region.CenterOfMass.y,midpoint)):target_moment[i]+=region.Area*(top-bottom)*value
        residual_face,gouge_face,margin=sections.difference(face,target,top-bottom);balance_error+=margin
        for current,collection in ((residual_face,residual_pieces),(gouge_face,gouge_pieces)):
            if current.Area>1e-10:
                solid=current.extrude(App.Vector(0,0,top-bottom));balance_error+=abs(solid.Volume-current.Area*(top-bottom))
                if not solid.isValid():fail('MATERIAL_REPLAY_FAILED','Invalid difference-layer extrusion')
                collection.append(solid)
        slabs.append({'bottom':bottom,'top':top,'remainingArea':area,'targetArea':target.Area,'residualArea':residual_face.Area,'gougeArea':gouge_face.Area,'footprints':len(cutters)})
    remaining=Part.makeCompound(pieces)
    if not remaining.isValid():fail('MATERIAL_REPLAY_FAILED','Layered replay did not retain valid stock geometry')
    residual=Part.makeCompound(residual_pieces) if residual_pieces else empty.copy();gouge=Part.makeCompound(gouge_pieces) if gouge_pieces else empty.copy()
    target_com=[v/target_volume for v in target_moment]
    if not all(math.isfinite(value) for value in [target_volume,*target_com,remaining.Volume,residual.Volume,gouge.Volume]) or abs(target_volume-source.Volume)>1e-5 or not close(target_com,[source.Solids[0].CenterOfMass.x,source.Solids[0].CenterOfMass.y,source.Solids[0].CenterOfMass.z]):fail('MATERIAL_REPLAY_FAILED','Independent CAD cross-section integration differs from source volume or centre of mass',integratedVolume=target_volume,sourceVolume=source.Volume)
    if not residual.isValid() or not gouge.isValid() or not math.isfinite(balance_error):fail('MATERIAL_REPLAY_FAILED','Independent replay has invalid or nonfinite geometry/balance evidence',balanceErrorVolume=balance_error)
    native_sha=hashlib.sha256((directory/'machining.FCStd').read_bytes()).hexdigest()
    if multiple:
        from schemaxis.artifacts import file_digest
        if file_digest(directory/'machining.FCStd')!=checked_native or text(directory/'program.ngc')!=program:
            fail('VERIFICATION_FAILED','CAM2 native/program bytes changed during independent material replay')
        from .cam_state2 import admit
        admit(directory,p)
    record={'pid':os.getpid(),'runtime':'.'.join(App.Version()[:3]),'method':'continuous-multitool-flat-endmill-sections' if multiple else 'continuous-flat-endmill-sections','integratedTargetVolume':target_volume,'integratedTargetCentreOfMass':target_com,'slabs':slabs,'balanceErrorVolume':balance_error,'assessedResidualVolume':max(0,residual.Volume)+balance_error,'assessedGougeVolume':max(0,gouge.Volume)+balance_error,'targetVolume':source.Volume,'stockVolume':stock.Volume,'remainingVolume':remaining.Volume,'removedVolume':stock.Volume-remaining.Volume,'residualVolume':max(0,residual.Volume),'gougeVolume':max(0,gouge.Volume),'sweeps':count,'tracks':len(paths)+len(vertical),'motions':len(replay['motions']),'programSha256':hashlib.sha256(program.encode()).hexdigest(),'nativeSha256':native_sha,'geometry':geometry,'selectedFaces':selected,'verified':False}
    remaining.exportBrep(str(output/'remaining.brep'));residual.exportBrep(str(output/'residual.brep'));gouge.exportBrep(str(output/'gouge.brep'))
    record['publications']={}
    for filename,expected in (('remaining.brep',remaining),('residual.brep',residual),('gouge.brep',gouge)):
        path=directory/filename
        if path.is_symlink() or not path.is_file() or path.stat().st_size>32*1024*1024:fail('VERIFICATION_FAILED','Missing, linked or oversized replay geometry',filename)
        payload=path.read_bytes()
        if output_directory:
            regenerated=(output/filename).read_bytes()
            if regenerated!=payload:fail('VERIFICATION_FAILED','Published replay geometry differs from fresh deterministic continuous cutter replay',filename,retainedSha256=hashlib.sha256(payload).hexdigest(),freshSha256=hashlib.sha256(regenerated).hexdigest())
        record['publications'][filename]={'sha256':hashlib.sha256(payload).hexdigest(),'volume':expected.Volume}
    record['verified']=record['assessedResidualVolume']<=p['quality']['residualVolume'] and record['assessedGougeVolume']<=p['quality']['gougeVolume'];atomic_json(output/'material.json',record)
    if record['assessedGougeVolume']>p['quality']['gougeVolume']:fail('TARGET_GOUGED','Posted cutter sweeps remove desired material; inspect gouge.brep and change tool, target selection or operation intent',gougeVolume=record['gougeVolume'])
    if record['assessedResidualVolume']>p['quality']['residualVolume']:fail('UNFINISHED_MATERIAL','Posted cutter sweeps leave excess stock; inspect residual.brep, choose a reachable cavity radius, smaller cutter or missing operation',residualVolume=record['residualVolume'])
