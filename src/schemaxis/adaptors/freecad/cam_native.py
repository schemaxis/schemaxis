"""Reviewed native milling constructors, isolated from host planning/discovery."""
import hashlib
import json
import os
from pathlib import Path
from schemaxis.artifacts import atomic_json
from schemaxis.errors import fail
from .cam_names import operation_names,require_free,require_created
from .adaptor import close

POST_ARGS='--no-header --no-comments --no-show-editor --precision 8 --preamble "G17 G54 G40 G49 G80 G90 G91.1 G94 G61 G92.1"'

def load(directory):
    directory=Path(directory);return directory,json.loads((directory/'plan.json').read_text())
def bounds(shape):
    b=shape.BoundBox;return [b.XMin,b.XMax,b.YMin,b.YMax,b.ZMin,b.ZMax]
def vec(v):return [v.x,v.y,v.z]
def read_source(directory,p):
    import Part
    shape=Part.Shape();shape.read(str(directory/('source.brep' if p['source']['format']=='FCStd' else 'source.step')))
    if not shape.isValid() or len(shape.Solids)!=1 or not close(shape.Volume,p['source']['volume']) or not close(bounds(shape),p['source']['bounds']) or not close(vec(shape.Solids[0].CenterOfMass),p['source']['centreOfMass']):fail('EXPECTATION_FAILED','Captured source solid differs from the independent volume, bounds or centre-of-mass requirement')
    from .cam_sections import levels
    levels(shape)
    import FreeCAD as App
    shape.translate(App.Vector(*[-x for x in p['origin']]));return shape

def face_at(shape,point):
    import FreeCAD as App,Part
    selected=[];vertex=Part.Vertex(App.Vector(*point))
    for i,f in enumerate(shape.Faces):
        if isinstance(f.Surface,Part.Plane) and f.normalAt(0,0).z>1-1e-7 and f.distToShape(vertex)[0]<1e-6 and min(e.distToShape(vertex)[0] for e in f.Edges)>1e-5:selected.append(i+1)
    if len(selected)!=1:fail('AMBIGUOUS_SELECTION' if selected else 'EMPTY_SELECTION','Choose one interior point on a horizontal, upward-facing pocket floor',matches=len(selected))
    return 'Face'+str(selected[0])


def build(directory):
    import FreeCAD as App
    directory,p=load(directory);operation_names(p)
    from Path import Preferences
    (directory/'cam-assets').mkdir(exist_ok=True)
    Preferences.setAssetPath(directory/'cam-assets')
    Preferences.preferences().SetFloat('LibAreaCurveAccuracy',1e-5)
    import Path as NativePath
    NativePath.Area.setDefaultParams(Accuracy=1e-5)
    import Path.Main.Job as Job
    import Path.Op.Pocket as Pocket
    import Path.Op.MillFace as Facing
    doc=App.newDocument('SchemaxisMilling');source=doc.addObject('Part::Feature','Source');source.Shape=read_source(directory,p);doc.recompute()
    # The native asset root is owned by this run and the configuration is
    # isolated. Standard tool creation can only fall back to installed built-ins,
    # never a user-supplied FCStd tool shape or postprocessor override.
    from .cam_tool_native import job_template
    t=p['tool'];job=Job.Create('Machining',[source],str(job_template(directory,t)));job.OrderOutputBy='Operation';job.SplitOutput=False;job.Fixtures=['G54'];job.GeometryTolerance=1e-5
    tc=job.Tools.Group[0];tc.ToolNumber=1;tc.SpindleDir='Forward';tc.SpindleSpeed=t['rpm'];tc.HorizFeed=str(t['feed'])+' mm/min';tc.VertFeed=str(t['plunge'])+' mm/min';tc.HorizRapid=str(t['feed']*3)+' mm/min';tc.VertRapid=str(t['plunge']*3)+' mm/min'
    stock=job.Stock
    for prop in ('ExtXneg','ExtXpos','ExtYneg','ExtYpos','ExtZneg'):setattr(stock,prop,0)
    stock.ExtZpos=p['stock']['top'];doc.recompute();model=job.Model.Group[0]
    for spec in p['operations']:
        identity=operation_names(p)[spec['id']];require_free(doc,identity)
        if spec['operation']=='faceStock':
            op=Facing.Create(identity,parentJob=job);require_created(doc,op,identity);point=[(p['stockBounds'][0]+p['stockBounds'][1])/2,(p['stockBounds'][2]+p['stockBounds'][3])/2,0];op.Base=[(stock,[face_at(stock.Shape,point)])];op.BoundaryShape='Boundbox';op.ClearEdges=True;op.ExcludeRaisedAreas=False
        else:
            op=Pocket.Create(identity,parentJob=job);require_created(doc,op,identity);point=[spec['floor'][i]-p['origin'][i] for i in range(3)];op.Base=[(model,[face_at(model.Shape,point)])];op.ClearingPattern='ZigZagOffset';op.ExtraOffset=0
        op.ToolController=tc;op.StepOver=round(spec['stepOver']*100)
        for prop,value in (('StepDown',spec['stepDown']),('StartDepth',spec['start']),('FinalDepth',spec['finish']),('ClearanceHeight',p['setup']['clearance']),('SafeHeight',p['setup']['safe'])):op.setExpression(prop,None);setattr(op,prop,value)
        if hasattr(op,'FinishDepth'):op.FinishDepth=0
        doc.recompute()
        if not op.isValid() or len(op.Path.Commands)<2:fail('EMPTY_TOOLPATH','Native operation produced no usable cutting path',spec['id'])
    doc.recompute();job.PostProcessor='linuxcnc';job.PostProcessorArgs=POST_ARGS
    from Path.Post.Processor import WrapperPost
    script=Path(Job.__file__).parents[1]/'Post/scripts/linuxcnc_post.py'
    sections=WrapperPost(job,str(script),'linuxcnc_post').export()
    if len(sections)!=1 or sections[0][0]!='allitems' or not isinstance(sections[0][1],str):fail('UNSUPPORTED_POST_OUTPUT','Expected one LinuxCNC program preserving the ordered operations')
    (directory/'program.ngc').write_text(sections[0][1]);doc.saveAs(str(directory/'machining.FCStd'));atomic_json(directory/'built.json',observe(doc,p,'build'));App.closeDocument(doc.Name)


def observe(doc,p,stage):
    import FreeCAD as App
    job=doc.getObject('Machining');tc=doc.getObject('Cutter');tool=tc.Tool;ops=[]
    for spec in p['operations']:
        op=doc.getObject(operation_names(p)[spec['id']]);item={'id':spec['id'],'name':op.Name,'type':op.TypeId,'valid':op.isValid(),'base':[[o.Name,list(sub)] for o,sub in op.Base],'tool':op.ToolController.Name,'stepOver':op.StepOver,'start':op.StartDepth.Value,'finish':op.FinalDepth.Value,'stepDown':op.StepDown.Value,'clearance':op.ClearanceHeight.Value,'safe':op.SafeHeight.Value,'commands':[{'name':c.Name,'parameters':dict(c.Parameters)} for c in op.Path.Commands]}
        item['areaParams']=op.AreaParams;item['clearingPattern']=op.ClearingPattern;ops.append(item)
    return {'stage':stage,'pid':os.getpid(),'runtime':'.'.join(App.Version()[:3]),'objects':{o.Name:o.TypeId for o in doc.Objects},'source':{'bounds':bounds(doc.getObject('Source').Shape),'volume':doc.getObject('Source').Shape.Volume,'centreOfMass':vec(doc.getObject('Source').Shape.Solids[0].CenterOfMass)},'model':{'group':[o.Name for o in job.Model.Group],'bounds':bounds(job.Model.Group[0].Shape),'volume':job.Model.Group[0].Shape.Volume},'job':{'operations':[o.Name for o in job.Operations.Group],'tools':[o.Name for o in job.Tools.Group],'fixtures':list(job.Fixtures),'order':job.OrderOutputBy,'split':job.SplitOutput,'postprocessor':job.PostProcessor,'postArgs':job.PostProcessorArgs},'stock':{'bounds':bounds(job.Stock.Shape),'volume':job.Stock.Shape.Volume},'tool':{'name':tool.Name,'diameter':tool.Diameter.Value,'cuttingLength':tool.CuttingEdgeHeight.Value,'length':tool.Length.Value,'shankDiameter':tool.ShankDiameter.Value,'flutes':tool.Flutes,'rpm':tc.SpindleSpeed,'feed':tc.HorizFeed.Value*60,'plunge':tc.VertFeed.Value*60,'number':tc.ToolNumber,'direction':tc.SpindleDir},'operations':ops}


def reopen(directory):
    import FreeCAD as App
    directory,p=load(directory)
    from Path import Preferences
    (directory/'cam-assets').mkdir(exist_ok=True)
    Preferences.setAssetPath(directory/'cam-assets')
    Preferences.preferences().SetFloat('LibAreaCurveAccuracy',1e-5)
    import Path as NativePath
    NativePath.Area.setDefaultParams(Accuracy=1e-5)
    doc=App.openDocument(str(directory/'machining.FCStd'));doc.recompute();result=observe(doc,p,'reopen')
    op=doc.getObject(operation_names(p)[p['operations'][0]['id']]);before=op.StepDown.Value;op.StepDown=before*.8;doc.recompute();result['edit']={'before':before,'changed':op.StepDown.Value,'commands':len(op.Path.Commands)};op.StepDown=before;doc.recompute();result['edit']['restored']=op.StepDown.Value
    atomic_json(directory/'reopened.json',result);App.closeDocument(doc.Name)
