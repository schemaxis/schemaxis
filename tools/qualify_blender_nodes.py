"""Run inside qualified Blender: save/reopen every reviewed node constructor."""
import json
import sys
from pathlib import Path
import bpy
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from schemaxis.adaptors.blender.node_catalogue import CATALOGUES,validate_graph
from schemaxis.adaptors.blender.node_native import build,observe
from schemaxis.adaptors.blender.settings import matching


def main():
    output=Path(sys.argv[sys.argv.index('--')+1]).absolute();output.mkdir(parents=True,exist_ok=False)
    image=bpy.data.images.new('texture',width=1,height=1);image.pixels=[.2,.4,.8,1];image.pack()
    material=bpy.data.materials.new('paint');material.use_nodes=True
    specs=[];failures=[]
    for family,catalogue in CATALOGUES.items():
        for kind in catalogue:
            graph={'id':family+'-'+kind,'nodes':[{'id':'reviewed','kind':kind}]+([] if kind=='output' else [{'id':'out','kind':'output'}]),'links':[]}
            if kind=='image':graph['nodes'][0]['properties']={'image':'texture'}
            if kind=='setMaterial':graph['nodes'][0]['values']={'material':'paint'}
            try:
                graph=validate_graph(graph,family,'graph');owner=build(graph,family,{'texture':image},{'paint':material});owner.use_fake_user=True
                actual=observe(graph,family);assert matching(actual,graph),(actual,graph);specs.append((family,graph))
            except Exception as e:failures.append({'family':family,'kind':kind,'error':str(e)})
    if failures:raise AssertionError(failures)
    path=output/'node-catalogue.blend';bpy.ops.wm.save_as_mainfile(filepath=str(path));bpy.ops.wm.open_mainfile(filepath=str(path),use_scripts=False)
    for family,graph in specs:assert matching(observe(graph,family),graph),graph['id']
    (output/'summary.json').write_text(json.dumps({'status':'passed','constructors':len(specs),'families':{f:len(c) for f,c in CATALOGUES.items()},'scope':'every reviewed constructor/default/property/socket literal readback and native save/reopen; graph effects covered separately by production cases'},indent=2)+'\n');print('NODE_CATALOGUE_PASS',len(specs))

if __name__=='__main__':main()
