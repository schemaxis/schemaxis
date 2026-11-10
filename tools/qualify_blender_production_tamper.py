"""Reject refreshed-hash native project edits using trusted fresh verification."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
from schemaxis.adaptors.blender.adaptor import verify
from schemaxis.configuration import location_context
from schemaxis.core.faults import SchemaxisError


def main():
    p=argparse.ArgumentParser();p.add_argument('--blender',required=True);p.add_argument('--run',required=True);p.add_argument('--output',required=True);a=p.parse_args();directory=Path(a.run).absolute();receipt_path=directory/'verification.json';blend=directory/'0000.blend';original=blend.read_bytes();receipt_bytes=receipt_path.read_bytes()
    with location_context({'blender':a.blender}):assert verify(directory)['verified']
    try:
        with tempfile.TemporaryDirectory(prefix='schemaxis-production-mutation-') as temp:
            script=Path(temp)/'mutate.py';script.write_text('import bpy\n'+f'bpy.ops.wm.open_mainfile(filepath={str(blend)!r},use_scripts=False)\n'+"obj=bpy.data.objects['motion']\nfor layer in obj.animation_data.action.layers:\n for strip in layer.strips:\n  bag=strip.channelbag(obj.animation_data.action_slot)\n  for curve in bag.fcurves:\n   if curve.data_path=='location' and curve.array_index==0:curve.keyframe_points[-1].co.y=9\n"+f'bpy.ops.wm.save_as_mainfile(filepath={str(blend)!r})\n')
            subprocess.run([a.blender,'--background','--factory-startup','--disable-autoexec','--python-exit-code','1','--python',str(script)],check=True,timeout=60,capture_output=True)
        receipt=json.loads(receipt_bytes)
        for artifact in receipt['artifacts']:
            if artifact['file']==str(blend):artifact['sha256']=hashlib.sha256(blend.read_bytes()).hexdigest()
        receipt_path.write_text(json.dumps(receipt,indent=2)+'\n')
        rejected=None
        with location_context({'blender':a.blender}):
            try:verify(directory)
            except SchemaxisError as error:rejected=error.fault.code
        assert rejected=='VERIFICATION_FAILED',rejected
        Path(a.output).write_text(json.dumps({'status':'passed','mutation':'changed native animation endpoint and refreshed scene hash; retained evidence unchanged','fault':rejected,'trustedRuntime':True},indent=2)+'\n');print('REFRESHED_HASH_PROJECT_TAMPER_REJECTED')
    finally:
        blend.write_bytes(original);receipt_path.write_bytes(receipt_bytes)

if __name__=='__main__':main()
