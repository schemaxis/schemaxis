"""Qualified native material-solid occurrences, without numerical measurement.

FreeCAD 1.1.4 / OCCT 7.8.1: countElement('SubShape') counts direct occurrences;
childShapes and typed maps deduplicate. A repeated or balanced compound must not
be admitted merely because its mapped solid count and signed mass match one
solid. Wire.OrderedEdges preserves legitimate repeated seam-edge occurrences.
This structural gate does not measure mass or replace the caller's positive
signed-volume/material checks. All returned handles remain native-process local. Callers choose their existing
resource limits and may provide an additional installed deadline checkpoint.
"""
from schemaxis.dispatch import remaining_timeout


class TopologyRefused(ValueError):
    """The input does not establish one closed, occurrence-complete solid."""


class TopologyLimit(TopologyRefused):
    """Admission exceeded its caller's finite prospective work limits."""


def admit(shape, *, max_faces, max_edges, max_occurrences, max_checks, checkpoint=None):
    import FreeCAD,Part
    if tuple(FreeCAD.Version()[:3])!=('1','1','4') or Part.OCC_VERSION!='7.8.1':
        raise TopologyRefused('Topology occurrence API requires qualified FreeCAD1.1.4/OCCT7.8.1')
    limits=(max_faces,max_edges,max_occurrences,max_checks)
    if any(type(n) is not int or not 1<=n<=4000000 for n in limits):
        raise TopologyLimit('Topology admission needs finite positive integral caller limits')
    nodes=checks=0
    def gate():
        remaining_timeout()
        if checkpoint is not None:checkpoint()
    def count(parent,maximum):
        nonlocal nodes
        gate();value=parent.countElement('SubShape')
        if type(value) is not int or not 1<=value<=maximum:
            raise TopologyLimit('Native direct topology occurrence count exceeds admission')
        nodes+=value
        if nodes>max_occurrences:raise TopologyLimit('Native direct topology occurrence budget exhausted')
        return value
    def children(parent,kind,maximum):
        expected=count(parent,maximum);result=parent.childShapes();gate()
        if len(result)!=expected or any(child.ShapeType!=kind for child in result):
            raise TopologyRefused('Native direct topology occurrences differ from deduplicated child map')
        return result
    def equal(left,right,*,same=False):
        nonlocal checks
        gate();checks+=1
        if checks>max_checks:raise TopologyLimit('Native topology identity-comparison budget exhausted')
        return left.isSame(right) if same else left.isEqual(right)
    gate()
    faces_count=shape.countElement('Face')
    if shape.countElement('Solid')!=1:
        raise TopologyRefused('Material input needs one mapped solid before occurrence admission')
    if not 1<=faces_count<=max_faces or shape.countElement('Edge')>max_edges:
        raise TopologyLimit('Material input exceeds mapped topology admission')
    # Arrays are materialized only after native count admission.
    mapped_faces=shape.Faces;mapped_solids=shape.Solids;gate()
    if len(mapped_faces)!=faces_count or len(mapped_solids)!=1:
        raise TopologyRefused('Native mapped material inventories differ')
    if not shape.isValid() or not mapped_solids[0].isClosed():
        raise TopologyRefused('Material input needs a valid closed solid')
    solid=shape;depth=0
    while solid.ShapeType=='Compound':
        depth+=1
        if depth>32:raise TopologyLimit('Native single-child wrapper depth exceeds admission')
        if count(solid,max_occurrences)!=1:
            raise TopologyRefused('Material input needs exactly one actual solid occurrence')
        parts=solid.childShapes();gate()
        if len(parts)!=1:raise TopologyRefused('Native single-child wrapper map differs')
        solid=parts[0]
    if solid.ShapeType!='Solid':raise TopologyRefused('Material input needs exactly one actual solid occurrence')
    shells=children(solid,'Shell',max_faces);inventory=[];edges_total=0
    for shell in shells:
        for face in children(shell,'Face',max_faces):
            if len(inventory)>=max_faces:raise TopologyLimit('Native face occurrence budget exhausted')
            if face.Orientation not in ('Forward','Reversed'):
                raise TopologyRefused('Native material face orientation is unsupported')
            if any(equal(face,prior['face'],same=True) for prior in inventory):
                raise TopologyRefused('Repeated native face occurrence')
            wires=children(face,'Wire',max_edges);mapped_wires=face.Wires;gate()
            if len(wires)!=len(mapped_wires) or any(sum(equal(w,m) for m in mapped_wires)!=1 for w in wires):
                raise TopologyRefused('Native face wire occurrences differ from mapped orientation/location')
            wire_inventory=[]
            for index,wire in enumerate(wires):
                if any(equal(wire,prior,same=True) for prior in wires[:index]):
                    raise TopologyRefused('Repeated native wire occurrence inside one face')
                expected=count(wire,max_edges);edges_total+=expected
                if edges_total>max_edges:raise TopologyLimit('Oriented boundary occurrence budget exhausted')
                ordered=wire.OrderedEdges;gate()
                if len(ordered)!=expected:
                    raise TopologyRefused('Ordered boundary chain omits or adds native edge occurrences')
                wire_inventory.append({'wire':wire,'edges':ordered})
            inventory.append({'face':face,'wires':wire_inventory})
    if len(inventory)!=len(mapped_faces) or any(sum(equal(r['face'],f) for f in mapped_faces)!=1 for r in inventory):
        raise TopologyRefused('Native face occurrences differ from mapped orientation/location')
    # Bind complete whole-shape membership to the one original solid as well.
    solid_faces=mapped_solids[0].Faces;gate()
    if len(solid_faces)!=len(mapped_faces):raise TopologyRefused('Faces exist outside the one material solid')
    for face in mapped_faces:
        matches=[i for i,other in enumerate(solid_faces) if equal(face,other)]
        if len(matches)!=1:raise TopologyRefused('Whole-shape solid face membership differs')
        solid_faces.pop(matches[0])
    if sum(len(w['edges']) for f in inventory for w in f['wires'])!=edges_total:
        raise TopologyRefused('Integration boundary occurrence total differs from admitted raw topology')
    gate()
    return {'solid':solid,'faces':inventory,'facts':{'solidOrientation':solid.Orientation,'wrapperDepth':depth,'shellOccurrences':len(shells),
            'faceOccurrences':len(inventory),'edgeOccurrences':edges_total,
            'directChildOccurrences':nodes,'identityComparisons':checks}}
