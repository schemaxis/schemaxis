"""Typed prescribed kinematics over a verified fixed-assembly publication."""
import copy
import json
import math
import os
from pathlib import Path
import shutil
import tempfile
import uuid

from schemaxis.artifacts import atomic_json,file_digest,runtime_archive
from schemaxis.core.declarations import validate_arguments
from schemaxis.errors import fail,keys

from .document_xml import ARCHIVE_ERRORS, parse_xml

VERSION='schemaxis.freecad.mechanism/1'
ARGUMENTS={
    'durationSeconds':{'type':'number','minimum':.01,'maximum':3600,'default':1},
    'intervals':{'type':'integer','minimum':2,'maximum':240,'default':12},
    'framesPerSecond':{'type':'integer','minimum':1,'maximum':120,'default':24},
    'motions':{'type':'array','minItems':1,'maxItems':31,'required':True,'items':{'type':'object','properties':{
        'joint':{'type':'string','required':True},'kind':{'type':'enum','values':['rotation','translation'],'required':True},
        'end':{'type':'number','minimum':-1000,'maximum':1000,'required':True}}}}}


def read(directory,name):
    from .saved_checks import read_json
    return read_json(Path(directory),name)


def source_record(value):
    """Admit fixed-assembly provenance without executing a native application."""
    from . import assembly
    from .assembly_sources import _plain,check_archive,digest
    if not isinstance(value,str) or not value or len(value)>4096:
        fail('UNSUPPORTED_SOURCE','source must name a verified fixed-assembly model.FCStd','source')
    path=_plain(value,'source');check_archive(path,'source')
    if path.name!='model.FCStd':fail('UNSUPPORTED_SOURCE','source must be the fixed-assembly model.FCStd publication','source')
    authored=read(path.parent,'authored.json')
    if authored.get('version')!=assembly.VERSION:
        fail('UNSUPPORTED_SOURCE','Mechanisms require the verified fixed-assembly route','source')
    prepared=assembly._native_plan(authored)
    if read(path.parent,'plan.json')!=prepared or read(path.parent,'result.json').get('verified') is not True:
        fail('UNSUPPORTED_SOURCE','Source assembly has no matching successful fixed-assembly plan','source')
    receipt=read(path.parent,'verification.json');artifact=receipt.get('artifact',{})
    portable=not prepared.get('sourced') and isinstance(artifact,dict) and artifact.get('file')=='model.FCStd'
    if not isinstance(artifact,dict) or any(artifact.get(k)!=v for k,v in
            {'file':'model.FCStd' if portable else str(path),'kind':'cadScene','units':'mm','sha256':digest(path)}.items()):
        fail('UNSUPPORTED_SOURCE','Source assembly publication identity differs','source')
    from .source_envelope import read_members
    source_gui='GuiDocument.xml' in read_members(path,'source','UNSUPPORTED_SOURCE')
    native={'components':{c['id']:'Component'+str(i) for i,c in enumerate(prepared['components'])},
            'joints':{j['id']:'Joint'+str(i) for i,j in enumerate(prepared['joints'])}}
    if prepared.get('sourced'):
        native={k:prepared['native'][k] for k in ('components','joints')}
    geometry={}
    parts={p['id']:p for p in prepared['parts']}
    for component in prepared['components']:
        identity=component['id'];part=parts[component['part']]
        if prepared.get('sourced'):
            from .assembly_sources import inverse,square,apply
            observed=receipt['snapshots']['persisted']['components'][identity]['shape']
            geometry[identity]={'volume':part['source']['volume'],
                'localCentre':apply(inverse(square(prepared['expected']['components'][identity]['matrix'])),observed['centreOfMass'])}
        else:
            options=part['options'];centre=([options['length']/2,options['width']/2,options['height']/2]
                if part['type']=='box' else [0,0,options['height']/2])
            geometry[identity]={'volume':prepared['expected'][identity]['volume'],'localCentre':centre}
    return {'file':str(path),'sha256':digest(path),'run':str(path.parent),'assembly':prepared,'native':native,
            'receiptSha256':file_digest(path.parent/'verification.json'),'geometry':geometry,'portable':portable,'gui':source_gui,
            'packetDigests':{str(path.parent/name):file_digest(path.parent/name) for name in
                ('model.FCStd','authored.json','plan.json','result.json','built.json','verification.json')}}


def plan(document):
    from schemaxis.documents import resolve_document
    document,_=resolve_document(copy.deepcopy(document))
    keys(document,('version','source',*ARGUMENTS,'definitions','dimensions','settings'),'$')
    if document.get('version')!=VERSION:fail('UNSUPPORTED_VERSION','Expected '+VERSION)
    source=source_record(document.get('source'))
    values=validate_arguments(ARGUMENTS,{k:document[k] for k in ARGUMENTS if k in document})
    joints=source['native']['joints'];seen=set()
    for motion in values['motions']:
        joint=motion['joint']
        if joint not in joints:fail('UNKNOWN_JOINT','Motion must name a joint in the verified source assembly',joint)
        if joint in seen:fail('DUPLICATE_MOTION','A joint can have only one prescribed motion',joint)
        seen.add(joint)
        if motion['kind']=='rotation' and (abs(motion['end'])>360 or abs(motion['end'])/values['intervals']>15):
            fail('MOTION_RESOLUTION','Use at most one revolution and no more than15 degrees per interval',joint)
        rate=motion['end']/values['durationSeconds']
        if motion['kind']=='rotation':rate=math.radians(rate)
        motion['formula']=format(rate,'.17g')+'*time'
    if not any(m['end'] for m in values['motions']):fail('INVALID_MOTION','At least one prescribed end displacement must be nonzero')
    native={**source['native'],'motions':{m['joint']:'Motion'+str(i) for i,m in enumerate(values['motions'])}}
    return {'version':'schemaxis.freecad.mechanism.plan/1','source':source,'native':native,**values,
            'units':{'rotation':'degrees','translation':'mm','time':'s'},'law':'constantSpeedFromZero',
            'expectedPublications':2}


def schema():
    from schemaxis.schema import DRAFT,object_schema,arguments_schema,json_value_schema
    options=arguments_schema(ARGUMENTS)
    return {'$schema':DRAFT,'$defs':{'json':json_value_schema()},**object_schema({
        'version':{'const':VERSION},'source':{'type':'string','minLength':1,'maxLength':4096},**options['properties'],
        **{k:{'$ref':'#/$defs/json'} for k in ('definitions','dimensions','settings')}},['version','source','motions'])}


def resources(document,spec=None,identity=None):return {}


def reusableInputs(document):
    source=plan(document)['source'];return dict(source['packetDigests'])


def poses(prepared,fraction):
    """Independent rigid tree oracle, with motion in each parent connector frame."""
    from .assembly_sources import frame,rot_z,mul,inverse,flat,mount_frame
    from .assembly import face_centre
    a=prepared['source']['assembly'];components={c['id']:c for c in a['components']};parts={p['id']:p for p in a['parts']}
    motions={m['joint']:m for m in prepared['motions']};root=components[a['grounded']]
    world={root['id']:frame(root['position'],rot_z(root['rotation']))}
    def mount(endpoint):
        part=parts[components[endpoint['component']]['part']]
        if a.get('sourced'):
            return mount_frame(next(m for m in part['mounts'] if m['id']==endpoint['mount']))
        return frame(face_centre(part,endpoint['face']),rot_z(0))
    for joint in a['joints']:
        motion=motions.get(joint['id']);angle=0;displacement=0
        if motion:
            if motion['kind']=='rotation':angle=motion['end']*fraction
            else:displacement=motion['end']*fraction
        fixed=frame(joint['offset'],rot_z(joint.get('clocking',0)))
        movement=frame([0,0,displacement],rot_z(angle))
        parent=joint['parent'];child=joint['child']
        world[child['component']]=mul(mul(mul(mul(world[parent['component']],mount(parent)),fixed),movement),inverse(mount(child)))
    return {key:flat(value) for key,value in world.items()}


def check_observation(prepared,record):
    from .drawing_checks import close
    from schemaxis.dispatch import remaining_timeout
    remaining_timeout()
    def require(ok,message):
        if not ok:fail('VERIFICATION_FAILED',message)
    require(record.get('runtime')=='1.1.4' and record.get('badStates')=={},'Native mechanism runtime or object state differs')
    require(record.get('generateCode')==0,'Native prescribed simulation did not solve')
    initial=poses(prepared,0)
    require(close(record.get('initial'),initial) and close(record.get('restored'),initial),'Saved/restored mechanism pose differs from the independent tree')
    frames=record.get('frames');count=prepared['intervals']
    require(isinstance(frames,list) and len(frames)==count+2,'Native simulation frame count differs (initial pose, then inclusive time samples)')
    for index,observed in enumerate(frames):
        remaining_timeout()
        fraction=max(0,index-1)/count
        require(close(observed,poses(prepared,fraction)),'Native mechanism frame differs from independent connector composition: '+str(index))
    shape_frames=record.get('shapes')
    require(isinstance(shape_frames,list) and len(shape_frames)==len(frames),'Native motion geometry is incomplete')
    from .assembly_sources import square,apply
    for index,shapes in enumerate(shape_frames):
        remaining_timeout()
        require(set(shapes)==set(initial),'Native motion shape membership differs')
        expected_pose=poses(prepared,max(0,index-1)/count)
        for key,facts in prepared['source']['geometry'].items():
            observed=shapes[key]
            require(observed.get('valid') is True and observed.get('solids')==1 and close(observed.get('volume'),facts['volume'])
                    and close(observed.get('centreOfMass'),apply(square(expected_pose[key]),facts['localCentre'])),
                    'Physical component geometry does not follow its independently composed motion: '+key)
    wanted={'start':0,'end':prepared['durationSeconds'],'step':prepared['durationSeconds']/count,
            'fps':prepared['framesPerSecond'],'tolerance':1e-6,'group':list(prepared['native']['motions'].values())}
    require(close(record.get('simulation'),wanted),'Native simulation timing, grouping or tolerance differs')
    motions={m['joint']:m for m in prepared['motions']}
    require(record.get('motions')=={key:{'formula':m['formula'],'type':'Angular' if m['kind']=='rotation' else 'Linear',
        'joint':prepared['native']['joints'][key]} for key,m in motions.items()},'Native motion formula/type/joint binding differs')
    for key,joint in record.get('joints',{}).items():
        require(joint.get('type')==('Revolute' if motions[key]['kind']=='rotation' else 'Slider') if key in motions else joint.get('type')=='Fixed',
                'Native joint type differs from prescribed motion')
    require(set(record.get('joints',{}))==set(prepared['native']['joints']),'Native joint membership differs')


def gui_location(executable=None):
    from schemaxis.configuration import executable as configured,locations
    location=executable or locations().get('freecad_gui')
    if not location:
        batch=configured('freecad') or os.environ.get('FREECAD_CMD')
        if batch:
            candidate=Path(batch).expanduser().absolute().with_name('freecad')
            if candidate.is_file():location=str(candidate)
    if not location:fail('GUI_RUNTIME_REQUIRED','Configure the FreeCAD GUI launcher for native mechanism simulation')
    return location


def prepare_directory(directory,prepared):
    directory.mkdir(parents=True)
    shutil.copyfile(prepared['source']['file'],directory/'source.FCStd')
    if file_digest(directory/'source.FCStd')!=prepared['source']['sha256']:fail('INPUT_CHANGED','Source assembly changed during capture')
    atomic_json(directory/'plan.json',prepared);(directory/'trusted-runtime.zip').write_bytes(runtime_archive())


def compare_saved(actual,expected,*,fresh_document=False):
    """Bind all native object/view properties and payloads to trusted regeneration.

    Neither submitted document nor its Python proxies are opened by verification.
    Native allocation IDs, status bits and topology-name encodings use the existing
    qualified same-regeneration normalisation; complete shadows and payloads stay
    bound separately. GUI expansion/camera/style remain bound to native output.
    """
    from schemaxis.dispatch import remaining_timeout
    from .assembly_sources_saved import Saved,_canonical
    from .history_copy_verify import bind_regenerated
    from .source_envelope import read_members
    from .assembly_payloads import file_map
    remaining_timeout()
    a=Saved(actual);b=Saved(expected)
    if a.root.attrib!=b.root.attrib or [c.tag for c in a.root]!=[c.tag for c in b.root]:
        raise ValueError('mechanism document structure differs from trusted regeneration')
    # Copying a fixed source preserves its document UUID and creation time.
    # Only the GUI save timestamp varies between identical regenerations.
    def properties(root):
        result=copy.deepcopy(root.find('Properties'))
        for prop in result:
            if prop.get('name') in (('LastModifiedDate','CreationDate','Uid') if fresh_document else ('LastModifiedDate',)):
                tag='Uuid' if prop.get('name')=='Uid' else 'String'
                kind='App::PropertyUUID' if tag=='Uuid' else 'App::PropertyString'
                if prop.tag!='Property' or prop.get('type')!=kind or [c.tag for c in prop]!=[tag]:
                    raise ValueError('invalid native save timestamp property')
                if tag=='Uuid':uuid.UUID(prop[0].attrib['value'])
                prop[0].set('value','<allocation-time-or-uuid>')
        return _canonical(result,{},set(),'document properties')
    if properties(a.root)!=properties(b.root):raise ValueError('mechanism document properties differ from trusted regeneration')
    if a.xml.types!=b.xml.types or a.deps.keys()!=b.deps.keys():raise ValueError('mechanism object/dependency membership differs')
    names={n:n for n in a.objects}
    if a.root.find('Objects').attrib!=b.root.find('Objects').attrib or [c.tag for c in a.root.find('Objects')]!=[c.tag for c in b.root.find('Objects')]:
        raise ValueError('mechanism object inventory structure differs')
    for name in names:
        remaining_timeout()
        if {k:v for k,v in a.objects[name].attrib.items() if k!='id'}!={k:v for k,v in b.objects[name].attrib.items() if k!='id'} or list(a.objects[name]) or list(b.objects[name]):
            raise ValueError('mechanism object record differs: '+name)
        def object_data(saved):
            result=copy.deepcopy(saved.data[name])
            if fresh_document:
                for prop in result.findall('./Properties/Property'):
                    if prop.get('type')=='App::PropertyUUID':
                        if prop.get('name')!='Uid' or [c.tag for c in prop]!=['Uuid']:raise ValueError('unexpected constructor object UUID')
                        uuid.UUID(prop[0].attrib['value']);prop[0].set('value','<allocation-uuid>')
            return result
        if _canonical(object_data(a),names,set(),name,regenerated_shadows=True)!=_canonical(object_data(b),names,set(),name,regenerated_shadows=True):
            raise ValueError('mechanism native properties differ from trusted regeneration: '+name)
        if name in a.deps and _canonical(a.deps[name],names,set(),name)!=_canonical(b.deps[name],names,set(),name):
            raise ValueError('mechanism dependencies differ from trusted regeneration: '+name)
    hasher=a.root.find('StringHasher2')
    if (hasher is None)!=(b.root.find('StringHasher2') is None):raise ValueError('mechanism string-hasher membership differs')
    for tag in ('StringHasher','StringHasher2'):
        if a.root.find(tag) is not None and _canonical(a.root.find(tag),{},set(),tag)!=_canonical(b.root.find(tag),{},set(),tag):
            raise ValueError('mechanism string-hasher declaration differs')
    if hasher is not None:bind_regenerated(actual,a.root,Path(expected).parent)
    left=read_members(actual,'model.FCStd','VERIFICATION_FAILED');right=read_members(expected,'regenerated.FCStd','VERIFICATION_FAILED')
    if set(left)!=set(right):raise ValueError('mechanism archive member set differs from trusted regeneration')
    def gui_signature(data,members,document):
        root=parse_xml(data,'GuiDocument.xml');providers=root.find('ViewProviderData')
        if providers is None:raise ValueError('native GUI view providers are absent')
        names=[p.get('name') for p in providers]
        if len(set(names))!=len(names):raise ValueError('native GUI view provider is repeated')
        # Native storage iterates pointer-keyed view providers in allocation
        # order. Their named identities and explicit tree ranks carry meaning.
        providers[:]=sorted(providers,key=lambda p:p.get('name',''))
        rank_order=[]
        if fresh_document:
            # FreeCAD's tree fallback rank is the owning native object ID
            # (Gui/Tree.cpp). Bind that allocation under the complete named-ID
            # bijection AND retain the explicit root order; no rank edits pass.
            from .assembly_payloads import object_ids
            allocated=object_ids(document);ranked=[]
            for provider in providers:
                if 'treeRank' not in provider.attrib:continue
                rank=int(provider.get('treeRank'))
                if rank< -1 or str(rank)!=provider.get('treeRank'):raise ValueError('constructor GUI rank is not canonical')
                if rank>0:
                    name=provider.get('name')
                    if allocated.get(name)!=rank:raise ValueError('constructor GUI rank differs from its native owner allocation')
                    ranked.append((rank,name));provider.set('treeRank','<owner-allocation>')
            rank_order=[name for _,name in sorted(ranked)]
        payloads={};files=set()
        for provider in providers:
            for prop in provider.findall('./Properties/Property'):
                for index,element in enumerate(prop.iter()):
                    member=element.get('file')
                    if member in (None,''):continue
                    if element.tag not in ('MaterialList','ColorList') or member not in members or member in files:
                        raise ValueError('native GUI payload is missing, repeated or unsupported')
                    key=(provider.get('name'),prop.get('name'),index)
                    if key in payloads:raise ValueError('native GUI payload owner is repeated')
                    payloads[key]=members[member];files.add(member)
                    # Pointer iteration allocates these file suffixes. Bind
                    # their complete bytes to the stable provider/property.
                    element.set('file','<owned-gui-payload>')
        def signature(node):
            return (node.tag,tuple(sorted(node.attrib.items())),(node.text or '').strip(),tuple(signature(c) for c in node))
        return (signature(root),rank_order),payloads,files
    gui_files=set()
    if 'GuiDocument.xml' in left:
        agui,apayloads,gui_files=gui_signature(left['GuiDocument.xml'],left,a.root)
        bgui,bpayloads,_=gui_signature(right['GuiDocument.xml'],right,b.root)
        if agui!=bgui:raise ValueError('mechanism view properties differ from trusted regeneration')
        if apayloads!=bpayloads:raise ValueError('mechanism owned GUI payload differs from trusted regeneration')
    # Bind the complete SID inventory, including records unused by any map or
    # XML shadow. Allocation IDs may differ only under the named-object bijection.
    from .assembly_payloads import object_ids
    identities=object_ids(a.root);reference_ids=object_ids(b.root)
    tags={reference_ids[name]:identities[name] for name in identities}
    if hasher is not None and sid_inventory(left,a.root)!=sid_inventory(right,b.root,tags):
        raise ValueError('mechanism complete string inventory differs from trusted regeneration')
    bound=set(file_map(a.root).values())|{'Document.xml','GuiDocument.xml'}
    if hasher is None:
        # Primitive constructor documents have no topology hasher. Every
        # shape/list payload is bound directly; encoded maps/shadows are absent.
        from .assembly_payloads import same_brep
        files=file_map(a.root);references=file_map(b.root)
        if files!=references:raise ValueError('constructor payload membership differs')
        if any(e.get('shadow') for e in a.root.iter()) or any(k[2]=='ElementMap2' for k in files):
            raise ValueError('constructor document has unbound topology names')
        for key,member in files.items():
            remaining_timeout()
            if left[member]!=right[member] and not (key[2]=='Part' and same_brep(right[member],left[member])):
                raise ValueError('constructor payload differs from trusted regeneration: '+member)
    if hasher is not None:bound.add(hasher.get('file'))
    for member in set(left)-bound-gui_files:
        remaining_timeout()
        if left[member]!=right[member]:raise ValueError('native GUI/auxiliary payload differs: '+member)

    remaining_timeout()


def sid_inventory(members,root,tags=None):
    """Canonical inventory shared with the independent history verifier."""
    from .history_element_maps import string_inventory
    return string_inventory(members,root,tags)


def _verify_source(prepared,*,executable=None):
    """Never open submitted constructor proxies; bind them to a trusted rebuild."""
    from . import assembly
    from schemaxis.configuration import executable as configured
    from schemaxis.dispatch import remaining_timeout
    source=prepared['source']
    if source['assembly'].get('sourced'):
        assembly.verify(source['run'])
    else:
        if not source.get('portable'):assembly.verify(source['run'])
        location=executable or configured('freecad') or os.environ.get('FREECAD_CMD')
        if not location:fail('VERIFICATION_RUNTIME_REQUIRED','Constructor admission requires the configured FreeCAD batch launcher')
        with tempfile.TemporaryDirectory(prefix='schemaxis-mechanism-source-') as temporary:
            root=Path(temporary);packet=root/'packet';packet.mkdir()
            for name in ('authored.json','plan.json','result.json','built.json','verification.json','model.FCStd'):
                shutil.copyfile(Path(source['run'])/name,packet/name)
            # Constructor packets may use the explicit relative publication
            # identity model.FCStd. Only relocate that identity; all typed/native
            # settings, topology, solver probes and payload bytes remain bound.
            receipt=read(packet,'verification.json')
            receipt['artifact']['file']=str(packet/'model.FCStd')
            if 'artifacts' in receipt:receipt['artifacts']=[receipt['artifact']]
            atomic_json(packet/'verification.json',receipt)
            assembly._native_verify(packet)
            rebuilt=root/'assembly'
            assembly._native_run(read(source['run'],'authored.json'),rebuilt,executable=location,
                gui_executable=gui_location() if source.get('gui') else None,timeout=remaining_timeout(180))
            compare_saved(source['file'],rebuilt/'model.FCStd',fresh_document=True)
    remaining_timeout()


def verify_source(prepared,*,executable=None):
    from schemaxis.core.faults import SchemaxisError
    try:return _verify_source(prepared,executable=executable)
    except SchemaxisError:raise
    except (OSError,ValueError,KeyError,TypeError,IndexError,AttributeError,OverflowError)+ARCHIVE_ERRORS as error:
        fail('UNSUPPORTED_SOURCE','Source assembly differs from its trusted constructor regeneration',
             prepared['source']['file'],detail=str(error))


def _verify(directory,require_result=True,*,gui_executable=None):
    from . import assembly
    from . import gui_process
    from .drawing_checks import close
    from schemaxis.dispatch import remaining_timeout
    directory=Path(directory).absolute();prepared=_native_plan(read(directory,'authored.json'))
    if prepared!=read(directory,'plan.json'):fail('VERIFICATION_FAILED','Mechanism plan differs from current source and authored motion')
    if require_result and read(directory,'result.json').get('verified') is not True:fail('INCOMPLETE_EXECUTION','Mechanism execution is incomplete')
    verify_source(prepared)
    if file_digest(directory/'source.FCStd')!=prepared['source']['sha256']:fail('VERIFICATION_FAILED','Retained source assembly differs')
    first=read(directory,'build.json')['observed'];second=read(directory,'reopen.json')['observed']
    for record in (first,second):check_observation(prepared,record)
    if first['pid']==second['pid'] or not close({k:v for k,v in first.items() if k!='pid'},{k:v for k,v in second.items() if k!='pid'}):
        fail('VERIFICATION_FAILED','Native simulation does not reproduce after fresh GUI reopening')
    with tempfile.TemporaryDirectory(prefix='schemaxis-mechanism-verify-') as temporary:
        fresh=Path(temporary)/'regeneration';prepare_directory(fresh,prepared)
        current=gui_process.run(fresh,gui_location(gui_executable),'build',timeout=remaining_timeout(120))['observed']
        check_observation(prepared,current);compare_saved(directory/'model.FCStd',fresh/'model.FCStd')
        if not close({k:v for k,v in current.items() if k!='pid'},{k:v for k,v in second.items() if k!='pid'}):
            fail('VERIFICATION_FAILED','Fresh current-code simulation differs from retained motion evidence')
    motion=read(directory,'motion.json')
    expected={'units':prepared['units'],'law':prepared['law'],'initialPose':poses(prepared,0),
        'samples':[{'timeSeconds':prepared['durationSeconds']*i/prepared['intervals'],'placements':poses(prepared,i/prepared['intervals'])}
                   for i in range(prepared['intervals']+1)]}
    if not close(motion,expected):fail('VERIFICATION_FAILED','Published trajectory differs from independent tree poses')
    artifacts=[{'file':str(directory/name),'kind':kind,'sha256':file_digest(directory/name),**extra}
        for name,kind,extra in [('model.FCStd','cadScene',{'units':'mm'}),('motion.json','text',{})]]
    if read(directory,'verification.json')!={'artifacts':artifacts,'runtime':'1.1.4'}:
        fail('VERIFICATION_FAILED','Mechanism publication membership or digest differs')
    remaining_timeout()
    return {'verified':True,'artifacts':artifacts,'runtime':'1.1.4','samples':prepared['intervals']+1,
            'motion':motion,'nativeFile':str(directory/'model.FCStd')}


def verify(directory,require_result=True):
    from schemaxis.core.faults import SchemaxisError
    try:return _verify(directory,require_result)
    except SchemaxisError:raise
    except (OSError,ValueError,KeyError,TypeError,IndexError,AttributeError,OverflowError)+ARCHIVE_ERRORS as error:
        fail('VERIFICATION_FAILED','Mechanism evidence is malformed or differs from trusted regeneration',str(directory),detail=str(error))


def run(document,directory,*,executable=None,gui_executable=None,timeout=300):
    from schemaxis.dispatch import execution_deadline,remaining_timeout
    from . import assembly,gui_process
    if type(timeout) not in (int,float) or not math.isfinite(timeout) or timeout<=0:fail('INVALID_TIMEOUT','Provide a finite positive mechanism deadline')
    with execution_deadline(timeout):
        prepared=_native_plan(document);directory=Path(directory).absolute()
        if directory.exists() or directory.is_symlink():fail('OUTPUT_EXISTS','Choose a fresh mechanism run directory',str(directory))
        verify_source(prepared,executable=executable)
        prepare_directory(directory,prepared);atomic_json(directory/'authored.json',document)
        atomic_json(directory/'result.json',{'status':'incomplete','verified':False})
        try:
            gui=gui_location(gui_executable)
            for stage in ('build','reopen'):
                result=gui_process.run(directory,gui,stage,timeout=remaining_timeout(timeout));check_observation(prepared,result['observed'])
            motion={'units':prepared['units'],'law':prepared['law'],'initialPose':poses(prepared,0),
                'samples':[{'timeSeconds':prepared['durationSeconds']*i/prepared['intervals'],'placements':poses(prepared,i/prepared['intervals'])}
                           for i in range(prepared['intervals']+1)]}
            atomic_json(directory/'motion.json',motion)
            artifacts=[{'file':str(directory/name),'kind':kind,'sha256':file_digest(directory/name),**extra}
                for name,kind,extra in [('model.FCStd','cadScene',{'units':'mm'}),('motion.json','text',{})]]
            atomic_json(directory/'verification.json',{'artifacts':artifacts,'runtime':'1.1.4'})
            result=_verify(directory,False,gui_executable=gui);remaining_timeout(timeout);result['status']='succeeded';atomic_json(directory/'result.json',result);return result
        except Exception as error:
            from schemaxis.core.faults import SchemaxisError,Fault
            fault=error.fault if isinstance(error,SchemaxisError) else Fault('NATIVE_EXECUTION_FAILED',str(error),'mechanism','native')
            atomic_json(directory/'result.json',{'status':'failed','verified':False,'fault':fault.to_dict()})
            if isinstance(error,SchemaxisError):raise
            raise SchemaxisError(fault) from error


from schemaxis.adaptor_runtime import bind as _bind_runtime
_bind_runtime(globals())
