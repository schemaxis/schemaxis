"""Pinned snapshot handoffs with literal content and independent CLI decoding."""
from pathlib import Path
import subprocess
from schemaxis.captured_inputs import adopt
from schemaxis.core.faults import SchemaxisError
from schemaxis.workflow import execute, verify


def captured_inputs(directory, executable):
    folder = directory/'captured-inputs';folder.mkdir()
    original = folder/'original.bin';content = b'\x00\xffpinned scientific records\n' * 300
    original.write_bytes(content)
    snapshot = adopt(original, folder/'file-snapshot')
    original.unlink()
    document = {'version': 'schemaxis.workflow/1', 'execution': {'maxWorkers': 1, 'cpus': 2}, 'operations': [
        {'id': 'compress', 'document': {'version': 'schemaxis.zstandard/1', 'operation': 'compress', 'source': snapshot['reference']}},
        {'id': 'restore', 'document': {'version': 'schemaxis.zstandard/1', 'operation': 'restore', 'source': {'$artifact': 'compress', 'index': 0}}}]}
    def run(doc, target, **options):
        return execute(doc, target, locations={'zstandard': executable}, timeout=180, **options)
    work = folder/'workflow';first = run(document, work)
    restored = Path(next(job for job in first['jobs'] if job['operation'] == 'restore')['directory'])/'restored.bin'
    assert restored.read_bytes() == content
    compressed = Path(next(job for job in first['jobs'] if job['operation'] == 'compress')['directory'])/'payload.zst'
    assert subprocess.check_output([str(executable), '--quiet', '--decompress', '--stdout', str(compressed)], timeout=30) == content
    assert verify(work)['verified']
    assert all(job['reused'] for job in run(document, work, resume=True)['jobs'])

    source = folder/'original-directory';source.mkdir();(source/'nested').mkdir()
    inputs = {'run.bin': b'first run\x00' * 40, 'nested/phase-\u03b2.bin': bytes(range(256)) * 8}
    for name, data in inputs.items():(source/name).write_bytes(data)
    selected = adopt(source, folder/'directory-snapshot', kind='directory')
    source.rename(folder/'original-directory-hidden')
    files_document = {'version': 'schemaxis.workflow/1', 'operations': [
        {'id': 'files', 'document': {'version': 'schemaxis.zstandard/1', 'operation': 'compressFiles',
                                   'fileSet': {'root': selected['reference'], 'recursive': True}}}]}
    files_work = folder/'files-workflow';files = run(files_document, files_work)
    job = Path(files['jobs'][0]['directory'])
    # Publication names retain the authored relative file names and codec suffix.
    assert {p.relative_to(job/'files').as_posix() for p in (job/'files').rglob('*.zst')} == {name + '.zst' for name in inputs}
    for name, data in inputs.items():
        compressed_member = job/'files'/(name + '.zst')
        assert subprocess.check_output([str(executable), '--quiet', '--decompress', '--stdout', str(compressed_member)], timeout=30) == data
    assert verify(files_work)['verified']
    assert all(job['reused'] for job in run(files_document, files_work, resume=True)['jobs'])
    # Refuse modified immutable bytes before treating a pinned reference as reusable.
    member = folder/'file-snapshot/data/original.bin';before = member.read_bytes();member.write_bytes(b'changed snapshot')
    try:
        try:run(document, work, resume=True)
        except SchemaxisError as error:assert error.fault.code == 'RESOURCE_MISMATCH', error.fault.to_dict()
        else:raise AssertionError('changed captured input was accepted')
    finally:member.write_bytes(before)
    # Failed admission leaves an incomplete workflow ledger; restore and resume
    # explicitly rather than treating restored bytes as a successful execution.
    run(document, work, resume=True)
    assert verify(work)['verified']
    return {'fileRoundtripBytes': len(content), 'independentDecodedFiles': sorted(inputs), 'sourceRemoval': True,
            'verifiedReuse': True, 'pinnedContentMutationRefused': True}
