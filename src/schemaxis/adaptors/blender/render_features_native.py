"""Trusted production-owned render feature construction and readback.

This capability is created from current normalized authored intent. A submitted
project cannot opt itself into an extended reader through tags or readbacks.
"""
import bpy
from schemaxis.errors import fail


class Features:
    def __init__(self, production):
        self.production = production
        self.spec = production.spec
        self.scene = production.scene
        self.previous_world = self.scene.world
        self.worlds = {}; self.projections = {}; self.layer_state = None
        self.extensions = None; self.writers = None; self.shading = None
        self.writer_tree=None;self.writer_nodes=set()
        self.npr_plan = None; self.caches = None; self.prefix='0000';self.previous_material_lines={}
        self.needs_shading=bool(self.spec.get('worlds') or self.spec.get('renderBundles') or self.spec.get('materialAovs'))
        self.previous_world_fake_user=self.previous_world.use_fake_user
        if self.spec.get('worlds'):self.previous_world.use_fake_user=True
        self.previous_freestyle = self.scene.render.use_freestyle
        self.previous_width = (self.scene.render.line_thickness_mode, self.scene.render.line_thickness)
        self.previous_layer_freestyle = {layer: layer.use_freestyle for layer in self.scene.view_layers}
        from .world_resources_native import build
        self.worlds, production.shader_budget = build(self.spec.get('worlds', []), production.images,
                                                       production.shader_budget)
        if self.spec.get('sceneWorld'):
            self.scene.world = self.worlds[self.spec['sceneWorld']]
        from .render_projection_native import realize
        self.projections = realize(self.spec, production.projection_sources)
        from .render_layers_native import build as build_layers
        self.layer_state = build_layers(self.spec, production.objects, production.collections,
                                       production.materials, self.worlds, self.projections)
        if self.layer_state is not None and 'compositor' in self.spec:
            # The existing typed compositor Render input denotes the base
            # layer. Its source remains that layer after logical renaming.
            tree=self.scene.compositing_node_group
            for authored in self.spec['compositor']['nodes']:
                if authored['kind']=='render':tree.nodes[authored['id']].layer=self.scene.view_layers[0].name
        self.layers = {layer.name: layer for layer in self.scene.view_layers}
        if 'npr' in self.spec:
            from . import npr, npr_native
            self.npr_plan = npr.validate(self.spec['npr'], layers=self.layers, objects=production.objects,
                                        collections=production.collections, materials=production.materials)
            self.previous_material_lines={production.materials[item['material']]:(list(production.materials[item['material']].line_color),production.materials[item['material']].line_priority) for item in self.npr_plan['materials']}
            npr_native.apply(self.npr_plan, **self.npr_context())
        captured={source['object'] for members in production.original_materials.values() for source in members.values()}
        self.source_objects={'$source:'+obj.name:obj for obj in bpy.data.objects
                             if obj not in set(production.objects.values())|captured}
        self.source_materials={'$source:'+mat.name:mat for mat in bpy.data.materials
                               if mat not in set(production.materials.values())}

    def _plan(self):
        from .effective_shading_native import EffectiveShadingPlan
        specs=self.spec.get('viewLayers') or [{'id':self.scene.view_layers[0].name,'enabled':True,'aovs':[]}]
        plan=EffectiveShadingPlan(self.scene,specs,objects={**self.production.objects,**self.source_objects},
            materials={**self.production.materials,**self.source_materials},worlds=self.worlds,
            original_materials=self.production.original_materials,fixed_world=self.previous_world)
        # Declared resources and overrides remain source-bound even when an
        # enabled frame happens to have no surface using them.
        for owner in [*self.production.materials.values(),*self.worlds.values(),self.previous_world]:
            if owner is not None:plan._owner(owner)
        return plan

    def capture_render(self):
        from contextlib import contextmanager
        @contextmanager
        def capture():
            plan=self._plan();errors=[]
            def observed(scene,graph=None):
                if graph is None or graph.mode!='RENDER' or graph.scene.original!=self.scene:return
                name=graph.view_layer.name
                if name not in plan.layer_aovs or name in plan.captured_layers:return
                try:plan.capture_layer(self.scene.view_layers[name],graph)
                except Exception as error:errors.append(error)
            bpy.app.handlers.frame_change_post.append(observed)
            try:yield plan
            finally:
                if observed in bpy.app.handlers.frame_change_post:bpy.app.handlers.frame_change_post.remove(observed)
            if errors:raise errors[0]
            plan.complete()
            if self.spec.get('materialAovs'):
                from .render_aov_native import original_slots,resolve_owners
                owners=resolve_owners(self.spec['materialAovs'],self.production.materials,self.worlds,
                    original_slots(self.spec['materialAovs'],self.production.original_materials))
                plan.require_fields(self.spec['materialAovs'],owners)
            self.shading=plan
        return capture()

    def prepare_shading(self):
        if not self.needs_shading:return
        from .render_writers_native import suppress
        with suppress(self.scene),self.capture_render():
            if bpy.ops.render.render(write_still=False)!={'FINISHED'}:
                fail('PUBLICATION_FAILED','effective shading prepass did not finish')
        if self.extensions is None and self.spec.get('materialAovs'):
            from .render_aov_native import original_slots,resolve_owners,Extensions
            from .surface_compile import all_material_graphs
            writers=self.spec['materialAovs']
            owners=resolve_owners(writers,self.production.materials,self.worlds,
                original_slots(writers,self.production.original_materials))
            self.extensions=Extensions(writers,owners,production=self.production,shading_plan=self.shading,
                graphs=all_material_graphs(self.spec),surfaces={surface['id'] for surface in self.spec.get('surfaceMaterials',())},
                groups=self.spec['nodeGroups'])
        if self.writers is None and self.spec.get('renderBundles'):
            from .render_bundle_native import Writers
            self.writers=Writers(self.spec,self.prefix)
            self.writer_tree=self.writers.tree;self.writer_nodes={node.name for node in self.writers.created}

    def compositor_auxiliary(self,tree):
        return self.writer_nodes if tree==self.writer_tree else set()

    def auxiliary(self,owner):
        if self.extensions is None:return ()
        return self.extensions.parts.get(owner,())

    def verify_auxiliary(self,owner):
        parts=self.auxiliary(owner)
        if not parts:return (0,0)
        from .render_aov_native import verify_auxiliary
        return verify_auxiliary(owner,parts,self.extensions.owner_graphs.get(owner),self.extensions.groups)

    def fidelity(self):
        if not self.needs_shading:return None
        if self.shading is None:fail('VERIFICATION_CONTEXT_REQUIRED','render source authority needs an actual render plan')
        from .render_aov_fidelity_native import observe
        return observe(self.shading,images=self.production.images,shader_budget=self.production.shader_budget)

    def admit_source(self,expected):
        """Check all fresh nominated owner trees before rendering candidate data.

        Expected rows here are only a temporary nomination for the shader guard.
        The actual RENDER depsgraph is independently recaptured immediately
        afterwards and must match the complete fresh plan and owner signatures.
        """
        if not self.needs_shading:return
        from types import SimpleNamespace
        from .render_aov_fidelity_native import verify
        owners={}
        for identity,binding in expected['bindings'].items():
            pool={'Material':bpy.data.materials,'World':bpy.data.worlds}.get(binding['kind'])
            owner=pool.get(binding['name']) if pool is not None else None
            if owner is None or owner.library is not None:fail('VERIFICATION_FAILED','fresh shader owner is absent',identity)
            owners[identity]=owner
        self.shading=SimpleNamespace(owners=owners,object_ids=set(self.production.objects.values())|set(self.source_objects.values())|
            {source['object'] for members in self.production.original_materials.values() for source in members.values()},
            observe=lambda:expected['effectiveShading'])
        verify(self.fidelity(),expected)

    def verify_render(self,expected):
        if not self.needs_shading:return
        from .render_writers_native import suppress
        from .render_aov_fidelity_native import verify
        with suppress(self.scene),self.capture_render():
            if bpy.ops.render.render(write_still=False)!={'FINISHED'}:
                fail('VERIFICATION_FAILED','candidate effective render did not finish')
        verify(self.fidelity(),expected)

    def publish(self,directory):
        from pathlib import Path
        from .render_bundle_layout import jobs
        from .render_bundle_data import verify
        import hashlib
        result=[]
        if not self.spec.get('renderBundles'):return result
        directory=Path(directory);folder=directory/'renders'/'bundles';folder.mkdir(parents=True,exist_ok=True)
        for bundle in self.spec['renderBundles']:
            for frame in bundle['frames']:
                camera=self.scene.camera;previous=self.scene.frame_current;subframe=self.scene.frame_subframe
                try:
                    if bundle['camera']:self.scene.camera=self.production.objects[bundle['camera']]
                    self.scene.frame_set(frame);self.prepare_shading()
                    stage=directory/('_bundle-stage-'+self.prefix+'-'+bundle['id']+'-'+str(frame))
                    with self.capture_render():records=self.writers.render(bundle['id'],frame,stage,self.production.objects)
                    for record in records:
                        source=Path(record['path']);target=folder/record['file']
                        if target.exists():fail('OUTPUT_EXISTS','render publication already exists',str(target))
                        source.replace(target)
                        result.append({'kind':'renderBundle','bundle':bundle['id'],'output':record['output'],
                            'frame':frame,'format':record['format'],'file':str(target),
                            'sha256':hashlib.sha256(target.read_bytes()).hexdigest()})
                    stage.rmdir()
                finally:
                    self.scene.camera=camera;self.scene.frame_set(previous,subframe=subframe)
        # Restore the saved writer camera/frame source state after bundle jobs.
        self.prepare_shading()
        return result

    def npr_context(self):
        return dict(scene=self.scene, layers=self.layers, objects=self.production.objects,
                    collections=self.production.collections, materials=self.production.materials)

    def npr_observation(self):
        if self.npr_plan is None:return None
        from .npr_native import observe
        return observe(self.npr_plan, **self.npr_context())

    def layer_observation(self):
        from .render_layers_native import observe
        p = self.production
        return observe(self.spec, p.objects, p.collections, p.materials, self.worlds, self.projections)

    def bindings(self):
        """Fresh locators carried across submitted open, never consumer tags."""
        p = self.production
        return {'objects': {key: value.name for key,value in p.objects.items()},
                'materials': {key: value.name for key,value in p.materials.items()},
                'collections': {key: value.name for key,value in p.collections.items()},
                'worlds': {key: value.name for key,value in self.worlds.items()},
                'fixedWorld':self.previous_world.name,
                'writerTree':self.writer_tree.name if self.writer_tree is not None else None,
                'writerNodes':sorted(self.writer_nodes),
                'sourceObjects':{key:value.name for key,value in self.source_objects.items()},
                'sourceMaterials':{key:value.name for key,value in self.source_materials.items()},
                'originalMaterials':{asset:{name:{'object':source['object'].name,
                    'slots':[[link,owner.name if owner else None] for link,owner in source['slots']]}
                    for name,source in members.items()} for asset,members in p.original_materials.items()},
                'images': {key: value.name for key,value in p.images.items()},
                'projections': [{'asset': key[0], 'path': list(key[1]), 'collection': value['collection'].name,
                                 'suffix': list(value['suffix'])} for key,value in self.projections.items()]}

    @classmethod
    def current(cls, spec, bindings, *, shader_budget):
        """Resolve only handles nominated by a freshly constructed reference."""
        from types import SimpleNamespace
        def resolve(pool, names):
            result = {}
            for key,name in names.items():
                owner = pool.get(name)
                if owner is None or owner.library is not None:
                    fail('VERIFICATION_FAILED', 'freshly nominated render feature owner is absent', key)
                result[key] = owner
            return result
        native = cls.__new__(cls)
        native.spec = spec; native.scene = bpy.context.scene
        native.production = SimpleNamespace(spec=spec, scene=native.scene, shader_budget=shader_budget,
            objects=resolve(bpy.data.objects, bindings['objects']),
            materials=resolve(bpy.data.materials, bindings['materials']),
            collections=resolve(bpy.data.collections, bindings['collections']),
            images=resolve(bpy.data.images, bindings['images']))
        native.worlds = resolve(bpy.data.worlds, bindings['worlds'])
        native.previous_world=resolve(bpy.data.worlds,{'fixed':bindings['fixedWorld']})['fixed']
        native.writer_tree=bpy.data.node_groups.get(bindings['writerTree']) if bindings['writerTree'] else None
        if bindings['writerTree'] and native.writer_tree is None:fail('VERIFICATION_FAILED','fresh bundle compositor is absent')
        native.writer_nodes=set(bindings['writerNodes'])
        native.source_objects=resolve(bpy.data.objects,bindings['sourceObjects'])
        native.source_materials=resolve(bpy.data.materials,bindings['sourceMaterials'])
        native.production.original_materials={}
        for asset,members in bindings['originalMaterials'].items():
            native.production.original_materials[asset]={}
            for name,source in members.items():
                obj=resolve(bpy.data.objects,{name:source['object']})[name]
                slots=[(link,resolve(bpy.data.materials,{'slot':owner})['slot'] if owner else None)
                       for link,owner in source['slots']]
                native.production.original_materials[asset][name]={'object':obj,'slots':slots}
        native.projections = {}
        for record in bindings['projections']:
            collection = bpy.data.collections.get(record['collection'])
            if collection is None:fail('VERIFICATION_FAILED', 'fresh projection collection is absent')
            native.projections[(record['asset'],tuple(record['path']))] = {
                'collection':collection, 'suffix':tuple(record['suffix'])}
        native.layers = {layer.name:layer for layer in native.scene.view_layers}
        native.npr_plan = None; native.caches = None
        if 'npr' in spec:
            from .npr import validate
            native.npr_plan = validate(spec['npr'], layers=native.layers, objects=native.production.objects,
                collections=native.production.collections, materials=native.production.materials)
        native.extensions = native.writers = native.shading = None
        native.prefix='0000'
        native.needs_shading=bool(spec.get('worlds') or spec.get('renderBundles') or spec.get('materialAovs'))
        if spec.get('materialAovs'):
            from types import SimpleNamespace
            from .render_aov_native import original_slots,resolve_owners
            from .render_aovs import extension,bind_owner_graphs
            from .surface_compile import all_material_graphs
            graphs=all_material_graphs(spec)
            owners=resolve_owners(spec['materialAovs'],native.production.materials,native.worlds,
                original_slots(spec['materialAovs'],native.production.original_materials))
            parts={}
            for writer in spec['materialAovs']:
                parts.setdefault(owners[writer['id']],[]).append(extension(writer,graphs=graphs,
                    surfaces={surface['id'] for surface in spec.get('surfaceMaterials',())},groups=spec['nodeGroups']))
            native.extensions=SimpleNamespace(parts=parts,groups={g['id']:g for g in spec['nodeGroups']},
                owner_graphs=bind_owner_graphs(spec['materialAovs'],owners,graphs))
            for owner in parts:native.verify_auxiliary(owner)
        return native

    def observation(self):
        result = {'layers':self.layer_observation()}
        if self.npr_plan is not None:result['npr'] = self.npr_observation()
        if self.caches is not None:result['simulationCaches'] = self.caches.observation()
        if self.needs_shading:result['shading']=self.fidelity()
        return result

    def cache_handles(self):
        if self.caches is None:return set()
        if getattr(self.caches,'_verified_scene',None) == self.scene:
            return {native for native,_ in self.caches.nominated_cache_handles(scene=self.scene)}
        return {native for native,_ in self.caches.nominated_cache_handles()}

    def close(self):
        if self.extensions is not None:self.extensions.close()
        if self.writers is not None:self.writers.close()
        if self.npr_plan is not None:
            # Saved projects keep their styles. Only the mutable construction
            # scene is cleared so another analytic visit can own the same IDs.
            for layer in self.scene.view_layers:
                settings=layer.freestyle_settings
                for line_set in list(settings.linesets):settings.linesets.remove(line_set)
            for owner,(colour,priority) in self.previous_material_lines.items():
                owner.line_color=colour;owner.line_priority=priority
        from .render_layers_native import restore
        restore(self.layer_state)
        self.scene.world = self.previous_world
        self.previous_world.use_fake_user=self.previous_world_fake_user
        self.scene.render.use_freestyle = self.previous_freestyle
        self.scene.render.line_thickness_mode, self.scene.render.line_thickness = self.previous_width
        for layer,value in self.previous_layer_freestyle.items():layer.use_freestyle = value


def enabled(spec):
    from .render_features import FIELDS
    return any(key in spec for key in FIELDS)
