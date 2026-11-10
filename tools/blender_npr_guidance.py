"""Curated host-only Freestyle field concepts for the central guide generator.

This helper explains semantic names, not native RNA or schema-address positions.
Unknown fields return None so a schema change cannot inherit generic approval.
"""


def explain(names: list[str], node: dict) -> str | None:
    if 'npr' not in names:
        return None
    path = names[names.index('npr')+1:]
    field = path[-1] if path else 'npr'
    array = node.get('type') == 'array'
    scalar = node.get('type') in ('number', 'integer', 'boolean', 'string')
    if not path:
        return ('Create reusable Freestyle technical line styles and ordered edge selections on declared logical view layers. '
                'The finite public renderer is Cycles on Blender 5.2.3, using ordinary faced meshes; Grease Pencil Line Art is a separate workflow. '
                'Omit NPR to preserve ordinary rendering. Source geometry and occluding objects remain independently verified.')
    if field == 'styles':
        return ('Reusable stroke styles, shared by logical reference across line sets. Every declared style must be used; '
                'this is not a native data-block-name or script catalogue.' if array else
                'One reusable stroke style: logical identity, linear RGBA or Material-owner colour, pixel width and a finite chaining/dash policy.')
    if field == 'layers':
        return ('Bind line sets to declared logical production.viewLayers. Layer collection exclusions remain authoritative; '
                'line membership does not re-include an excluded object.' if array else
                'One logical view-layer line configuration. Its line sets share the retained complete smooth view map and apply in authored order.')
    if field == 'materials':
        return ('Explicit line colour and priority overlays on logical Material owners. Shared Materials affect all their users; '
                'these records are not a per-object palette, surface-shader edit or per-line-set override.' if array else
                'One Material-owner line overlay. Conflicting logical aliases to the same native owner refuse before assignment.')
    if field == 'lineSets':
        return ('Ordered combinations of edge selection, camera visibility, inclusive logical scope and a reusable style. '
                'Use separate visible and hidden sets for technical illustrations.' if array else
                'One line selection within this layer. Its identity is distinct from the reusable style identity and from native list positions.')
    if field == 'id':
        if 'lineSets' in path:
            return 'Logical identity unique among this layer\'s line sets. It does not select a native LineSet by name or list position.'
        if 'styles' in path:
            return 'Logical reusable style identity, referenced by line sets. Duplicate or unused styles refuse; the compiler owns native names.'
        return None
    if field == 'layer':
        return 'Logical ID from production.viewLayers. This reference does not invent a hidden layer or search arbitrary native names.'
    if field == 'style':
        return 'Logical ID from npr.styles. Several line sets may share a style; its exact native pointer and complete used settings are checked after reopen.'
    if field == 'colour':
        owner = ('Material-owner line colour used by materialLine styles; it does not change the surface shader' if 'materials' in path else
                 'Constant stroke colour, used when colourSource is constant')
        return (('One linear red, green, blue or alpha component from 0 to 1. ' if scalar else
                 'Linear RGBA channels from 0 to 1, interpreted before output colour management. ') + owner + '.')
    if field == 'colourSource':
        return ('Choose constant style RGBA or materialLine. The latter requires explicit npr.materials and uses the '
                'higher-priority adjacent Material owner\'s line colour; it does not read a mutable receipt as colour authority.')
    if field == 'width':
        return ('Absolute stroke thickness in output pixels, from 0.1 to 64. It is independent of model length units; '
                'camera scale and image resolution still determine how much model geometry each pixel spans.')
    if field == 'caps':
        return ('How a stroke ends. The finite public slice keeps butt caps, which terminate at the endpoint; '
                'round and square cap variants are not silently substituted or admitted by this gate.')
    if field == 'chaining':
        return ('Plain chaining joins compatible feature edges into strokes on the same object. Individual-segment '
                'chaining belongs to the private development catalogue and is refused by the finite public slice.')
    if field == 'sameObject':
        return ('Keep true so plain chains do not join different source objects. False refuses in the public slice '
                'rather than silently changing ownership or crossing repeated occurrences.')
    if field == 'dash':
        return ('Empty means continuous strokes. One positive integer dash/gap pair defines the public repeating pattern in pixels; '
                'the native view map chooses stroke starts, so this does not phase-lock dashes to a screen coordinate.' if array else
                'One repeated pair: visible dash length followed by an empty gap, both measured in output pixels.')
    if field == 'length' and 'dash' in path:
        return 'Visible dash length in output pixels, a positive integer from 1 to 1024. It is unrelated to model-space edge length.'
    if field == 'gap' and 'dash' in path:
        return 'Empty interval between consecutive dashes in output pixels, a positive integer from 1 to 1024.'
    if field == 'creaseAngle':
        return ('View-map crease threshold in radians. The retained native value is verified, but crease-edge selection '
                'is not among the finite public silhouette, border and material-boundary detectors.')
    if field == 'culling':
        return ('Keep false to retain the qualified complete view map. This acceleration flag is separate from '
                'layer collection exclusion and is not a way to declare occluders invisible.')
    if field == 'smoothness':
        return ('Keep true for the qualified smooth view map used to compute apparent silhouettes. This does not '
                'add a mesh modifier, change topology or grant access to unsupported evaluated geometry.')
    if field == 'edges':
        return ('One selected feature type: silhouette is the camera-dependent outline, border is a mesh boundary, '
                'and materialBoundary separates adjacent face Materials.' if not array else
                'Choose distinct silhouette, border or materialBoundary features, or their union. These are rendered '
                'feature classes rather than all mesh edges; additional private edge detectors are not public variants.')
    if field == 'edgeMatch':
        return ('Use any for the union of the selected feature classes. The all/intersection private option is '
                'not admitted by the finite public slice; it is not silently converted to any.')
    if field == 'invertEdges':
        return ('Keep false for the selected feature classes. Complemented edge matching is a separate private '
                'variant and is refused publicly rather than broadening selection.')
    if field == 'visibility':
        return ('Select camera-visible edges, hidden edges, or an inclusive quantitative-invisibility range. '
                'QI counts occluding surfaces: 0 is visible, 1 is behind one surface. It is not physical depth, opacity or a render-layer mask.')
    if field == 'minimum' and 'visibility' in path:
        return 'Smallest included occluding-surface count, from 0 to 64. A range starting at 0 can include camera-visible edges.'
    if field == 'maximum' and 'visibility' in path:
        return 'Largest included occluding-surface count, from 0 to 64 and at least minimum. The range 1–1 selects exactly one occluding surface.'
    if field == 'scope':
        return ('An inclusive logical object list or declared collection subtree contributing selected lines. '
                'Membership preserves layer exclusions. This is whole-object selection, not a particular repeated or captured instance occurrence.')
    if field == 'objects' and 'scope' in path:
        return ('Logical faced-mesh object IDs. Distinct aliases to one native owner refuse; private membership '
                'collections stay unlinked so selected objects cannot reappear in excluded layers.' if array else
                'One declared logical faced-mesh object ID, not a native Object name, polygon index or repeated-occurrence address.')
    if field == 'collection' and 'scope' in path:
        return ('Logical production collection whose complete subtree and mesh membership are verified. It selects '
                'whole source objects, not independent captured collection-instance occurrences; unsupported geometry refuses.')
    if field == 'invert' and 'scope' in path:
        return ('Keep false for inclusive object/collection membership. Complement scopes are not qualified '
                'public variants, and scope inversion cannot bypass layer exclusions.')
    if field == 'kind':
        values = node.get('enum', [node.get('const')])
        if 'visibility' in path:
            if values == ['visible']:
                return 'Visible selects feature edges with no camera-occluding surface (QI 0). Geometry behind an occluder is not drawn by this set.'
            if values == ['hidden']:
                return 'Hidden selects occluded feature edges. Use an explicit range when only a particular number of occluding surfaces is wanted.'
            if values == ['range']:
                return 'Range selects an inclusive minimum–maximum count of occluding surfaces, not a distance interval.'
            return 'Choose visible, hidden or an inclusive quantitative-invisibility range; the selection counts occluding surfaces from the camera.'
        if 'scope' in path:
            if values == ['objects']:
                return 'Objects selects the inclusive declared logical object list, using an unlinked private membership helper that preserves layer exclusion.'
            if values == ['collection']:
                return 'Collection selects the inclusive declared collection subtree and its exact logical mesh membership.'
            return 'Choose inclusive logical objects or a declared collection subtree; the private all-scope variant is not admitted publicly.'
        return None
    if field == 'material' and 'materials' in path:
        return ('Logical Material resource receiving this owner-wide line colour and priority. Every user of a '
                'shared owner is affected; aliases to one native Material cannot carry conflicting overlays.')
    if field == 'priority' and 'materials' in path:
        return ('Integer Material line priority from 0 to 32767. At a material boundary the higher-priority '
                'adjacent Material supplies materialLine colour; this does not change surface shading or object depth order.')
    return None
