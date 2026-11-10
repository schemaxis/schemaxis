"""Current native spline/control mutations with identical unchanged-save positives."""
import argparse,json
from pathlib import Path
from blender_tamper import qualify


def main():
    p=argparse.ArgumentParser();p.add_argument('--blender',required=True);p.add_argument('--suite',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();root=a.suite.absolute();records=[]
    cases=[('cubic-analytic',{'explicitHandle':"bpy.data.objects['arch'].data.splines[0].bezier_points[0].handle_right.y+=.25",'unexpectedRadius':"bpy.data.objects['arch'].data.splines[0].bezier_points[0].radius=.75"}),
     ('rational-quarter',{'interiorWeightSameBounds':"bpy.data.objects['quarter'].data.splines[0].points[1].weight=.5",'knotEndpoint':"bpy.data.objects['quarter'].data.splines[0].use_endpoint_u=False",'unsampledRenderResolution':"bpy.data.objects['quarter'].data.render_resolution_u=128"}),
     ('gasket-even-odd-same-winding',{'fillRule':"bpy.data.objects['gasket'].data.fill_rule='NONZERO'",'contourMembership':"bpy.data.objects['gasket'].data.splines.remove(bpy.data.objects['gasket'].data.splines[1])"}),
     ('rectangle-profile',{'wrongProfilePointer':"source=bpy.data.objects['section'];other=source.copy();other.data=source.data.copy();bpy.context.scene.collection.objects.link(other);bpy.data.objects['sweep'].data.bevel_object=other",'trim':"bpy.data.objects['sweep'].data.bevel_factor_end=.75",'sectionDirection':"s=bpy.data.objects['section'].data.splines[0];co=[list(p.co) for p in s.points][::-1]\nfor p,c in zip(s.points,co):p.co=c"}),
     ('linear-taper-frustum',{'taperCombination':"bpy.data.objects['cable'].data.taper_radius_mode='ADD'",'taperCoordinate':"bpy.data.objects['taper'].data.splines[0].points[1].co.y=3"}),
     ('mixed-edge-scales',{'shortEdgePosition':"bpy.data.objects['edgeScales'].data.splines[0].points[1].co.x=1e9+256"}),
     ('mixed-scale-splines',{'smallSplinePosition':"bpy.data.objects['mixed'].data.splines[1].points[1].co.x=.0005"}),
     ('automatic-handles',{'handlePolicy':"bpy.data.objects['auto'].data.splines[0].bezier_points[0].handle_right_type='FREE'"}),
     ('profile-chamfer',{'customProfilePoint':"p=bpy.data.objects['profile'].data.bevel_profile;p.points[1].location=(.9,.5);p.update()",'profileSampling':"bpy.data.objects['profile'].data.bevel_profile.use_sample_even_lengths=True"})]
    for label,mutations in cases:records.append(qualify(a.blender,[(label,root/label)],mutations))
    report={'status':'passed','cases':[r for record in records for r in record['cases']],'controls':[r for record in records for r in record['controls']]};a.output.write_text(json.dumps(report,indent=2)+'\n');print(json.dumps({'status':'passed','mutations':len(report['cases']),'controls':len(report['controls'])}))

if __name__=='__main__':main()
