"""Finite qualifier-owned native observations/edits; no authored execution API."""
PROBE = r'''
import bpy,json,os
from pathlib import Path
from schemaxis.adaptors.blender.cache_fidelity_native import observe,inputs
bpy.ops.wm.open_mainfile(filepath=CONFIG['scene'],use_scripts=False)
scene=bpy.context.scene;scene.frame_set(1)
if CONFIG.get('edit'):
    if CONFIG['kind']=='rigidBody':bpy.data.objects['Faller'].rigid_body.mass=2
    else:bpy.data.objects['Sheet'].modifiers['schemaxis-cloth'].settings.mass=2
    bpy.context.preferences.filepaths.save_version=0
    bpy.ops.wm.save_as_mainfile(filepath=CONFIG['scene'],check_existing=False)
result={'pid':os.getpid(),'inputFingerprint':inputs(scene),
        'geometry':observe(scene,CONFIG['objects'],CONFIG['frames'])}
Path(CONFIG['output']).write_text(json.dumps(result,indent=2)+'\n')
'''


def literal_geometry(records, kind):
    """Known initial coordinates/pins and bounded freefall, not native witnesses."""
    import math
    if set(records)!={str(i) for i in range(1,11)}:raise ValueError('literal frame membership differs')
    expected_names={'Faller','Floor'} if kind=='rigidBody' else {'Sheet'}
    for frame, row in records.items():
        if set(row)!=expected_names:raise ValueError('literal physical consumer membership differs')
        for item in row.values():
            matrix=item['matrix'];points=item['vertices']
            if len(matrix)!=4 or any(len(r)!=4 for r in matrix):raise ValueError('world matrix shape differs')
            if any(len(v)!=3 for v in points):raise ValueError('world vertex shape differs')
            if not all(type(v) in (int,float) and math.isfinite(v) for r in [*matrix,*points] for v in r):raise ValueError('nonfinite physical observation')
            if len(points)!=(8 if kind=='rigidBody' else 9) or len(item['faces'])!=(6 if kind=='rigidBody' else 4):raise ValueError('literal indexed mesh membership differs')
        if kind=='rigidBody':
            z=row['Faller']['matrix'][2][3]
            expected=5-.5*9.81*((int(frame)-1)/24)**2
            # Bullet's native .04/s default damping changes displacement by
            # <g*(-log(.96))*t^3/6=.0036m here;240Hz integration adds<.008m.
            # The explicit .02m bound encloses both at t<=.375s, no floor contact.
            if abs(z-expected)>.02:raise ValueError(('literal freefall differs',frame,z,expected))
            if abs(row['Floor']['matrix'][2][3]+.5)>1e-6:raise ValueError('passive floor moved')
        else:
            points=row['Sheet']['vertices']
            if len(points)!=9:raise ValueError('cloth indexed vertex membership differs')
            for i in (0,2,6,8):
                expected=[(-1,0,1)[i%3],(-1,0,1)[i//3],2]
                if any(abs(a-b)>1e-6 for a,b in zip(points[i],expected)):raise ValueError(('fixed pin moved',frame,i))
            if int(frame)==10 and points[4][2]>=1.995:raise ValueError('unpinned centre did not sag under gravity')
