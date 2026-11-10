"""Host-safe conceptual guidance for the finite public simulation-cache fields.

Meanings follow docs/blender-simulation-caches.md and cache_policy.py. This helper
only supplies text; it neither imports native code nor changes generated guidance.
"""

_ARRAY = (
    'Bake the declared rigid-body world or cloth consumers for stable saved results '
    'when frames are reopened in a different order. Declare at most 32 distinct '
    'cache IDs and consumers. Each cache covers the complete production timeline, '
    'within 1000 frames; production fps determines the time between frames. '
    'Scene ownership, runtime, constructor and source fingerprints come from trusted '
    'construction and cannot be authored here. Changed simulation inputs require '
    'fresh construction and baking; a saved cache manifest alone cannot authorize reuse.'
)

_ITEM = (
    'One bake for an existing typed physics consumer in this production scene. '
    'Choose the consumer kind, logical cloth object when applicable, full timeline '
    'and storage together. Construction binds the declared physics, admitted '
    'dependencies and fixed Blender runtime. Editing geometry, physics parameters, '
    'gravity, fps, frame bounds or dependency bytes invalidates the old bake.'
)

_FIELDS = {
    'id': (
        'Unique portable cache identity: begin with a letter and use up to 63 letters, '
        'digits, underscores or hyphens. It identifies this bake and its managed '
        'payloads; it is not a native object name, file path or source-authority token.'
    ),
    'kind': (
        'Select the actual existing physics consumer: rigidBody bakes the scene rigid-body '
        'world; cloth bakes one declared cloth object. This does not create physics or '
        'enable other simulation families. Qualified Blender 5.2.3 supports packed rigid-body '
        'caches and packed or disk cloth caches; rigid-body disk conversion is explicitly '
        'refused because its native storage setter crashes before baking.'
    ),
    'object': (
        'Logical production object ID of the declared cloth mesh consumer. For rigidBody, '
        'leave this empty: the cache belongs to the owning scene world and covers its '
        'rigid bodies. Native scene names and arbitrary native object lookup are not authored selectors.'
    ),
    'frameStart': (
        'First inclusive baked frame, equal to production.frameStart. Together with '
        'frameEnd it must cover the entire production timeline within 1000 consecutive '
        'positive frames; partial cache intervals are refused. Production fps sets '
        'physical time per frame. Changing the range or fps requires a fresh bake.'
    ),
    'frameEnd': (
        'Last inclusive baked frame, equal to production.frameEnd. The complete timeline '
        'must fit within 1000 consecutive positive frames so render, export and other '
        'timeline samples cannot silently use an unbaked interval. Changing the range '
        'or production fps invalidates the old bake.'
    ),
    'storage': (
        'packed retains the bake inside the saved scene; disk publishes managed cloth '
        '.bphys files beside that scene in blendcache_<visit basename>/. Keep those '
        'declared files with the scene. External paths and inherited external caches '
        'are refused. Verification compares disk bytes with an independently constructed '
        'fresh bake before opening the submitted scene; packed data also requires '
        'all-frame geometry and physics checks. Rigid-body disk mode is explicitly '
        'unsupported in the qualified runtime; use packed rigid-body storage.'
    ),
}


def explain(names: list[str], node: dict) -> str | None:
    """Explain only recognized cache fields, array nodes and record/item nodes.

    Accept semantic paths as well as schema paths containing properties/items.
    Unknown descendants return None so callers cannot silently label them reviewed.
    """
    if 'simulationCaches' not in names:
        return None
    tail = names[names.index('simulationCaches') + 1:]
    semantic = [name for name in tail
                if name not in ('properties', 'items', '[]', '*') and not name.isdigit()]
    if not semantic:
        return _ITEM if node.get('type') == 'object' else _ARRAY
    if len(semantic) == 1:
        return _FIELDS.get(semantic[0])
    return None
