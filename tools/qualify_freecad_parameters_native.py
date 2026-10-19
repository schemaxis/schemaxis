"""Independent native qualification worker; run only by qualify_freecad_parameters.py."""
import copy
import json
import math
import os
import sys
from pathlib import Path
import FreeCAD as App


def check(doc, plan, values):
    targets = {'box':{'length':'Length','width':'Width','height':'Height'},
               'cylinder':{'radius':'Radius','height':'Height'},'extrude':{'length':'LengthFwd'}}
    result={}
    expected_options={}
    for i,node in enumerate(plan['nodes']):
        obj=doc.getObject('N'+str(i))
        assert not any(s in obj.State for s in ('Invalid','Error'))
        assert obj.Shape.isValid()
        dimensions=dict(node['options'])
        for option,binding in node.get('drive',{}).items():
            expected=binding['offset']+sum(c*values[k] for k,c in binding['terms'].items())
            dimensions[option]=expected
            actual=float(getattr(obj,targets[node['filter']][option]).Value)
            assert math.isclose(actual,expected,abs_tol=1e-7,rel_tol=1e-10),(option,actual,expected)
            result[node['id']+'.'+option]=actual
        for option,native in targets.get(node['filter'],{}).items():
            actual=float(getattr(obj,native).Value)
            assert math.isclose(actual,dimensions[option],abs_tol=1e-7,rel_tol=1e-10),(node['id'],option,actual,dimensions[option])
        expected_options[node['id']]=dimensions
    output=doc.getObject('N'+str(next(i for i,n in enumerate(plan['nodes']) if n['id']==plan['output'])))
    if plan['output']=='plate':
        h=values['thickness'];expected=(4000-9*math.pi)*h
        area=2*(4000-9*math.pi)+(260+6*math.pi)*h
        assert math.isclose(output.Shape.Area,area,rel_tol=1e-10)
    elif plan['nodes'][-1]['filter']=='extrude':expected=200*values['depth']
    else:
        assert plan['nodes'][-1]['filter']=='box'
        dims=expected_options[plan['output']]
        expected=dims['length']*dims['width']*dims['height']
        origin=dims['origin'];bb=output.Shape.BoundBox
        observed=[bb.XMin,bb.XMax,bb.YMin,bb.YMax,bb.ZMin,bb.ZMax]
        wanted=[origin[0],origin[0]+dims['length'],origin[1],origin[1]+dims['width'],origin[2],origin[2]+dims['height']]
        assert all(math.isclose(a,b,abs_tol=1e-7,rel_tol=1e-10) for a,b in zip(observed,wanted))
    assert math.isclose(output.Shape.Volume,expected,rel_tol=1e-10)
    assert len(output.Shape.Solids)==1
    return {'targets':result,'volume':float(output.Shape.Volume)}


def main(directory, mode):
    directory=Path(directory);plan=json.loads((directory/'plan.json').read_text())
    values={k:p['value'] for k,p in plan['parameters'].items()}
    if mode=='hostile':
        sys.path.insert(0,str(directory/'runtime.zip'))
        from schemaxis.adaptors.freecad.parameters_native import observe
        from schemaxis.core.faults import SchemaxisError
        changes={
            'missing-expression':lambda d:d.N0.setExpression('Height',None),
            'wrong-same-value':lambda d:d.N0.setExpression('Height','0.5 * SchemaxisParameters.dim_thickness + 2.5 mm'),
            'extra-expression':lambda d:d.N0.setExpression('Width','50 mm'),
            'unknown-varset':lambda d:d.addObject('App::VarSet','OtherParameters'),
            'unknown-property':lambda d:d.SchemaxisParameters.addProperty('App::PropertyLength','dim_unknown'),
            'clamped-negative':lambda d:setattr(d.SchemaxisParameters,'dim_thickness',-2),
            'unit-error':lambda d:d.N0.setExpression('Height','1 * SchemaxisParameters.dim_thickness + 2')}
        report={'pid':os.getpid(),'rejected':{}}
        for label,change in changes.items():
            doc=App.openDocument(str(directory/'model.FCStd'));change(doc);doc.recompute()
            if label in ('missing-expression','wrong-same-value','extra-expression'):
                assert doc.N0.Height.Value==5 and doc.N0.Width.Value==50
            if label=='clamped-negative':assert doc.SchemaxisParameters.dim_thickness.Value==0
            try:observe(doc,plan)
            except SchemaxisError as error:report['rejected'][label]=error.fault.code
            else:raise AssertionError('invalid native relationship accepted: '+label)
            App.closeDocument(doc.Name)
        (directory/'independent-hostile.json').write_text(json.dumps(report,indent=2)+'\n')
        return
    if mode=='edit':
        report={'pid':os.getpid(),'perturbations':{},'runtime':App.Version()}
        for identity,param in plan['parameters'].items():
            observed=[]
            for end in ('minimum','maximum'):
                doc=App.openDocument(str(directory/'model.FCStd'));var=doc.getObject('SchemaxisParameters')
                name='dim_'+identity
                assert name in var.PropertiesList and var.getTypeIdOfProperty(name)=='App::PropertyLength'
                assert var.Visibility is False
                setattr(var,name,param[end]);doc.recompute()
                current={**values,identity:param[end]};observed.append(check(doc,plan,current))
                App.closeDocument(doc.Name)
            assert observed[0]!=observed[1],identity+' perturbation was unobservable'
            report['perturbations'][identity]=observed
        edited={k:p['maximum'] for k,p in plan['parameters'].items()}
        doc=App.openDocument(str(directory/'model.FCStd'));var=doc.getObject('SchemaxisParameters')
        for k,v in edited.items():setattr(var,'dim_'+k,v)
        doc.recompute();report['edited']=check(doc,plan,edited)
        report['expressions']={o.Name:list(o.ExpressionEngine) for o in doc.Objects}
        doc.saveAs(str(directory/'independently-edited.FCStd'));App.closeDocument(doc.Name)
    else:
        doc=App.openDocument(str(directory/'independently-edited.FCStd'));doc.recompute()
        report={'pid':os.getpid(),'edited':check(doc,plan,{k:p['maximum'] for k,p in plan['parameters'].items()}),
                'expressions':{o.Name:list(o.ExpressionEngine) for o in doc.Objects}}
        App.closeDocument(doc.Name)
    (directory/('independent-'+mode+'.json')).write_text(json.dumps(report,indent=2)+'\n')
