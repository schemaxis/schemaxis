"""Native Draft mapping; authored geometry never selects native property names."""
from schemaxis.errors import fail
from .draft import selected


def inventory(shape):
    result=[]
    for index,face in enumerate(shape.Faces,1):
        surface=face.Surface;kind=type(surface).__name__
        record={'index':index,'surface':'other','normal':[0,0,0],'centre':list(face.CenterOfMass),
                'area':float(face.Area),'axis':[0,0,0],'axisPoint':[0,0,0],'radius':0}
        if kind=='Plane':
            u0,u1,v0,v1=face.ParameterRange
            record.update(surface='plane',normal=list(face.normalAt((u0+u1)/2,(v0+v1)/2)))
        elif kind=='Cylinder':record.update(surface='cylinder',axis=list(surface.Axis),axisPoint=list(surface.Center),radius=float(surface.Radius))
        result.append(record)
    return result


def configure(obj,node,objects):
    base=objects[node['inputs']['base']];base.Document.recompute()
    obj.Base=(base,selected(node['options'],inventory(base.Shape),node['id']))
    obj.NeutralPlane=(objects[node['inputs']['neutralPlane']],[''])
    obj.PullDirection=(objects[node['inputs']['axis']],['']) if 'axis' in node['inputs'] else None
    obj.Angle=node['options']['angle'];obj.Reversed=node['options']['reversed']
    obj.SupportTransform=False;obj.FuzzyTolerance=-1


def observe(obj,node):
    expected={'Angle':'App::PropertyAngle','Base':'App::PropertyLinkSub','NeutralPlane':'App::PropertyLinkSub',
              'PullDirection':'App::PropertyLinkSub','Reversed':'App::PropertyBool','SupportTransform':'App::PropertyBool','FuzzyTolerance':'App::PropertyFloatConstraint'}
    if any(obj.getTypeIdOfProperty(key)!=value for key,value in expected.items()):
        fail('VERIFICATION_FAILED','Native Draft property types differ',node['id'])
    def link(value):return [value[0].Name,list(value[1])] if value and value[0] else None
    return {'base':link(obj.Base),'neutralPlane':link(obj.NeutralPlane),'pullDirection':link(obj.PullDirection),
            'angle':float(obj.Angle.Value),'reversed':bool(obj.Reversed),'suppressed':bool(obj.Suppressed),'supportTransform':bool(obj.SupportTransform),
            'fuzzyTolerance':float(obj.FuzzyTolerance),'faceInventory':inventory(obj.BaseFeature.Shape)}


def inspect_saved_breps(directory):
    """Measure bounded run-owned BREP bytes without opening an FCStd document."""
    import json
    from pathlib import Path
    import Part
    from schemaxis.artifacts import atomic_json,file_digest
    from .native import check_runtime
    check_runtime()
    root=Path(directory);result={};faces=0
    for item in json.loads((root/'draft-breps.json').read_text()):
        path=root/item['file']
        if path.parent!=root or path.suffix!='.brp' or file_digest(path)!=item['sha256']:
            fail('VERIFICATION_FAILED','Draft measurement input changed')
        shape=Part.Shape();shape.read(str(path))
        if shape.isNull():fail('VERIFICATION_FAILED','Saved Draft base is empty',item['id'])
        count=shape.countElement('Face');faces+=count
        if not 1<=count<=10000 or faces>100000:
            fail('VERIFICATION_FAILED','Saved Draft base exceeds the face measurement budget',item['id'])
        if shape.countElement('Solid')!=1 or not shape.isValid():
            fail('VERIFICATION_FAILED','Saved Draft base must be one valid solid',item['id'])
        result[item['id']]=inventory(shape)
    atomic_json(root/'draft-inventories.json',result)
