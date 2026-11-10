"""Bound expansion before launch; render useful small shared nested shaders."""
import argparse
import copy
import hashlib
import json
import subprocess
from pathlib import Path
from schemaxis.adaptors.blender.adaptor import run, _verify
from schemaxis.artifacts import runtime_archive
from schemaxis.assessments import source_fingerprint
from schemaxis.configuration import location_context
from schemaxis.errors import SchemaxisError
from qualify_blender_material_assignments import fixture
from qualify_blender_render_policy import expected
from qualify_blender_image_preview import rgba
from qualify_blender_mesh_data import native


def link(a,socket,b,target):
    return {'from':{'node':a,'socket':socket},'to':{'node':b,'socket':target}}


def document(level, colour, doubling=True):
    d=fixture();p=d['production'];p['nodeGroups']=[]
    for i in range(level+1):
        if i==0:
            nodes=[{'id':'light','kind':'emission','values':{'colour':[*colour,1]}},
                   {'id':'out','kind':'output'}]
            links=[link('light','shader','out','surface')]
        else:
            nodes=[{'id':'left','kind':'group','group':'g'+str(i-1)}, {'id':'out','kind':'output'}]
            links=[link('left','surface','out','surface')]
            if doubling:
                nodes.extend([{'id':'right','kind':'group','group':'g'+str(i-1)},
                              {'id':'mix','kind':'mixShader','values':{'factor':.25}}])
                links=[link('left','surface','mix','a'),link('right','surface','mix','b'),
                       link('mix','shader','out','surface')]
        p['nodeGroups'].append({'id':'g'+str(i),'family':'material','inputs':[],
            'outputs':[{'id':'surface','kind':'shader'}],'nodes':nodes,'links':links})
    p['materialGraphs'][0]['nodes']=[{'id':'nested','kind':'group','group':'g'+str(level)},
                                   {'id':'out','kind':'output'}]
    p['materialGraphs'][0]['links']=[link('nested','surface','out','surface')]
    return d


def consumer(source, level=None, count=1):
    d=document(level,[.2,.4,.6]) if level is not None else fixture()
    d['prepareOnly']=True;d['visible']=['asset0'];p=d['production']
    p['objects']=[];p['materialAssignments']=[]
    if level is None:p['materialGraphs']=[]
    p['assets']=[{'id':'asset'+str(i),'file':str(source),'format':'blend'} for i in range(count)]
    return d


def main():
    p=argparse.ArgumentParser();p.add_argument('--blender',required=True)
    p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    out=a.output.absolute();out.mkdir(parents=True,exist_ok=False)
    source=source_fingerprint('blender');archive=hashlib.sha256(runtime_archive()).hexdigest()
    report={'status':'running','providerCommit':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
        'sourceFingerprint':source,'runtimeArchiveSha256':archive,'checks':[]}
    def write():(out/'summary.json').write_text(json.dumps(report,indent=2)+'\n')
    try:
        for level,colour in ((4,[.2,.4,.6]),(7,[.7,.18,.05])):
            packet=out/('nested-'+str(level));run(document(level,colour),packet,executable=a.blender,timeout=240)
            with location_context({'blender':a.blender}):assert _verify(packet)['verified']
            actual=rgba(packet,[(27,16),(37,16)]);wanted=[expected(c,0) for c in (colour,[0,0,1])]
            assert all(abs(x-y)<=1 for row,ref in zip(actual,wanted) for x,y in zip(row,ref)),(actual,wanted)
            report['checks'].append({'case':'nested-'+str(level),'encodedRGBA':actual,
                'independentExpectedRGBA':wanted,'literalLeafOccurrences':2**level});write()
        cases={'repeated-expansion':document(11,[.2,.4,.6]),
               'unused-group-depth':document(32,[.2,.4,.6],False),
               'aggregate-material-expansion':document(10,[.2,.4,.6])}
        cases['unused-group-depth']['production']['materialGraphs'][0]['nodes'][0]['group']='g0'
        aggregate=cases['aggregate-material-expansion']['production']['materialGraphs']
        aggregate[1]['nodes']=copy.deepcopy(aggregate[0]['nodes'])
        aggregate[1]['links']=copy.deepcopy(aggregate[0]['links'])
        for label,value in cases.items():
            packet=out/label;fault=None
            try:run(value,packet,executable=a.blender,timeout=240)
            except SchemaxisError as exc:fault=exc.fault.to_dict()
            assert fault and fault['code']=='RESOURCE_BUDGET_EXCEEDED' and not packet.exists(),fault
            report['checks'].append({'case':label,'fault':fault,'nativeOutputDirectoryAbsent':True});write()
        # These graphs allocate only a few dozen actual nodes. prepareOnly
        # avoids compiling a large shader as a resource-exhaustion experiment.
        for level in (4,10):
            d=document(level,[.2,.4,.6]);d['prepareOnly']=True
            source_packet=out/('source-'+str(level))
            run(d,source_packet,executable=a.blender,timeout=240)
            source_file=source_packet/'0000.blend'
            for kind,value in [('two-assets',consumer(source_file,count=2)),
                               ('asset-and-authored',consumer(source_file,level=level))]:
                label=kind+'-'+str(level);packet=out/label;fault=None
                try:run(value,packet,executable=a.blender,timeout=240)
                except SchemaxisError as exc:fault=exc.fault.to_dict()
                if level==4:
                    assert fault is None,fault
                    with location_context({'blender':a.blender}):assert _verify(packet)['verified']
                else:
                    assert fault and fault['code']=='RESOURCE_BUDGET_EXCEEDED',fault
                    assert 'aggregate' in fault['message'],fault
                report['checks'].append({'case':label,'fault':fault,'prepareOnly':True,
                    'separatelyAdmittedSource':str(source_packet),
                    'expectedAccepted':level==4,'literalSourceLeafOccurrences':2**level});write()
        # Basic DAG materials are included even without a production envelope.
        d={'version':'schemaxis.blender/1','nodes':[{'id':'paint','filter':'material'},
            {'id':'box','filter':'cube','inputs':{'material':'paint'}}],
            'scenes':[{'id':'plain','visible':['box'],'prepareOnly':True,
                'images':[{'id':'view','size':[32,32],
                    'cameras':[{'direction':[0,0,1],'up':[0,1,0]}]}]}]}
        packet=out/'pure-dag-small';run(d,packet,executable=a.blender,timeout=240)
        with location_context({'blender':a.blender}):assert _verify(packet)['verified']
        report['checks'].append({'case':'pure-dag-small','accepted':True});write()
        blend=packet/'0000.blend';receipt=packet/'verification.json'
        originals={p:p.read_bytes() for p in (blend,receipt)}
        try:
            for label,mutation in [('unchanged-save',''),('hidden-subsurface-edit',
                    "bpy.data.materials['paint'].node_tree.nodes.get('Principled BSDF').inputs['Subsurface Weight'].default_value=.75")]:
                for path,value in originals.items():path.write_bytes(value)
                native(a.blender,'import bpy\n'+f'bpy.ops.wm.open_mainfile(filepath={str(blend)!r},use_scripts=False)\n'
                       +mutation+'\n'+f'bpy.ops.wm.save_as_mainfile(filepath={str(blend)!r})\n')
                value=json.loads(originals[receipt])
                next(x for x in value['artifacts'] if x['file']==str(blend))['sha256']=hashlib.sha256(blend.read_bytes()).hexdigest()
                receipt.write_text(json.dumps(value));fault=None
                with location_context({'blender':a.blender}):
                    try:_verify(packet)
                    except SchemaxisError as exc:fault=exc.fault.to_dict()
                assert (fault is None)==(label=='unchanged-save'),fault
                if fault:assert fault['code']=='VERIFICATION_FAILED',fault
                report['checks'].append({'case':'pure-dag-'+label,'fault':fault,
                    'nativeHashRefreshed':True,'retainedDescriptorUnchanged':True});write()
        finally:
            for path,value in originals.items():path.write_bytes(value)
        with location_context({'blender':a.blender}):assert _verify(packet)['verified']
        report['checks'].append({'case':'pure-dag-restored','accepted':True});write()
        assert source_fingerprint('blender')==source and hashlib.sha256(runtime_archive()).hexdigest()==archive
        report['status']='passed'
    finally:
        if report['status']=='running':report['status']='failed'
        write()


if __name__=='__main__':main()
