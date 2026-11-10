"""Internal AOV augmentation from trusted descriptors and fresh source owners.

Production calls this kernel with original slots captured only while freshly
constructing trusted inputs, before authored palette changes and submitted open.
Full fresh shader signatures remain mandatory beyond this semantic readback.
"""
import bpy

from schemaxis.errors import fail
from .node_native import port, plain
from .node_groups import descriptor
from .node_specs import node, S, C, text
from .settings import matching
from .render_aovs import extension, target_key, bind_owner_graphs


AOV = node('ShaderNodeOutputAOV', {'value': S('Value'), 'colour': C('Color')},
           properties={'name': ('aov_name', text())})


def _descriptor(authored, groups):
    return AOV if authored['kind'] == 'aov' else descriptor(authored, 'material', groups)


def original_slots(writers, originals):
    """Select only the process-local capability returned by fresh load_asset.

    Captured targets nominate their original Material ID, owner-wide: every
    effective user of that shared ID writes the pass. They do not promise a
    per-object matte; collection/layer masks are a separate intent.
    """
    result = {}
    for writer in writers:
        selected = writer['target']
        if selected['kind'] != 'captured':
            continue
        source = originals.get(selected['asset'], {}).get(selected['sourceObject'])
        if source is None:
            fail('UNKNOWN_REFERENCE', 'original source object provenance is absent', writer['id'])
        obj = source['object']
        index = selected['sourceSlot']
        if index >= len(source['slots']) or source['slots'][index][1] is None:
            fail('UNKNOWN_REFERENCE', 'original source material slot is absent or empty', writer['id'])
        result[writer['id']] = {'target': target_key(selected), 'object': obj,
                                'slot': index, 'link': source['slots'][index][0],
                                'owner': source['slots'][index][1]}
    return result


def resolve_owners(writers, materials, worlds, original_slots):
    result, aliases = {}, set()
    for writer in writers:
        selected = writer['target'];kind = selected['kind']
        if kind == 'captured':
            original = original_slots.get(writer['id'])
            if original is None or original['target'] != target_key(selected):
                fail('VERIFICATION_FAILED', 'AOV needs its freshly captured original slot provenance', writer['id'])
            owner = original['owner']
        else:
            owner = (materials if kind == 'material' else worlds).get(selected[kind])
        expected = bpy.types.World if kind == 'world' else bpy.types.Material
        if not isinstance(owner, expected) or owner.library is not None or owner.node_tree is None or not owner.use_nodes:
            fail('TYPE_MISMATCH', 'AOV owner requires a local node-enabled Material or World', writer['id'])
        key = (owner, writer['aov'])
        if key in aliases:
            fail('DUPLICATE_AOV_WRITER', 'different selectors resolve to one actual shader owner and AOV', writer['id'])
        aliases.add(key);result[writer['id']] = owner
    return result


def _ports(owner, specification, groups):
    descriptions = {n['id']: n for n in specification['nodes']}
    def endpoint(end, side):
        authored = descriptions.get(end['node'])
        native = owner.node_tree.nodes.get(end['node'])
        if authored is None or native is None:
            fail('VERIFICATION_FAILED', 'AOV endpoint is outside its trusted compiled graph', end['node'])
        desc = _descriptor(authored, groups)
        if native.bl_idname != desc['native']:
            fail('VERIFICATION_FAILED', 'AOV endpoint native type differs', end['node'])
        return native, port(getattr(native, side), desc[side][end['socket']]['native'])
    return endpoint


def verify_auxiliary(owner, extensions, graph=None, groups=None):
    """Check the exact auxiliary subgraph without changing submitted state.

    The caller supplies descriptors compiled from fresh trusted intent. The
    incident-link equality prevents any helper feeding a surface terminal.
    Unexposed settings/defaults still require full fresh ShaderSnapshot equality.
    """
    graph = graph or {'nodes': [], 'links': []}
    groups = groups or {}
    auxiliary = [n for part in extensions for n in part['nodes']]
    identities = [n['id'] for n in auxiliary]
    if len(identities) != len(set(identities)):
        fail('DUPLICATE_ID', 'compiled AOV node identities collide', owner.name)
    lookup = _ports(owner, {'nodes': graph['nodes'] + auxiliary}, groups)
    for authored in auxiliary:
        desc = _descriptor(authored, groups);native = owner.node_tree.nodes.get(authored['id'])
        if native is None or native.bl_idname != desc['native'] or native.mute:
            fail('VERIFICATION_FAILED', 'compiled AOV node identity or enabled state differs', authored['id'])
        for key, value in authored['properties'].items():
            if getattr(native, desc['properties'][key][0]) != value:
                fail('VERIFICATION_FAILED', 'compiled AOV property differs', authored['id'], property=key)
        for key, value in authored['values'].items():
            actual = plain(port(native.inputs, desc['inputs'][key]['native']).default_value)
            if not matching(actual, value):
                fail('VERIFICATION_FAILED', 'compiled AOV input differs', authored['id'], socket=key)
    expected = set()
    for part in extensions:
        for link in part['links']:
            source, output = lookup(link['from'], 'outputs')
            target, input_ = lookup(link['to'], 'inputs')
            if not output.enabled or not input_.enabled:
                fail('VERIFICATION_FAILED', 'compiled AOV endpoint is inactive', owner.name)
            expected.add((source, output.identifier, target, input_.identifier))
    names = set(identities)
    incident = [link for link in owner.node_tree.links
                if link.from_node.name in names or link.to_node.name in names]
    actual = {(link.from_node, link.from_socket.identifier, link.to_node, link.to_socket.identifier)
              for link in incident}
    if any(link.is_muted for link in incident) or len(incident) != len(expected) or actual != expected:
        fail('VERIFICATION_FAILED', 'compiled AOV links or terminal ownership differ', owner.name)
    return len(auxiliary), len(expected)


class Extensions:
    def __init__(self, writers, owners, *, production, shading_plan, graphs=(), surfaces=(), groups=()):
        self.owners = owners;self.created = [];self.parts = {}
        self.production = production;self.committed = False
        self.groups = {g['id']: g for g in groups}
        if set(owners) != {w['id'] for w in writers}:
            fail('VERIFICATION_FAILED', 'AOV owner membership differs from trusted writers')
        aliases = [(owners[w['id']], w['aov']) for w in writers]
        if len(aliases) != len(set(aliases)):
            fail('DUPLICATE_AOV_WRITER', 'AOV selectors alias one actual shader owner and pass')
        self.owner_graphs = bind_owner_graphs(writers, owners, graphs)
        shading_plan.require_fields(writers, owners)
        baseline = production.shader_budget.rebuilt(owners=shading_plan.owners.values())
        try:
            plans = []
            for writer in writers:
                part = extension(writer, graphs=graphs, surfaces=surfaces, groups=groups)
                owner = owners[writer['id']]
                for authored in part['nodes']:
                    if owner.node_tree.nodes.get(authored['id']) is not None:
                        fail('DUPLICATE_ID', 'generated AOV node collides with existing source topology', writer['id'])
                plans.append((owner, part))
            # New taps add terminals/helpers, never group instances. Predict
            # their exact root-node expansion BEFORE allocating native nodes.
            additions = {}
            link_counts = {}
            for owner, part in plans:
                additions[owner] = additions.get(owner, 0) + len(part['nodes'])
                link_counts[owner] = link_counts.get(owner, 0) + len(part['links'])
            roots = {key: list(value) for key, value in baseline.roots.items()}
            for owner, count in additions.items():
                if len(owner.node_tree.nodes) + count > 2048:
                    fail('RESOURCE_BUDGET_EXCEEDED', 'AOV owner exceeds 2048 shader nodes', owner.name)
                if len(owner.node_tree.links) + link_counts[owner] > 8192:
                    fail('RESOURCE_BUDGET_EXCEEDED', 'AOV owner exceeds 8192 shader links', owner.name)
                roots[baseline.material_ids[owner]].extend([None] * count)
            from .shader_budget import admit
            admit(roots, baseline.groups, 'production.materialAovs')
            for owner, part in plans:
                for authored in part['nodes']:
                    desc = _descriptor(authored, self.groups);native = owner.node_tree.nodes.new(desc['native'])
                    self.created.append((owner, native));native.name = authored['id']
                    if native.name != authored['id']:
                        fail('UNSUPPORTED_NATIVE_NAME', 'native changed generated AOV identity', authored['id'])
                    for key, value in authored['properties'].items():setattr(native, desc['properties'][key][0], value)
                    for key, value in authored['values'].items():port(native.inputs, desc['inputs'][key]['native']).default_value = value
                self.parts.setdefault(owner, []).append(part)
            for owner, parts in self.parts.items():
                graph = self.owner_graphs[owner] or {'nodes': [], 'links': []}
                lookup = _ports(owner, {'nodes': graph['nodes'] + [n for p in parts for n in p['nodes']]}, self.groups)
                for part in parts:
                    for link in part['links']:
                        _, output = lookup(link['from'], 'outputs');_, input_ = lookup(link['to'], 'inputs')
                        if not output.enabled or not input_.enabled:
                            fail('INACTIVE_SOCKET', 'AOV tap source is unavailable', owner.name)
                        owner.node_tree.links.new(output, input_)
                verify_auxiliary(owner, parts, graph, self.groups)
            self.shader_budget = baseline.rebuilt(owners=self.parts)
            # Publish one complete aggregate only after every allocation and
            # exact auxiliary-topology check succeeded. Later production
            # observations must never keep using the pre-augmentation cache.
            production.shader_budget = self.shader_budget
            self.committed = True
        except BaseException:
            self.close();raise

    def rebuilt_budget(self, budget):
        return budget.rebuilt(owners=self.parts)

    def close(self):
        for owner, native in reversed(self.created):owner.node_tree.nodes.remove(native)
        self.created.clear()
        if self.committed:
            self.production.shader_budget = self.production.shader_budget.rebuilt()
            self.committed = False
