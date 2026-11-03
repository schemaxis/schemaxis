# Copyright (C) 2026 David L F Gaden
"""Independent standard-library checks for benchmark MSH publications."""
import math
from pathlib import Path


def mesh_check(path, case):
    path=Path(path)
    if not path.is_file() or path.is_symlink() or path.stat().st_size>32*1024*1024:raise ValueError('missing/excessive MSH')
    lines=path.read_text().splitlines()
    if lines[lines.index('$MeshFormat')+1]!='2.2 0 8':raise ValueError('expected ASCII MSH 2.2')
    def section(name):
        i=lines.index('$'+name);count=int(lines[i+1])
        if not 0<count<=200000:raise ValueError('mesh section count bound')
        records=lines[i+2:i+2+count]
        if lines[i+2+count]!='$End'+name:raise ValueError('mesh section count differs')
        return records
    names={}
    for row in section('PhysicalNames'):
        dim,tag,name=row.split(maxsplit=2);names[(int(dim),int(tag))]=name.strip('"')
    if names!={(3,1):'part',(2,2):'outside',(2,3):'fixed',(2,4):'loaded'}:raise ValueError('MSH names/tags differ')
    points={}
    for row in section('Nodes'):
        tag,*xyz=row.split();tag=int(tag)
        if tag in points or len(xyz)!=3:raise ValueError('invalid/repeated node')
        points[tag]=tuple(map(float,xyz))
        if not all(math.isfinite(x) for x in points[tag]):raise ValueError('nonfinite point')
    def sub(a,b):return tuple(x-y for x,y in zip(a,b))
    def cross(a,b):return (a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0])
    def dot(a,b):return sum(x*y for x,y in zip(a,b))
    def close(a,b):
        if not math.isclose(a,b,rel_tol=1e-7,abs_tol=1e-7):raise ValueError('MSH measure differs')
    volume=0.;areas={2:0.,3:0.,4:0.};faces={};boundary=set();ids=set();tetrahedra=triangles=0
    for row in section('Elements'):
        row=list(map(int,row.split()));identity,kind,tags=row[:3]
        if identity in ids or kind not in (2,4) or tags<1:raise ValueError('unsupported/repeated element')
        ids.add(identity);group=row[3];node_ids=row[3+tags:]
        if len(node_ids)!=(3 if kind==2 else 4) or len(set(node_ids))!=len(node_ids):raise ValueError('invalid element width')
        xyz=[points[n] for n in node_ids];a,b,c=xyz[:3]
        if kind==4:
            if group!=1:raise ValueError('volume group differs')
            measured=dot(sub(b,a),cross(sub(c,a),sub(xyz[3],a)))/6
            if measured<=0:raise ValueError('inverted/degenerate tetrahedron')
            volume+=measured;tetrahedra+=1
            for indices in ((0,1,2),(0,1,3),(0,2,3),(1,2,3)):
                key=tuple(sorted(node_ids[i] for i in indices));faces[key]=faces.get(key,0)+1
        else:
            if group not in areas:raise ValueError('boundary group differs')
            normal=cross(sub(b,a),sub(c,a));area=math.sqrt(dot(normal,normal))/2
            if area<=0:raise ValueError('degenerate boundary')
            areas[group]+=area;triangles+=1;key=tuple(sorted(node_ids))
            if key in boundary:raise ValueError('repeated boundary face')
            boundary.add(key)
            if group in (3,4):
                for p in xyz:close(p[0],0 if group==3 else case['length'])
            elif all(math.isclose(p[0],0,abs_tol=1e-7) for p in xyz) or all(math.isclose(p[0],case['length'],abs_tol=1e-7) for p in xyz):raise ValueError('end face incorrectly in outside group')
    if any(n not in (1,2) for n in faces.values()) or boundary!={k for k,n in faces.items() if n==1}:raise ValueError('mesh boundary coverage differs')
    close(volume,case['length']*case['width']*case['height'])
    close(areas[3],case['width']*case['height']);close(areas[4],case['width']*case['height'])
    close(areas[2],2*case['length']*(case['width']+case['height']))
    return {'tetrahedra':tetrahedra,'triangles':triangles,'volume':volume,'areas':areas}
