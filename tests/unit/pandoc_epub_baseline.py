"""Digests of what a report WITHOUT an `epub` declaration produces (plan, model, tree, native commands, launchers, summary, captures, result).

`fingerprint` runs against any adaptor module. The pinned values in test_pandoc_epub.py were computed from the pre-change adaptor source
(the baseline preserved before the EPUB change) with this same procedure, so a change that alters one byte of an epub-free report fails.
"""
import hashlib
import json
from pathlib import Path
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent))
import pandoc_epub_fixture as fx  # noqa: E402


def fingerprint(module, directory):
    directory = Path(directory)
    def sha(value): return hashlib.sha256(json.dumps(value, sort_keys=True).replace(str(directory), '<dir>').encode()).hexdigest()
    document = fx.document(directory, language=None)
    prepared = module.plan(document)
    for i, j, block in module.image_blocks(prepared): (directory / f'image-{i}-{j}.png').write_bytes(Path(block['source']).read_bytes())
    for i, j, block in module.transcript_blocks(prepared): (directory / f'transcript-{i}-{j}.json').write_bytes(Path(block['segments']['path']).read_bytes())
    tree = module.ast(prepared, [1, 23, 1, 2], directory)
    model = module.expected({**prepared, '_directory': directory})
    native = module.commands('/x/pandoc')
    captured = {}
    for i, j, block in module.transcript_blocks(prepared):
        captured[f'transcript-{i}-{j}.json'] = module.transcript_summary(block, module.retained_transcript(directory, i, j))
    with patch('schemaxis.adaptors.pandoc.inspection.html_report'), patch('schemaxis.adaptors.pandoc.inspection.docx_report'), \
            patch('schemaxis.adaptors.pandoc.inspection.ast_report'):
        for name in ('report.html', 'report.docx'): (directory / name).write_bytes(b'x')
        (directory / 'reopened.json').write_text('{}')
        summary = module.inspect(directory, prepared)
    for name in ('report.html', 'report.docx', 'report-summary.json'): (directory / name).write_bytes(b'x')
    return {'plan': sha(prepared), 'tree': sha(tree), 'model': sha(model), 'commands': sha(native), 'captured': sha(captured), 'summary': sha(summary),
            'launchers': sha({stage: module.launcher(directory, stage, command, prepared) for stage, command in native.items()}),
            'inputs': sha({stage: module.stage_inputs(stage, prepared) for stage in native}),
            'artifacts': sha([{k: v for k, v in a.items() if k != 'file'} for a in module.artifacts(directory)]),
            'artifactNames': [Path(a['file']).name for a in module.artifacts(directory)],
            'result': sha({k: summary[k] for k in ('sections', 'blocks', 'tables', 'images', 'transcripts', 'transcriptTimeFormats') if k in summary})}


if __name__ == '__main__':
    import tempfile
    from schemaxis.adaptors.pandoc import adaptor
    with tempfile.TemporaryDirectory() as name: print(json.dumps(fingerprint(adaptor, name), indent=1))
