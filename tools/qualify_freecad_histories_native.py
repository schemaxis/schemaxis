"""Independent edits of a native enclosure; executed by FreeCAD, never on the host."""
import json
import math
import os
from pathlib import Path
import FreeCAD as App
from schemaxis.artifacts import atomic_json


def main(directory,mode):
    root=Path(directory);prepared=json.loads((root/'enclosure'/'plan.json').read_text());mapped={n['id']:'N'+str(i) for i,n in enumerate(prepared['nodes'])}
    path=root/'enclosure'/'model.FCStd' if mode=='edit' else root/'edited.FCStd'
    doc=App.openDocument(str(path));drivers=doc.getObject('SchemaxisParameters')
    def facts(values):
        wall,floor,height,boss=values
        enclosure=doc.getObject(mapped['finished']);lid=doc.getObject(mapped['lidFinished'])
        wanted=40*30*height-(40-2*wall)*(30-2*wall)*(height-floor)+4*math.pi*4*boss-4*math.pi*(floor+boss)
        lid_wanted=floor*(1200-24-math.pi)
        assert enclosure.Shape.isValid() and len(enclosure.Shape.Solids)==1
        assert lid.Shape.isValid() and len(lid.Shape.Solids)==1
        assert math.isclose(enclosure.Shape.Volume,wanted,rel_tol=1e-8,abs_tol=1e-6),(enclosure.Shape.Volume,wanted)
        assert math.isclose(lid.Shape.Volume,lid_wanted,rel_tol=1e-8,abs_tol=1e-6),(lid.Shape.Volume,lid_wanted)
        assert math.isclose(doc.getObject(mapped['bossProfile1']).Placement.Base.z,floor,abs_tol=1e-6)
        assert math.isclose(doc.getObject(mapped['boreProfile4']).Placement.Base.z,height,abs_tol=1e-6)
        assert math.isclose(doc.getObject(mapped['ventProfile']).Placement.Base.z,floor,abs_tol=1e-6)
        for identity in ('enclosure','lid'):
            assert doc.getObject(mapped[identity]).TypeId=='PartDesign::Body'
        return {'enclosureVolumeMM3':enclosure.Shape.Volume,'expectedEnclosureVolumeMM3':wanted,
                'lidVolumeMM3':lid.Shape.Volume,'expectedLidVolumeMM3':lid_wanted,
                'floorAttachmentZMM':doc.getObject(mapped['bossProfile1']).Placement.Base.z,
                'boreAttachmentZMM':doc.getObject(mapped['boreProfile4']).Placement.Base.z}
    baseline=facts((3,3,20,6) if mode=='edit' else (2.5,4,22,8))
    values=(2.5,4,22,8) if mode=='edit' else (3.2,2.5,19,5)
    drivers.dim_wall,drivers.dim_floor,drivers.dim_height,drivers.dim_bossHeight=values
    doc.recompute();edited=facts(values)
    assert not any(any(s in o.State for s in ('Error','Invalid','Touched')) for o in doc.Objects)
    expressions={o.Name:[list(p) for p in o.ExpressionEngine] for o in doc.Objects}
    attachments={identity:[[o.Name,list(sub)] for o,sub in doc.getObject(mapped[identity]).AttachmentSupport]
                 for identity in ('cavityProfile','bossProfile1','bossProfile4','boreProfile4','ventProfile')}
    if mode=='edit':doc.saveAs(str(root/'edited.FCStd'))
    else:doc.saveAs(str(root/'edited-twice.FCStd'))
    atomic_json(root/('native-'+mode+'.json'),{'verified':True,'pid':os.getpid(),'runtime':App.Version(),
        'baseline':baseline,'edited':edited,'parameters':list(values),'expressions':expressions,'attachments':attachments})
    App.closeDocument(doc.Name)
