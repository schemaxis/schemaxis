"""Apply the same bounded shader expansion policy to admitted captured IDs."""
from .shader_budget import admit, MAX_NODES
from schemaxis.errors import fail


class ShaderBudget:
    def __init__(self):
        self.roots={};self.groups={};self.trees=set();self.nodes=0
        self.material_ids={};self.group_ids={}

    def group_id(self, tree):
        if tree not in self.group_ids:
            self.group_ids[tree]='group:'+str(len(self.group_ids))+':'+tree.name
        return self.group_ids[tree]

    def tree(self, tree):
        if tree in self.trees:return
        self.trees.add(tree)
        self.nodes+=len(tree.nodes)
        if self.nodes>MAX_NODES:
            fail('RESOURCE_BUDGET_EXCEEDED','shader allocation exceeds 8192 distinct nodes',tree.name)
        pending=[];refs=[]
        for node in tree.nodes:
            child=node.node_tree if node.bl_idname=='ShaderNodeGroup' else None
            if child:
                if child.bl_idname!='ShaderNodeTree' or child.is_embedded_data:
                    fail('UNSUPPORTED_ASSET_DEPENDENCY','shader instances need a local standalone shader group',node.name)
                refs.append(self.group_id(child));pending.append(child)
            else:refs.append(None)
        self.groups[self.group_id(tree)]=refs
        # Iteration avoids following an unbounded native chain on the Python
        # stack. The generic check below independently bounds group depth.
        return pending

    def collect(self, tree):
        pending=[tree]
        while pending:
            pending.extend(self.tree(pending.pop()) or [])

    def material(self, owner):
        if owner in self.material_ids:return
        identity='material:'+str(len(self.material_ids))+':'+owner.name
        self.material_ids[owner]=identity
        tree=owner.node_tree
        if tree:
            # Embedded roots commonly share a display name. They are roots
            # owned by materials, never keys in the standalone group namespace.
            refs=[];self.nodes+=len(tree.nodes)
            if self.nodes>MAX_NODES:
                fail('RESOURCE_BUDGET_EXCEEDED','shader allocation exceeds 8192 distinct nodes',owner.name)
            for node in tree.nodes:
                child=node.node_tree if node.bl_idname=='ShaderNodeGroup' else None
                if child:
                    if child.bl_idname!='ShaderNodeTree' or child.is_embedded_data:
                        fail('UNSUPPORTED_ASSET_DEPENDENCY','shader instances need a standalone shader group',node.name)
                    self.collect(child);refs.append(self.group_id(child))
                else:refs.append(None)
            self.roots[identity]=refs
        else:self.roots[identity]=[]
        admit(self.roots,self.groups,owner.name)

    def group(self, tree):
        if tree.is_embedded_data:return
        self.collect(tree);admit(self.roots,self.groups,tree.name)

    def rebuilt(self, *, owners=(), groups=()):
        """Re-admit complete actual roots after a typed shader augmentation.

        An already charged native owner may acquire generated AOV nodes. Calling
        material(owner) again deliberately does nothing, so a new family must
        rebuild its complete aggregate rather than charge only the new roots.
        The existing budget remains untouched if the new allocation refuses.
        """
        result=ShaderBudget()
        roots=dict.fromkeys([*self.material_ids,*owners])
        trees=dict.fromkeys([*(t for t in self.group_ids if not t.is_embedded_data),*groups])
        for owner in roots:result.material(owner)
        for tree in trees:result.group(tree)
        return result
