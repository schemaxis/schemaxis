"""Review classic spline authoring routes with geometry-specific explanations."""
import json,re
from pathlib import Path
from studio_guidance import seed,report
from schemaxis.adaptors import registry
from schemaxis.studio_guidance import fields

MEANINGS={
 'spline':'Create editable classic Curve data with ordered POLY, Bezier or rational NURBS splines, planar fills and swept sections. This is distinct from modern hair Curves and Surface data.',
 'id':'Stable public Object identity, or a locally unique spline identity within this object. Spline IDs identify ordered authored records; native Blender splines have no independent names.',
 'location':'Object-local translation in production units, applied after constructing all spline controls and before parenting. It does not move a referenced profile section inside its own local XY frame.',
 'rotation':'Object XYZ Euler rotation in radians. Profile section source rotation is ignored by Blender; the target path determines its sweep frame.',
 'scale':'Positive Object component scale. A referenced profile consumes its X/Y section scale while ignoring translation and rotation. The target curve transform applies to the final sweep.',
 'collection':'Optional declared collection containing this Curve Object. An empty value uses the scene collection; native collection instancing and hierarchy remain separate declarations.',
 'material':'Optional declared material for the entire Curve data. Per-spline material assignment remains unfinished; later materialBindings can replace the construction material.',
 'hidden':'Hide this Object from rendered images while retaining native editable geometry. Resource and profile dependencies remain available to consumers.',
 'splines':'One to128 ordered classic splines sharing this Curve data and sweep settings. Local IDs are distinct; at most16384 controls across one object and conservative evaluation bounds apply.',
 'closed':'Connect the last control back to the first. At least three controls are required. Cyclic NURBS disable endpoint and Bezier knots to use periodic knots.',
 'reverse':'Reverse the curve direction without changing its geometric locus; Bezier left/right handles exchange. Closed profile direction matters to native cap/side winding, so choose clockwise sections for the qualified solid sweep.',
 'smooth':'Choose smooth shading for surfaces generated from this spline; this does not change tessellation or repair geometric winding.',
 'sampling':'Subdivision sampling: object preview/render controls bound evaluation, while per-spline zero inherits object preview subdivisions. Positive per-spline sampling overrides preview subdivisions for that spline.',
 'radiusInterpolation':'Bezier interpolation of per-control radius multipliers. LINEAR blends directly, CARDINAL/BSPLINE shape the transition, and EASE softens ends. Non-Bezier splines retain LINEAR.',
 'tiltInterpolation':'Bezier interpolation of twist angles in radians between controls. LINEAR is the declared policy for POLY and NURBS splines.',
 'points':'Ordered control records in Curve-local coordinates. POLY joins controls directly; Bezier uses tangent handles; NURBS combines positive rational weights and knot policy.',
 'position':'Required local XYZ control or explicit Bezier handle position in production units. Planar curves require z zero. Recenter/rescale when float32 native storage cannot preserve local feature size.',
 'radius':'Nonnegative per-control multiplier of the swept section, or the path option that enables radius along deformation. A multiplier of one preserves the declared section size; taper mode can replace or combine it.',
 'tilt':'Local sweep-frame twist at this control in radians; interpolation follows the spline policy. This differs from Object Euler rotation and does not move the centreline.',
 'left':'Incoming Bezier tangent handle: AUTO derives smooth geometry, VECTOR creates a straight connection, FREE uses a local coordinate, and ALIGNED requires an opposite explicit collinear partner.',
 'right':'Outgoing Bezier tangent handle, independent from the incoming handle unless ALIGNED is chosen. Explicit positions are local to the same Curve Object as the control.',
 'weight':'Strictly positive rational NURBS weight. Larger values pull the evaluated curve toward this control; changing weight can alter interior geometry without changing bounds.',
 'order':'NURBS polynomial degree plus one, between two and six and no greater than the control count. Order three with rational weights can represent exact conic arcs.',
 'endpoint':'Clamp an open NURBS spline to its end controls. Cyclic splines disable this setting because their knots are periodic.',
 'bezierKnots':'Use complete quadratic/cubic Bezier-style NURBS spans. Control counts must fit the chosen order, and cyclic splines disable this setting.',
 'dimensions':'2D constrains controls/handles to local XY and enables planar fill/outline offset; 3D permits spatial paths and spatial surface fill policies.',
 'fill':'AUTO chooses BOTH for planar contours and FULL for spatial sweeps. Other choices select front/back sides or disable planar filling; incompatible dimensional choices refuse.',
 'fillRule':'For planar contours, EVEN_ODD alternates inside/outside at each crossing; NONZERO fills same-winding overlap as a union. Native nonzero extrusions can retain internal walls; this is not arbitrary solid repair.',
 'fillSolver':'Planar sweep-line filling is fast but lacks self-intersection support. CDT supports intersections and uses a conservative quadratic intersection budget before evaluation.',
 'offset':'Signed planar outline distance in local production units. Spatial curve offset refuses because native outline offset requires planar shape semantics.',
 'extrude':'Local Z extension on each side of a planar curve, so one produces thickness two. Filled contours and winding determine side/cap topology; arbitrary valid-solid results are not guaranteed.',
 'preview':'Object preview subdivisions per curve segment. Per-spline zero inherits this value; more subdivisions increase geometric approximation cost.',
 'render':'Render subdivisions per segment; zero falls back to preview sampling. Admission bounds the maximum preview/render/spline resolution, including supported imported keys.',
 'bevel':'Choose no sweep, a round section, an editable quarter-profile section or a referenced planar Curve section. This is curve sweeping, distinct from rounding polygon mesh edges.',
 'depth':'Positive local round/custom-profile section distance before per-control radius, taper and Object transforms. Choose no swept section for a centreline.',
 'resolution':'Section subdivision level for round or custom-profile bevels. More segments refine the cross-section and increase conservative vertex cost.',
 'handle':'AUTO smooths both quarter-profile tangents at this control; VECTOR makes a sharp corner with straight adjoining edges. Native independent free profile handle coordinates are not exposed by this declaration.',
 'evenLengths':'Sample the profile at approximately even lengths instead of following its control spacing; this changes generated section geometry, not the centreline.',
 'straightEdges':'Include profile straight-edge sampling when distributing section segments. The profile remains editable in the native project.',
 'object':'Declared Curve Object identity or object geometry-resource alias used as a section/taper. Asset members use original native source selectors; mutable imported collision names are not authority.',
 'caps':'Request native end filling for swept geometry. Object profile direction affects cap/side orientation; use the qualified clockwise section direction for solid sweeps.',
 'twist':'Sweep-frame policy along the centreline: MINIMUM minimizes twist, Z_UP anchors the frame to Z, and TANGENT follows native tangent frames.',
 'twistSmooth':'Native frame-twist smoothing iterations between path samples. It changes the swept frame while preserving declared control positions.',
 'trim':'Start/end factors select a subrange of swept geometry without deleting native controls. Each end has its own resolution/segment/spline mapping. Partial trimming requires constant point radius along each spline because Blender5.2 can retain an untrimmed endpoint radius.',
 'start':'Start factor in zero to one; it must not exceed end. This changes the swept extent and retains the editable original centreline.',
 'end':'End factor in zero to one; it must be at least start. Caps and taper mapping follow the resulting swept range.',
 'startMapping':'Interpret the start factor by sample resolution, segment count or spline parameter, matching the corresponding native curve policy.',
 'endMapping':'Interpret the end factor independently by resolution, segments or spline parameter. Different mappings can select different points on a nonuniform curve.',
 'taper':'Optional one-open-spline planar Curve dependency whose local X maps along the path and local Y controls section radius. It requires swept geometry and participates in cycle admission.',
 'mode':'OVERRIDE replaces control radii with taper values, MULTIPLY combines them multiplicatively, and ADD sums them. Nondefault taper options require a taper object.',
 'mapTrim':'Map taper along the trimmed sweep portion rather than the original entire spline. Useful when changing trim factors.',
 'path':'Retain native path/deformation controls for followPath consumers. Constraint factor authoring is currently fixed; broader animated parameter and curve-deform authoring remain required.',
 'enabled':'Enable native path evaluation for constraints and deformation consumers; retained independently from whether the Curve has swept thickness.',
 'duration':'Native path duration in frames, used by path-time consumers. A fixed followPath factor directly selects normalized path position instead.',
 'follow':'Enable tangent-oriented path following in Curve settings. A followPath constraint also has its own following flag and fixed normalized factor.',
 'stretch':'Stretch a curve-deformed object along the path length. This retains the native deformation policy; a full curve modifier authoring family remains unfinished.',
 'bounds':'Use the deforming object bounds when mapping curve deformation along the path; this differs from a followPath constraint location factor.',
}


def main():
    seed('blender');path=Path(__file__).resolve().parents[1]/'src/schemaxis/adaptors/blender/guidance.json';d=json.loads(path.read_text());count=0
    for version,route in d['routes'].items():
        valid=dict(fields(registry.binding(registry.metadata('blender')['routes'][version]['schema'])()))
        for address in list(route['fields']):
            if re.search(r'/properties/objects/items/oneOf/8(?:/|$)',address) and address not in valid:del route['fields'][address]
        for address,r in route['fields'].items():
            if not re.search(r'/properties/objects/items/oneOf/8(?:/|$)',address):continue
            key=address.rsplit('/properties/',1)[-1].split('/')[0] if '/properties/' in address else 'spline'
            if address.endswith('/oneOf/8'):key='spline';r['label']='Editable spline curves'
            match=re.search(r'/properties/splines/items/(?:anyOf|oneOf)/(\d+)(?:/|$)',address)
            kind=['POLY','BEZIER','NURBS'][int(match[1])] if match else None
            if key=='kind':
                if '/properties/bevel/' in address:explanation='Choose no section, a round section, an explicit quarter profile or a referenced planar Curve section.'
                elif '/properties/left/' in address or '/properties/right/' in address:explanation='Choose an automatic smooth, automatic straight, free positioned or explicitly aligned Bezier handle.'
                else:explanation='Classic spline representation '+str(kind)+': ordered native controls retained for later editing and reuse.'
            else:
                if key not in MEANINGS:raise ValueError((address,key))
                explanation=MEANINGS[key]
                if key=='radius' and '/properties/path/' in address:explanation='Apply curve radius to path followers and curve-deformed objects. This flag does not change the swept section itself.'
                if '/properties/bevel/' in address and key=='points':explanation='Ordered normalized quarter-section controls, starting at (1,0) and ending at (0,1), with distinct coordinates in the unit square. Sweeping mirrors this quarter around the centreline.'
                if '/properties/bevel/' in address and key=='position':explanation='Normalized quarter-profile XY control in the unit square, scaled by bevel depth. First and last controls stay (1,0) and (0,1); nearby controls can collapse in native float32 storage.'
            for pattern,labels in [(r'/properties/splines/items/(?:anyOf|oneOf)/(\d+)$',['Straight polyline','Cubic Bezier controls','Rational NURBS controls']),
              (r'/properties/bevel/(?:anyOf|oneOf)/(\d+)$',['No swept section','Round swept section','Referenced Curve section','Editable quarter-profile section']),
              (r'/properties/(?:left|right)/(?:anyOf|oneOf)/(\d+)$',['Automatic smooth handle','Automatic straight handle','Free positioned handle','Aligned positioned handle'])]:
                m=re.search(pattern,address)
                if m:r['label']=labels[int(m[1])]
            if r.get('status')=='pending':count+=1
            r.update(status='reviewed',explanation=explanation,sources=['docs/blender-splines.md','src/schemaxis/adaptors/blender/spline.py','src/schemaxis/adaptors/blender/spline_native.py'])
            if key=='position' and '/properties/bevel/' in address:r['units']='Dimensionless normalized quarter-section coordinates.'
            elif key in ('tilt','rotation'):r['units']='Radians.'
            elif key in ('position','offset','extrude','depth','location'):r['units']='Curve-local production distance units before Object/parent/asset transforms.'
    path.write_text(json.dumps(d,indent=2)+'\n');r=report('blender');print(json.dumps({'newReviewed':count,'counts':r['counts'],'stale':r['stale'],'complete':r['complete']}))

if __name__=='__main__':main()
