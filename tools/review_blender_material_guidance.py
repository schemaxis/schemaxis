"""Conceptual review for named surface layouts and independent Object palettes."""
import json,re
from pathlib import Path
from studio_guidance import seed,report
from schemaxis.adaptors import registry
from schemaxis.studio_guidance import fields

MEANINGS={
 'materialAssignments':'Give an editable surface several named material regions, then optionally give another linked Object its own palette. A DATA layout owns shared element indices; an OBJECT override changes material pointers while keeping exactly the same geometric data.',
 'object':'Declared Mesh, classic Curve, text, linked instance or captured asset root. A captured root must resolve to one geometric part, or sourceObject must select a unique original native/glTF part.',
 'sourceObject':'Optional original source Object identity inside a captured native/glTF asset. It is a unique source selector, not an appended collision name or a mutable output witness. Omit it only when the asset contains exactly one supported geometric part.',
 'sharing':'DATA-layout ownership: refuse requires one existing Object owner; copy isolates only this Object; shared applies the layout to all remaining owners after explicit copies. Layout construction resets affected slots to DATA links. OBJECT palette overrides do not copy geometry.',
 'slots':'Named logical material slots. A layout defines their order and referenced materials explicitly, replacing the captured palette and all element mappings. An override maps every logical layout slot exactly once; its authored list order is irrelevant. Unused slots may remain for later native editing.',
 'defaultSlot':'Logical slot assigned to every surface element outside the explicit regions. It must belong to this layout, so native slot numbers and imported palette order are never assumed.',
 'regions':'Disjoint nonempty selected surface regions, each assigned a logical slot. Missing, empty, out-of-range and overlapping selections refuse; there is no implicit last-writer rule. Select current base-data elements after mesh edits/fields and before evaluated modifiers. Repeated full-domain scans consume an aggregate one-million-element work budget; sparse explicit indices charge only selected entries.',
 'slot':'Logical slot ID from this layout, used for the selected region. This names a material role such as shell or label rather than a native integer slot.',
 'selection':'Choose current Mesh faces by indices/local box/normal, authored classic splines by local IDs, imported splines by indices, or a half-open Unicode text-character range. All selects the complete supported data domain; incompatible domains refuse.',
 'layout':'ID of a named DATA layout in this production. The override target must be a distinct Object sharing the exact same actual data ID after all explicit copies. Equal geometry or equal slot names on another data block is insufficient.',
 'material':'Declared material resource or material graph used in this logical slot. Material shader and Workbench display-image settings remain independent, so different regions can use different captured previews without changing their shaders.',
 'indices':'Distinct zero-based current-stage surface element indices. faceIndices selects Mesh polygons after topology edits; splineIndices selects ordered native classic splines. Values must exist and the selection must be nonempty.',
 'names':'Distinct local IDs of authored classic splines. These IDs identify declared spline records; Blender splines have no independent native names. Imported controls require explicit splineIndices instead.',
 'minimum':'Lower local XYZ corner of the face-selection box in production units, before the Object transform. It must not exceed maximum on any axis.',
 'maximum':'Upper local XYZ corner of the face-selection box. Center tests face centres; contained requires every face vertex inside the closed box.',
 'test':'Center selects faces whose vertex-average centre is inside the local box. Contained selects only faces with every vertex inside it. Boundary comparisons are inclusive.',
 'invert':'Select the complement of this box/normal face selection within the current Mesh. The final selection must still be nonempty and disjoint from all other material regions.',
 'direction':'Nonzero local XYZ direction for the face-normal cone. Newell polygon normals determine membership before Object transforms and evaluated modifiers.',
 'angle':'Maximum face-normal angle from direction in radians, from zero to pi. Zero selects aligned faces; inversion selects the complement. Degenerate geometry cannot establish a normal.',
 'start':'Inclusive zero-based Unicode character position in the text body. Positions count code points, not UTF-8 bytes or shaped glyphs; whitespace still has a native character record.',
 'end':'Exclusive Unicode character position. It must exceed start and stay within the current text body; a material range never implicitly extends the text.',
}
KINDS={
 'layout':'Define a DATA-linked surface layout, explicitly replacing the whole palette and every element material index under refuse/copy/shared ownership.',
 'override':'Give a distinct linked Object an OBJECT-linked material palette for a named DATA layout. Geometry and element indices remain shared; the layout must resolve to the identical data ID.',
 'all':'Select every Mesh face, classic spline or text character. This remains a region and therefore cannot overlap another region.',
 'faceIndices':'Select distinct existing zero-based Mesh polygon indices at the current topology stage.',
 'faceBox':'Select Mesh faces by a local XYZ box, with centre/contained and complement choices.',
 'faceNormal':'Select Mesh faces by a local polygon-normal cone and optional complement.',
 'splines':'Select authored classic splines by their locally unique declared IDs.',
 'splineIndices':'Select existing ordered native classic splines by zero-based indices, including imported controls without authored spline IDs.',
 'characters':'Select a nonempty half-open Unicode text-character range; this does not select bytes or rendered glyph geometry.',
}
LABELS={'layout':'Shared data layout','override':'Independent Object palette','all':'Complete surface','faceIndices':'Face indices','faceBox':'Local face box','faceNormal':'Face normal cone','splines':'Named authored splines','splineIndices':'Ordered native splines','characters':'Text character range'}


def main():
    seed('blender');target=Path('src/schemaxis/adaptors/blender/guidance.json');guide=json.loads(target.read_text());changed=0
    for version,route in registry.metadata('blender')['routes'].items():
        records=guide['routes'][version]['fields']
        for address,node in fields(registry.binding(route['schema'])()):
            if '/properties/materialAssignments' not in address:continue
            key=re.findall(r'/properties/([^/]+)',address)[-1]
            if key=='kind':meaning=KINDS.get(node.get('const'),'Choose a DATA surface layout, an independent OBJECT palette, or a finite region selector; each variant admits only effective fields.')
            elif key=='id':meaning=('Locally unique logical material slot ID, such as shell or label. It identifies a material role independently of native slot numbers.' if '/properties/slots/' in address else 'Unique material-assignment ID within this production. Palette overrides reference a layout by this ID, without depending on declaration order.')
            else:meaning=MEANINGS[key]
            records[address]={'status':'reviewed','explanation':meaning,'sources':['src/schemaxis/adaptors/blender/material_assignments.py','src/schemaxis/adaptors/blender/material_assignments_native.py','docs/blender-material-assignments.md','https://docs.blender.org/manual/en/5.2/render/materials/assignment.html']}
            branch=node.get('properties',{}).get('kind',{}).get('const')
            if branch in LABELS:records[address]['label']=LABELS[branch]
            changed+=1
        for record in records.values():
            if 'Per-spline material assignment remains unfinished' in record.get('explanation',''):
                record['explanation']=record['explanation'].replace('Per-spline material assignment remains unfinished','Use a named materialAssignments layout for per-spline regions and Object palettes for linked instances')
    target.write_text(json.dumps(guide,ensure_ascii=False,indent=2)+'\n');audit=report('blender');print(json.dumps({'reviewedMaterialFields':changed,'counts':audit['counts'],'complete':audit['complete'],'stale':len(audit['stale']),'linkIssues':len(audit['linkIssues'])}))


if __name__=='__main__':main()
