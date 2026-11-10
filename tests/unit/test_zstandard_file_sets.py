"""Finite file membership, path names and aggregate budgets before native execution."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from schemaxis.adaptors.zstandard import adaptor as a,file_sets
from schemaxis.core.faults import SchemaxisError

class FileSetAdmission(unittest.TestCase):
    def doc(self,**values):
        return {'version':a.VERSION,'operation':'compressFiles','fileSet':{'files':[{'source':'/example/input','name':'run/data.bin'}]},**values}

    def test_names_and_inapplicable_directory_controls_are_refused_without_io(self):
        for selected in ({'files':[{'source':'/example/input','name':'../outside'}]},
                         {'root':'/example/root','files':[{'source':'/example/input','name':'data'}]},
                         {'files':[{'source':'/example/input','name':'data'}],'recursive':False},
                         {'root':'/example/root','include':['../outside*']}):
            with self.subTest(selected=selected),self.assertRaises(SchemaxisError):a.plan(self.doc(fileSet=selected))

    def test_recursive_selection_and_reuse_include_new_files_and_ignore_excluded_links(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);(root/'a.bin').write_bytes(b'alpha');(root/'nested').mkdir();(root/'nested/b.bin').write_bytes(b'beta')
            (root/'ignore.link').symlink_to('/does-not-exist')
            doc=self.doc(fileSet={'root':str(root),'include':['*.bin'],'exclude':['*.link']})
            p=a.plan(doc);selected=file_sets.selection(p)
            self.assertEqual([i['name'] for i in selected],['a.bin','nested/b.bin'])
            # Retained closure validates without consulting original paths.
            self.assertEqual(file_sets.retained(p,selected),selected)
            before=a.reusableInputs(doc);(root/'new.bin').write_bytes(b'new')
            self.assertNotEqual(a.reusableInputs(doc),before)
            changed={**p,'fileSet':{**p['fileSet'],'recursive':False}}
            self.assertEqual([i['name'] for i in file_sets.selection(changed)],['a.bin','new.bin'])
            with self.assertRaises(SchemaxisError):file_sets.selection(a.plan(self.doc(fileSet={'root':str(root)})))

    def test_restore_suffix_collision_and_file_directory_collision_are_refused(self):
        for names in (['a.gz','a.zst'],['a.zst','a/b.zst'],['A.zst','a.zst']):
            selected=[{'source':'/example/'+str(i),'name':name} for i,name in enumerate(names)]
            with self.subTest(names=names),self.assertRaises(SchemaxisError):a.plan(self.doc(operation='restoreFiles',fileSet={'files':selected}))

    def test_output_inside_selected_root_is_refused_before_mkdir_or_native(self):
        with tempfile.TemporaryDirectory() as temporary,patch.object(a,'_identity') as native:
            root=Path(temporary);(root/'data').write_bytes(b'x');out=root/'new-output'
            with self.assertRaises(SchemaxisError):a.run(self.doc(fileSet={'root':str(root)}),out)
            self.assertFalse(out.exists());native.assert_not_called()

    def test_published_aggregate_budget_and_named_stream_pledge_are_checked(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);outputs=[]
            for i in range(3):
                path=root/str(i);path.write_bytes(b'x'*600);outputs.append(path)
            p=a.plan(self.doc(operation='restoreFiles',maxDecodedBytes=1799))
            with self.assertRaises(SchemaxisError) as caught:file_sets.admit_outputs(p,outputs)
            self.assertEqual(caught.exception.fault.code,'ZSTANDARD_BUDGET')
            p=a.plan(self.doc(streamInput=True,contentSize='require'))
            sub=file_sets.subplan(p,p['fileSet']['files'][0],a.MAX_BYTES,600)
            self.assertEqual(sub['pledgedBytes'],600)

    def test_retained_names_obey_excluded_ancestor_directory_pruning(self):
        for pattern in ('private','private/','*/secret-area'):
            root='/example/root';name='private/secret.bin' if pattern!='*/secret-area' else 'run/secret-area/secret.bin'
            p=a.plan(self.doc(fileSet={'root':root,'exclude':[pattern]}))
            with self.subTest(pattern=pattern),self.assertRaises(SchemaxisError):
                file_sets.retained(p,[{'name':name,'source':root+'/'+name}])

    def test_utf8_component_suffix_and_metadata_name_limits_are_admitted_without_truncation(self):
        for name in ('x'*220,'x'*252,'folder/'+'x'*256,'ø'*128):
            with self.subTest(name=name),self.assertRaises(SchemaxisError):
                a.plan(self.doc(fileSet={'files':[{'source':'/example/data','name':name}]}))
        p=a.plan(self.doc(fileSet={'files':[{'source':'/example/data','name':'x'*219}]}))
        self.assertEqual(file_sets.output_names(p,p['fileSet']['files'])[0],'files/'+'x'*219+'.zst')
        p=a.plan(self.doc(operation='restoreFiles',fileSet={'files':[{'source':'/example/data','name':'x'*223+'.zst'}]}))
        self.assertEqual(file_sets.output_names(p,p['fileSet']['files'])[0],'files/'+'x'*223)
        for suffix in ('.metadata.json','.metadata.json.staging'):
            with self.subTest(suffix=suffix),self.assertRaises(SchemaxisError):
                a.plan(self.doc(operation='restoreFiles',fileSet={'files':[
                    {'source':'/example/a','name':'a.zst'},{'source':'/example/b','name':'a'+suffix+'.zst'}]}))

    def test_actual_filesystem_path_limit_refuses_before_capture_and_native(self):
        with tempfile.TemporaryDirectory() as temporary,patch.object(file_sets.os,'pathconf',side_effect=lambda path,key:255 if key=='PC_NAME_MAX' else 10),patch.object(a,'_identity') as native:
            with self.assertRaises(SchemaxisError) as caught:a.run(self.doc(),Path(temporary)/'run')
            self.assertEqual(caught.exception.fault.code,'INVALID_ZSTANDARD_FILE_SET');native.assert_not_called()

    def test_os_publication_failure_is_structured(self):
        with tempfile.TemporaryDirectory() as temporary,patch.object(a,'_capture',side_effect=OSError(28,'No space left on device')):
            with self.assertRaises(SchemaxisError) as caught:a.run(self.doc(),Path(temporary)/'run')
            self.assertEqual(caught.exception.fault.code,'ZSTANDARD_FAILED')
