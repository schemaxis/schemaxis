#!/usr/bin/env python3
"""Qualify checked STEP import, parametric refine and hardened exports on native FreeCAD 1.1.x.

PYTHONPATH=src python3 tools/qualify_freecad_step_import.py --directory DIR --executable FREECADCMD

Every STEP input is written here, without a CAD kernel: planar solids with an
asymmetric notch and hole, a void-bearing solid, a split-face block for refine,
and a box with a cylindrical through-hole (CYLINDRICAL_SURFACE and CIRCLE edges).
Exact volumes, centres of mass and point membership come from closed forms, so the
native reader is compared with independent facts. Native readback (FCStd reopen,
STEP re-read, isInside) is same-kernel self-consistency; the independent layers
are this writer's oracle, the host STL integrals and the host STEP scan.

Groups: baseline, revision, units, orientation, wrong identity, topology, refine
with a headless placement edit and fresh reopen, curved oracle at two
deflections, far placement, representation relationship, admission refusals
before any native launch, refreshed-hash semantic mutants, strict no-downgrade of
evidence without hardened fields, source removal with schema-aware portable
export, relative authored paths verified from another directory, legacy readSTEP
retained-copy verification, workflow reuse and invalidation, and a whole-run
timeout. Use a fresh directory; earlier evidence is never overwritten.
"""
import argparse
import copy
import hashlib
import io
import json
import math
import os
import shutil
import struct
import time
import zipfile
from pathlib import Path

from schemaxis.adaptors import registry
from schemaxis.adaptor_delivery import source_digest
from schemaxis.artifacts import atomic_json
from schemaxis.core.faults import SchemaxisError

ROOT = Path(__file__).resolve().parents[1]


# ------------------------------------------------------- independent STEP writer

def fmt(x):
    text = repr(float(x))
    if 'e' in text:
        mantissa, exponent = text.split('e')
        return (mantissa if '.' in mantissa else mantissa+'.')+'E'+exponent
    return text


class Writer:
    """Hand-written AP214 instances; no CAD kernel is involved."""

    def __init__(self, name):
        self.lines, self.name = [], name

    def add(self, text):
        self.lines.append('#%d=%s;' % (len(self.lines)+1, text))
        return '#%d' % len(self.lines)

    def point(self, p):
        return self.add("CARTESIAN_POINT('',(%s))" % ','.join(fmt(c) for c in p))

    def direction(self, d):
        return self.add("DIRECTION('',(%s))" % ','.join(fmt(c) for c in d))

    def placement(self, location, axis, ref):
        return self.add("AXIS2_PLACEMENT_3D('',%s,%s,%s)" % (self.point(location), self.direction(axis), self.direction(ref)))

    def header(self, unit):
        app = self.add("APPLICATION_CONTEXT('automotive_design')")
        self.add("APPLICATION_PROTOCOL_DEFINITION('international standard','automotive_design',2000,%s)" % app)
        pctx = self.add("PRODUCT_CONTEXT('',%s,'mechanical')" % app)
        prod = self.add("PRODUCT('%s','%s','',(%s))" % (self.name, self.name, pctx))
        pdf = self.add("PRODUCT_DEFINITION_FORMATION('','',%s)" % prod)
        pdctx = self.add("PRODUCT_DEFINITION_CONTEXT('part definition',%s,'design')" % app)
        pd = self.add("PRODUCT_DEFINITION('design','',%s,%s)" % (pdf, pdctx))
        self.pds = self.add("PRODUCT_DEFINITION_SHAPE('','',%s)" % pd)
        if unit == 'inch':
            mm = self.add("( LENGTH_UNIT() NAMED_UNIT(*) SI_UNIT(.MILLI.,.METRE.) )")
            measure = self.add("LENGTH_MEASURE_WITH_UNIT(LENGTH_MEASURE(25.4),%s)" % mm)
            dims = self.add("DIMENSIONAL_EXPONENTS(1.,0.,0.,0.,0.,0.,0.)")
            length = self.add("( CONVERSION_BASED_UNIT('INCH',%s) LENGTH_UNIT() NAMED_UNIT(%s) )" % (measure, dims))
        else:
            prefix = {'mm': '.MILLI.', 'cm': '.CENTI.', 'm': '$'}[unit]
            length = self.add("( LENGTH_UNIT() NAMED_UNIT(*) SI_UNIT(%s,.METRE.) )" % prefix)
        angle = self.add("( NAMED_UNIT(*) PLANE_ANGLE_UNIT() SI_UNIT($,.RADIAN.) )")
        solid = self.add("( NAMED_UNIT(*) SI_UNIT($,.STERADIAN.) SOLID_ANGLE_UNIT() )")
        unc = self.add("UNCERTAINTY_MEASURE_WITH_UNIT(LENGTH_MEASURE(1.E-07),%s,'distance_accuracy_value','')" % length)
        self.context = self.add("( GEOMETRIC_REPRESENTATION_CONTEXT(3) GLOBAL_UNCERTAINTY_ASSIGNED_CONTEXT((%s)) "
                                "GLOBAL_UNIT_ASSIGNED_CONTEXT((%s,%s,%s)) REPRESENTATION_CONTEXT('','') )" % (unc, length, angle, solid))
        self.world = self.placement((0, 0, 0), (0, 0, 1), (1, 0, 0))

    def finish(self, brep, path, structure='direct'):
        if structure == 'direct':
            rep = self.add("ADVANCED_BREP_SHAPE_REPRESENTATION('%s',(%s,%s),%s)" % (self.name, self.world, brep, self.context))
            self.add("SHAPE_DEFINITION_REPRESENTATION(%s,%s)" % (self.pds, rep))
        else:
            # Ordinary (untransformed) relationship: an empty shape representation linked to the B-rep representation.
            outer = self.add("SHAPE_REPRESENTATION('%s',(%s),%s)" % (self.name, self.world, self.context))
            rep = self.add("ADVANCED_BREP_SHAPE_REPRESENTATION('',(%s,%s),%s)" % (self.placement((0, 0, 0), (0, 0, 1), (1, 0, 0)), brep, self.context))
            self.add("SHAPE_REPRESENTATION_RELATIONSHIP('','',%s,%s)" % (outer, rep))
            self.add("SHAPE_DEFINITION_REPRESENTATION(%s,%s)" % (self.pds, outer))
        text = ("ISO-10303-21;\nHEADER;\nFILE_DESCRIPTION(('Schemaxis qualification part'),'2;1');\n"
                "FILE_NAME('%s.step','2026-10-19T00:00:00',(''),(''),'schemaxis qualifier','','');\n"
                "FILE_SCHEMA(('AUTOMOTIVE_DESIGN { 1 0 10303 214 1 1 1 1 }'));\nENDSEC;\nDATA;\n" % self.name
                + '\n'.join(self.lines) + '\nENDSEC;\nEND-ISO-10303-21;\n')
        Path(path).write_text(text, newline='\n')
        return path


def area_vector(loop):
    total = [0.0, 0.0, 0.0]
    for p, q in zip(loop, loop[1:]+loop[:1]):
        total = [total[0]+(p[1]*q[2]-p[2]*q[1])/2, total[1]+(p[2]*q[0]-p[0]*q[2])/2, total[2]+(p[0]*q[1]-p[1]*q[0])/2]
    return total


def planar_shell(w, faces, edges, vertices):
    refs = []
    for face in faces:
        bounds = []
        for li, loop in enumerate(face):
            oriented = []
            for p, q in zip(loop, loop[1:]+loop[:1]):
                for v in (p, q):
                    if v not in vertices:
                        vertices[v] = w.add("VERTEX_POINT('',%s)" % w.point(v))
                key = frozenset((p, q))
                if key not in edges:
                    d = [q[i]-p[i] for i in range(3)]; size = math.sqrt(sum(c*c for c in d))
                    vector = w.add("VECTOR('',%s,%s)" % (w.direction([c/size for c in d]), fmt(size)))
                    line = w.add("LINE('',%s,%s)" % (w.point(p), vector))
                    edges[key] = (w.add("EDGE_CURVE('',%s,%s,%s,.T.)" % (vertices[p], vertices[q], line)), p)
                curve, first = edges[key]
                oriented.append(w.add("ORIENTED_EDGE('',*,*,%s,%s)" % (curve, '.T.' if first == p else '.F.')))
            loop_ref = w.add("EDGE_LOOP('',(%s))" % ','.join(oriented))
            bounds.append(w.add("%s('',%s,.T.)" % ('FACE_OUTER_BOUND' if li == 0 else 'FACE_BOUND', loop_ref)))
        n = area_vector(face[0]); s = math.sqrt(sum(c*c for c in n)); n = [c/s for c in n]
        r = [face[0][1][i]-face[0][0][i] for i in range(3)]; rs = math.sqrt(sum(c*c for c in r)); r = [c/rs for c in r]
        plane = w.add("PLANE('',%s)" % w.placement(face[0][0], n, r))
        refs.append(w.add("ADVANCED_FACE('',(%s),%s,.T.)" % (','.join(bounds), plane)))
    return w.add("CLOSED_SHELL('',(%s))" % ','.join(refs))


def write_planar(path, faces, *, unit='mm', voids=(), structure='direct', name='part'):
    w = Writer(name); w.header(unit)
    edges, vertices = {}, {}
    shell = planar_shell(w, faces, edges, vertices)
    if voids:
        inner = [w.add("ORIENTED_CLOSED_SHELL('',*,%s,.F.)" % planar_shell(w, v, edges, vertices)) for v in voids]
        brep = w.add("BREP_WITH_VOIDS('%s',%s,(%s))" % (name, shell, ','.join(inner)))
    else:
        brep = w.add("MANIFOLD_SOLID_BREP('%s',%s)" % (name, shell))
    return w.finish(brep, path, structure)


def prism(outer, holes, z0, z1):
    faces = [[[(x, y, z1) for x, y in outer]] + [[(x, y, z1) for x, y in h] for h in holes],
             [[(x, y, z0) for x, y in reversed(outer)]] + [[(x, y, z0) for x, y in reversed(h)] for h in holes]]
    for loop in [outer]+holes:
        for (ax, ay), (bx, by) in zip(loop, loop[1:]+loop[:1]):
            faces.append([[(ax, ay, z0), (bx, by, z0), (bx, by, z1), (ax, ay, z1)]])
    return faces


def transform(faces, m, scale=1.0):
    det = (m[0][0]*(m[1][1]*m[2][2]-m[1][2]*m[2][1]) - m[0][1]*(m[1][0]*m[2][2]-m[1][2]*m[2][0])
           + m[0][2]*(m[1][0]*m[2][1]-m[1][1]*m[2][0]))
    def t(p): return tuple(scale*sum(m[r][c]*p[c] for c in range(3)) for r in range(3))
    out = [[[t(p) for p in loop] for loop in face] for face in faces]
    return [[list(reversed(loop)) for loop in face] for face in out] if det < 0 else out


def facts(faces):
    """Exact planar-solid volume, area and centre (signed tetrahedra on every loop fan)."""
    volume, moment, area = 0.0, [0.0]*3, 0.0
    for face in faces:
        vector = [0.0]*3
        for loop in face:
            v = area_vector(loop); vector = [vector[i]+v[i] for i in range(3)]
            o = loop[0]
            for p, q in zip(loop[1:], loop[2:]):
                d = (o[0]*(p[1]*q[2]-p[2]*q[1]) - o[1]*(p[0]*q[2]-p[2]*q[0]) + o[2]*(p[0]*q[1]-p[1]*q[0]))/6
                volume += d; moment = [moment[i]+d*(o[i]+p[i]+q[i])/4 for i in range(3)]
        area += math.sqrt(sum(c*c for c in vector))
    return {'volume': volume, 'area': area, 'centreOfMass': [m/volume for m in moment]}


OUTER = [(-20, -15), (20, -15), (20, 2), (10, 2), (10, 10), (20, 10), (20, 15), (-20, 15)]
REVISED = [(-20, -15), (20, -15), (20, 2), (6, 2), (6, 10), (20, 10), (20, 15), (-20, 15)]
HOLE = [(-12, -9), (-12, -3), (-6, -3), (-6, -9)]
I3 = [[1, 0, 0], [0, 1, 0], [0, 0, 1]]
MIRROR = [[-1, 0, 0], [0, 1, 0], [0, 0, 1]]
TURN = [[-1, 0, 0], [0, -1, 0], [0, 0, 1]]
Y_UP = [[1, 0, 0], [0, 0, 1], [0, -1, 0]]       # a Y-up exporter: part +Z written as file +Y
INSIDE = [[0, 0, 5], [15, -6, 5], [-15, 6, 5]]
OUTSIDE = [[15, 6, 5], [-9, -6, 5], [0, 0, 11]]


def split_block():
    """40x30x10 block whose top is two coplanar faces (refine merges them)."""
    x0, x1, y0, y1, z0, z1 = -20, 20, -15, 15, 0, 10
    return [[[(x0, y0, z1), (0, y0, z1), (0, y1, z1), (x0, y1, z1)]], [[(0, y0, z1), (x1, y0, z1), (x1, y1, z1), (0, y1, z1)]],
            [[(x0, y0, z0), (x0, y1, z0), (x1, y1, z0), (x1, y0, z0)]],
            [[(x0, y0, z0), (x1, y0, z0), (x1, y0, z1), (0, y0, z1), (x0, y0, z1)]],
            [[(x1, y0, z0), (x1, y1, z0), (x1, y1, z1), (x1, y0, z1)]],
            [[(x1, y1, z0), (x0, y1, z0), (x0, y1, z1), (0, y1, z1), (x1, y1, z1)]],
            [[(x0, y1, z0), (x0, y0, z0), (x0, y0, z1), (x0, y1, z1)]]]


# Box 40x30x10 with a cylindrical through-hole of radius 3 at (-9,-6): curved oracle.
R, CX, CY, H = 3.0, -9.0, -6.0, 10.0


def cylinder_facts():
    hole = math.pi*R*R*H
    volume = 40*30*H - hole
    return {'volume': volume, 'area': 2*(1200-math.pi*R*R) + 2*(400+300) + 2*math.pi*R*H,
            'centreOfMass': [-hole*CX/volume, -hole*CY/volume, H/2], 'curvedArea': 2*math.pi*R*H}


def write_cylinder(path, unit='mm'):
    w = Writer('drilled'); w.header(unit)
    k = {'mm': 1.0, 'cm': 0.1, 'm': 0.001, 'inch': 1/25.4}[unit]
    s = lambda p: tuple(k*c for c in p)
    vertices, edges = {}, {}
    def vertex(p):
        if p not in vertices: vertices[p] = w.add("VERTEX_POINT('',%s)" % w.point(s(p)))
        return vertices[p]
    def line_loop(points):
        oriented = []
        for p, q in zip(points, points[1:]+points[:1]):
            key = frozenset((p, q))
            if key not in edges:
                d = [q[i]-p[i] for i in range(3)]; size = math.sqrt(sum(c*c for c in d))
                vec = w.add("VECTOR('',%s,%s)" % (w.direction([c/size for c in d]), fmt(k*size)))
                edges[key] = (w.add("EDGE_CURVE('',%s,%s,%s,.T.)" % (vertex(p), vertex(q), w.add("LINE('',%s,%s)" % (w.point(s(p)), vec)))), p)
            curve, first = edges[key]
            oriented.append(w.add("ORIENTED_EDGE('',*,*,%s,%s)" % (curve, '.T.' if first == p else '.F.')))
        return w.add("EDGE_LOOP('',(%s))" % ','.join(oriented))
    def circle(z):
        v = vertex((CX+R, CY, z))
        c = w.add("CIRCLE('',%s,%s)" % (w.placement(s((CX, CY, z)), (0, 0, 1), (1, 0, 0)), fmt(k*R)))
        return w.add("EDGE_CURVE('',%s,%s,%s,.T.)" % (v, v, c))
    top, bottom = circle(H), circle(0)
    loop = lambda e, sense: w.add("EDGE_LOOP('',(%s))" % w.add("ORIENTED_EDGE('',*,*,%s,%s)" % (e, sense)))
    faces = []
    def planar(points, normal, ref, inner=()):
        bounds = [w.add("FACE_OUTER_BOUND('',%s,.T.)" % line_loop(points))] + [w.add("FACE_BOUND('',%s,.T.)" % l) for l in inner]
        faces.append(w.add("ADVANCED_FACE('',(%s),%s,.T.)" % (','.join(bounds), w.add("PLANE('',%s)" % w.placement(s(points[0]), normal, ref)))))
    x0, x1, y0, y1 = -20, 20, -15, 15
    planar([(x0, y0, H), (x1, y0, H), (x1, y1, H), (x0, y1, H)], (0, 0, 1), (1, 0, 0), [loop(top, '.F.')])
    planar([(x0, y0, 0), (x0, y1, 0), (x1, y1, 0), (x1, y0, 0)], (0, 0, -1), (0, 1, 0), [loop(bottom, '.T.')])
    planar([(x0, y0, 0), (x1, y0, 0), (x1, y0, H), (x0, y0, H)], (0, -1, 0), (1, 0, 0))
    planar([(x1, y0, 0), (x1, y1, 0), (x1, y1, H), (x1, y0, H)], (1, 0, 0), (0, 1, 0))
    planar([(x1, y1, 0), (x0, y1, 0), (x0, y1, H), (x1, y1, H)], (0, 1, 0), (-1, 0, 0))
    planar([(x0, y1, 0), (x0, y0, 0), (x0, y0, H), (x0, y1, H)], (-1, 0, 0), (0, -1, 0))
    wall = [w.add("FACE_BOUND('',%s,.T.)" % loop(top, '.T.')), w.add("FACE_BOUND('',%s,.T.)" % loop(bottom, '.F.'))]
    surface = w.add("CYLINDRICAL_SURFACE('',%s,%s)" % (w.placement(s((CX, CY, 0)), (0, 0, 1), (1, 0, 0)), fmt(k*R)))
    faces.append(w.add("ADVANCED_FACE('',(%s),%s,.F.)" % (','.join(wall), surface)))
    brep = w.add("MANIFOLD_SOLID_BREP('drilled',%s)" % w.add("CLOSED_SHELL('',(%s))" % ','.join(faces)))
    return w.finish(brep, path)


# ------------------------------------------------------------- documents and oracle

def importing(path, expect, *, units='mm', orientation=None, placement=None, refine=False, extra=None, output=None, deflection=None):
    options = {'file': str(path), 'units': units, 'expect': expect, 'refine': refine}
    if orientation: options['orientation'] = orientation
    if placement: options['placement'] = placement
    doc = {'version': 'schemaxis.freecad/1', 'units': 'mm', 'nodes': [{'id': 'part', 'filter': 'importSTEP', 'options': options}] + (extra or []),
           'output': output or 'part'}
    if deflection: doc['linearDeflection'] = deflection
    return doc


def base_expect(f, points=True, com=True):
    expect = {'volume': {'value': f['volume']}}
    if com: expect['centreOfMass'] = {'value': f['centreOfMass'], 'tolerance': 0.01}
    if points: expect['points'] = {'inside': INSIDE, 'outside': OUTSIDE, 'guard': 0.5}
    return expect


def placed(point, clocking, position):
    c, s = {0: (1, 0), 90: (0, 1), 180: (-1, 0), 270: (0, -1)}[clocking % 360]
    return [c*point[0]-s*point[1]+position[0], s*point[0]+c*point[1]+position[1], point[2]+position[2]]


def failures(callable_):
    try:
        callable_()
    except SchemaxisError as error:
        return {'code': error.fault.code, 'location': error.fault.location, 'message': error.fault.message[:200]}
    return None


def launches(log):
    return sum(1 for _ in open(log)) if log and Path(log).exists() else None


# -------------------------------------------------------------- refreshed mutants

def refresh(run, names):
    """What an attacker can do: re-digest changed publications and regenerate their metadata."""
    from schemaxis.publication_metadata import finalise
    receipt = json.loads((run/'verification.json').read_text())
    for artifact in receipt['artifacts']:
        if Path(artifact['file']).name in names:
            artifact['sha256'] = hashlib.sha256((run/Path(artifact['file']).name).read_bytes()).hexdigest()
    (run/'verification.json').write_text(json.dumps(receipt, indent=2)+'\n')
    origin = json.loads((run/'publication-metadata.json').read_text()).get('recordedDirectory')
    finalise(run)
    if origin:
        # finalise rewrites the manifest without the export origin hint; restore it as an attacker could.
        manifest = json.loads((run/'publication-metadata.json').read_text())
        manifest['recordedDirectory'] = origin
        (run/'publication-metadata.json').write_text(json.dumps(manifest))


def stl_rewrite(path, change):
    data = path.read_bytes(); count = struct.unpack('<I', data[80:84])[0]
    facets = [struct.unpack('<12fH', data[84+50*i:134+50*i]) for i in range(count)]
    facets = change(facets)
    out = bytearray(data[:80]) + struct.pack('<I', len(facets))
    for f in facets:
        out += struct.pack('<12fH', *f)
    path.write_bytes(bytes(out))


def fcstd_rewrite(path, edit):
    source = path.read_bytes(); out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(source)) as a, zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as b:
        for info in a.infolist():
            data = a.read(info)
            b.writestr(info.filename, edit(data.decode()).encode() if info.filename == 'Document.xml' else data)
    path.write_bytes(out.getvalue())


def mutants(base_run, directory):
    """Each mutant copies a verified run, changes meaning and refreshes digests; verification must refuse."""
    built = json.loads((base_run/'built.json').read_text())
    centre = [(a+b)/2 for a, b in zip(built['shape']['bounds'][0::2], built['shape']['bounds'][1::2])]
    def inverted(facets):
        return [(*f[0:3], *f[3:6], *f[9:12], *f[6:9], f[12]) for f in facets]
    def mirrored(facets):
        m = lambda p: (2*centre[0]-p[0], p[1], p[2])
        return [(*f[0:3], *m(f[3:6]), *m(f[9:12]), *m(f[6:9]), f[12]) for f in facets]
    def turned(facets):
        t = lambda p: (2*centre[0]-p[0], 2*centre[1]-p[1], p[2])
        return [(*f[0:3], *t(f[3:6]), *t(f[6:9]), *t(f[9:12]), f[12]) for f in facets]
    def dropped(facets):
        return facets[:-1]
    cases = {}
    def mutate(label, action, names=('model.stl',), refresh_hashes=True):
        from schemaxis.schema_snapshots import export_run
        target = directory/label
        export_run(base_run, target)
        action(target)
        if refresh_hashes:
            refresh(target, names)
        cases[label] = failures(lambda: registry.verify(target)) or {'code': 'ACCEPTED'}
    mutate('stl-inverted', lambda t: stl_rewrite(t/'model.stl', inverted))
    mutate('stl-mirrored', lambda t: stl_rewrite(t/'model.stl', mirrored))
    mutate('stl-turned', lambda t: stl_rewrite(t/'model.stl', turned))
    mutate('stl-dropped-facet', lambda t: stl_rewrite(t/'model.stl', dropped))
    mutate('step-metre-label', lambda t: (t/'model.step').write_text((t/'model.step').read_text().replace('SI_UNIT(.MILLI.,.METRE.)', 'SI_UNIT($,.METRE.)')),
           names=('model.step',))
    def json_edit(name, edit):
        def action(t):
            value = json.loads((t/name).read_text()); edit(value); (t/name).write_text(json.dumps(value, indent=2))
        return action
    mutate('forged-centre', json_edit('built.json', lambda b: b['exportEvidence']['shape']['centreOfMass'].__setitem__(0, b['exportEvidence']['shape']['centreOfMass'][0]+1.6)), names=())
    mutate('forged-curved-area', json_edit('built.json', lambda b: b['exportEvidence']['shape'].__setitem__('curvedArea', b['exportEvidence']['shape']['area'])), names=())
    mutate('no-downgrade-built', json_edit('built.json', lambda b: b.pop('exportEvidence')), names=())
    mutate('no-downgrade-receipt', json_edit('verification.json', lambda r: r.pop('exportEvidence')), names=())
    mutate('no-downgrade-version', json_edit('verification.json', lambda r: r['exportEvidence'].__setitem__('version', 'schemaxis.freecad.export/1')), names=())
    mutate('forged-placement', json_edit('built.json', lambda b: b['importObservations']['part']['placement'].__setitem__(3, 1.0)), names=())
    def retained_bytes(t):
        step = t/'import-0.step'; step.write_text(step.read_text().replace("'2026-10-19T00:00:00'", "'2026-10-19T00:00:01'"))
        records = json.loads((t/'sources.json').read_text())
        records['part']['sha256'] = hashlib.sha256(step.read_bytes()).hexdigest()
        (t/'sources.json').write_text(json.dumps(records))
    mutate('retained-source-refreshed', retained_bytes, names=())
    mutate('fcstd-source-digest', lambda t: fcstd_rewrite(t/'model.FCStd', lambda x: x.replace(
        json.loads((t/'sources.json').read_text())['part']['sha256'], '0'*64)), names=('model.FCStd',))
    mutate('fcstd-refine-unlinked', lambda t: fcstd_rewrite(t/'model.FCStd', lambda x: x.replace('<Link value="N0"/>', '<Link value=""/>', 1)),
           names=('model.FCStd',))
    def drop_gui_state(t):
        source = (t/'model.FCStd').read_bytes(); out = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(source)) as a, zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as b:
            for info in a.infolist():
                if info.filename != 'GuiDocument.xml':
                    b.writestr(info.filename, a.read(info))
        (t/'model.FCStd').write_bytes(out.getvalue())
    mutate('fcstd-gui-visibility-removed', drop_gui_state, names=('model.FCStd',))
    return cases


# ------------------------------------------------------------------ qualification

class Qualification:
    def __init__(self, directory, executable, log):
        self.directory, self.executable, self.log = directory, executable, log
        self.report = {'verified': False, 'sourceDigest': source_digest('freecad'), 'started': time.time(), 'checks': {}}

    def save(self):
        atomic_json(self.directory/'report.json', self.report)

    def check(self, name, value):
        self.report['checks'][name] = value
        self.save()
        print(name, 'ok', flush=True)

    def run(self, doc, target, timeout=120):
        return registry.run(doc, target, locations={'freecad': self.executable}, timeout=timeout)

    def refused(self, doc, target, code, *, native=None):
        before = launches(self.log)
        fault = failures(lambda: self.run(doc, target))
        after = launches(self.log)
        assert fault and fault['code'] == code, (target.name, fault)
        result = {**fault, 'nativeLaunches': None if before is None else after-before}
        if native is not None and before is not None:
            assert (after-before > 0) == native, (target.name, result)
        if target.exists():
            assert json.loads((target/'result.json').read_text()).get('verified') is False, target.name
        return result


def native_edit(q, run, target):
    """Qualification-only native edit: move the imported source placement, recompute, save and reopen fresh."""
    from schemaxis.core.runners import Interpreter
    from schemaxis.dispatch import SubprocessRunner
    target.mkdir()
    shutil.copy2(run/'model.FCStd', target/'model.FCStd')
    script = target/'edit.py'
    script.write_text(
        "import json, sys\nimport FreeCAD as App\n"
        "d=%r\n"
        "def facts(o):\n    s=o.Shape; b=s.BoundBox\n    return {'volume':s.Volume,'bounds':[b.XMin,b.XMax,b.YMin,b.YMax,b.ZMin,b.ZMax],'faces':len(s.Faces),'placement':str(o.Placement)}\n"
        "doc=App.openDocument(d+'/model.FCStd'); src=doc.getObject('N0'); ref=doc.getObject('N0Refined')\n"
        "out={'before':{'source':facts(src),'refined':facts(ref)}}\n"
        "src.Placement=App.Placement(App.Vector(-200,10,5),App.Rotation(App.Vector(0,0,1),180)).multiply(src.Placement)\n"
        "doc.recompute(); out['after']={'source':facts(src),'refined':facts(ref),'refineSource':ref.Source.Name}\n"
        "doc.saveAs(d+'/edited.FCStd'); App.closeDocument(doc.Name)\n"
        "doc=App.openDocument(d+'/edited.FCStd'); out['reopened']={'source':facts(doc.getObject('N0')),'refined':facts(doc.getObject('N0Refined'))}\n"
        "json.dump(out,open(d+'/edit.json','w'),indent=1)\n" % str(target))
    runner = SubprocessRunner(Interpreter('freecad', q.executable), target, timeout=90)
    report = runner(script.read_text())
    atomic_json(target/'edit-submission.json', report.to_dict())
    return json.loads((target/'edit.json').read_text())


def qualify(directory, executable, log=None, targeted=False):
    """targeted=True runs baseline, revision and the two source-removal lifecycle groups only."""
    directory = Path(directory).absolute()
    directory.mkdir(parents=True, exist_ok=False)
    q = Qualification(directory, executable, log)
    inputs = directory/'inputs'; inputs.mkdir()
    base = prism(OUTER, [HOLE], 0, 10)
    truth = facts(base)
    write_planar(inputs/'bracket.step', base, name='bracket')

    # 1 Baseline: independent oracle, placement, refine off; hardened export evidence.
    position, clocking = [100, 50, 0], 90
    doc = importing(inputs/'bracket.step', base_expect(truth), placement={'position': position, 'clocking': clocking})
    result = q.run(doc, directory/'baseline')
    built = json.loads((directory/'baseline/built.json').read_text())
    obs = built['importObservations']['part']
    expected_centre = placed(truth['centreOfMass'], clocking, position)
    assert abs(obs['part']['volume']-truth['volume']) <= 1e-9*truth['volume']
    assert math.dist(obs['output']['centreOfMass'], expected_centre) <= 1e-9
    q.check('baseline', {'verify': registry.verify(directory/'baseline')['exportChecks'], 'analyticVolume': truth['volume'],
                         'nativeVolume': obs['part']['volume'], 'placedCentre': obs['output']['centreOfMass'], 'expectedPlacedCentre': expected_centre})

    # 2 Revision: the genuine changed file fails the baseline facts, passes its own.
    revised = prism(REVISED, [HOLE], 0, 10); revised_truth = facts(revised)
    write_planar(inputs/'bracket-rev-b.step', revised, name='bracket')
    stale = q.refused(importing(inputs/'bracket-rev-b.step', base_expect(truth)), directory/'revision-stale', 'EXPECTATION_FAILED', native=True)
    q.run(importing(inputs/'bracket-rev-b.step', base_expect(revised_truth, points=False)), directory/'revision')
    q.check('revision', {'staleExpectations': stale, 'updated': registry.verify(directory/'revision')['verified'],
                         'volumes': [truth['volume'], revised_truth['volume']]})
    if targeted:
        q.check('workflowSourceRemoval', workflow_source_removal(q, directory, base, truth))
        q.check('workflowStudySourceRemoval', workflow_source_removal(q, directory, base, truth, study=True))
        q.check('studySourceRemoval', study_source_removal(q, directory, base, truth))
        return finish(q)

    # 3 Units: inch and metre files; a wrong label is refused before any native launch.
    write_planar(inputs/'bracket-inch.step', transform(base, I3, 1/25.4), unit='inch', name='bracket')
    write_planar(inputs/'bracket-m.step', transform(base, I3, 0.001), unit='m', name='bracket')
    write_planar(inputs/'bracket-cm.step', transform(base, I3, 0.1), unit='cm', name='bracket')
    write_planar(inputs/'bracket-mislabelled.step', base, unit='inch', name='bracket')
    units = {}
    for unit, name in (('inch', 'bracket-inch'), ('m', 'bracket-m'), ('cm', 'bracket-cm')):
        doc = importing(inputs/(name+'.step'), base_expect(truth), units=unit)
        doc['nodes'][0]['options']['expect']['volume']['relativeTolerance'] = 1e-6
        q.run(doc, directory/('units-'+unit))
        units[unit] = json.loads((directory/('units-'+unit)/'built.json').read_text())['importObservations']['part']['part']['volume']
    units['mislabelled'] = q.refused(importing(inputs/'bracket-mislabelled.step', base_expect(truth)), directory/'units-mislabelled',
                                     'UNIT_MISMATCH', native=False)
    q.check('units', units)

    # 4 Orientation: a Y-up file with an explicit axis map equals the baseline; unmapped it fails declared facts.
    write_planar(inputs/'bracket-yup.step', transform(base, Y_UP), name='bracket')
    q.run(importing(inputs/'bracket-yup.step', base_expect(truth), orientation={'z': '+Y', 'x': '+X'}), directory/'orientation')
    unmapped = q.refused(importing(inputs/'bracket-yup.step', base_expect(truth)), directory/'orientation-unmapped', 'EXPECTATION_FAILED', native=True)
    axis = q.refused(importing(inputs/'bracket-yup.step', base_expect(truth), orientation={'z': '+Y'}), directory/'orientation-no-x', 'INVALID_AXIS', native=False)
    q.check('orientation', {'mapped': registry.verify(directory/'orientation')['verified'], 'unmapped': unmapped, 'missingX': axis})

    # 5 Wrong identity: mirror and turn keep volume, area and bounds; declared centre and points refuse them.
    write_planar(inputs/'bracket-mirror.step', transform(base, MIRROR), name='bracket')
    write_planar(inputs/'bracket-turn.step', transform(base, TURN), name='bracket')
    identity = {}
    for label in ('mirror', 'turn'):
        identity[label+'-centre'] = q.refused(importing(inputs/('bracket-'+label+'.step'), base_expect(truth, points=False)),
                                              directory/('identity-'+label+'-centre'), 'EXPECTATION_FAILED', native=True)
        identity[label+'-points'] = q.refused(importing(inputs/('bracket-'+label+'.step'), base_expect(truth, com=False)),
                                              directory/('identity-'+label+'-points'), 'EXPECTATION_FAILED', native=True)
    identity['volumeOnly'] = failures(lambda: registry.plan(importing(inputs/'bracket-mirror.step', {'volume': {'value': truth['volume']}}), legacy=True))
    near = base_expect(truth, com=False); near['points']['outside'] = [[-6.2, -6, 5]]
    identity['guard'] = q.refused(importing(inputs/'bracket.step', near), directory/'identity-guard', 'INVALID_ARGUMENT', native=True)
    q.check('wrongIdentity', identity)

    # 6 Topology: void, open shell, two solids.
    cavity_outer = prism([(-20, -15), (20, -15), (20, 15), (-20, 15)], [], 0, 10)
    void = prism([(-7.25, -5), (7.25, -5), (7.25, 5), (-7.25, 5)], [], 1, 9)
    write_planar(inputs/'cavity.step', cavity_outer, voids=[void], name='bracket')
    open_faces = base[1:]
    write_planar(inputs/'open.step', open_faces, name='bracket')
    w = Writer('pair'); w.header('mm')
    edges, vertices = {}, {}
    b1 = w.add("MANIFOLD_SOLID_BREP('a',%s)" % planar_shell(w, prism([(-20, -15), (-1, -15), (-1, 15), (-20, 15)], [], 0, 10), edges, vertices))
    b2 = w.add("MANIFOLD_SOLID_BREP('b',%s)" % planar_shell(w, prism([(1, -15), (20, -15), (20, 15), (1, 15)], [], 0, 10), edges, vertices))
    rep = w.add("ADVANCED_BREP_SHAPE_REPRESENTATION('pair',(%s,%s,%s),%s)" % (w.world, b1, b2, w.context))
    w.add("SHAPE_DEFINITION_REPRESENTATION(%s,%s)" % (w.pds, rep))
    text = ("ISO-10303-21;\nHEADER;\nFILE_DESCRIPTION((''),'2;1');\nFILE_NAME('pair.step','',(''),(''),'','','');\n"
            "FILE_SCHEMA(('AUTOMOTIVE_DESIGN'));\nENDSEC;\nDATA;\n"+'\n'.join(w.lines)+'\nENDSEC;\nEND-ISO-10303-21;\n')
    (inputs/'two-solids.step').write_text(text)
    q.check('topology', {
        'cavity': q.refused(importing(inputs/'cavity.step', base_expect(truth, points=False)), directory/'topology-cavity', 'EXPECTATION_FAILED', native=True),
        'open': q.refused(importing(inputs/'open.step', base_expect(truth)), directory/'topology-open', 'INVALID_GEOMETRY', native=True),
        'twoSolids': q.refused(importing(inputs/'two-solids.step', base_expect(truth)), directory/'topology-two', 'INVALID_GEOMETRY', native=False)})

    # 7 Refine: parametric merge, identity output placement, headless placement edit and fresh reopen.
    block = split_block(); block_truth = facts(block)
    write_planar(inputs/'split.step', block, name='block')
    q.run(importing(inputs/'split.step', base_expect(block_truth, points=False), refine=True,
                    placement={'position': [10, 0, 0], 'clocking': 0}), directory/'refine')
    refine = json.loads((directory/'refine/built.json').read_text())['importObservations']['part']
    edited = native_edit(q, directory/'refine', directory/'refine-edit')
    assert refine['source']['faces'] == 7 and refine['refine']['output']['faces'] == 6
    assert edited['after']['refined']['bounds'] == edited['after']['source']['bounds'] and edited['reopened']['refined'] == edited['after']['refined']
    q.check('refine', {'faces': [refine['source']['faces'], refine['refine']['output']['faces']], 'edit': edited,
                       'verify': registry.verify(directory/'refine')['verified']})

    # 8 Curved independent oracle at default and fine deflection; far placement with the host integral.
    write_cylinder(inputs/'drilled.step')
    cylinder = cylinder_facts()
    cyl_expect = {'volume': {'value': cylinder['volume']}, 'centreOfMass': {'value': cylinder['centreOfMass'], 'tolerance': 1e-6},
                  'points': {'inside': [[0, 0, 5]], 'outside': [[CX, CY, 5]], 'guard': 0.5}}
    curved = {}
    for label, deflection, position in (('default', None, [0, 0, 0]), ('fine', 0.01, [0, 0, 0]), ('coarse', 1.0, [0, 0, 0]),
                                        ('far', None, [99950, 99950, 99950])):
        target = directory/('curved-'+label)
        q.run(importing(inputs/'drilled.step', cyl_expect, placement={'position': position, 'clocking': 0}, deflection=deflection), target)
        obs = json.loads((target/'built.json').read_text())['importObservations']['part']
        receipt = json.loads((target/'verification.json').read_text())
        curved[label] = {'nativeVolumeMinusAnalytic': obs['part']['volume']-cylinder['volume'],
                         'nativeCentreError': math.dist(obs['part']['centreOfMass'], cylinder['centreOfMass']),
                         'nativeCurvedArea': json.loads((target/'built.json').read_text())['exportEvidence']['shape']['curvedArea'],
                         'analyticCurvedArea': cylinder['curvedArea'], 'nativeMeshVolume': receipt['mesh']['volume'],
                         'exportChecks': registry.verify(target)['exportChecks']}
        assert abs(curved[label]['nativeVolumeMinusAnalytic']) <= 1e-9*cylinder['volume']
    q.check('curved', curved)

    # 9 Ordinary representation relationship (outer shape representation linked to the B-rep representation).
    write_planar(inputs/'bracket-related.step', base, structure='relationship', name='bracket')
    q.run(importing(inputs/'bracket-related.step', base_expect(truth)), directory/'relationship')
    q.check('relationship', {'source': json.loads((directory/'relationship/plan.json').read_text())['nodes'][0]['source']['structure'],
                             'verify': registry.verify(directory/'relationship')['verified']})

    # 10 Admission refusals before any native process: loop cap, entity cap, orphan context, unassigned unit, traps.
    traps = admission_traps(inputs, base)
    refusals = {}
    for label, (path, code) in traps.items():
        if code is None:
            refusals[label] = {'admitted': registry.plan(importing(path, base_expect(truth)), legacy=True)['nodes'][0]['source']['schema']}
        else:
            refusals[label] = q.refused(importing(path, base_expect(truth)), directory/('admission-'+label), code, native=False)
    q.check('admission', refusals)

    # 11 Refreshed-hash semantic mutants and strict no-downgrade.
    mutant_root = directory/'mutants'; mutant_root.mkdir()
    q.run(importing(inputs/'bracket.step', base_expect(truth), refine=True), directory/'mutant-base')
    cases = mutants(directory/'mutant-base', mutant_root)
    # Stated limit: a part whose centre of mass is its bounds centre cannot reveal a mirrored STL by its centre.
    symmetric_root = directory/'mutants-symmetric'; symmetric_root.mkdir()
    q.run(importing(inputs/'split.step', base_expect(block_truth, points=False), refine=True), directory/'mutant-symmetric')
    from schemaxis.schema_snapshots import export_run
    export_run(directory/'mutant-symmetric', symmetric_root/'stl-mirrored')
    target = symmetric_root/'stl-mirrored'
    stl_rewrite(target/'model.stl', lambda facets: [(*f[0:3], -f[3], f[4], f[5], -f[9], f[10], f[11], -f[6], f[7], f[8], f[12]) for f in facets])
    refresh(target, ('model.stl',))
    symmetric = failures(lambda: registry.verify(target))
    flips = registry.verify(directory/'mutant-symmetric')['exportChecks']['mirrorDiscriminability']
    assert symmetric is None and flips['x']['detectable'] is False
    cases['symmetricMirrorLimit'] = {'accepted': True, 'mirrorDiscriminability': flips}
    expected_codes = {'no-downgrade-built': 'RERUN_REQUIRED', 'no-downgrade-receipt': 'RERUN_REQUIRED', 'no-downgrade-version': 'RERUN_REQUIRED'}
    for label, fault in cases.items():
        if label == 'symmetricMirrorLimit':
            continue
        assert fault['code'] == expected_codes.get(label, fault['code']) and fault['code'] != 'ACCEPTED', (label, fault)
        if label not in expected_codes:
            assert fault['code'] in ('VERIFICATION_FAILED', 'INPUT_CHANGED', 'EXPECTATION_FAILED'), (label, fault)
    q.check('refreshedMutants', cases)

    # 12 Source removal, schema-aware export, relative path from another directory, legacy readSTEP.
    q.check('sourceLifecycle', lifecycle(q, directory, base, truth))

    # 13 Workflow reuse and invalidation through the scheduler.
    q.check('workflowReuse', workflow_reuse(q, directory, base, truth))
    q.check('workflowSourceRemoval', workflow_source_removal(q, directory, base, truth))
    q.check('workflowStudySourceRemoval', workflow_source_removal(q, directory, base, truth, study=True))
    q.check('studySourceRemoval', study_source_removal(q, directory, base, truth))

    # 14 Whole-run timeout: process tree stopped, failed result, nothing verified.
    q.check('timeout', {'fault': failures(lambda: registry.run(importing(inputs/'bracket.step', base_expect(truth)), directory/'timeout',
                                                               locations={'freecad': executable}, timeout=0.5)),
                        'result': json.loads((directory/'timeout/result.json').read_text()) if (directory/'timeout/result.json').exists() else None})

    return finish(q)




def finish(q):
    q.report['sourceDigestAtEnd'] = source_digest('freecad')
    q.report['sourceUnchangedDuringRun'] = q.report['sourceDigestAtEnd'] == q.report['sourceDigest']
    q.report.update(verified=q.report['sourceUnchangedDuringRun'], seconds=time.time()-q.report['started'])
    q.save()
    return q.report


def study_document(source, truth):
    """A common analytic study: two placement states of one imported part."""
    return importing(source, base_expect(truth),
                     placement={'position': [{'$analytic': {'type': 'values', 'values': [0, 50]}}, 0, 0], 'clocking': 0})


def scheduler_results(tree):
    return [p for p in sorted(Path(tree).rglob('result.json')) if isinstance(json.loads(p.read_text()).get('jobs'), list)]


def forge_job_maps(tree):
    """Forge every scheduler input map (each workflow result and each job record); return the originals."""
    originals = {}
    for path in scheduler_results(tree) + sorted(Path(tree).rglob('job.json')):
        originals[path] = path.read_text()
        value = json.loads(originals[path])
        for record in (value['jobs'] if path.name == 'result.json' else [value]):
            record['inputHashes'] = {k: '0'*64 for k in record['inputHashes']}
        path.write_text(json.dumps(value))
    assert originals, 'no scheduler input maps found'
    return originals


def workflow_source_removal(q, directory, base, truth, *, study=False):
    """Scheduled workflow (study=True: with an analytic member, so a study of workflows) after original removal."""
    from schemaxis.workflow import execute, verify as verify_workflow
    from schemaxis.schema_snapshots import export_run
    from schemaxis.parallel import retained_inputs, reusable_inputs
    work = directory/('workflow-study-removal' if study else 'workflow-removal'); work.mkdir()
    source = work/'supplier'/'bracket.step'; source.parent.mkdir(); write_planar(source, base, name='bracket')
    second = study_document(source, truth) if study else importing(source, base_expect(truth), refine=True)
    document = {'version': 'schemaxis.workflow/1', 'operations': [
        {'id': 'part', 'document': importing(source, base_expect(truth))}, {'id': 'second', 'document': second}]}
    execute(document, work/'run', freecad=q.executable, timeout=300)
    jobs = [json.loads(p.read_text()) for p in sorted((work/'run').rglob('job.json'))]
    retained = [retained_inputs(Path(j['directory']), j['effective']) for j in jobs]
    assert jobs and all(r == j['inputHashes'] for r, j in zip(retained, jobs)), retained
    record = {'jobs': len(jobs), 'schedulerResults': len(scheduler_results(work/'run')),
              'commonStudy': json.loads((work/'run'/'result.json').read_text()).get('protocol') is not None,
              'before': verify_workflow(work/'run'), 'retainedEqualsJobMaps': True, 'retained': retained}
    export_run(work/'run', work/'exported')
    source.unlink()
    record['originalAfterRemoval'] = verify_workflow(work/'run')
    record['exportedAfterRemoval'] = verify_workflow(work/'exported')
    export_run(work/'exported', work/'re-exported')
    record['reExportedAfterRemoval'] = verify_workflow(work/'re-exported')
    originals = forge_job_maps(work/'re-exported')
    forged = failures(lambda: verify_workflow(work/'re-exported'))
    for path, text in originals.items():
        path.write_text(text)
    assert forged and forged['code'] == 'VERIFICATION_FAILED', forged
    record['forgedResultAndJobMaps'] = {**forged, 'forgedFiles': len(originals)}
    record['restoredAfterForgery'] = verify_workflow(work/'re-exported')
    record['reuseWithOriginalAbsent'] = failures(lambda: reusable_inputs(document['operations'][0]['document']))
    record['freshRunWithOriginalAbsent'] = failures(lambda: execute(document, work/'fresh-absent', freecad=q.executable, timeout=300))
    record['resumeExportedWithOriginalAbsent'] = failures(lambda: execute(document, work/'exported', freecad=q.executable,
                                                                          timeout=300, resume=True))
    assert record['reuseWithOriginalAbsent']['code'] == 'RESOURCE_NOT_FOUND'
    assert record['freshRunWithOriginalAbsent'] and record['freshRunWithOriginalAbsent']['code'] == 'RESOURCE_NOT_FOUND'
    assert record['resumeExportedWithOriginalAbsent'] is not None, 'resume must not reuse or succeed without the original'
    write_planar(source, base, name='bracket')
    source.write_text(source.read_text().replace("'2026-10-19T00:00:00'", "'2026-10-19T12:00:00'"))
    execute(document, work/'run', freecad=q.executable, timeout=300, resume=True)
    reused = [job.get('reused') for p in scheduler_results(work/'run') for job in json.loads(p.read_text())['jobs']]
    record['changedOriginalResumeReused'] = reused
    assert reused and not any(reused), reused
    record['afterChangedRerun'] = verify_workflow(work/'run')
    return record


def study_source_removal(q, directory, base, truth):
    """Standalone common study: verify, export and re-export after source removal; planning refuses the absent source."""
    from schemaxis.schema_snapshots import export_run
    from schemaxis.parallel import retained_inputs, reusable_inputs
    work = directory/'study-removal'; work.mkdir()
    source = work/'supplier'/'bracket.step'; source.parent.mkdir(); write_planar(source, base, name='bracket')
    document = study_document(source, truth)
    q.run(document, work/'run', timeout=300)
    states = json.loads((work/'run'/'result.json').read_text())['states']
    before = retained_inputs(work/'run', document)
    record = {'states': len(states), 'before': registry.verify(work/'run'), 'retained': before,
              'reusableBefore': reusable_inputs(document) == before}
    export_run(work/'run', work/'exported')
    source.unlink()
    record['originalAfterRemoval'] = registry.verify(work/'run')
    record['exportedAfterRemoval'] = registry.verify(work/'exported')
    export_run(work/'exported', work/'re-exported')
    record['reExportedAfterRemoval'] = registry.verify(work/'re-exported')
    record['retainedAfterRemoval'] = retained_inputs(work/'re-exported', document) == before
    record['planWithOriginalAbsent'] = failures(lambda: registry.plan(document, legacy=True))
    record['reuseWithOriginalAbsent'] = failures(lambda: reusable_inputs(document))
    assert record['retainedAfterRemoval'] and record['planWithOriginalAbsent']['code'] == 'RESOURCE_NOT_FOUND'
    return record


def admission_traps(inputs, base):
    traps = {}
    w_text = write_planar(inputs/'bracket.step', base, name='bracket').read_text()
    head, data = w_text.split('DATA;\n', 1)
    body, tail = data.rsplit('ENDSEC;', 1)
    # Orphan mm context before an inch-assigned file (the reader would still use the referenced inch).
    inch = write_planar(inputs/'trap-inch.step', transform(base, I3, 1/25.4), unit='inch', name='bracket').read_text()
    ih, idata = inch.split('DATA;\n', 1); ibody, itail = idata.rsplit('ENDSEC;', 1)
    orphan = ("#90001=( LENGTH_UNIT() NAMED_UNIT(*) SI_UNIT(.MILLI.,.METRE.) );\n"
              "#90002=( GEOMETRIC_REPRESENTATION_CONTEXT(3) GLOBAL_UNIT_ASSIGNED_CONTEXT((#90001)) REPRESENTATION_CONTEXT('','') );\n")
    (inputs/'trap-orphan-context.step').write_text(ih+'DATA;\n'+orphan+ibody+'ENDSEC;'+itail)
    traps['orphanContext'] = (inputs/'trap-orphan-context.step', 'UNSUPPORTED_SOURCE')
    # Strings and comments that mention units, assemblies and B-reps are inert.
    comment = "/* #99=MANIFOLD_SOLID_BREP('x',#1); NEXT_ASSEMBLY_USAGE_OCCURRENCE SI_UNIT(.CENTI.,.METRE.) */\n"
    trap = (head.replace("FILE_DESCRIPTION(('Schemaxis qualification part')", "FILE_DESCRIPTION(('SI_UNIT($,.METRE.); MAPPED_ITEM'')')")
            + 'DATA;\n' + comment + body + 'ENDSEC;' + tail)
    (inputs/'trap-strings.step').write_text(trap)
    traps['stringsAndComments'] = (inputs/'trap-strings.step', None)
    (inputs/'trap-no-unit.step').write_text(w_text.replace('GLOBAL_UNIT_ASSIGNED_CONTEXT((#9,#10,#11))', 'GLOBAL_UNIT_ASSIGNED_CONTEXT((#10,#11))'))
    traps['noLengthUnit'] = (inputs/'trap-no-unit.step', 'UNDECLARED_UNIT')
    extra = "#90010=ITEM_DEFINED_TRANSFORMATION('','',#17,#17);\n"
    (inputs/'trap-transformation.step').write_text(head+'DATA;\n'+extra+body+'ENDSEC;'+tail)
    traps['transformation'] = (inputs/'trap-transformation.step', 'UNSUPPORTED_SOURCE')
    teeth = 500   # 2002 oriented edges in each face loop, well under the entity cap
    xs = [-20+40*i/(2*teeth) for i in range(2*teeth+1)]
    comb = [(-20, -15), (20, -15)]
    for k in range(2*teeth, 0, -1):
        hi = 20 if k % 2 else 15
        comb += [(xs[k], hi), (xs[k-1], hi)]
    comb = [p for i, p in enumerate(comb) if i == 0 or p != comb[i-1]]
    write_planar(inputs/'comb.step', prism(comb, [], 0, 10), name='comb')
    traps['loopCap'] = (inputs/'comb.step', 'RESOURCE_LIMIT')
    padding = ''.join("#%d=CARTESIAN_POINT('',(0.,0.,%d.));\n" % (200000+i, i) for i in range(100001))
    (inputs/'padded.step').write_text(head+'DATA;\n'+body+padding+'ENDSEC;'+tail)
    traps['entityCap'] = (inputs/'padded.step', 'RESOURCE_LIMIT')
    return traps


def lifecycle(q, directory, base, truth):
    from schemaxis.schema_snapshots import export_run
    from schemaxis.adaptors.freecad.integration import retainedInputs
    work = directory/'lifecycle'; work.mkdir()
    disposable = work/'supplier'; disposable.mkdir()
    write_planar(disposable/'bracket.step', base, name='bracket')
    doc = importing(disposable/'bracket.step', base_expect(truth))
    q.run(doc, work/'run')
    before = retainedInputs(work/'run', doc)
    export_run(work/'run', work/'exported')
    (disposable/'bracket.step').unlink()
    result = {'retainedBeforeRemoval': before,
              'runAfterRemoval': registry.verify(work/'run')['verified'],
              'exportedAfterRemoval': registry.verify(work/'exported')['verified'],
              'retainedExported': retainedInputs(work/'exported', doc) == before,
              'newPlanAfterRemoval': failures(lambda: registry.plan(doc, legacy=True))}
    assert result['newPlanAfterRemoval']['code'] == 'RESOURCE_NOT_FOUND'
    # Relative authored path: planned in one directory, verified and replayed from another.
    rel = work/'relative'; rel.mkdir(); write_planar(rel/'part.step', base, name='bracket')
    cwd = os.getcwd()
    try:
        os.chdir(rel)
        rdoc = importing(Path('part.step'), base_expect(truth))
        q.run(rdoc, rel/'run')
        recorded = json.loads((rel/'run/sources.json').read_text())['part']['file']
        os.chdir(directory)
        result['relative'] = {'recorded': recorded, 'verifiedElsewhere': registry.verify(rel/'run')['verified'],
                              'retained': retainedInputs(rel/'run', rdoc)}
        assert result['relative']['retained'] == {str(rel/'part.step'): hashlib.sha256((rel/'part.step').read_bytes()).hexdigest()}
    finally:
        os.chdir(cwd)
    # Legacy readSTEP: same authored shape and plan, now verified from its retained copy only.
    legacy_source = work/'legacy.step'; write_planar(legacy_source, base, name='bracket')
    ldoc = {'version': 'schemaxis.freecad/1', 'nodes': [{'id': 'solid', 'filter': 'readSTEP', 'options': {'file': str(legacy_source)}}],
            'output': 'solid'}
    q.run(ldoc, work/'legacy')
    legacy_retained = retainedInputs(work/'legacy', ldoc)
    legacy_source.unlink()
    result['legacyReadSTEP'] = {'verifiedWithoutOriginal': registry.verify(work/'legacy')['verified'], 'retained': legacy_retained}
    return result


def workflow_reuse(q, directory, base, truth):
    from schemaxis.workflow import execute, verify as verify_workflow
    work = directory/'workflow'; work.mkdir()
    source = work/'bracket.step'; write_planar(source, base, name='bracket')
    document = {'version': 'schemaxis.workflow/1', 'operations': [{'id': 'part', 'document': importing(source, base_expect(truth))}]}
    first = execute(document, work/'run', freecad=q.executable, timeout=300)
    resumed = execute(document, work/'run', freecad=q.executable, timeout=300, resume=True)
    assert all(job.get('reused') is True for job in resumed['jobs'])
    source.write_text(source.read_text().replace("'2026-10-19T00:00:00'", "'2026-10-19T08:00:00'"))
    changed = execute(document, work/'run', freecad=q.executable, timeout=300, resume=True)
    assert all(job.get('reused') is False for job in changed['jobs'])
    job = json.loads((Path(changed['jobs'][0]['directory'])/'job.json').read_text())
    # Forge the scheduler's recorded input hashes (job.json and the workflow result) to other bytes.
    originals = {}
    for path in (Path(changed['jobs'][0]['directory'])/'job.json', work/'run'/'result.json'):
        originals[path] = path.read_text()
        value = json.loads(originals[path])
        for record in ([value] if path.name == 'job.json' else value['jobs']):
            record['inputHashes'] = {k: '0'*64 for k in record['inputHashes']}
        path.write_text(json.dumps(value))
    forged_fault = failures(lambda: verify_workflow(work/'run'))
    for path, text in originals.items():
        path.write_text(text)
    assert forged_fault and forged_fault['code'] == 'VERIFICATION_FAILED', forged_fault
    return {'firstReused': [j.get('reused') for j in first['jobs']], 'unchangedResumeReused': [j.get('reused') for j in resumed['jobs']],
            'changedSourceRerun': [j.get('reused') for j in changed['jobs']], 'newInputHashes': job['inputHashes'],
            'forgedJobInputHashes': forged_fault, 'restoredVerify': verify_workflow(work/'run').get('verified')}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--directory', required=True)
    parser.add_argument('--executable', required=True, help='absolute FreeCAD command-line launcher')
    parser.add_argument('--pid-log', help='optional launcher PID log used to prove refusals start no native process')
    parser.add_argument('--targeted', action='store_true', help='baseline, revision and source-removal lifecycle groups only')
    arguments = parser.parse_args()
    print(json.dumps(list(qualify(arguments.directory, arguments.executable, arguments.pid_log, arguments.targeted)['checks'])))
