"""Internal plan/3 constructor; not a public restored-document admission API."""
import os
import shutil
import tempfile
from pathlib import Path
from schemaxis.artifacts import atomic_json,file_digest
from schemaxis.dispatch import remaining_timeout
from schemaxis.errors import fail
from .cam_evidence2 import binary
from .cam_names import operation_names,require_free,require_created
from .cam_native import load,face_at,bounds,vec,POST_ARGS
from .cam_pointed_native import template_record,attach_cutting_metadata,physical,create_holder,holder_readback


def configure(tc,t):
    tc.ToolNumber=t['number'];tc.SpindleDir='Forward';tc.SpindleSpeed=t['rpm']
    for prop,value in (('HorizFeed',t['feed']),('VertFeed',t['plunge']),('HorizRapid',t['feed']*3),('VertRapid',t['plunge']*3)):
        setattr(tc,prop,str(value)+' mm/min')


def construct(directory,p):
    """Build only admitted typed intent. Never open a submitted CAM document."""
    import FreeCAD as App
    from Path import Preferences
    import Path as NativePath
    from Path.Main import Job
    from Path.Op import Pocket,MillFace,Drilling
    from Path.Tool import Controller
    if p.get('version')!='schemaxis.freecad.cam.plan/3':raise ValueError('Expected internal plan/3')
    from .cam_reduced import needed,native_module
    if needed(p):native_module()
    operation_names(p)
    directory=Path(directory);(directory/'cam-assets').mkdir(exist_ok=True)
    Preferences.setAssetPath(directory/'cam-assets');Preferences.preferences().SetFloat('LibAreaCurveAccuracy',1e-5)
    NativePath.Area.setDefaultParams(Accuracy=1e-5)
    doc=App.newDocument('SchemaxisMachining')
    try:
        source=doc.addObject('Part::Feature','Source');source.Shape=read_source(directory,p);doc.recompute()
        tools={t['id']:t for t in p['tools']};first=tools[p['operations'][0]['tool']]
        template=directory/'job-template.json';atomic_json(template,{'Version':1,'ToolController':[template_record(first)]})
        job=Job.Create('Machining',[source],str(template));job.OrderOutputBy='Operation';job.SplitOutput=False;job.Fixtures=['G54'];job.GeometryTolerance=1e-5
        configure(job.Tools.Group[0],first);attach_cutting_metadata(job.Tools.Group[0].Tool,first);create_holder(doc,job.Tools.Group[0].Tool,first)
        for prop in ('ExtXneg','ExtXpos','ExtYneg','ExtYpos','ExtZneg'):setattr(job.Stock,prop,0)
        job.Stock.ExtZpos=p['stock']['top'];doc.recompute();model=job.Model.Group[0]
        from .cam_mixed_budget import BooleanBudget
        selection_budget=BooleanBudget()
        for index,spec in enumerate(p['operations']):
            tool=tools[spec['tool']];identity=operation_names(p)[spec['id']];kind=spec['operation'];require_free(doc,identity)
            if kind=='faceStock':
                op=MillFace.Create(identity,parentJob=job);require_created(doc,op,identity);op.Base=[(job.Stock,[face_at(job.Stock.Shape,[0,0,0])])]
                op.BoundaryShape='Boundbox';op.ClearEdges=True;op.ExcludeRaisedAreas=False
            elif kind=='pocket':
                point=[spec['floor'][i]-p['origin'][i] for i in range(3)]
                op=Pocket.Create(identity,parentJob=job);require_created(doc,op,identity);op.Base=[(model,[face_at(model.Shape,point)])]
                op.ClearingPattern='ZigZagOffset';op.ExtraOffset=0
            elif kind=='drill':
                from .cam_holes_native import select
                if tool['kind']=='drill':
                    from .cam_pointed_source_native import select as pointed
                    edges=pointed(model.Shape,spec,tool,p['stockBounds'],p['origin'],budget=selection_budget)
                else:edges=select(model.Shape,spec,tool)
                op=Drilling.Create(identity,parentJob=job);require_created(doc,op,identity);op.Base=[(model,edges)];op.Locations=[];op.Disabled=[]
                cycle=spec['cycle'];op.PeckEnabled=cycle['kind'] in ('peck','chipBreak');op.DwellEnabled=cycle['kind']=='dwell'
                # The native setup initially drives PeckDepth from tool diameter.
                # Authored peck intent replaces that finite default expression.
                op.setExpression('PeckDepth',None);op.PeckDepth=cycle['peck']
                op.DwellTime=cycle['dwell'];op.KeepToolDown=cycle['return']=='retract'
                op.chipBreakEnabled=cycle['kind']=='chipBreak';op.feedRetractEnabled=cycle['kind']=='feedRetract'
                op.ExtraOffset=spec.get('extraOffset','None');op.AddTipLength=False
                op.setExpression('RetractHeight',None);op.RetractHeight=cycle['retract']
            else:fail('INVALID_MACHINING','Unexpected compiled machining operation',spec['id'])
            tc=doc.getObject(tool['controller']);op.ToolController=tc
            # SafeHeight establishes the actual pre-cycle initial plane. R is
            # the separate safe inter-hole/retract plane. The independent NC
            # reader derives G98's return from state, never from these labels.
            safe=p['setup']['clearance'] if kind=='drill' else p['setup']['safe']
            settings=[('StartDepth',spec['start']),('FinalDepth',spec.get('nativeFinish',spec['finish'])),('ClearanceHeight',p['setup']['clearance']),('SafeHeight',safe)]
            if kind!='drill':
                op.StepOver=round(spec['stepOver']*100);settings.append(('StepDown',spec['stepDown']))
                if hasattr(op,'FinishDepth'):op.FinishDepth=0
            for prop,value in settings:op.setExpression(prop,None);setattr(op,prop,value)
            doc.recompute()
            if not op.isValid() or len(op.Path.Commands)<2:fail('EMPTY_TOOLPATH','Native operation produced no usable path',spec['id'])
            if kind=='drill':
                from .cam_holes_native import check_commands
                check_commands(op.Path.Commands,spec)
            if index==0:
                # Native findToolController has no headless first-op selection
                # when multiple controllers exist. Create the first operation
                # with its sole controller, then add the rest by the public API.
                # Every later assignment and final group order is explicit.
                for other in p['tools']:
                    if other['id']!=first['id']:
                        added=Controller.FromTemplate(template_record(other));job.Proxy.addToolController(added);configure(added,other);attach_cutting_metadata(added.Tool,other);create_holder(doc,added.Tool,other)
                job.Tools.Group=[doc.getObject(t['controller']) for t in p['tools']]
        doc.recompute();job.PostProcessor='linuxcnc';job.PostProcessorArgs=POST_ARGS
        measured={tool['id']:physical(doc.getObject(tool['nativeTool']),tool)['noncuttingStart'] for tool in p['tools']}
        for tool in p['tools']:holder_readback(doc,tool)
        from Path.Post.Processor import WrapperPost
        script=Path(Job.__file__).parents[1]/'Post/scripts/linuxcnc_post.py'
        sections=WrapperPost(job,str(script),'linuxcnc_post').export()
        if len(sections)!=1 or sections[0][0]!='allitems' or not isinstance(sections[0][1],str):
            fail('UNSUPPORTED_POST_OUTPUT','Expected one ordered LinuxCNC program')
        from .cam_code2 import parse
        from .cam_cycles2 import validate
        replay=parse(sections[0][1],p['tools'],p['setup']['safe'],
                     ordered=p['setup']['toolClearance']['kind']=='evolvingStock');validate(p,replay)
        from .cam_pointed import admit_reach,admit_tip_clearance
        if p['setup']['toolClearance']['kind']=='aboveBlank':
            admit_reach(p,replay,actual_starts=measured)
        elif p['setup']['toolClearance']['kind']!='evolvingStock':
            fail('INVALID_MACHINING','Unknown physical clearance policy')
        # An evolving-stock construction is not clearance verification. Its
        # mandatory separate material worker must check every actual prefix,
        # full fresh bit partition and holder before successful publication.
        admit_tip_clearance(p,replay)
        (directory/'program.ngc').write_text(sections[0][1]);doc.saveAs(str(directory/'machining.FCStd'))
        atomic_json(directory/'built.json',observe(doc,p,'build'))
    finally:App.closeDocument(doc.Name)


def observe(doc,p,stage):
    import FreeCAD as App
    job=doc.getObject('Machining');operations=[];tools=[]
    for spec in p['operations']:
        op=doc.getObject(operation_names(p)[spec['id']])
        record={'id':spec['id'],'name':op.Name,'type':op.TypeId,'valid':op.isValid(),
                'base':[[o.Name,list(sub)] for o,sub in op.Base],'tool':op.ToolController.Name,
                'start':op.StartDepth.Value,'finish':op.FinalDepth.Value,'safe':op.SafeHeight.Value,
                'clearance':op.ClearanceHeight.Value,'commands':[{'name':c.Name,'parameters':dict(c.Parameters)} for c in op.Path.Commands]}
        if spec['operation']=='drill':
            record.update(retract=op.RetractHeight.Value,retractMode=op.RetractMode,peck=op.PeckDepth.Value,
                          dwell=op.DwellTime,keepToolDown=op.KeepToolDown,peckEnabled=op.PeckEnabled,
                          dwellEnabled=op.DwellEnabled,chipBreakEnabled=op.chipBreakEnabled,
                          feedRetractEnabled=op.feedRetractEnabled,addTipLength=op.AddTipLength,
                          extraOffset=op.ExtraOffset,locations=[vec(v) for v in op.Locations],disabled=list(op.Disabled))
        else:record.update(stepDown=op.StepDown.Value,stepOver=op.StepOver,areaParams=op.AreaParams,clearingPattern=op.ClearingPattern)
        operations.append(record)
    for spec in p['tools']:
        tc=doc.getObject(spec['controller']);tool=tc.Tool
        tools.append({'id':spec['id'],'controller':tc.Name,'tool':tool.Name,'number':tc.ToolNumber,
                      'direction':tc.SpindleDir,'rpm':tc.SpindleSpeed,'feed':tc.HorizFeed.Value*60,
                      'plunge':tc.VertFeed.Value*60,'physical':physical(tool,spec),'holder':holder_readback(doc,spec)})
    return {'stage':stage,'pid':os.getpid(),'runtime':'.'.join(App.Version()[:3]),'objects':{o.Name:o.TypeId for o in doc.Objects},
            'source':{'bounds':bounds(doc.getObject('Source').Shape),'volume':doc.getObject('Source').Shape.Volume,
                      'centreOfMass':vec(doc.getObject('Source').Shape.Solids[0].CenterOfMass)},
            'model':{'group':[o.Name for o in job.Model.Group],'bounds':bounds(job.Model.Group[0].Shape),'volume':job.Model.Group[0].Shape.Volume},
            'stock':{'bounds':bounds(job.Stock.Shape),'volume':job.Stock.Shape.Volume},
            'job':{'operations':[o.Name for o in job.Operations.Group],'tools':[o.Name for o in job.Tools.Group],
                   'fixtures':list(job.Fixtures),'order':job.OrderOutputBy,'split':job.SplitOutput,
                   'postprocessor':job.PostProcessor,'postArgs':job.PostProcessorArgs},'tools':tools,'operations':operations}



def read_source(directory,p):
    """Geometry-only read of captured bytes; never restore the source FCStd."""
    import Part,FreeCAD as A
    from .adaptor import close
    from .cam_pointed_source_native import topology
    from .cam_mixed_budget import preflight
    path=directory/('source.brep' if p['source']['format']=='FCStd' else 'source.step')
    expected=p['source']['brepSha256'] if p['source']['format']=='FCStd' else p['source']['sha256']
    if file_digest(path)!=expected:fail('VERIFICATION_FAILED','Working pointed source differs from admitted captured geometry bytes')
    shape=Part.Shape();shape.read(str(path));faces,_=topology(shape)
    from .solid_topology_native import admit,TopologyRefused,TopologyLimit
    try:admit(shape,max_faces=8192,max_edges=16384,max_occurrences=65536,max_checks=2000000)
    except TopologyLimit as error:fail('RESOURCE_LIMIT',str(error))
    except TopologyRefused as error:fail('UNSUPPORTED_SOURCE',str(error))
    if (not shape.isValid() or len(shape.Solids)!=1 or shape.Volume<=0 or
            not close(shape.Volume,p['source']['volume']) or not close(bounds(shape),p['source']['bounds']) or
            not close(vec(shape.Solids[0].CenterOfMass),p['source']['centreOfMass'])):
        fail('EXPECTATION_FAILED','Pointed source differs from independent solid geometry requirements')
    count=sum(len(o['centres']) for o in p['operations'] if o['operation']=='drill' and next(t for t in p['tools'] if t['id']==o['tool'])['kind']=='drill')
    preflight(pieces=2*count,faces=12*count,edges=24*count,booleans=3*count,facePairs=faces*6*count+72*count)
    shape.translate(A.Vector(*[-v for v in p['origin']]));return shape


def build(directory):
    directory,p=load(directory);construct(directory,p)


def reopen(directory):
    """Reopen only a private copy of a completely admitted native byte stream."""
    import FreeCAD as App
    directory,p=load(directory)
    from .cam_state2 import reference,bind
    with reference(directory,p) as canonical:
        checked=bind(directory/'machining.FCStd',canonical/'machining.FCStd',p)
        if binary(directory/'program.ngc',4*1024*1024)!=binary(canonical/'program.ngc',4*1024*1024):
            fail('VERIFICATION_FAILED','CAM3 program differs before native reopen')
        with tempfile.TemporaryDirectory(prefix='schemaxis-cam-reopen-') as temporary:
            target=Path(temporary)/'machining.FCStd';shutil.copyfile(directory/'machining.FCStd',target)
            if file_digest(target)!=checked or file_digest(directory/'machining.FCStd')!=checked:
                fail('VERIFICATION_FAILED','CAM3 bytes changed between complete admission and private native copy')
            remaining_timeout()
            if file_digest(target)!=checked:fail('VERIFICATION_FAILED','Private CAM3 reopen bytes changed before native use')
            doc=App.openDocument(str(target))
            try:
                doc.recompute();remaining_timeout();result=observe(doc,p,'reopen')
            finally:App.closeDocument(doc.Name)
            if file_digest(target)!=checked or file_digest(directory/'machining.FCStd')!=checked:
                fail('VERIFICATION_FAILED','CAM3 reopen changed the admitted native bytes')
            if binary(directory/'program.ngc',4*1024*1024)!=binary(canonical/'program.ngc',4*1024*1024):
                fail('VERIFICATION_FAILED','CAM3 program changed during native reopen')
        # reference() re-admits captured source on normal exit. Publish only
        # after that final input-authority gate and the shared deadline gate.
    remaining_timeout();atomic_json(directory/'reopened.json',result)
