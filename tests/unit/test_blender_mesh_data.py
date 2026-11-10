"""Mesh-field topology, sharing intent and mapping contracts stay host-safe."""
import copy
import unittest
from schemaxis.errors import SchemaxisError
from schemaxis.adaptors.blender.production import validate,schema
from schemaxis.adaptors.blender.mesh_data import projection,edges_for,values_for,validate_topology,transform_uv
from schemaxis.adaptors.blender.node_groups import descriptor


def project():
    return {'objects':[{'id':'plate','kind':'mesh','vertices':[[0,0,0],[2,0,0],[2,3,0],[0,3,0]],'faces':[[0,1,2,3]]}],
        'meshData':[{'object':'plate','attributes':[{'name':'temperature','kind':'float','domain':'POINT','mode':'dense','values':[10,20,30,40]}],
            'uvMaps':[{'name':'Label','method':'planar','size':[2,3]}]}]}


class MeshDataContracts(unittest.TestCase):
    def test_stored_uv_copy_transform_and_packing_boundary(self):
        d=project();maps=d['meshData'][0]['uvMaps']
        maps.append({'name':'Finish','method':'copy','source':'Label',
                     'transform':{'pivot':[.5,.5],'scale':[-2,3],'rotationDegrees':90,'offset':[1,-1]}})
        r=validate(d,{})
        intent=r['meshData'][0]['uvMaps'][1]['transform']
        result=transform_uv([[[0,0],[1,0],[1,1],[0,1]]],intent)
        expected=[[[3,.5],[3,-1.5],[0,-1.5],[0,.5]]]
        for face,wanted in zip(result,expected):
            for point,target in zip(face,wanted):
                for actual,reference in zip(point,target):self.assertAlmostEqual(actual,reference)
        self.assertEqual(validate(r,{}),r)
        for patch in ({'source':'Finish'},{'source':'Later'},{'pack':True},{'transform':{'scale':[0,1]}}):
            value=copy.deepcopy(d);value['meshData'][0]['uvMaps'][1].update(patch)
            if patch.get('source')=='Later':value['meshData'][0]['uvMaps'].append({'name':'Later','method':'planar'})
            with self.subTest(patch=patch),self.assertRaises(SchemaxisError):validate(value,{})

    def test_stored_uv_transform_refuses_local_float32_feature_loss(self):
        source=[[[0,0],[1,0],[1,1],[0,1]]]
        base={'pivot':[0,0],'scale':[1,1],'rotationDegrees':0,'offset':[0,0]}
        for patch in ({'scale':[1e-100,1]},{'offset':[1e12,0]},{'offset':[1e100,0]}):
            with self.subTest(patch=patch),self.assertRaises(SchemaxisError) as caught:transform_uv(source,{**base,**patch})
            self.assertEqual(caught.exception.fault.code,'NATIVE_VALUE_MISMATCH')
        # All three stored points would remain distinct while the thin triangle
        # becomes collinear. Adjacent-point checks alone cannot detect this.
        with self.assertRaises(SchemaxisError):
            transform_uv([[[0,0],[1,1e-8],[2,0]]],{**base,'offset':[0,1]})
        self.assertEqual(transform_uv(source,base),source)
    def test_schema_normalization_immutable_and_idempotent(self):
        from jsonschema import Draft202012Validator
        d=project();before=copy.deepcopy(d);r=validate(d,{})
        self.assertEqual(d,before);self.assertEqual(validate(r,{}),r)
        self.assertEqual(list(Draft202012Validator(schema()).iter_errors(d)),[])
        self.assertEqual(list(Draft202012Validator(schema()).iter_errors(r)),[])
    def test_projection_and_edge_order_are_literal(self):
        d=validate(project(),{});m=d['objects'][0]
        self.assertEqual(projection(d['meshData'][0]['uvMaps'][0],m['vertices'],m['faces']),[[[0,0],[1,0],[1,1],[0,1]]])
        self.assertEqual(edges_for(m['faces']),[(0,1),(0,3),(1,2),(2,3)])
    def test_invalid_fields_and_topology_fail_before_native(self):
        for patch in ({'values':[1]},{'name':'position'},{'name':'.internal'},{'domain':'CURVE'},{'kind':'untypedRNA'},{'mode':'code'},{'values':[1,2,float('nan'),4]}):
            d=project();d['meshData'][0]['attributes'][0].update(patch)
            with self.subTest(patch=patch),self.assertRaises(SchemaxisError):validate(d,{})
    def test_sparse_and_domain_variants(self):
        for domain,count in [('POINT',4),('EDGE',4),('FACE',1),('CORNER',4)]:
            d=project();c={'name':'zone','kind':'integer','domain':domain,'mode':'sparse','default':7,'entries':[{'index':count-1,'value':9}]};d['meshData'][0]['attributes']=[c]
            r=validate(d,{});self.assertEqual(values_for(r['meshData'][0]['attributes'][0],count),[7]*(count-1)+[9])
            c['entries'].append({'index':count-1,'value':2})
            with self.assertRaises(SchemaxisError):validate(d,{})
    def test_uv_seams_selection_and_naming_rejections(self):
        for uv in ({'name':'X','method':'coordinates','coordinates':[[[0,0],[1,0],[1,1]]]}, {'name':'X','method':'unwrap','seams':[[0,2]]}, {'name':'X','method':'unwrap','seams':[[0,1],[1,0]]}, {'name':'X','method':'box','size':[0,1,1]}, {'name':'X','method':'planar','pack':True,'textureSize':[4,4],'paddingPixels':4}):
            d=project();d['meshData'][0]['uvMaps']=[uv]
            with self.subTest(uv=uv),self.assertRaises(SchemaxisError):validate(d,{})
        d=project();d['meshData'][0]['activeUV']='absent'
        with self.assertRaises(SchemaxisError):validate(d,{})
    def test_typed_attribute_ports_change_with_channel(self):
        for native,kind in [('FLOAT','number'),('INT','integer'),('BOOLEAN','boolean'),('FLOAT_VECTOR','vector'),('FLOAT_COLOR','colour'),('QUATERNION','rotation')]:
            self.assertEqual(descriptor({'kind':'namedAttribute','properties':{'dataType':native}},'geometry')['outputs']['attribute']['kind'],kind)
    def test_reserved_uv_storage_and_quaternion_semantics(self):
        for c in ({'name':'uv','kind':'vector2','domain':'CORNER','mode':'constant','value':[0,0]}, {'name':'q','kind':'quaternion','mode':'constant','value':[0,0,0,0]}):
            d=project();d['meshData'][0]['attributes']=[c]
            with self.assertRaises(SchemaxisError):validate(d,{})
    def test_projection_handles_collinear_first_three_corners(self):
        points=[[0,0,0],[1,0,0],[2,0,0],[2,3,0],[0,3,0]]
        uv={'method':'box','origin':[0,0,0],'size':[2,3,1]}
        self.assertEqual(projection(uv,points,[[0,1,2,3,4]]),[[[0,0],[.5,0],[1,0],[1,1],[0,1]]])
    def test_legacy_uv_owner_and_unused_solver_control_reject(self):
        d=project();d['objects'][0]['uv']=[[[0,0],[1,0],[1,1],[0,1]]];d['meshData'][0]['uvMaps'][0]['name']='UVMap'
        with self.assertRaises(SchemaxisError):validate(d,{})
        d=project();d['meshData'][0]['uvMaps']=[{'name':'U','method':'unwrap','unwrapMethod':'CONFORMAL','iterations':20}]
        with self.assertRaises(SchemaxisError):validate(d,{})
    def test_imported_loose_edges_participate_in_domain_counts(self):
        c={'name':'wire','kind':'float','domain':'EDGE','mode':'dense','values':[11,22,33,44]};s={'attributes':[c],'uvMaps':[]}
        vertices=[[0,0,0],[2,0,0],[0,3,0],[2,3,0]];faces=[[0,1,2]]
        self.assertEqual(validate_topology(s,vertices,faces,edges=[[2,3],[0,2],[1,2],[0,1]])['EDGE'],4)
        for edges in ([[0,1],[1,2],[0,1],[2,3]],[[0,1],[0,2],[1,2],[2,4]],[[0,1],[0,2],[2,3]]):
            with self.subTest(edges=edges),self.assertRaises(SchemaxisError):validate_topology(s,vertices,faces,edges=edges)
    def test_duplicate_and_nonmesh_targets_fail(self):
        d=project();d['meshData'].append(copy.deepcopy(d['meshData'][0]))
        with self.assertRaises(SchemaxisError):validate(d,{})
        d=project();d['meshData'][0]['object']='absent'
        with self.assertRaises(SchemaxisError):validate(d,{})

if __name__=='__main__':unittest.main()
