"""Refreshed-hash material/link/index attacks and unchanged native save controls."""
import argparse,hashlib,json,subprocess
from pathlib import Path
from schemaxis.artifacts import runtime_archive
from schemaxis.assessments import source_fingerprint
from blender_tamper import qualify


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--blender',required=True);parser.add_argument('--suite',type=Path,required=True);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    report={'status':'running','providerCommit':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),'sourceFingerprint':source_fingerprint('blender'),'runtimeArchiveSha256':hashlib.sha256(runtime_archive()).hexdigest(),'qualifierSha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'cases':[],'controls':[]}
    def run(label,mutations,preamble=''):
        result=qualify(args.blender,[(label,args.suite/label)],mutations,preamble)
        report['cases']+=result['cases'];report['controls']+=result['controls'];args.output.write_text(json.dumps(report,indent=2)+'\n')
    try:
        run('linked-palette-cycles',{
            'faceIndex':"mesh.polygons[1].material_index=0",
            'dataSlotOrder':"mesh.materials[0],mesh.materials[1]=mesh.materials[1],mesh.materials[0]",
            'objectPalettePointer':"other.material_slots[0].material=bpy.data.materials['yellow']",
            'objectSlotLink':"other.material_slots[0].link='DATA'",
            'unrelatedOwnerSlot':"patch.material_slots[0].link='OBJECT';patch.material_slots[0].material=bpy.data.materials['green']",
            'equalGeometryWrongData':"other.data=mesh.copy()",
            'unrequestedSharedOwner':"extra=patch.copy();extra.name='unexpectedOwner';bpy.context.scene.collection.objects.link(extra)",
        },"patch=bpy.data.objects['patch'];other=bpy.data.objects['other'];mesh=patch.data\n")
        run('named-splines',{'splineRegionIndex':"bpy.data.objects['patch'].data.splines[1].material_index=0"})
        run('unicode-text',{'characterRegionIndex':"bpy.data.objects['patch'].data.body_format[2].material_index=0"})
        run('linked-per-face-captured-images',{'overrideDisplayImage':"bpy.data.materials['green'].node_tree.nodes['__schemaxis_display_texture'].image=bpy.data.images['yellowImage']"})
        report['status']='passed'
    finally:
        if report['status']=='running':report['status']='failed'
        args.output.write_text(json.dumps(report,indent=2)+'\n')


if __name__=='__main__':main()
