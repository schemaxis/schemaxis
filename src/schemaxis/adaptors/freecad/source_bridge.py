"""Portable imported-solid history authority, without submitted document restore.

Planning reads bounded embedded original geometry and recompiles the authored
typed graph. Before native source capture/copy, the installed host reconstructs
that graph independently and binds the entire submitted archive to it.
"""
from contextlib import contextmanager
import copy,tempfile
from pathlib import Path
from schemaxis.errors import fail
from .source_assets import descriptors,verify_members
from .step_source import checkpoint,consistent

BODY_HISTORY='schemaxis.freecad.body-history/1'
PRIMITIVES={'box','cylinder','cone','cut','fuse'}


def capability(facts):
    """One finite replay record; legacy seeded serialization stays unchanged."""
    if not isinstance(facts,dict):return None
    keys=[key for key in ('seedHistory','bodyHistory') if key in facts]
    if len(keys)>1:fail('UNSUPPORTED_SOURCE','Source has conflicting typed history contracts')
    return keys[0] if keys else None


def requires_copy_regeneration(facts):
    """Keep legacy gen1 direct binding; opt in only a compiled pure Body record.

    This selects the copy binder, never source admission. Every caller still
    requires complete retained source authority before a native restore. Gen2
    preserves its existing independently admitted regeneration contract.
    """
    if not isinstance(facts,dict):fail('UNSUPPORTED_SOURCE','Copy regeneration source facts must be an object')
    key=capability(facts)
    if facts.get('generation')==2:return True
    if key!='bodyHistory':return False
    history=facts[key]
    if (type(facts.get('generation',1)) is not int or facts.get('generation',1)!=1
            or not isinstance(history,dict) or set(history)!={'version','authored','definition'}
            or history['version']!=BODY_HISTORY or facts.get('sourceFrame')!='bodyLocal'):
        fail('UNSUPPORTED_SOURCE','Generation1 copy regeneration needs its finite typed Body contract')
    from .adaptor import _native_plan
    prepared=_native_plan(history['authored'])
    selected_body(prepared)
    if (prepared['partDesign'].get('generation',1)!=1 or prepared!=history['definition']
            or record(history['authored'],prepared)!={'bodyHistory':history,'sourceFrame':'bodyLocal'}):
        fail('UNSUPPORTED_SOURCE','Generation1 copy regeneration definition differs from typed intent')
    return True


def selected_body(prepared):
    history=prepared.get('partDesign')
    if not isinstance(history,dict):fail('UNSUPPORTED_SOURCE','Source needs a typed Body history')
    if history.get('generation',1)==1:
        selected=history
        if {n['id'] for n in prepared['nodes']}!=set(history['members'])|{history['body']}:
            fail('UNSUPPORTED_SOURCE','Generation1 history contains geometry outside its Body')
    elif history['generation']==2:
        owner=history['owners'].get(prepared['output'])
        if owner not in history['bodies']:fail('UNSUPPORTED_SOURCE','Output is not an owned Body feature')
        selected={'body':owner,**history['bodies'][owner]}
        external=[n for n in prepared['nodes'] if n['id'] not in history['owners'] and n['filter']!='body']
        if any(n['filter'] not in {'importSTEP','importMesh'}|PRIMITIVES for n in external):
            fail('UNSUPPORTED_SOURCE','External Part source is outside the finite portable history vocabulary')
        if external and not history.get('seeds'):fail('UNSUPPORTED_SOURCE','Unseeded Body source has external geometry')
    else:fail('UNSUPPORTED_SOURCE','Unknown typed Body history generation')
    if selected.get('tip')!=prepared['output']:fail('UNSUPPORTED_SOURCE','Source must publish its selected final Body tip')
    return selected


class EmbeddedSources:
    replay=True

    def __init__(self,path,definition):
        from .source_envelope import read_members
        if (not isinstance(definition,dict) or not isinstance(definition.get('nodes'),list)
                or not 1<=len(definition['nodes'])<=200 or any(not isinstance(n,dict) or not isinstance(n.get('filter'),str) for n in definition['nodes'])):
            fail('UNSUPPORTED_SOURCE','Seeded history definition is malformed',str(path))
        for node in definition['nodes']:
            if node['filter'] in ('importSTEP','importMesh') and (not isinstance(node.get('source'),dict) or not isinstance(node.get('options'),dict) or not isinstance(node.get('frame'),dict)):
                fail('UNSUPPORTED_SOURCE','Seeded import descriptor is malformed',str(path))
        self.members=read_members(path,str(path),'UNSUPPORTED_SOURCE')
        self.assets={item['id']:item for item in descriptors(definition).values()}

    def read(self,value,identity,location):
        item=self.assets.get(identity)
        if item is None or not consistent(value,item['source']['path']):
            fail('UNSUPPORTED_SOURCE','Seeded history source identity differs from typed original',location)
        data=self.members.get(item['member'])
        if data is None:fail('UNSUPPORTED_SOURCE','Seeded history original geometry payload is absent',location)
        from .source_assets import admit
        admit(data,item,location)
        return item['source']['path'],data


def record(authored,definition):
    """Keep the finite source contract visibly distinct from earlier histories."""
    from .body_seed import active
    if 'partDesign' not in definition:return {}
    selected_body(definition)
    history=definition['partDesign']
    legacy=active(definition) and all(n['filter'] in ('importSTEP','importMesh') for n in definition['nodes']
        if n['id'] not in history['owners'] and n['filter']!='body')
    saved={'authored':copy.deepcopy(authored),'definition':copy.deepcopy(definition)}
    if legacy:return {'sourceFrame':'bodyLocal','seedHistory':saved}
    return {'sourceFrame':'bodyLocal','bodyHistory':{'version':BODY_HISTORY,**saved}}


def definition(path,facts):
    from .adaptor import _native_plan
    key=capability(facts);history=facts.get(key) if key else None
    expected={'authored','definition'}|({'version'} if key=='bodyHistory' else set())
    if (not isinstance(history,dict) or set(history)!=expected
            or key=='bodyHistory' and history['version']!=BODY_HISTORY):
        fail('UNSUPPORTED_SOURCE','Seeded source has no finite typed history contract',str(path))
    original=history['definition']
    prepared=_native_plan(history['authored'],source=EmbeddedSources(path,original))
    if prepared!=original or record(history['authored'],prepared)!={key:history,'sourceFrame':facts.get('sourceFrame')}:
        fail('UNSUPPORTED_SOURCE','Seeded source typed definition differs from its embedded original inputs',str(path))
    return prepared


def policy(path,facts,properties,extensions,transient,vocabulary):
    """Extend only this recognizable finite case, leaving older vocabularies exact."""
    prepared=definition(path,facts)
    if facts.get('generation',1)!=prepared['partDesign'].get('generation',1):fail('UNSUPPORTED_SOURCE','Body history generation differs',str(path))
    if not prepared['partDesign'].get('seeds'):
        return prepared,properties,extensions,transient,vocabulary
    common={'ExpressionEngine':'App::PropertyExpressionEngine','Label':'App::PropertyString','Label2':'App::PropertyString',
            'Placement':'App::PropertyPlacement','Shape':'Part::PropertyPartShape','ShapeMaterial':'Materials::PropertyMaterial','Visibility':'App::PropertyBool'}
    feature={**common,'SourceSHA256':'App::PropertyString','SourceAsset':'App::PropertyFileIncluded'}
    seed={**common,'BaseFeature':'App::PropertyLink','Suppressed':'App::PropertyBool','SuppressedShape':'Part::PropertyPartShape'}
    properties={**properties,'Part::Feature':feature,'Part::Refine':{**common,'Source':'App::PropertyLink'},'PartDesign::FeatureBase':seed}
    extensions={**extensions,'Part::Feature':[],'Part::Refine':[],'PartDesign::FeatureBase':['App::SuppressibleExtension','Part::PreviewExtension']}
    t={'_ElementMapVersion':'App::PropertyString'}
    transient={**transient,'Part::Feature':t,'Part::Refine':t,'PartDesign::FeatureBase':{**t,'PreviewShape':'Part::PropertyPartShape','_Body':'App::PropertyLinkHidden'}}
    from .body_history_source_policy import extend
    properties,extensions,transient=extend(prepared,properties,extensions,transient)
    return prepared,properties,extensions,transient,({**vocabulary,'FileIncluded':[{'file'}]} if descriptors(prepared) else vocabulary)


def inline_seed_history(prepared,root,location,code):
    """Recognize the seed-only native graph that emits an empty inline table."""
    nodes={node['id']:node for node in prepared['nodes']}
    history=prepared.get('partDesign',{})
    if (not history.get('seeds') or nodes[prepared['output']]['filter']!='bodySeed'
            or any(node['filter'] not in {'importMesh','importSTEP','body','bodySeed'}|PRIMITIVES for node in nodes.values())
            or any(body['members']!=[body['tip']] or nodes[body['tip']]['filter']!='bodySeed'
                   for body in history['bodies'].values())):
        fail(code,'Empty inline strings require the finite checked-import seed-only history',location)
    from .part_reconstruction import empty_inline_table
    try:empty_inline_table(root)
    except ValueError as error:fail(code,str(error),location)
    return True


def bind_inline_copy(prepared,path,root,retained,regenerated):
    """A table-less assembly is admitted only for independently closed seed-only sources."""
    if not prepared.get('parts') or regenerated is None:
        raise ValueError('Inline source copies require fresh complete regeneration')
    from .source_envelope import inspect,read_members
    from .assembly_sources import envelope_facts
    from .document_xml import Document
    from .part_reconstruction import bind_literal_payloads
    for part in prepared['parts']:
        facts=part['source'];source=retained[part['id']]
        if facts.get('generation')!=2 or not capability(facts):
            raise ValueError('Inline source copy is outside the admitted seed-only family')
        inspect(source,envelope_facts(facts),part['id'],'VERIFICATION_FAILED')
        inline_seed_history(definition(source,facts),Document(source).root,part['id'],'VERIFICATION_FAILED')
    expected=Path(regenerated)/'model.FCStd'
    bind_literal_payloads(read_members(path,'model.FCStd','VERIFICATION_FAILED'),root,
                          read_members(expected,'regenerated.FCStd','VERIFICATION_FAILED'),Document(expected).root)


@contextmanager
def originals(path,prepared):
    """Extract admitted source bytes to host-owned finite paths for fresh replay."""
    from .source_envelope import read_members
    from .document_xml import Document
    members=read_members(path,str(path),'VERIFICATION_FAILED');assets=descriptors(prepared)
    verify_members(members,Document(path).root,assets,str(path))
    with tempfile.TemporaryDirectory(prefix='schemaxis-freecad-originals-') as temporary:
        directory=Path(temporary);captured={};size=0
        for item in assets.values():
            checkpoint();size+=len(members[item['member']])
            if size>64*1024*1024:fail('RESOURCE_LIMIT','Included original geometry exceeds 64 MiB aggregate',str(path))
            target=directory/item['member'];target.write_bytes(members[item['member']])
            captured[item['id']]={'file':item['source']['path'],'retained':str(target),'sha256':item['source']['sha256'],
                                  'bytes':item['source']['bytes'],'route':item['route']}
        yield captured


def verify_before_open(path,facts,*,executable=None):
    if not capability(facts):return
    from .assembly_sources import digest
    def unchanged():
        checkpoint()
        try:matches=Path(path).stat().st_size==facts['bytes'] and digest(path)==facts['sha256']
        except OSError:matches=False
        if not matches:fail('INPUT_CHANGED','Retained source changed across trusted reconstruction',str(path))
        checkpoint()
    unchanged()
    prepared=definition(path,facts)
    from .part_reconstruction import verify
    from schemaxis.configuration import location_context
    with originals(path,prepared) as captured:
        if executable is None:local=verify(path,prepared,captured,body_local=True)
        else:
            with location_context({'freecad':executable}):local=verify(path,prepared,captured,body_local=True)
    from .assembly_sources import close
    if not isinstance(local,dict) or local.get('frame')!='bodyLocal' or any(not close(local.get('shape',{}).get(key),facts.get(key)) for key in ('volume','area','bounds')):
        fail('VERIFICATION_FAILED','Source Body-local facts differ from fresh trusted geometry',str(path))
    unchanged()
    checkpoint()


def retained_facts(path,facts,authored_source):
    """Validate a captured source definition without its retired producer packet.

    Original geometry and typed source intent are captured input authority.
    Shape witnesses still require verify_before_open's fresh physical binding.
    """
    from .assembly_sources import digest,envelope_facts,_finite,_vector
    from .source_envelope import inspect
    from .part_design import names,verify_auxiliaries
    from .part_design_saved import verify as verify_history
    from .operations import extra_objects
    from .adaptor import DECLARATIONS
    from .parameters import object_type
    import re
    key=capability(facts)
    required={'file','sha256','run','bytes','expandedBytes','receiptSha256','body','tip','members','labels','objects',
              'xyPlane','varset','parameters','volume','area','bounds','profile','sourceFrame',key}
    if facts.get('generation')==2:required.add('generation')
    if not isinstance(facts,dict) or set(facts)-{'spreadsheet'}!=required:
        fail('VERIFICATION_FAILED','Retained seeded source descriptor fields differ',str(path))
    if (authored_source!=facts['file'] or str(Path(facts['file']).parent)!=facts['run']
            or Path(facts['file']).name!='model.FCStd' or not Path(facts['file']).is_absolute()
            or not isinstance(facts['receiptSha256'],str) or not re.fullmatch('[0-9a-f]{64}',facts['receiptSha256'])
            or Path(path).stat().st_size!=facts['bytes'] or digest(path)!=facts['sha256']):
        fail('VERIFICATION_FAILED','Retained seeded source identity differs from capture',str(path))
    prepared=definition(path,facts);observed=verify_history(prepared,path)
    mapped=names(prepared);history=prepared['partDesign'];body=selected_body(prepared);owner=body['body']
    generation=history.get('generation',1)
    objects={mapped[n['id']]:DECLARATIONS[n['filter']]['native'] for n in prepared['nodes']}
    objects.update(extra_objects(prepared));objects.update(verify_auxiliaries(prepared,observed['auxiliaries']))
    parameters={k:{f:v[f] for f in ('value','minimum','maximum')} for k,v in prepared.get('parameters',{}).items()}
    if parameters:objects['SchemaxisParameters']=object_type(prepared)
    expected={'body':mapped[owner],'tip':mapped[prepared['output']],'members':[mapped[n] for n in body['members']],
              'labels':{mapped[n['id']]:n['id'] for n in prepared['nodes']},'objects':dict(sorted(objects.items())),
              'xyPlane':(observed['auxiliaries'][owner] if generation==2 else observed['auxiliaries'])['XY_Plane']['name'],'parameters':parameters,
              'varset':'SchemaxisParameters' if parameters else None,
              **({'profile':'designHistory','generation':2} if generation==2 else {'profile':next(n['filter'] for n in prepared['nodes']
                  if n['id']==next(n['inputs']['profile'] for n in prepared['nodes'] if n['filter']=='pad'))}),
              **record(facts[key]['authored'],prepared)}
    if any(facts[k]!=v for k,v in expected.items()) or facts.get('spreadsheet')!=prepared.get('spreadsheet'):
        fail('VERIFICATION_FAILED','Retained source descriptor differs from typed history',str(path))
    envelope=inspect(path,envelope_facts(facts),str(path),'VERIFICATION_FAILED')
    if facts['expandedBytes']!=envelope['expandedBytes'] or not _finite(facts['volume']) or facts['volume']<=0 or not _finite(facts['area']) or not _vector(facts['bounds'],6):
        fail('VERIFICATION_FAILED','Retained source geometry witness or archive budget is malformed',str(path))
    return copy.deepcopy(facts)


def replay_plan(directory,authored,saved):
    """Replan seeded sources from finite run-owned captures, never old paths."""
    from . import assembly
    parts=saved.get('parts',[]) if isinstance(saved,dict) else []
    if (isinstance(saved,dict) and saved.get('sourced') is True and isinstance(parts,list)
            and any(isinstance(p,dict) and isinstance(p.get('source'),dict) and not capability(p['source']) for p in parts)):
        fail('RERUN_REQUIRED','This older assembly lacks captured typed Body intent; recapture it while the producer is available',str(directory))
    if not isinstance(parts,list) or not any(isinstance(p,dict) and capability(p.get('source')) for p in parts):
        return assembly.plan(authored)
    from schemaxis.documents import resolve_document
    resolved,_=resolve_document(copy.deepcopy(authored));inputs=resolved.get('parts')
    if not isinstance(inputs,list) or len(inputs)!=len(parts) or len(parts)>assembly.MAX_COMPONENTS:
        fail('VERIFICATION_FAILED','Retained source part membership differs',str(directory))
    from .assembly_sources import check_archive
    admitted={}
    for index,(part,item) in enumerate(zip(parts,inputs)):
        checkpoint()
        if not isinstance(part,dict) or not isinstance(item,dict) or part.get('id')!=item.get('id'):
            fail('VERIFICATION_FAILED','Retained source part identity differs',str(directory))
        if not capability(part.get('source')):continue
        # The stored native path is untrusted. Select the capture by the same
        # finite array-index naming policy used by native_names, then replan
        # the entire document and compare the stored native map afterward.
        path=Path(directory)/'sources'/('source'+str(index)+'.FCStd')
        check_archive(path,str(path),code='VERIFICATION_FAILED')
        admitted[part['id']]=retained_facts(path,part['source'],item.get('source'))
    prepared=assembly._native_plan(authored,source_facts=admitted)
    if prepared!=saved:fail('VERIFICATION_FAILED','Retained assembly plan differs from authored intent',str(directory))
    return prepared
