"""A small multilingual report with an EPUB declaration, its genuine Pandoc 3.12.1 outputs, and a stand-in executable that replays them.

`examples/schemaxis/fixtures/pandoc-epub` holds the real HTML, DOCX, EPUB and readback files that Pandoc 3.12.1 wrote for `document()`
(no tool writes them: after a reviewed Pandoc change, run tools/qualify_pandoc_epub.py against that Pandoc into a fresh output directory, then
copy report.html, report.docx, reopened.json, report.epub, epub-reopened.json and the `reopened/media` directory (as `reopened-media`) from its
`a/epub` run; the qualifier asserts that the committed files equal the live output, so it fails until they are replaced). Host tests replay them through the unchanged
`run` and `verify` code, so every inspector reads genuine writer output; nothing here is a Pandoc implementation.
"""
import json
from pathlib import Path
import shutil
import stat
import sys

sys.path.insert(0, str(Path(__file__).parent))
import pandoc_docx_fixture as docx  # noqa: E402
import test_timed_text as source  # noqa: E402
from schemaxis.adaptors.whispercpp import corrections_deletion as deletion  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / 'examples/schemaxis/fixtures/pandoc-epub'
VERSION = 'schemaxis.pandoc/1'
TITLE = "Rapport d'étalonnage — 校准 & <test>"
LANGUAGE = 'fr-CA'


def sources(directory):
    """A machine-draft transcript and a reviewed/2 transcript whose every cue was deleted (publishes provenance only)."""
    directory = Path(directory)
    draft = directory / 'segments.json'; draft.write_bytes(source.encode(source.document()))
    import hashlib
    authored = {'version': deletion.VERSION, 'draft': {'path': str(draft)}, 'basisSha256': hashlib.sha256(draft.read_bytes()).hexdigest(),
                'review': {'status': 'human-corrected', 'note': 'Illustrative automated declaration; no person reviewed this.'}, 'deletions': [0, 1]}
    outputs, _, _ = deletion.derive(deletion.plan(authored), draft.read_bytes())
    empty = directory / 'reviewed-empty.json'; empty.write_bytes(outputs['reviewed-segments.json'])
    return draft, empty


def document(directory, language=LANGUAGE):
    """The report as authored; `language=None` omits the epub declaration and leaves everything else unchanged."""
    directory = Path(directory)
    (directory / 'a.png').write_bytes(docx.png(8, 4, 10)); (directory / 'b.png').write_bytes(docx.png(8, 4, 200))
    draft, empty = sources(directory)
    report = {'version': VERSION, 'operation': 'report', 'title': TITLE, 'sections': [
        {'heading': 'Méthode & <x>', 'level': 1, 'content': [
            {'kind': 'paragraph', 'text': 'Texte avec é, 日本語, العربية & <b> "quotes" \'single\'.'},
            {'kind': 'table', 'columns': ['A&B', 'Ç'], 'rows': [['1', '<2>'], ['x y', 'z']]}]},
        {'heading': 'Détails', 'level': 2, 'content': [
            {'kind': 'image', 'source': str(directory / 'a.png'), 'alt': 'Alt <1> & "2"', 'widthMm': 60},
            {'kind': 'image', 'source': str(directory / 'b.png'), 'alt': 'Second', 'widthMm': 37.5}]},
        {'heading': 'Sous', 'level': 3, 'content': [{'kind': 'paragraph', 'text': 'deep'}]},
        {'heading': 'Transcription', 'level': 1, 'content': [
            {'kind': 'transcript', 'segments': {'path': str(draft)}, 'timeFormat': 'timecode'},
            {'kind': 'transcript', 'segments': {'path': str(empty)}, 'timeFormat': 'timecode'}]}]}
    if language is not None: report['epub'] = {'language': language}
    return report


STAND_IN = '''#!{python}
import json, shutil, sys
from pathlib import Path
fixture = Path({fixture!r}); args = sys.argv[1:]
if args[:1] == ['--version']: print('pandoc 3.12.1'); sys.exit(0)
name = [a[len('--output='):] for a in args if a.startswith('--output=')][0]
if name == 'api.json': Path(name).write_text(json.dumps({{'pandoc-api-version': [1, 23, 1, 2]}}))
else:
    shutil.copyfile(fixture / name, name)
    if name == 'reopened.json': shutil.copytree(fixture / 'reopened-media', 'reopened/media')
'''


def stand_in(directory, fixture=FIXTURE):
    """An executable that writes the genuine fixture outputs named by --output=, so the real stage launcher, receipts and inspectors run."""
    path = Path(directory) / 'pandoc-stand-in'
    path.write_text(STAND_IN.format(python=sys.executable, fixture=str(fixture))); path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path
