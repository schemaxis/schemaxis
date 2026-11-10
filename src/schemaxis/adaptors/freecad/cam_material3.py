"""Separate finite physical-solid replay for the opt-in pointed/envelope family.

Posted motion, captured source and fresh whole native reconstruction are the
inputs. Editable tool/shape/material receipts never establish authority. This
module is internal until the public family qualification is complete.
"""
import hashlib
import math
import os
import tempfile
from pathlib import Path
from schemaxis.artifacts import atomic_json,file_digest
from schemaxis.dispatch import remaining_timeout
from schemaxis.errors import fail
from .cam_evidence2 import read,binary
from .cam_mixed_budget import preflight
from .cam_mixed_geometry_native import Geometry,disc,capsule,arc_faces
from .cam_tracks3 import tracks


def replay_geometry(prepared,replay,source):
    """Continuous physical cutting union, not selected-depth sampling.

    Every accepted cutting move is vertical or planar and the separate envelope
    proof establishes cutting reach above the original blank. Hence each planar
    footprint occupies the entire interval from its actual posted tip to Z=0.
    Pointed vertical tracks retain their cone and full-diameter junction.
    """
    import FreeCAD as A,Part
    from .cam_pointed import admit_reach,admit_tip_clearance
    from .cam_pointed_source_native import cutting_piece,topology
    if prepared.get('version')!='schemaxis.freecad.cam.plan/3':
        fail('VERIFICATION_FAILED','Mixed physical replay requires compiled plan/3')
    admit_reach(prepared,replay)
    admit_tip_clearance(prepared,replay)
    tools={t['id']:t for t in prepared['tools']};horizontal,vertical=tracks(replay,prepared['tools'])
    pointed=sum(tools[key[0]]['kind']=='drill' for key in vertical)
    flat=len(vertical)-pointed;annuli=0
    for _,motion in horizontal.values():
        if motion['code']==1:flat+=1
        elif motion['from'][:2]==motion['to'][:2]:flat+=1;annuli+=1
        else:flat+=3
    pieces=2*pointed+flat;faces=12*pieces;source_faces,_=topology(source)
    # Each global union/cut also measures its intersection. Face multiplication
    # and actual result topology are independently charged before/after every
    # kernel operation. This is a prospective work bound, never a tolerance.
    preflight(pieces=pieces,faces=faces,edges=24*pieces,
              booleans=4*pointed+3*flat+annuli+6,
              facePairs=2*(source_faces+6+faces)**2)
    geometry=Geometry();box=prepared['stockBounds']
    stock=Part.makeBox(box[1]-box[0],box[3]-box[2],-box[4],A.Vector(box[0],box[2],box[4]))
    stock_mass=geometry.mass(stock);target_mass=geometry.mass(source)
    cuts=Part.Shape();regions=0
    def append(piece):
        nonlocal cuts,regions
        cuts=geometry.union(cuts,piece);regions+=1
    def flat_piece(face,area,z):
        piece=geometry.prism(face,area,-z)
        return geometry.boolean(piece,stock,'common')
    for key,z in vertical.items():
        remaining_timeout();tool=tools[key[0]];xy=list(key[1:]);radius=tool['diameter']/2
        if tool['kind']=='drill':
            piece=cutting_piece(xy,{'id':tool['id'],'finish':z,'junction':z+tool['tipHeight']},tool,stock,geometry.budget)
        else:piece=flat_piece(disc([*xy,z],radius),math.pi*radius*radius,z)
        append(piece)
    for z,motion in horizontal.values():
        remaining_timeout();radius=tools[motion['tool']]['diameter']/2
        if motion['code']==1:
            face,area=capsule([*motion['from'][:2],z],[*motion['to'][:2],z],radius)
            append(flat_piece(face,area,z))
        else:
            for face,area in arc_faces(motion,z,radius,geometry):append(flat_piece(face,area,z))
    cut_mass=geometry.mass(cuts,boundary=True)
    remaining=geometry.difference(stock,cuts)
    residual=geometry.difference(remaining,source)
    gouge=geometry.difference(source,remaining)
    rm=geometry.mass(remaining,boundary=True);em=geometry.mass(residual,boundary=True);gm=geometry.mass(gouge,boundary=True)
    conservation=[abs(stock_mass['volume']-rm['volume']-cut_mass['volume']),
                  abs(rm['volume']-target_mass['volume']-em['volume']+gm['volume'])]
    error=math.fsum([geometry.balance_error,*conservation])
    if not math.isfinite(error):fail('MATERIAL_REPLAY_FAILED','Nonfinite mixed material balance')
    record={'method':'continuous-mixed-physical-solid-union','stockVolume':stock_mass['volume'],
            'targetVolume':target_mass['volume'],'remainingVolume':rm['volume'],
            'remainingCentreOfMass':rm['centreOfMass'],'removedVolume':cut_mass['volume'],
            'removedCentreOfMass':cut_mass['centreOfMass'],'residualVolume':em['volume'],
            'gougeVolume':gm['volume'],'balanceErrorVolume':error,
            'assessedResidualVolume':em['volume']+error,'assessedGougeVolume':gm['volume']+error,
            'conservationErrors':conservation,'tracks':len(horizontal)+len(vertical),
            'sweeps':regions,'motions':len(replay['motions']),
            'work':{'booleans':geometry.budget.operations,'booleanFacePairs':geometry.budget.face_pairs,
                    'identityComparisons':geometry.identity_checks}}
    return record,{'remaining.brep':remaining,'residual.brep':residual,'gouge.brep':gouge}


def material(directory,output_directory=None):
    """Reconstruct complete authority before geometry-only submitted reads.

    The checked native SHA is pinned before verification, retained throughout
    replay, and rechecked with the NC and captured source before publication.
    This worker never opens the submitted native CAM document.
    """
    import FreeCAD as A,Part
    from .cam_state2 import admit,reference,bind
    from .cam_native3 import read_source
    from .cam_code2 import parse
    from .cam_cycles2 import validate
    directory=Path(directory);output=Path(output_directory) if output_directory else directory
    output.mkdir(parents=True,exist_ok=True);prepared=read(directory/'plan.json')
    if prepared.get('version')!='schemaxis.freecad.cam.plan/3':fail('VERIFICATION_FAILED','Expected mixed physical plan/3')
    native_pin=file_digest(directory/'machining.FCStd')
    program_bytes=binary(directory/'program.ngc',4*1024*1024);program=program_bytes.decode('ascii')
    _,source_member,source_data=admit(directory,prepared)
    ordered=prepared['setup']['toolClearance']['kind']=='evolvingStock'
    replay=parse(program,prepared['tools'],prepared['setup']['safe'],ordered=ordered);validate(prepared,replay)
    if ordered:
        from .cam_ordered import preflight_ordered
        from .cam_ordered_native import OrderedGeometry,profiles
        preflight_ordered(prepared,replay);geometry=OrderedGeometry()
    with reference(directory,prepared) as canonical:
        checked=bind(directory/'machining.FCStd',canonical/'machining.FCStd',prepared)
        if program_bytes!=binary(canonical/'program.ngc',4*1024*1024):
            fail('VERIFICATION_FAILED','Posted mixed program differs from fresh trusted construction')
        trusted=read(canonical/'built.json')
        trusted={k:v for k,v in trusted.items() if k not in ('pid','stage')}
        if ordered:
            # Only the freshly generated installed reference is restored, after
            # whole submitted native/source/NC binding. Never a submitted Job.
            doc=A.openDocument(str(canonical/'machining.FCStd'))
            try:fresh_profiles=profiles(doc,prepared,geometry)
            finally:A.closeDocument(doc.Name)
    if checked!=native_pin:fail('VERIFICATION_FAILED','Native CAM bytes changed during authority-to-material handoff')
    # Geometry is read from the exact admitted original capture member, not a
    # later working-path read. The same bytes drive fresh native reconstruction.
    with tempfile.TemporaryDirectory(prefix='schemaxis-cam-material-source-') as temporary:
        staged=Path(temporary);(staged/source_member).write_bytes(source_data)
        source=read_source(staged,prepared)
    if ordered:
        from .cam_ordered_native import replay_geometry as ordered_geometry
        record,shapes=ordered_geometry(prepared,replay,source,fresh_profiles,geometry)
    else:record,shapes=replay_geometry(prepared,replay,source)
    record.update(pid=os.getpid(),runtime='.'.join(A.Version()[:3]),nativeSha256=checked,
                  authoritativeNativeReadback=trusted,
                  programSha256=hashlib.sha256(program_bytes).hexdigest(),publications={})
    for filename,shape in shapes.items():
        remaining_timeout()
        if shape.isNull():shape=Part.makeCompound([])
        path=output/filename;shape.exportBrep(str(path))
        if output_directory and binary(path,32*1024*1024)!=binary(directory/filename,32*1024*1024):
            fail('VERIFICATION_FAILED','Published mixed geometry differs from fresh physical replay',filename)
        record['publications'][filename]={'sha256':file_digest(path),'volume':record[filename.split('.')[0]+'Volume']}
    admit(directory,prepared);remaining_timeout()
    if file_digest(directory/'machining.FCStd')!=checked or binary(directory/'program.ngc',4*1024*1024)!=program_bytes:
        fail('VERIFICATION_FAILED','Admitted native/program bytes changed during mixed material replay')
    record['verified']=(record['assessedResidualVolume']<=prepared['quality']['residualVolume'] and
                        record['assessedGougeVolume']<=prepared['quality']['gougeVolume'])
    atomic_json(output/'replay.json',replay);atomic_json(output/'material.json',record)
    if record['assessedGougeVolume']>prepared['quality']['gougeVolume']:
        fail('TARGET_GOUGED','Actual physical cutter union removes desired material',gougeVolume=record['gougeVolume'])
    if record['assessedResidualVolume']>prepared['quality']['residualVolume']:
        fail('UNFINISHED_MATERIAL','Actual physical cutter union leaves excess stock',residualVolume=record['residualVolume'])
