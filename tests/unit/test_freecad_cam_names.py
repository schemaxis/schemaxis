"""Authored/native identity separation and pre-write collision controls."""
import unittest
from types import SimpleNamespace
from schemaxis.adaptors.freecad.cam_names import operation_names,require_free,require_created
from schemaxis.core.faults import SchemaxisError


class Names(unittest.TestCase):
    def plan(self,*ids):return {'operations':[{'id':identity} for identity in ids]}

    def test_sanitized_alias_and_allocator_names_stay_distinct(self):
        ids=('pilot-hole','pilot_hole','SCX0','second-hole','SCX2')
        self.assertEqual(operation_names(self.plan(*ids)),dict(zip(ids,('Op_SCX1','Op_pilot_hole','Op_SCX0','Op_SCX3','Op_SCX2'))))
        self.assertEqual(operation_names(self.plan(*reversed(ids)))['pilot_hole'],'Op_pilot_hole')

    def test_all_existing_safe_identities_preserve_names_and_order(self):
        ids=('face','pocket1','A_02','SCX0')
        self.assertEqual(list(operation_names(self.plan(*ids)).items()),[(s,'Op_'+s) for s in ids])

    def test_all_sixteen_unsafe_names_are_injective(self):
        mapped=operation_names(self.plan(*('hole-'+str(i) for i in range(16))))
        self.assertEqual(len(set(mapped.values())),16)
        for value in mapped.values():self.assertNotIn('-',value)

    def test_ambiguous_authored_or_malformed_input_refuses(self):
        for p in (self.plan('a','a'),self.plan('bad name'),self.plan(),self.plan(*('x'+str(i) for i in range(17)))):
            with self.subTest(p=p),self.assertRaises(SchemaxisError):operation_names(p)

    def test_existing_or_suffixed_native_identity_refuses(self):
        op=SimpleNamespace(Name='Op_a');doc=SimpleNamespace(getObject=lambda identity:op if identity=='Op_a' else None)
        with self.assertRaises(SchemaxisError):require_free(doc,'Op_a')
        require_free(doc,'Op_b');require_created(doc,op,'Op_a')
        with self.assertRaises(SchemaxisError):require_created(doc,SimpleNamespace(Name='Op_a001'),'Op_a')
        with self.assertRaises(SchemaxisError):require_created(doc,SimpleNamespace(Name='Op_a'),'Op_a')
