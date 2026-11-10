"""Independent host checks of admitted intent, typed saved CAM and NC publication."""
import json
import math
from pathlib import Path
from zipfile import ZipFile
from schemaxis.errors import fail
from .cam_names import operation_names
from . import cam as policy
from .cam_code import parse,PERSISTED_ARC_RADIUS_TOLERANCE,WORD
import re
from .cam_native import POST_ARGS
from .drawing_checks import close
from .document_xml import Document,read_member


def compare_saved_paths(directory,p,saved=None):
    """Bind actual saved Path payloads to posted NC, including after native edits.

    Native Path XML rounds coordinates to six decimals. Its relaxed circle
    admission is only for comparing that representation; physical material is
    always replayed from the eight-decimal posted program at the strict gate.
    """
    directory=Path(directory);saved=saved or Document(directory/'machining.FCStd')
    def require(condition,message):
        if not condition:fail('VERIFICATION_FAILED',message,str(directory))
    header='G17 G21 G54 G40 G80 G90 G91.1 G94 G61 G92.1\nM5\nM6 T1\nG43 H1\nM3 S'+str(p['tool']['rpm'])+'\n'
    native_lines=[]
    with ZipFile(directory/'machining.FCStd') as archive:
        for spec in p['operations']:
            identity=operation_names(p)[spec['id']];native=saved.child(identity,'Path','Path','Path::PropertyPath')
            payload=read_member(archive,native.get('file'),4*1024*1024).decode()
            require(payload.startswith('('+identity+')\n'),'Saved native path identity differs')
            lines=[]
            for line in payload.splitlines():
                if line.startswith('('):continue
                # XY-plane native paths may redundantly store K0. A nonzero K
                # changes the arc plane and must never disappear in conversion.
                require(all(float(raw)==0 for word,raw in WORD.findall(line) if word=='K'),'Saved native XY path has nonzero K')
                line=re.sub(r'\bK[-+0-9.]+','',line)
                line=re.sub(r'\bF([-+0-9.]+)',lambda m:'F'+str(float(m.group(1))*60),line)
                lines.append(line)
            native_lines.extend(lines)
            parsed=parse(header+'\n'.join(lines)+'\nM5\nM2\n',p['tool'],p['setup']['safe'],arc_radius_tolerance=PERSISTED_ARC_RADIUS_TOLERANCE)
            require(bool(parsed['motions']),'Saved native operation contains no interpretable motion')
    replay=parse((directory/'program.ngc').read_text(),p['tool'],p['setup']['safe'])
    native_replay=parse(header+'\n'.join(native_lines)+'\nM5\nM2\n',p['tool'],p['setup']['safe'],arc_radius_tolerance=PERSISTED_ARC_RADIUS_TOLERANCE)
    require(len(native_replay['motions'])==len(replay['motions']),'Posted motion count differs from persisted native operations')
    for native,posted in zip(native_replay['motions'],replay['motions']):
        require(native.keys()==posted.keys(),'Posted NC motion fields differ from persisted native toolpaths')
        for key in native:
            # The six-decimal persisted endpoints differ by <=0.505e-6 mm
            # from eight-decimal posted ones. Centres sum position and IJ,
            # so permit their combined <=1.01e-6 mm rounding only.
            if key in ('from','to','centre'):
                tolerance=1.01e-6 if key=='centre' else .505e-6
                matches=len(native[key])==len(posted[key]) and all(math.isclose(a,b,abs_tol=tolerance,rel_tol=0) for a,b in zip(native[key],posted[key]))
            elif key=='feed' and native[key] is not None:
                matches=math.isclose(native[key],posted[key],abs_tol=6e-5,rel_tol=0)
            else:matches=native[key]==posted[key]
            require(matches,'Posted NC motion differs from persisted native toolpaths')
    return replay


def verify(directory,require_result,fresh=True):
    from .cam_evidence2 import read
    version=read(Path(directory)/'plan.json').get('version')
    if version=='schemaxis.freecad.cam.plan/3':
        from .cam_checks3 import verify as physical
        return physical(directory,require_result,fresh)
    if version=='schemaxis.freecad.cam.plan/2':
        from .cam_checks2 import verify as extended
        return extended(directory,require_result,fresh)
    def require(condition,message):
        if not condition:fail('VERIFICATION_FAILED',message,str(directory))
    def enumeration(saved,identity,prop):
        record=saved.properties[identity][prop]
        require(record.get('type')=='App::PropertyEnumeration' and [c.tag for c in record]==['Integer','CustomEnumList'],'Saved enumeration representation differs')
        index=int(record[0].get('value'));values=[v.get('value') for v in record[1]]
        require(record[1].get('count')==str(len(values)) and 0<=index<len(values),'Saved enumeration range differs')
        return values[index]
    p=json.loads((directory/'plan.json').read_text());authored=json.loads((directory/'authored.json').read_text());require(p==policy._native_plan(authored,captured=directory/p['source']['capture']),'Machining plan differs from admitted source or authored intent')
    if require_result:require(json.loads((directory/'result.json').read_text()).get('verified') is True,'Machining execution is incomplete')
    built=json.loads((directory/'built.json').read_text());reopened=json.loads((directory/'reopened.json').read_text());material=json.loads((directory/'material.json').read_text());require(len({r['pid'] for r in (built,reopened,material)})==3,'Build, reopen and independent material replay must run in separate native processes')
    require(all(r['runtime']=='1.1.4' for r in (built,reopened,material)),'Native machining runtime differs from qualified FreeCAD1.1.4')
    expected_bounds=[v-p['origin'][i//2] for i,v in enumerate(p['source']['bounds'])];expected_com=[v-p['origin'][i] for i,v in enumerate(p['source']['centreOfMass'])]
    for report,stage in ((built,'build'),(reopened,'reopen')):
        require(report['stage']==stage and close(report['source'],{'volume':p['source']['volume'],'bounds':expected_bounds,'centreOfMass':expected_com}),'Native source geometry or work frame differs')
        require(report['model']['group']==['Clone'] and close(report['model']['bounds'],expected_bounds) and close(report['model']['volume'],p['source']['volume']),'Native model clone differs from admitted workpiece')
        require(close(report['stock']['bounds'],p['stockBounds']) and close(report['stock']['volume'],(p['stockBounds'][1]-p['stockBounds'][0])*(p['stockBounds'][3]-p['stockBounds'][2])*(-p['stockBounds'][4])),'Native stock shape differs from declared blank')
        require(report['job']=={'operations':[operation_names(p)[s['id']] for s in p['operations']],'tools':['Cutter'],'fixtures':['G54'],'order':'Operation','split':False,'postprocessor':'linuxcnc','postArgs':POST_ARGS},'Native machining ownership, operation order or postprocessor differs')
        require(close(report['tool'],dict(p['tool'],name='Endmill',number=1,direction='Forward')),'Native cutter or cutting data differs')
        require(len(report['operations'])==len(p['operations']),'Native operation evidence is incomplete')
        for op,spec in zip(report['operations'],p['operations']):
            require(op['id']==spec['id'] and op['name']==operation_names(p)[spec['id']] and op['type']=='Path::FeaturePython' and op['valid'] is True and op['tool']=='Cutter','Native operation identity/type/tool differs')
            for k,v in dict(start=spec['start'],finish=spec['finish'],stepDown=spec['stepDown'],stepOver=round(spec['stepOver']*100),clearance=p['setup']['clearance'],safe=p['setup']['safe']).items():require(close(op[k],v),'Native cutting depth, stepover or traverse plane differs')
            require(op['base'][0][0]==('Stock' if spec['operation']=='faceStock' else 'Clone') and len(op['base'])==1 and len(op['base'][0][1])==1,'Native operation target ownership differs')
            require(op['clearingPattern']==('ZigZag' if spec['operation']=='faceStock' else 'ZigZagOffset'),'Native clearing/finishing strategy differs')
            require(1<len(op['commands'])<=10000,'Native toolpath is empty or exceeds the bounded contract')
    require(close(built['operations'],reopened['operations']),'Saved native toolpath changes after fresh reopen')
    require(close(reopened['edit'],{'before':p['operations'][0]['stepDown'],'changed':p['operations'][0]['stepDown']*.8,'restored':p['operations'][0]['stepDown'],'commands':reopened['edit']['commands']}) and reopened['edit']['commands']>1,'Native operation edit did not recompute a usable path')
    saved=Document(directory/'machining.FCStd');require(saved.types==built['objects'],'Saved native object membership differs')
    from .cam_tool_checks import closed
    closed(saved,p,directory/'machining.FCStd')
    require(saved.links('Operations','Group')==[operation_names(p)[s['id']] for s in p['operations']] and saved.links('Tools','Group')==['Cutter'] and saved.links('Model','Group')==['Clone'],'Saved job ownership or operation order differs')
    require(saved.link('Cutter','Tool')=='Endmill','Saved tool controller link differs')
    require(saved.child('Endmill','Flutes','Integer','App::PropertyInteger').get('value')==str(int(p['tool']['flutes'])),'Saved flute count differs')
    require(saved.child('Cutter','ToolNumber','Integer','App::PropertyIntegerConstraint').get('value')=='1','Saved tool number differs')
    require(close(saved.number('Machining','GeometryTolerance','App::PropertyDistance'),1e-5) and enumeration(saved,'Machining','PostProcessor')=='linuxcnc' and saved.string('Machining','PostProcessorArgs')==POST_ARGS and saved.boolean('Machining','SplitOutput') is False,'Saved Job tolerance or publication policy differs')
    for prop,key in (('Diameter','diameter'),('CuttingEdgeHeight','cuttingLength'),('Length','length'),('ShankDiameter','shankDiameter')):require(close(saved.number('Endmill',prop),p['tool'][key]),'Saved cutter geometry differs')
    for prop,key in (('HorizFeed','feed'),('VertFeed','plunge')):require(close(saved.number('Cutter',prop,'App::PropertySpeed')*60,p['tool'][key]),'Saved cutting feed differs')
    require(close(saved.number('Cutter','SpindleSpeed','App::PropertyFloat'),p['tool']['rpm']),'Saved spindle speed differs')
    expected_types={'Source':'Part::Feature','Machining':'Path::FeaturePython','Operations':'App::DocumentObjectGroup','SetupSheet':'App::FeaturePython','Model':'App::DocumentObjectGroup','Clone':'Part::FeaturePython','Tools':'App::DocumentObjectGroup','Cutter':'Path::FeaturePython','Endmill':'Part::FeaturePython','PropertyBag':'App::FeaturePython','XZ_Plane':'App::Plane','Sketch':'Sketcher::SketchObject','Revolution':'PartDesign::Revolution','X_Axis':'App::Line','Y_Axis':'App::Line','Z_Axis':'App::Line','XY_Plane':'App::Plane','YZ_Plane':'App::Plane','Origin001':'App::Point','Origin':'App::Origin','Body':'PartDesign::Body','Stock':'Part::FeaturePython',**{operation_names(p)[op['id']]:'Path::FeaturePython' for op in p['operations']}}
    require(saved.types==expected_types,'Saved Job contains foreign, missing or wrongly typed native objects')
    require(enumeration(saved,'Cutter','SpindleDir')=='Forward' and enumeration(saved,'Machining','OrderOutputBy')=='Operation','Saved spindle or output ordering differs')
    fixtures=saved.child('Machining','Fixtures','StringList','App::PropertyStringList');require(fixtures.get('count')=='1' and [v.get('value') for v in fixtures]==['G54'],'Saved work frame differs')
    for prop,value in [('ExtXneg',0),('ExtXpos',0),('ExtYneg',0),('ExtYpos',0),('ExtZneg',0),('ExtZpos',p['stock']['top'])]:require(close(saved.number('Stock',prop,'App::PropertyDistance'),value),'Saved stock allowance differs')
    with ZipFile(directory/'machining.FCStd') as archive:
        for identity in ('Source','Clone','Stock'):
            geom=material['geometry'][identity];member=saved.properties[identity]['Shape'].find('Part').get('file');require(member==geom['member'] and policy.digest(read_member(archive,member,32*1024*1024))==geom['sha256'],'Saved solid geometry differs from independent replay')
            placement=saved.child(identity,'Placement','PropertyPlacement','App::PropertyPlacement');require(close([float(placement.get(k)) for k in ('Px','Py','Pz','Q0','Q1','Q2','Q3')],geom['placement']),'Saved solid placement differs from independent shape readback')
        for op,spec in zip(built['operations'],p['operations']):
            identity=operation_names(p)[spec['id']];require(saved.link(identity,'ToolController')=='Cutter','Saved operation tool differs')
            for prop,key in (('StartDepth','start'),('FinalDepth','finish'),('StepDown','stepDown'),('SafeHeight','safe'),('ClearanceHeight','clearance')):require(close(saved.number(identity,prop,'App::PropertyDistance' if prop not in ('StepDown',) else 'App::PropertyDistance'),op[key]),'Saved cutting or traverse depth differs')
            require(saved.child(identity,'StepOver','Integer','App::PropertyPercent').get('value')==str(round(spec['stepOver']*100)) and enumeration(saved,identity,'ClearingPattern')==op['clearingPattern'],'Saved stepover or clearing strategy differs')
            if spec['operation']=='faceStock':require(enumeration(saved,identity,'BoundaryShape')=='Boundbox' and saved.boolean(identity,'ClearEdges') and not saved.boolean(identity,'ExcludeRaisedAreas'),'Saved facing boundary differs')
            else:require(close(saved.number(identity,'ExtraOffset','App::PropertyDistance'),0),'Saved pocket offset differs')
            refs=saved.child(identity,'Base','LinkSubList','App::PropertyLinkSubListGlobal');require([(c.get('obj'),c.get('sub')) for c in refs]==[(op['base'][0][0],op['base'][0][1][0])],'Saved geometric target differs')
        proxies={'Machining':('Path.Main.Job','ObjectJob'),'SetupSheet':('Path.Base.SetupSheet','SetupSheet'),'Clone':('draftobjects.clone','Clone'),'Cutter':('Path.Tool.Controller','ToolController'),'Stock':('Path.Main.Stock','StockFromBase'),'Endmill':('Path.Tool.toolbit.models.endmill','ToolBitEndmill'),'PropertyBag':('Path.Base.PropertyBag','PropertyBag')}
        for spec in p['operations']:proxies[operation_names(p)[spec['id']]]=('Path.Op.MillFace','ObjectFace') if spec['operation']=='faceStock' else ('Path.Op.Pocket','ObjectPocket')
        for identity,properties in saved.properties.items():
            for key,prop in properties.items():
                if prop.get('type')=='App::PropertyPythonObject':require(key=='Proxy' and identity in proxies,'Foreign executable native Python property is not admitted')
        for identity,(module,cls) in proxies.items():
            from .cam_proxies import check,tool_state
            proxy=saved.child(identity,'Proxy','Python','App::PropertyPythonObject')
            check(proxy,module,cls,tool_state(p['tool']) if identity=='Endmill' else 'Clone' if identity=='Clone' else {} if identity=='Cutter' else None)
    program=(directory/'program.ngc').read_text();replay=compare_saved_paths(directory,p,saved)
    require(replay==json.loads((directory/'replay.json').read_text()),'Posted NC replay differs')
    require(material['verified'] is True and material['method']=='continuous-flat-endmill-sections' and material['programSha256']==policy.digest(program.encode()) and material['nativeSha256']==policy.digest((directory/'machining.FCStd').read_bytes()),'Independent material replay is incomplete or bound to different outputs')
    require(close(material['targetVolume'],p['source']['volume']) and material['assessedResidualVolume']<=p['quality']['residualVolume'] and material['assessedGougeVolume']<=p['quality']['gougeVolume'] and math.isfinite(material['balanceErrorVolume']) and material['balanceErrorVolume']>=0,'Material replay does not meet the requested finish limits')
    for filename in ('remaining.brep','residual.brep','gouge.brep'):
        require(policy.digest((directory/filename).read_bytes())==material['publications'][filename]['sha256'],'Published replay geometry differs from retained material proof')
    from .cam_publication import verify as verify_publication
    artifacts=verify_publication(directory)
    require(json.loads((directory/'verification.json').read_text())=={'runtime':built['runtime'],'artifacts':artifacts},'Machining publication membership differs')
    if fresh:
        from .cam_verify import fresh_material
        current=fresh_material(directory)
        require(close({k:v for k,v in current.items() if k!='pid'},{k:v for k,v in material.items() if k!='pid'}),'Fresh cutter replay differs from retained material evidence')
    return {'verified':True,'artifacts':artifacts,'runtime':built['runtime'],'operations':len(p['operations']),'motions':len(replay['motions']),'residualVolume':material['residualVolume'],'gougeVolume':material['gougeVolume'],'nativeFile':str(directory/'machining.FCStd'),'programFile':str(directory/'program.ngc'),'sourceHistoryPreserved':False}
