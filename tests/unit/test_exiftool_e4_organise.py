"""E4 planNames and organiseCopies: native runs against ExifTool 13.55 (contract cases N-1..N-4, N-9, N-12, O-1..O-6, O-9) with hand-literal expected paths and slots.

Injected races (a link or a file appearing under organised/ just before a copy) are test-owned patches of the copier; nothing else is simulated.
"""
import hashlib
import os
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'tests/unit')]

import exiftool_e4_fixtures as f  # noqa: E402
from exiftool_e4_fixtures import V  # noqa: E402
from schemaxis.adaptors.exiftool import e4host  # noqa: E402

RULE = {'name': [{'token': 'captureDate', 'format': 'YYYYMMDD'}, {'literal': '_'}, {'token': 'captureTime', 'format': 'HHmmss'}], 'collisions': 'sequence'}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def photo(dto, off='+09:00', seed=1, model='Model', xmp=None, **extra):
    return f.fx.jpeg(make='Make', model=model, dto=dto, off=off, sub=None, seed=seed, xmp=xmp, **extra)


class Names(f.NativeCase):
    def three(self):
        self.put('a.jpg', photo('2024:03:01 10:20:30', seed=1))
        self.put('b.jpg', photo('2024:03:01 10:20:30', seed=2))
        self.put('c.jpg', photo('2024:03:01 11:00:00', off=None, seed=3))

    def names(self, name, rule=None, **more):
        doc = {'version': V, 'operation': 'planNames', 'media': self.items('a', 'b', 'c'), **(rule or RULE), **more}
        return self.run_op(doc, name)

    def paths(self, name):
        return [(r['id'], r['relativePath'], (r['fault'] or {}).get('code')) for r in self.json(name, 'names-plan.json')['items']]

    def test_N1_recorded_local_names_with_the_manifest_ordered_collision_suffix(self):
        self.three()
        result = self.names('n1')
        self.assertEqual((result['planned'], result['setStatus']), (3, 'complete'))
        self.assertEqual(self.paths('n1'), [('a', '20240301_102030.jpg', None), ('b', '20240301_102030-2.jpg', None), ('c', '20240301_110000.jpg', None)])
        self.assertEqual(self.verify('n1')['proofs'], ['namePlan'])
        self.record('test_exiftool_e4_organise.Names.N1', 'planNames', 'supported', supported=True, outcome='succeeded', independentlyVerified=True)

    def test_N1_refuse_lists_every_colliding_member_and_publishes_the_others(self):
        self.three()
        self.names('n1r', {**RULE, 'collisions': 'refuse'})
        self.assertEqual(self.paths('n1r'), [('a', None, 'NAME_COLLISION'), ('b', None, 'NAME_COLLISION'), ('c', '20240301_110000.jpg', None)])
        self.assertEqual(self.json('n1r', 'names-plan.json')['items'][0]['fault']['items'], ['a', 'b'])

    def test_N2_utc_basis_converts_with_the_recorded_offset_and_names_the_missing_one(self):
        self.three()
        self.names('n2', {**RULE, 'time': {'basis': 'utc'}})
        self.assertEqual(self.paths('n2'), [('a', '20240301_012030.jpg', None), ('b', '20240301_012030-2.jpg', None), ('c', None, 'NAME_OFFSET_MISSING')])

    def test_N3_disagreeing_time_sources_refuse_unless_a_family_is_named(self):
        self.put('a.jpg', photo('2024:03:01 10:20:30', xmp=f.fx.xmp_properties(captured='2024-03-01T10:21:00+09:00')))
        self.put('b.jpg', photo('2024:03:01 11:00:00', seed=2))
        self.put('c.jpg', photo('2024:03:01 12:00:00', seed=3))
        self.names('n3', {**RULE, 'collisions': 'refuse'})
        row = self.json('n3', 'names-plan.json')['items'][0]
        self.assertEqual((row['fault']['code'], len(row['fault']['values'])), ('NAME_TIME_CONFLICT', 2))
        self.names('n3b', {**RULE, 'time': {'source': 'exif'}})
        row = self.json('n3b', 'names-plan.json')['items'][0]
        self.assertEqual((row['relativePath'], row['notes'][0]['code']), ('20240301_102030.jpg', 'NAME_TIME_SOURCES_DISAGREE'))

    def test_N4_a_declared_fallback_names_a_folder_for_a_photo_without_a_time(self):
        self.put('a.jpg', f.fx.jpeg(make='Make', model='Model', dto=None, off=None, sub=None, seed=1))
        self.put('b.jpg', photo('2024:03:01 11:00:00', seed=2))
        self.put('c.jpg', photo('2024:03:01 12:00:00', seed=3))
        self.names('n4', {'name': [{'token': 'originalStem'}], 'folders': [{'token': 'year'}], 'time': {'missing': {'fallback': 'undated'}}})
        self.assertEqual(self.paths('n4'), [('a', 'undated/a.jpg', None), ('b', '2024/b.jpg', None), ('c', '2024/c.jpg', None)])

    def test_N9_a_year_month_model_tree(self):
        self.three()
        self.names('n9', {**RULE, 'folders': [{'token': 'year'}, {'token': 'month'}, {'token': 'cameraModel'}]})
        self.assertEqual([p for _, p, _ in self.paths('n9')], ['2024/03/Model/20240301_102030.jpg', '2024/03/Model/20240301_102030-2.jpg', '2024/03/Model/20240301_110000.jpg'])

    def test_the_names_plan_is_the_text_artifact_with_the_capture_hash_of_every_item(self):
        self.three()
        self.names('plan')
        doc = self.json('plan', 'names-plan.json')
        self.assertEqual([r['captureSha256'] for r in doc['items']], [sha((self.media / (n + '.jpg')).read_bytes()) for n in 'abc'])
        slots = self.json('plan', 'verification.json')['artifacts']
        self.assertEqual([(s['kind'], s.get('identity', {}).get('kind')) for s in slots], [('text', 'namePlan'), ('table', 'table'), ('text', None)])           # the plan is artifact index 0


class Organise(f.NativeCase):
    TREE = {'name': RULE['name'], 'collisions': 'sequence', 'folders': [{'token': 'year'}, {'token': 'month'}, {'token': 'cameraModel'}]}

    def setUp(self):
        super().setUp()
        self.data = {'a': photo('2024:03:01 10:20:30', seed=1), 'b': photo('2024:03:01 10:20:30', seed=2), 'c': photo('2024:03:01 11:00:00', off=None, seed=3)}
        for n, d in self.data.items():
            self.put(n + '.jpg', d)
        self.put('a.xmp', b'<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"><rdf:Description rdf:about="" xmlns:xmp="http://ns.adobe.com/xap/1.0/" xmp:Rating="3"/></rdf:RDF></x:xmpmeta>')
        self.folder = {'folder': {'path': str(self.media)}}

    def organise(self, name, names=None, **more):
        return self.run_op({'version': V, 'operation': 'organiseCopies', 'media': self.folder, 'names': names or self.TREE, **more}, name)

    def test_O1_every_output_is_the_capture_byte_for_byte_with_the_sidecar_beside_it(self):
        result = self.organise('o1')
        self.assertEqual((result['written'], result['setStatus'], result['proofs']), (3, 'complete', ['namePlan', 'exactCopy']))
        base = self.tmp / 'o1' / 'organised' / '2024' / '03' / 'Model'
        self.assertEqual((base / '20240301_102030.jpg').read_bytes(), self.data['a'])
        self.assertEqual((base / '20240301_102030-2.jpg').read_bytes(), self.data['b'])
        self.assertEqual((base / '20240301_110000.jpg').read_bytes(), self.data['c'])
        self.assertEqual((base / '20240301_102030.xmp').read_bytes(), (self.media / 'a.xmp').read_bytes())
        tree = self.json('o1', 'tree.json')['files']
        self.assertEqual([(t['relativePath'], t['item'], t['kind']) for t in tree], [('2024/03/Model/20240301_102030-2.jpg', 'b', 'image'), ('2024/03/Model/20240301_102030.jpg', 'a', 'image'),
                                                                                       ('2024/03/Model/20240301_102030.xmp', 'a', 'sidecar'), ('2024/03/Model/20240301_110000.jpg', 'c', 'image')])
        self.assertEqual(tree[1]['sha256'], sha(self.data['a']))
        slots = self.json('o1', 'verification.json')['artifacts']
        self.assertEqual([(s['kind'], s['identity']['kind'], s['identity'].get('item')) for s in slots[:7]],
                         [('image', 'image', 'a'), ('image', 'image', 'b'), ('image', 'image', 'c'), ('text', 'sidecar', 'a'), ('text', 'noSidecar', 'b'), ('text', 'noSidecar', 'c'), ('text', 'namePlan', None)])
        self.assertEqual(self.verify('o1')['nativeReplay'], 'fresh-replay-matched')
        self.record('test_exiftool_e4_organise.Organise.O1', 'organiseCopies', 'supported', supported=True, outcome='succeeded', independentlyVerified=True)

    def test_omitted_sidecars_are_not_copied_and_the_original_files_are_untouched(self):
        self.organise('omit', sidecars='omit')
        self.assertFalse(list((self.tmp / 'omit' / 'organised').rglob('*.xmp')))
        self.assertEqual({n: (self.media / (n + '.jpg')).read_bytes() for n in 'abc'}, self.data)

    def test_O9_the_slot_layout_is_fixed_by_item_and_kind(self):
        (self.media / 'a.xmp').unlink()
        self.put('c.xmp', b'<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"><rdf:Description rdf:about=""/></rdf:RDF></x:xmpmeta>')
        self.put('b.jpg', f.fx.jpeg(make='Make', model='Model', dto=None, off=None, sub=None, seed=2))          # item 1 has no capture time: refused
        self.organise('o9', {**self.TREE, 'collisions': 'refuse'})
        slots = self.json('o9', 'verification.json')['artifacts']
        self.assertEqual([(s['kind'], s['identity']['kind'], s['identity'].get('item')) for s in slots[:7]],
                         [('image', 'image', 'a'), ('text', 'outcome', 'b'), ('image', 'image', 'c'), ('text', 'noSidecar', 'a'), ('text', 'noSidecar', 'b'), ('text', 'sidecar', 'c'), ('text', 'namePlan', None)])
        self.assertEqual(self.json('o9', 'outcomes/b.json')['fault']['code'], 'NAME_TIME_MISSING')

    def test_O2_a_plan_for_other_bytes_is_stale_for_the_whole_run_before_anything_is_copied(self):
        self.run_op({'version': V, 'operation': 'planNames', 'media': self.folder, **self.TREE}, 'plan')
        (self.media / 'c.jpg').write_bytes(photo('2024:03:01 11:00:00', off=None, seed=9))
        fault = self.refuses({'version': V, 'operation': 'organiseCopies', 'media': self.folder, 'names': str(self.tmp / 'plan' / 'names-plan.json')}, 'stale', 'NAME_PLAN_STALE')
        self.assertEqual(fault.observed['items'], ['c'])
        self.assertFalse((self.tmp / 'stale' / 'organised').exists() and any((self.tmp / 'stale' / 'organised').iterdir()))

    def test_O2_a_member_added_to_the_folder_is_stale_too(self):
        self.run_op({'version': V, 'operation': 'planNames', 'media': self.folder, **self.TREE}, 'plan')
        self.put('d.jpg', photo('2024:03:05 11:00:00', seed=8))
        self.refuses({'version': V, 'operation': 'organiseCopies', 'media': self.folder, 'names': str(self.tmp / 'plan' / 'names-plan.json')}, 'stale', 'NAME_PLAN_STALE')

    def inject(self, action):
        original = e4host.copy_tree
        self.addCleanup(setattr, e4host, 'copy_tree', original)

        def patched(directory, copies, checkpoint):
            action(directory / 'organised')
            return original(directory, copies, checkpoint)
        e4host.copy_tree = patched

    def test_O3_a_link_planted_at_a_directory_refuses_the_affected_items_and_nothing_is_written_through_it(self):
        outside = self.tmp / 'outside'
        outside.mkdir()
        self.inject(lambda base: os.symlink(outside, base / '2024'))
        self.put('d.jpg', photo('2025:01:05 09:00:00', seed=8))
        result = self.organise('o3')
        self.assertEqual((result['written'], result['failed']), (1, 3))
        self.assertEqual(list(outside.iterdir()), [])
        self.assertEqual({self.json('o3', 'outcomes/%s.json' % n)['fault']['code'] for n in 'abc'}, {'ORGANISE_PATH_UNSAFE'})
        self.assertEqual(self.json('o3', 'organise-runtime.json')['foreign'][0], {'kind': 'symlink', 'path': '2024', 'target': str(outside)})
        self.assertEqual(self.verify('o3')['failed'], 3)

    def test_O4_planted_directories_are_not_ours_so_their_items_are_refused_and_the_others_complete(self):
        self.put('d.jpg', photo('2025:01:05 09:00:00', seed=8))

        def plant(base):
            (base / '2024' / '03' / 'Model').mkdir(parents=True)
            (base / '2024' / '03' / 'Model' / '20240301_110000.jpg').write_bytes(b'precious')
        self.inject(plant)
        result = self.organise('o4')
        self.assertEqual((result['written'], result['failed']), (1, 3))           # the planted directories are not directories this run created
        self.assertEqual({self.json('o4', 'outcomes/%s.json' % n)['fault']['code'] for n in 'abc'}, {'ORGANISE_PATH_UNSAFE'})
        self.assertEqual((self.tmp / 'o4' / 'organised' / '2024' / '03' / 'Model' / '20240301_110000.jpg').read_bytes(), b'precious')
        self.assertEqual(self.verify('o4')['failed'], 3)

    def test_O4_an_existing_file_in_a_flat_target_is_refused_without_being_replaced(self):
        self.inject(lambda base: (base / '20240301_110000.jpg').write_bytes(b'precious'))
        result = self.organise('o4f', {**RULE})
        self.assertEqual((result['written'], result['failed']), (2, 1))
        self.assertEqual(self.json('o4f', 'outcomes/c.json')['fault']['code'], 'ORGANISE_TARGET_EXISTS')
        self.assertEqual((self.tmp / 'o4f' / 'organised' / '20240301_110000.jpg').read_bytes(), b'precious')
        self.assertEqual(self.verify('o4f')['failed'], 1)

    def test_M_O5_a_flipped_byte_in_an_organised_copy_is_a_copy_mismatch(self):
        self.organise('o5')

        def change(target):
            path = target / 'organised' / '2024' / '03' / 'Model' / '20240301_110000.jpg'
            data = bytearray(path.read_bytes())
            data[-5] ^= 1
            path.write_bytes(bytes(data))
        f.mutate_and_refresh(self, 'o5', 'O5-flip', change, 'ORGANISE_COPY_MISMATCH')

    def test_M_O6_an_extra_file_dropped_under_organised_fails_verification(self):
        self.organise('o6')
        f.mutate_and_refresh(self, 'o6', 'O6-extra', lambda target: (target / 'organised' / 'extra.jpg').write_bytes(b'x'), 'ORGANISE_COPY_MISMATCH')

    def test_M_a_changed_name_plan_is_stale_at_verification(self):
        self.organise('plan2')

        def change(target):
            path = target / 'names-plan.json'
            path.write_bytes(path.read_bytes().replace(b'20240301_110000.jpg', b'20240301_110001.jpg', 1))
        f.mutate_and_refresh(self, 'plan2', 'Nm-plan', change, 'NAME_PLAN_STALE')

    def test_all_items_refused_is_no_success_and_no_copy_exists(self):
        for n in 'abc':
            self.put(n + '.jpg', f.fx.jpeg(make='M', model='M', dto=None, off=None, sub=None, seed=ord(n)))
        self.refuses({'version': V, 'operation': 'organiseCopies', 'media': self.folder, 'names': self.TREE}, 'none', 'NO_USABLE_ITEMS')
        self.assertFalse(list((self.tmp / 'none').glob('organised*')))


class DirectoryDescriptors(unittest.TestCase):
    """E4R7: the intermediate directories of organised/ are reached through directory descriptors (O_DIRECTORY | O_NOFOLLOW, relative mkdir/open), so a component swapped for a link
    after it was opened is never written through. Host only; the swap is a test-owned patch of ``os.open`` / ``os.mkdir``."""

    def setUp(self):
        import tempfile
        self.holder = tempfile.TemporaryDirectory()
        self.addCleanup(self.holder.cleanup)
        root = Path(self.holder.name)
        self.base, self.outside = root / 'organised', root / 'outside'
        self.base.mkdir()
        self.outside.mkdir()

    def test_an_intermediate_directory_swapped_for_a_link_after_it_was_opened_receives_no_byte(self):
        from unittest import mock
        real_open, swapped = os.open, []

        def swapping_open(path, flags, *args, **kwargs):
            descriptor = real_open(path, flags, *args, **kwargs)
            if path == 'year' and kwargs.get('dir_fd') is not None and not swapped:
                (self.base / 'year').rename(self.base / 'year.original')           # the race window: the checked directory is replaced by a link to a foreign folder
                (self.base / 'year').symlink_to(self.outside, target_is_directory=True)
                swapped.append(path)
            return descriptor
        created = set()
        with mock.patch.object(os, 'open', swapping_open):
            e4host.copy_exact(self.base, 'year/month/a.jpg', b'CAPTURE-BYTES', created)
        self.assertEqual(swapped, ['year'])
        self.assertEqual(list(self.outside.iterdir()), [])                                               # nothing was written through the link
        self.assertEqual((self.base / 'year.original' / 'month' / 'a.jpg').read_bytes(), b'CAPTURE-BYTES')   # the descriptor kept naming the directory that was checked
        self.assertTrue((self.base / 'year').is_symlink())

    def test_a_link_already_on_the_path_is_the_structured_path_fault_and_writes_nothing(self):
        (self.base / 'year').symlink_to(self.outside, target_is_directory=True)
        with self.assertRaises(e4host.Unsafe) as raised:
            e4host.copy_exact(self.base, 'year/a.jpg', b'X', set())
        self.assertEqual((raised.exception.code, raised.exception.observed['path']), ('ORGANISE_PATH_UNSAFE', 'year'))
        self.assertEqual(list(self.outside.iterdir()), [])

    def test_a_mkdir_that_loses_a_race_is_the_structured_path_fault_not_a_raw_file_exists_error(self):
        from unittest import mock
        real_mkdir = os.mkdir

        def racing_mkdir(path, *args, **kwargs):
            real_mkdir(path, *args, **kwargs)              # the foreign directory appears first
            real_mkdir(path, *args, **kwargs)              # ... so this run's own mkdir raises FileExistsError
        with mock.patch.object(os, 'mkdir', racing_mkdir):
            with self.assertRaises(e4host.Unsafe) as raised:
                e4host.copy_exact(self.base, 'year/a.jpg', b'X', set())
        self.assertEqual((raised.exception.code, raised.exception.observed['path']), ('ORGANISE_PATH_UNSAFE', 'year'))
        self.assertEqual([x.name for x in self.base.iterdir()], ['year'])                              # the foreign directory is left alone, and no file was created in it
        self.assertEqual(list((self.base / 'year').iterdir()), [])

    def test_a_cleanup_unlink_never_follows_a_swapped_directory(self):
        created = set()
        e4host.copy_exact(self.base, 'year/a.jpg', b'X', created)
        (self.outside / 'a.jpg').write_bytes(b'FOREIGN')
        (self.base / 'year').rename(self.base / 'year.original')
        (self.base / 'year').symlink_to(self.outside, target_is_directory=True)
        e4host.unlink_exact(self.base, 'year/a.jpg')
        self.assertEqual((self.outside / 'a.jpg').read_bytes(), b'FOREIGN')                            # the foreign file survived
        self.assertEqual((self.base / 'year.original' / 'a.jpg').read_bytes(), b'X')


if __name__ == '__main__':
    unittest.main()
