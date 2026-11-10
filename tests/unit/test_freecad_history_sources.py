"""Independent controls for native sparse string IDs and decimal persistence."""
import unittest
from schemaxis.adaptors.freecad.source_envelope import string_ids
from schemaxis.adaptors.freecad.source_envelope import document_ids
from schemaxis.adaptors.freecad.assembly_payloads import same_brep
from schemaxis.core.faults import SchemaxisError
from schemaxis.adaptors.freecad.history_element_maps import Names,canonical,archive_maps
from schemaxis.adaptors.freecad.history_element_maps import string_inventory
from xml.etree import ElementTree as ET


class HistoryPersistence(unittest.TestCase):
    def test_sparse_ids_and_related_column_deltas(self):
        data=b'StringTableStart v1 3\n-1.0 0:a\n-2.0.2 0:b\n-5.0.0 0:c\n'
        self.assertEqual(string_ids(data,'test','BAD_SOURCE','table'),{1,3,8})
        self.assertEqual(string_ids(b'StringTableStart v1 2\n1.0 0:a\n3.0.1 0:b\n',
                                    'test','BAD_SOURCE','table'),{1,3})

    def test_missing_related_ids_duplicate_ids_and_bad_counts_fail(self):
        for data in [b'StringTableStart v1 3\n-1.0 0:a\n-2.0.2 0:b\n-5.0.5 0:c\n',
                     b'StringTableStart v1 2\n-1.0 0:a\n-0.0 0:b\n',
                     b'StringTableStart v1 3\n-1.0 0:a\n-2.0 0:b\n']:
            with self.subTest(data=data),self.assertRaises(SchemaxisError):
                string_ids(data,'test','BAD_SOURCE','table')

    def test_current_payload_binding_refuses_even_one_decimal_quantum(self):
        old=b'2 54.00000000000000000 -0.00000000000000089\n'
        new=b'2 54.00000000000000000 -0.00000000000000090\n'
        self.assertFalse(same_brep(old,new))
        for bad in [b'2 54.00000000000000000 -0.00000000000000091\n',
                    b'3 54.00000000000000000 -0.00000000000000090\n',
                    b'2 54.00000000000000000 -9e-16\n']:
            with self.subTest(bad=bad):
                self.assertFalse(same_brep(old,bad))

    def test_regeneration_comparison_keeps_nested_content_indices_and_owners(self):
        records={1:(0,'0:g',[]),2:(0,'0:;SKT',[]),3:(76,'',[2,1])}
        parsed={'postfixId':10,'postfixes':['Edge',';:H7,E'],
                'maps':[(10,[('Edge',0,1,[],['$#3:1.2 0'])])]}
        original=canonical(parsed,records,{7:7})
        # Allocation and local dictionary order do not define contents.
        renamed={'postfixId':20,'postfixes':[';:H9,E','Edge'],
                 'maps':[(20,[('Edge',0,1,[],['$#1e:1.1 0'])])]}
        self.assertEqual(original,canonical(renamed,{10:records[1],20:records[2],30:(76,'',[20,10])},{9:7}))
        for change in [(76,'',[1,2]),(76,'',[2,2])]:
            self.assertNotEqual(original,canonical(parsed,{**records,3:change},{7:7}))
        indexed={**parsed,'maps':[(10,[('Edge',0,1,[],['$#3:2.2 0'])])]}
        self.assertNotEqual(original,canonical(indexed,records,{7:7}))
        with self.assertRaises(ValueError):canonical(parsed,records,{8:8})

    def test_unknown_flags_missing_indirect_ids_root_and_zero_prefix_are_refused(self):
        for flags in [512,1,2,4,8|32|64]:
            with self.subTest(flags=flags),self.assertRaises(ValueError):Names({1:(flags,'0:a',[])},{}).sid(1)
        for records in [{1:(0,'0:#2',[])},{1:(0,'0:a',[2])}]:
            with self.subTest(records=records),self.assertRaises(ValueError):Names(records,{}).sid(1)
        for root,row in [(2,':1.1.0 0'),(1,':0.1.0 0')]:
            parsed={'postfixId':root,'postfixes':['Edge'],'maps':[(1,[('Edge',0,1,[],[row])])]}
            with self.subTest(root=root,row=row),self.assertRaises(ValueError):canonical(parsed,{}, {})

    def test_alias_consistency_spans_payloads_and_shadows_bind_real_ids(self):
        def payload(row):
            return ('BeginElementMap v1\n1 PostfixCount 1\nEdge\n\nMapCount 1\n\n'
                    'ElementMap 1 1 1\n\nEdge\n\nChildCount 0\n\nNameCount 1\n'+row+'\n\nEndMap\n').encode()
        root=ET.fromstring('<Document><Objects><Object name="A" id="7"/></Objects>'
            '<StringHasher2 file="table"/><ObjectData><Object name="A"><Properties>'
            '<Property name="Shape"><ElementMap2 file="a"/></Property>'
            '<Property name="Other"><ElementMap2 file="b"/><Sub shadow="#1"/></Property>'
            '</Properties></Object></ObjectData></Document>')
        members={'table':b'StringTableStart v1 2\n-1.0 0:good\n-1.0 0:wrong\n',
                 'a':payload(':1.1.0 0'),'b':payload(':1.1.0 0')}
        maps,shadows=archive_maps(members,root)
        self.assertEqual(len(maps),2)
        with self.assertRaises(ValueError):archive_maps({**members,'b':payload(':1.2.0 0')},root)
        root.find('.//Sub').set('shadow','#2')
        self.assertNotEqual(shadows,archive_maps(members,root)[1])
        root.find('.//Sub').set('shadow','#3')
        with self.assertRaises(ValueError):archive_maps(members,root)

    def test_nested_owner_length_binds_operation_span_across_id_widths(self):
        a=Names({}, {0x123:1,0x456:2}).text(';:H123,E;:H456:8,E')
        b=Names({}, {0x1234:1,0x4567:2}).text(';:H1234,E;:H4567:9,E')
        self.assertEqual(a,b)
        # The earlier bug remapped owner digits without adjusting this length.
        # Dropping the length would hide changed operation-history boundaries.
        with self.assertRaises(ValueError):Names({}, {0x1234:1,0x4567:2}).text(';:H1234,E;:H4567:8,E')
        self.assertNotEqual(a,Names({}, {0x123:1,0x456:2}).text(';:H123,E;:H456,E'))

    def test_literal_hash_prefix_is_not_a_dangling_string_reference(self):
        def parsed(prefix):return {'postfixId':1,'postfixes':['Edge'],'maps':[(1,[('Edge',0,1,[],[prefix+'.0 0'])])]}
        literal=canonical(parsed(';#25:3'),{}, {})
        self.assertNotEqual(literal,canonical(parsed(';#26:3'),{}, {}))
        with self.assertRaises(ValueError):canonical(parsed('$#25:3'),{}, {})

    def test_archive_comparison_retains_unreferenced_local_definitions(self):
        root=ET.fromstring('<Document><Objects><Object name="A" id="7"/></Objects>'
            '<StringHasher2 file="table"/><ObjectData><Object name="A"><Properties>'
            '<Property name="Shape"><ElementMap2 file="map"/></Property>'
            '</Properties></Object></ObjectData></Document>')
        def payload(first):
            text='BeginElementMap v1\n2 PostfixCount 1\nEdge\n\nMapCount 2\n'
            for index,row in [(1,first),(2,':1.1.0 0')]:
                text+=f'\nElementMap {index} {index} 1\n\nEdge\n\nChildCount 0\n\nNameCount 1\n{row}\n\nEndMap\n'
            return text.encode()
        a,_=archive_maps({'table':b'StringTableStart v1 0\n','map':payload(':1.1.0 0')},root)
        b,_=archive_maps({'table':b'StringTableStart v1 0\n','map':payload(':1.2.0 0')},root)
        self.assertEqual(a[('A','Shape','ElementMap2')][-1],b[('A','Shape','ElementMap2')][-1])
        self.assertNotEqual(a,b)

    def test_owner_ids_require_a_positive_canonical_bijection(self):
        def root(a,b):return ET.fromstring(f'<Document><Objects><Object name="A" id="{a}"/><Object name="B" id="{b}"/></Objects></Document>')
        self.assertEqual(document_ids(root('1','4')),{'A':1,'B':4})
        for a,b in [('1','1'),('0','1'),('-1','1'),('01','2'),('+1','2'),('1',str(2**63))]:
            with self.subTest(a=a,b=b),self.assertRaises(ValueError):document_ids(root(a,b))

    def test_complete_string_inventory_binds_unused_records_under_owner_rename(self):
        def root(identity):
            return ET.fromstring(f'<Document><Objects><Object name="A" id="{identity}"/></Objects>'
                                 '<StringHasher2 file="table"/></Document>')
        a = {'table': b'StringTableStart v1 2\n1.0 0:literal\n2.0 0:;:H7,E\n'}
        b = {'table': b'StringTableStart v1 2\n3.0 0:literal\n5.0 0:;:H9,E\n'}
        expected = string_inventory(a, root(7))
        self.assertEqual(expected, string_inventory(b, root(9), {9:7}))
        extra = {'table': b'StringTableStart v1 3\n1.0 0:literal\n2.0 0:;:H7,E\n3.0 0:unused\n'}
        self.assertNotEqual(expected, string_inventory(extra, root(7)))
        for payload in (b'0:;:H8,E', b'0:#ffff', b'0:literal'):
            changed = {'table': b'StringTableStart v1 3\n1.0 0:literal\n2.0 0:;:H7,E\n3.0 '+payload+b'\n'}
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                string_inventory(changed, root(7))

    def test_native_null_child_map_is_distinct_from_a_preceding_map(self):
        def parsed(child):
            return {'postfixId': 2, 'postfixes': ['Face'], 'maps': [
                (1, [('Face', 0, 1, [], [':1.1.0 0'])]),
                (2, [('Face', 1, 0, [child], [])])]}
        null = canonical(parsed('1 0 5 7 0 ;:H7,F 0'), {}, {7:7})
        linked = canonical(parsed('1 0 5 7 1 ;:H7,F 0'), {}, {7:7})
        self.assertNotEqual(null, linked)
        renamed = canonical(parsed('1 0 5 9 0 ;:H9,F 0'), {}, {9:7})
        self.assertEqual(null, renamed)
        for child in ('1 0 5 7 -1 ;:H7,F 0', '1 0 5 7 2 ;:H7,F 0',
                      '1 0 0 7 0 ;:H7,F 0', '1 0 5 8 0 ;:H7,F 0'):
            with self.subTest(child=child), self.assertRaises(ValueError):
                canonical(parsed(child), {}, {7:7})


if __name__=='__main__':
    unittest.main()
