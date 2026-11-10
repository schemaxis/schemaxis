"""Instrument actual native construction to detect premature scene evaluation.

The marker controls isolate order; ordinary public constructor qualifications
separately establish successful geometry and readback. No large curve is evaluated.
"""
import argparse,json
from pathlib import Path
from qualify_blender_mesh_data import native
from qualify_blender_splines import curve,point
from schemaxis.adaptors.blender.production import validate
from schemaxis.artifacts import runtime_archive


def main():
    p=argparse.ArgumentParser();p.add_argument('--blender',required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();out=a.output.absolute();out.mkdir(parents=True,exist_ok=False)
    shape=curve('sweep',[point(i,i%2) for i in range(16)],'BEZIER',sampling={'preview':1,'render':1},bevel={'kind':'round','depth':.1,'resolution':0})
    spec=validate({'objects':[shape],'materialBindings':[{'object':'sweep','material':'paint'}]},{'paint':{'filter':'material'}})
    source=out/'spec.json';source.write_text(json.dumps(spec,indent=2)+'\n');archive=out/'runtime.zip';archive.write_bytes(runtime_archive());target=out/'summary.json'
    script=f'import sys\nsys.path.insert(0,{str(archive)!r})\n'+'''import bpy,json,copy
from pathlib import Path
from schemaxis.adaptors.blender.production_native import Production
from schemaxis.adaptors.blender import mesh_data_native,production_output_native
from schemaxis.errors import SchemaxisError
class MarkerReached(Exception):pass
'''+f'spec=json.loads(Path({str(source)!r}).read_text())\n'+'''
original_build=mesh_data_native.build;original_resolve=production_output_native._resolved_geometry;checks=[]
for mode in ('oversized-before-mesh-operators','expansion-before-material-evaluation','unchanged-small-reaches-material'):
 bpy.ops.wm.read_factory_settings(use_empty=True);current=copy.deepcopy(spec);material=bpy.data.materials.new('paint')
 if mode=='oversized-before-mesh-operators':current['objects'][0].update(sampling={'preview':1024,'render':1024},bevel={'kind':'round','depth':.1,'resolution':32})
 def mesh_data(*args,**kwargs):
  if mode=='oversized-before-mesh-operators':raise MarkerReached('mesh operators reached before oversized admission')
  result=original_build(*args,**kwargs)
  if mode=='expansion-before-material-evaluation':
   data=bpy.data.objects['sweep'].data;data.resolution_u=1024;data.render_resolution_u=1024;data.bevel_resolution=32
  return result
 def resolution(*args,**kwargs):raise MarkerReached('material evaluation reached')
 mesh_data_native.build=mesh_data;production_output_native._resolved_geometry=resolution
 try:Production(current,{'paint':material},{})
 except SchemaxisError as error:
  assert mode!='unchanged-small-reaches-material' and error.fault.code=='RESOURCE_BUDGET_EXCEEDED',error.fault.to_dict()
  checks.append({'case':mode,'fault':error.fault.to_dict()})
 except MarkerReached as error:
  assert mode=='unchanged-small-reaches-material',str(error)
  checks.append({'case':mode,'positiveControl':str(error)})
 else:raise AssertionError('instrumentation did not observe the intended construction boundary')
 finally:mesh_data_native.build=original_build;production_output_native._resolved_geometry=original_resolve
'''+f'Path({str(target)!r}).write_text(json.dumps({{"status":"passed","scope":"native construction-order instrumentation; no large curve evaluation","checks":checks}},indent=2)+"\\n")\n'
    native(a.blender,script);print(json.dumps({'status':'passed','earlyRefusals':2,'reachableControl':1}))

if __name__=='__main__':main()
