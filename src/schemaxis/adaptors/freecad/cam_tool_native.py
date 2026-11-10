"""Trusted builtin tool reconstruction; submitted FCStd proxies are never opened."""
import math
from pathlib import Path
import tempfile

from schemaxis.artifacts import atomic_json
from schemaxis.errors import fail


def job_template(directory,t):
    params={'Diameter':str(t['diameter'])+' mm','CuttingEdgeHeight':str(t['cuttingLength'])+' mm','Length':str(t['length'])+' mm','ShankDiameter':str(t['shankDiameter'])+' mm','Flutes':int(t['flutes']),'Material':'HSS','SpindleDirection':'Forward'}
    attrs={'version':2,'id':'bffbfb6d-8a40-46dd-9147-73c44f21775b','name':'Endmill','shape':'endmill','shape-type':'Endmill','parameter':params}
    path=Path(directory)/'job-template.json'
    atomic_json(path,{'Version':1,'ToolController':[{'version':1,'name':'Cutter','nr':1,'tool':attrs}]})
    return path


def physical_cutter(shape,p):
    """Read native surfaces, independently of ToolBit scalar/proxy metadata."""
    import Part
    radius=p['tool']['diameter']/2;reach=-p['stockBounds'][4];box=shape.BoundBox
    if not shape.isValid() or len(shape.Solids)!=1 or abs(box.ZMin)>1e-7 or abs(box.ZMax-p['tool']['length'])>1e-7:
        fail('VERIFICATION_FAILED','Trusted native endmill shape has invalid geometry or length')
    flat=False;edge=False
    for face in shape.Faces:
        bounds=face.BoundBox
        if isinstance(face.Surface,Part.Plane) and abs(bounds.ZMin)<1e-7 and bounds.ZLength<1e-7 and abs(face.Area-math.pi*radius**2)<1e-6:
            flat=True
        if isinstance(face.Surface,Part.Cylinder) and abs(face.Surface.Radius-radius)<1e-7 and abs(abs(face.Surface.Axis.z)-1)<1e-12 and bounds.ZMin<=1e-7 and bounds.ZMax>=reach-1e-7:
            edge=True
    if not flat or not edge:fail('VERIFICATION_FAILED','Native endmill lacks the declared flat end or full-depth cylindrical cutting edge')


def verify(directory,p):
    import FreeCAD as App,Part
    from Path import Preferences
    import Path.Main.Job as Job
    from .cam_tool_checks import compare
    with tempfile.TemporaryDirectory(prefix='schemaxis-cam-tool-') as temporary:
        root=Path(temporary);assets=root/'cam-assets';assets.mkdir();Preferences.setAssetPath(assets)
        doc=App.newDocument('TrustedCutterTemplate')
        try:
            source=doc.addObject('Part::Feature','Source');source.Shape=Part.makeBox(1,1,1);doc.recompute()
            Job.Create('Machining',[source],str(job_template(root,p['tool'])));doc.recompute()
            physical_cutter(doc.getObject('Endmill').Shape,p)
            path=root/'canonical.FCStd';doc.saveAs(str(path))
        finally:App.closeDocument(doc.Name)
        compare(Path(directory)/'machining.FCStd',path,p['tool'])
