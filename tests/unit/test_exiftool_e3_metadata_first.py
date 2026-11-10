"""Metadata-first semantic mutants of real E3 runs (genuine ExifTool 13.55 through SCHEMAXIS_EXIFTOOL).

Every mutant edits a copy of a retained correctTime, setLocation or geotagFromTrack run, then refreshes every ordinary binding (launcher input digests, receipt evidence and
artifact records, publication metadata) so that ``publication_metadata.verify`` PASSES, and only then asks the public adaptor ``verify``, which must refuse it with exactly the
semantic code and location of the mutated fact and a non-empty message. The mutants are the same hand-written edits as the per-operation mutant tests, which also run them
without the refresh; synthetic edits of retained records are distinguished from real native observations in the qualifier report.
"""
import shutil
import sys
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / 'tools'))
sys.path.insert(0, str(ROOT / 'tests/unit'))

import test_exiftool_e3_correct as correct  # noqa: E402
import test_exiftool_e3_geotag as geotag  # noqa: E402
import test_exiftool_e3_place as place  # noqa: E402
from schemaxis import publication_metadata  # noqa: E402
from schemaxis.adaptors.exiftool import adaptor  # noqa: E402
from schemaxis.core.faults import SchemaxisError  # noqa: E402
from test_exiftool_write_complete import refresh  # noqa: E402

RESULTS = {}


def refreshed_mutant(case, operation, label, change):
    """Copy the retained run, apply ``change``, refresh the bindings, require the publication metadata to verify, then require one exact semantic refusal."""
    target = case.tmp / ('mf-' + label)
    shutil.copytree(case.main, target, symlinks=True)
    change(target)
    refresh(target, case.main)
    assert publication_metadata.verify(target)['verified'], 'the publication metadata must verify before the public route is asked'
    with case.assertRaises(SchemaxisError) as caught:
        adaptor.verify(target, executable=case.exe)
    fault = caught.exception.fault
    cause = fault.observed.get('cause', {})
    code, location = cause.get('code', fault.code), cause.get('location', fault.location)
    message = cause.get('message') or fault.message
    case.assertTrue(isinstance(message, str) and message.strip(), 'a refusal states why')
    RESULTS['%s:%s' % (operation, label)] = {'id': '%s:%s' % (operation, label), 'operation': operation, 'container': 'jpeg', 'publicationMetadataVerified': True, 'code': code, 'location': location,
                                           'message': message, 'route': 'public adaptor.verify after the full refresh', 'independentlyVerified': True}
    problems = [p['code'] for p in cause.get('observed', {}).get('problems', [])] if isinstance(cause.get('observed'), dict) else []
    return code, location, problems


class CorrectTimeMetadataFirst(correct.PlanAndMutants):
    def mutate(self, name, change, refresh_first=False):
        return refreshed_mutant(self, 'correctTime', name, change)


class SetLocationMetadataFirst(place.Mutants):
    def mutate(self, name, change):
        return refreshed_mutant(self, 'setLocation', name, change)


class GeotagMetadataFirst(geotag.Mutants):
    def mutate(self, name, relative, replace, refresh_first=True):
        def change(target):
            path = target / relative
            path.write_bytes(replace(path.read_bytes()))
        code, location, _ = refreshed_mutant(self, 'geotagFromTrack', name, change)
        return code, location




if __name__ == '__main__':
    unittest.main()
