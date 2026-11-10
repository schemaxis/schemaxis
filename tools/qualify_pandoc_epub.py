#!/usr/bin/env python3
"""Bounded native acceptance of the Pandoc report `epub` declaration: real EPUB 3 writer and reader, literal package content, forged packages.

Runs the real Pandoc against a multilingual report (PNGs, a table, a timecode machine-draft transcript and an all-cues-deleted reviewed/2
transcript), a language matrix of direct native probes (each with its native PID, deadline and exit code; adaptor stage submissions record the supervisor PID and
the reported exit code instead), a budget-sized report, the workflow path and
lifecycle cases. It never registers a qualification receipt, never installs anything and never writes into a retained run passed with
--genuine-run (those are only re-verified, then compared byte for byte). The proof is bounded: not EPUBCheck, not a reading system or device.
"""
import argparse
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import time
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tests/unit'))
from qualify_pandoc import refused, tree_digests  # noqa: E402
import pandoc_epub_fixture as fx  # noqa: E402
import test_pandoc_epub as zipbytes  # noqa: E402
import pandoc_docx_fixture as docx  # noqa: E402
from schemaxis import workflow  # noqa: E402
from schemaxis.adaptors.pandoc import adaptor, epub  # noqa: E402
from schemaxis.artifacts import atomic_json  # noqa: E402
from schemaxis.core.faults import SchemaxisError  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
# EN and zh-hans-cn are accepted by the planning grammar as authored; Pandoc keeps their case, and the matrix runs them natively.
LANGUAGES = ['en', 'fr-CA', 'zh-Hans-CN', 'ar', 'ja', 'de-CH-1996', 'yue', 'sr-Latn-RS', 'EN', 'zh-hans-cn']
# Independent literals, written here and not derived from the adaptor or the fixture builder.
CHAPTER_ONE = ['<h1>Méthode &amp; &lt;x&gt;</h1>', '<p>Texte avec é, 日本語, العربية &amp; &lt;b&gt; "quotes" \'single\'.</p>', '<th>A&amp;B</th>', '<th>Ç</th>', '<td>&lt;2&gt;</td>',
               '<td>x y</td>', '<h2>Détails</h2>', 'style="width:60mm" alt="Alt &lt;1&gt; &amp; &quot;2&quot;"', 'style="width:37.5mm" alt="Second"', '<h3>Sous</h3>', '<p>deep</p>']
CHAPTER_TWO = ['<h1>Transcription</h1>', '<th>Start (HH:MM:SS.mmm)</th>', '<td>00:00:05.410</td>', '<td>00:00:11.000</td>', 'And so, my fellow Americans,',
               'the author deleted every cue, so no cues are retained']
PROCESSES = []


def probe(label, argv, deadline_seconds=60):
    """One direct native process with its PID, deadline and exit code recorded."""
    started = time.time(); process = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try: out, err = process.communicate(timeout=deadline_seconds)
    except subprocess.TimeoutExpired:
        process.kill(); process.communicate(); PROCESSES.append({'label': label, 'pid': process.pid, 'deadlineSeconds': deadline_seconds, 'exitCode': None, 'timedOut': True}); raise
    PROCESSES.append({'label': label, 'pid': process.pid, 'deadlineSeconds': deadline_seconds, 'exitCode': process.returncode, 'seconds': round(time.time() - started, 3),
                      'argv': [os.path.basename(argv[0]), *argv[1:]]})
    assert process.returncode == 0, (label, err[:300]); return out


def native(document, directory, locations, timeout=120):
    result = adaptor.run(document, directory, executable=locations['pandoc'], timeout=timeout)
    assert result['verified'] and adaptor.verify(directory)['verified'], result
    for stage in ('version', 'api', 'html', 'docx', 'reopen', 'epub', 'epubreopen'):
        if (directory / f'{stage}-submission.json').exists():
            submission = adaptor.read(directory, f'{stage}-submission.json')
            PROCESSES.append({'label': f'{directory.name}:{stage}', 'supervisorPid': os.getpid(), 'deadlineSeconds': timeout, 'exitCode': submission['exitCode'], 'seconds': submission['seconds']})
    return result


def refresh(run):
    """Refresh every ordinary hash a forger who rewrites all evidence would: stage inputs, evidence, artifacts and common metadata."""
    prepared = adaptor.plan(adaptor.read(run, 'authored.json'), retained=True); receipt = adaptor.read(run, 'verification.json')
    for stage in adaptor.commands(receipt['executable'], prepared.get('epub')):
        atomic_json(run / (stage + '-inputs.json'), {str(run / n): adaptor.digest(run, n) for n in adaptor.stage_inputs(stage, prepared)})
    receipt['evidence'] = {name: adaptor.digest(run, name) for name in receipt['evidence']}; receipt['artifacts'] = adaptor.artifacts(run, (run / 'report.epub').exists())
    atomic_json(run / 'verification.json', receipt)


def zip_members(path):
    with zipfile.ZipFile(path) as archive: return [(i.filename, archive.read(i)) for i in archive.infolist()]


def epub_edit(run, change, name='report.epub'):
    def action():
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w') as out:
            for member, body in change(zip_members(run / name)):
                out.writestr(zipfile.ZipInfo(member, (1980, 1, 1, 0, 0, 0)), body, zipfile.ZIP_STORED if member == 'mimetype' else zipfile.ZIP_DEFLATED)
        (run / name).write_bytes(buffer.getvalue())
    return action


def replace(member, old, new):
    def change(members):
        out = []; found = 0
        for name, body in members:
            if member is None or name == member: found += body.count(old); body = body.replace(old, new)
            out.append((name, body))
        assert found, (member, old)
        return out
    return change


def byte_edit(run, change, name='report.epub'):
    """A forgery written below the ZIP library: `change` receives the raw EPUB bytes and returns the forged bytes."""
    def action(): (run / name).write_bytes(change((run / name).read_bytes()))
    return action


def json_edit(run, name, mutate):
    def action(): value = adaptor.read(run, name); mutate(value); atomic_json(run / name, value)
    return action


def last_gap(raw):
    entries = zipbytes.walk(raw); entries[-1] = {**entries[-1], 'gap': b'\0'}
    return zipbytes.build(entries)


def forgeries(run, probes, report):
    saved = {p: p.read_bytes() for p in run.rglob('*') if p.is_file()}
    def restore():
        for p in sorted((p for p in run.rglob('*') if p not in saved and not p.is_dir()), key=str, reverse=True): p.unlink()
        for p, data in saved.items(): p.write_bytes(data)
    for name, change, reason in probes:
        try:
            change(); refresh(run); report[name] = refused(lambda: adaptor.verify(run), reason=reason)['code']
        finally: restore()
    assert adaptor.verify(run)['verified']


def literal_package(run, report):
    """Reopen the retained EPUB with zipfile and string literals only: no Pandoc, no adaptor inspector."""
    raw = (run / 'report.epub').read_bytes()
    # Physical framing from the raw bytes with struct alone: members tile the file from offset 0 to the central directory, then the end record.
    assert raw[:4] == b'PK\x03\x04' and raw[30:38] == b'mimetype' and raw[38:58] == b'application/epub+zip', 'mimetype is not first, stored, and unpadded'
    count, directory_size, directory_offset, comment = struct.unpack('<HIIH', raw[-22:][10:])
    assert raw[-22:-18] == b'PK\x05\x06' and comment == 0 and directory_offset + directory_size == len(raw) - 22 and count == 12
    position = 0
    for _ in range(count):
        signature, _, flags, method, _, _, _, packed, _, name_length, extra = struct.unpack('<4sHHHHHIIIHH', raw[position:position + 30])
        assert signature == b'PK\x03\x04' and flags == 0x800 and extra == 0 and method in (0, 8), (position, flags, method, extra)
        position += 30 + name_length + packed
    assert position == directory_offset, 'bytes between members or before the central directory'
    with zipfile.ZipFile(run / 'report.epub') as archive:
        assert archive.testzip() is None
        infos = archive.infolist(); assert infos[0].filename == 'mimetype' and infos[0].compress_type == 0 and archive.read('mimetype') == b'application/epub+zip'
        names = [i.filename for i in infos]; assert len(names) == len(set(names)) == 12, names
        assert all(not n.startswith('/') and '..' not in n and '\\' not in n for n in names) and not any(n.endswith(('.js', '.svg', '.otf', '.ttf', '.woff')) for n in names)
        one, two = (archive.read(f'EPUB/text/ch00{n}.xhtml').decode() for n in (1, 2))
        opf = archive.read('EPUB/content.opf').decode()
        media = [archive.read(n) for n in names if n.startswith('EPUB/media/')]
    for literal in CHAPTER_ONE: assert literal in one, literal
    for literal in CHAPTER_TWO: assert literal in two, literal
    assert '<dc:language>fr-CA</dc:language>' in opf and 'xml:lang="fr-CA"' in opf and '<itemref idref="ch001_xhtml" />' in opf and '<itemref idref="ch002_xhtml" />' in opf
    assert sorted(hashlib.sha256(m).hexdigest() for m in media) == sorted(hashlib.sha256(b).hexdigest() for b in (docx.png(8, 4, 10), docx.png(8, 4, 200)))
    pages = (one + two).replace('http://www.w3.org/1999/xhtml', '').replace('http://www.idpf.org/2007/ops', '')
    for forbidden in ('<script', 'http://', 'https://', '<svg', '<iframe', '<!--', '<link rel="alternate'): assert forbidden not in pages, forbidden
    report['literalPackage'] = {'members': len(names), 'chapters': 2, 'images': len(media), 'language': 'fr-CA'}


def main_acceptance(directory, locations, report):
    directory.mkdir(parents=True)
    source = directory / 'source'; source.mkdir()
    run = directory / 'epub'; result = native(fx.document(source), run, locations)
    assert result['artifacts'] == 4 and result['epub'] == {'language': 'fr-CA', 'chapters': 2, 'entries': 12, 'mediaFiles': 2}, result
    literal_package(run, report)
    for name in ('report.html', 'report.docx', 'reopened.json', 'report.epub', 'epub-reopened.json'):
        assert (run / name).read_bytes() == (fx.FIXTURE / name).read_bytes(), f'{name} differs from the committed genuine fixture'
    report['fixtureMatchesNativeOutput'] = True
    plain = directory / 'plain'; plain_source = directory / 'plain-source'; plain_source.mkdir()
    plain_result = native(fx.document(plain_source, language=None), plain, locations)
    assert plain_result['artifacts'] == 3 and 'epub' not in plain_result and not any(p.name.startswith(('report.epub', 'epub')) for p in plain.iterdir())
    for name in ('report.html', 'report.docx', 'reopened.json', 'api.json', 'report-input.json'):
        assert (plain / name).read_bytes() == (run / name).read_bytes(), name
    assert [Path(a['file']).name for a in adaptor.read(plain, 'verification.json')['artifacts']] == ['report.html', 'report.docx', 'report-summary.json']
    report['absentEpub'] = {'artifacts': 3, 'htmlDocxReadbackIdentical': True, 'epubFiles': 0}
    return run


def language_matrix(directory, locations, report):
    """Direct native writer and reader per language, each with PID/deadline/exit, then independent package and readback checks."""
    directory.mkdir(parents=True); exe = locations['pandoc']; rows = {}
    source = directory / 'source'; source.mkdir(); document = fx.document(source, language=None); prepared = adaptor.plan(document)
    work = directory / 'dir'; work.mkdir()
    for i, j, block in adaptor.image_blocks(prepared): (work / f'image-{i}-{j}.png').write_bytes(Path(block['source']).read_bytes())
    for i, j, block in adaptor.transcript_blocks(prepared): (work / f'transcript-{i}-{j}.json').write_bytes(Path(block['segments']['path']).read_bytes())
    atomic_json(work / 'report-input.json', adaptor.ast(prepared, [1, 23, 1, 2], work)); model = adaptor.expected({**prepared, '_directory': work})
    for language in LANGUAGES:
        book = directory / f'{language}.epub'; back = directory / f'{language}.json'
        probe(f'writer:{language}', [exe, '--from=json', '--to=epub3', '--standalone', '--sandbox', f'--metadata=lang:{language}', f'--output={book}', str(work / 'report-input.json')])
        probe(f'reader:{language}', [exe, '--from=epub', '--to=json', '--sandbox', f'--output={back}', str(book)])
        facts = epub.package_report(book.read_bytes(), fx.TITLE, language, model); epub.readback_report(json.loads(back.read_text()), fx.TITLE, language, facts, model)
        rows[language] = {'bytes': book.stat().st_size, 'entries': facts['entries'], 'sha256': hashlib.sha256(book.read_bytes()).hexdigest()}
        again = directory / f'{language}-again.epub'
        probe(f'writer-repeat:{language}', [exe, '--from=json', '--to=epub3', '--standalone', '--sandbox', f'--metadata=lang:{language}', f'--output={again}', str(work / 'report-input.json')])
        assert again.read_bytes() == book.read_bytes(), 'native EPUB output is not repeatable'
    report['languageMatrix'] = rows


def budget_report(directory, locations, report):
    """The report maxima: 32 level 1 sections (32 chapters), 8 images, a long unbroken paragraph, in one EPUB."""
    directory.mkdir(parents=True)
    pngs = []
    for k in range(8): path = directory / f'big-{k}.png'; path.write_bytes(docx.png(2048 // 4, 64, k * 30)); pngs.append(path)
    sections = []
    for n in range(32):
        content = [{'kind': 'paragraph', 'text': ' '.join(f'word{n}-{w}' for w in range(180))}]
        if n < 8: content.append({'kind': 'image', 'source': str(pngs[n]), 'alt': f'Figure {n}', 'widthMm': 100})
        sections.append({'heading': f'Section {n + 1}', 'level': 1, 'content': content})
    document = {'version': adaptor.VERSION, 'operation': 'report', 'title': 'Budget report', 'sections': sections, 'epub': {'language': 'en'}}
    run = directory / 'run'; result = native(document, run, locations)
    assert result['epub']['chapters'] == 32 and result['epub']['mediaFiles'] == 8 and result['images'] == 8, result
    with zipfile.ZipFile(run / 'report.epub') as archive:
        assert 'EPUB/text/ch032.xhtml' in archive.namelist()
        assert ' '.join(f'word31-{w}' for w in range(180)) in archive.read('EPUB/text/ch032.xhtml').decode()
    report['budgetReport'] = {'chapters': 32, 'images': 8, 'epubBytes': (run / 'report.epub').stat().st_size}


def outline_shapes(directory, locations, report):
    """Nested and descending outlines (chapters split at level 1; nesting follows heading level) through the real writer, reader and inspectors."""
    directory.mkdir(parents=True); shapes = {'deep-and-back': [1, 2, 3, 2, 3, 1, 2, 1], 'flat': [1, 1, 1], 'single': [1], 'staircase': [1, 2, 3, 3, 2, 1, 2, 3]}
    for name, levels in shapes.items():
        sections = [{'heading': f'H{k + 1} level {level}', 'level': level, 'content': [{'kind': 'paragraph', 'text': f'Body {k + 1}'}]} for k, level in enumerate(levels)]
        document = {'version': adaptor.VERSION, 'operation': 'report', 'title': f'Outline {name}', 'sections': sections, 'epub': {'language': 'en'}}
        result = native(document, directory / name, locations)
        assert result['epub']['chapters'] == levels.count(1), (name, result)
        shapes[name] = {'levels': levels, 'chapters': result['epub']['chapters']}
    report['outlineShapes'] = shapes


def forged(run, report):
    ch1, ch2, opf = 'EPUB/text/ch001.xhtml', 'EPUB/text/ch002.xhtml', 'EPUB/content.opf'
    reason = 'EPUB'
    probes = [
        ('bodyWord', epub_edit(run, replace(ch1, b'<p>deep</p>', b'<p>dEEp</p>')), 'semantics differ'),
        ('tableCell', epub_edit(run, replace(ch1, b'<td>z</td>', b'<td>Z</td>')), 'semantics differ'),
        ('timecodeCell', epub_edit(run, replace(ch2, b'<td>00:00:05.410</td>', b'<td>00:00:05.411</td>')), 'semantics differ'),
        ('droppedParagraph', epub_edit(run, replace(ch1, b'<p>deep</p>\n', b'')), 'semantics differ'),
        ('injectedParagraph', epub_edit(run, replace(ch1, b'<p>deep</p>', b'<p>deep</p>\n<p>injected</p>')), 'semantics differ'),
        ('titleEverywhere', epub_edit(run, replace(None, b'Rapport', b'Rapports')), reason),
        ('languageEverywhere', epub_edit(run, replace(None, b'fr-CA', b'en-CA')), reason),
        ('spineOrder', epub_edit(run, replace(opf, b'    <itemref idref="ch002_xhtml" />\n', b'')), reason),
        ('manifestMedia', epub_edit(run, replace(opf, b'media/file0.png', b'media/file5.png')), reason),
        ('navigation', epub_edit(run, replace('EPUB/nav.xhtml', 'Détails'.encode(), b'Autre')), 'table of contents'),
        ('ncx', epub_edit(run, replace('EPUB/toc.ncx', b'content="urn:uuid:', b'content="urn:uuid:0')), 'identifier'),
        ('mimetypeChanged', epub_edit(run, replace('mimetype', b'application/epub+zip', b'application/zip')), 'mimetype'),
        ('mimetypeNotFirst', epub_edit(run, lambda m: [*m[1:], m[0]]), 'mimetype'),
        ('script', epub_edit(run, replace(ch1, b'<p>deep</p>', b'<p>deep</p><script>1</script>')), reason),
        ('externalStylesheet', epub_edit(run, replace(ch1, b'../styles/stylesheet1.css', b'https://example.test/x.css')), reason),
        ('stylesheetOverride', epub_edit(run, replace('EPUB/styles/stylesheet1.css', b'/* This defines', b'@import url(https://example.test/x.css);\n/* This defines')), 'differs from qualified'),
        ('unreferencedDuplicateMedia', epub_edit(run, lambda m: [*[(n, b.replace(b'  </manifest>', b'    <item id="file5_png" href="media/file5.png" media-type="image/png" />\n  </manifest>') if n == opf else b) for n, b in m],
                                                              ('EPUB/media/file5.png', dict(m)['EPUB/media/file0.png'])]), 'media membership'),
        ('externalImage', epub_edit(run, replace(ch1, b'../media/file1.png', b'https://example.test/b.png')), reason),
        ('doctypeEntity', epub_edit(run, replace(ch1, b'<!DOCTYPE html>', b'<!DOCTYPE html [<!ENTITY x "y">]>')), 'document type'),
        ('hiddenComment', epub_edit(run, replace(ch1, b'<p>deep</p>', b'<p>deep</p><!-- hidden -->')), 'comment'),
        ('unsafeMember', epub_edit(run, lambda m: [*m, ('../evil.txt', b'x')]), 'unsafe'),
        ('fontMember', epub_edit(run, lambda m: [*m, ('EPUB/fonts/f.otf', b'x')]), 'member'),
        ('svgMember', epub_edit(run, lambda m: [*m, ('EPUB/media/x.svg', b'<svg/>')]), 'member'),
        ('mediaBody', epub_edit(run, replace('EPUB/media/file0.png', docx.png(8, 4, 10), docx.png(8, 4, 99))), reason),
        ('physicalScriptPrefix', byte_edit(run, lambda raw: b'<html><script>alert(1)</script></html>' + raw), 'local file header'),
        ('physicalTrailingBytes', byte_edit(run, lambda raw: raw + b'<script>1</script>'), 'end record'),
        ('physicalHiddenBetweenMembers', byte_edit(run, lambda raw: zipbytes.build([{**e, 'gap': b'HIDDEN'} if e['name'] == b'EPUB/nav.xhtml' else e for e in zipbytes.walk(raw)])), 'previous member ends'),
        ('physicalHiddenAfterMimetype', byte_edit(run, lambda raw: zipbytes.build(zipbytes.patched(zipbytes.walk(raw), 'mimetype', gap=b'x'))), 'previous member ends'),
        ('physicalHiddenBeforeDirectory', byte_edit(run, last_gap), 'central directory'),
        ('physicalCentralReordered', byte_edit(run, lambda raw: zipbytes.build(zipbytes.walk(raw), central=[1, 0, *range(2, 12)])), 'previous member ends'),
        ('physicalMimetypeLastListedFirst', byte_edit(run, lambda raw: zipbytes.build([*zipbytes.walk(raw)[1:], zipbytes.walk(raw)[0]], central=[11, *range(11)])), 'previous member ends'),
        ('physicalMimetypeLast', byte_edit(run, lambda raw: zipbytes.build([*zipbytes.walk(raw)[1:], zipbytes.walk(raw)[0]])), 'mimetype must be the first'),
        ('physicalMimetypeLocalExtra', byte_edit(run, lambda raw: zipbytes.build(zipbytes.patched(zipbytes.walk(raw), 'mimetype', local_extra=b'\xfe\xca\x00\x00'))), 'mimetype'),
        ('physicalLocalCrcMismatch', byte_edit(run, lambda raw: zipbytes.build(zipbytes.patched(zipbytes.walk(raw), 'EPUB/nav.xhtml', local={'crc': 0}))), 'local header differs'),
        ('physicalLocalNameMismatch', byte_edit(run, lambda raw: zipbytes.build(zipbytes.patched(zipbytes.walk(raw), 'EPUB/nav.xhtml', local={'name': b'EPUB/nav.xhtmL'}))), 'local header differs'),
        ('physicalLocalMethodMismatch', byte_edit(run, lambda raw: zipbytes.build(zipbytes.patched(zipbytes.walk(raw), 'EPUB/nav.xhtml', local={'method': 0}))), 'local header differs'),
        ('physicalCentralSizeMismatch', byte_edit(run, lambda raw: zipbytes.build(zipbytes.patched(zipbytes.walk(raw), 'EPUB/nav.xhtml', central={'size': 1}))), reason),
        ('physicalEndRecordComment', byte_edit(run, lambda raw: zipbytes.build(zipbytes.walk(raw), eocd={'comment': b'x'})), 'end record'),
        ('zipBomb', epub_edit(run, lambda m: [*m, ('EPUB/media/file9.png', bytes(5 * 1024 * 1024))]), reason),
        ('readbackWord', json_edit(run, 'epub-reopened.json', lambda v: v['blocks'][2]['c'][1][1]['c'].__setitem__(0, {'t': 'Str', 'c': 'Autre'})), 'native EPUB readback'),
        ('readbackLanguage', json_edit(run, 'epub-reopened.json', lambda v: v['meta']['language']['c'].__setitem__(0, {'t': 'Str', 'c': 'en'})), 'native EPUB readback'),
        ('readbackExtraBlock', json_edit(run, 'epub-reopened.json', lambda v: v['blocks'].append({'t': 'Para', 'c': [{'t': 'Str', 'c': 'x'}]})), 'native EPUB readback'),
        ('summaryForged', json_edit(run, 'report-summary.json', lambda v: v['epub'].update(language='en')), 'report summary differs'),
        ('summaryEpubRemoved', json_edit(run, 'report-summary.json', lambda v: v.pop('epub')), 'report summary differs'),
        ('publicationClaimedMissing', lambda: (run / 'report.epub').unlink(), 'report.epub')]
    saved = {p: p.read_bytes() for p in run.rglob('*') if p.is_file()}
    forgeries(run, [p for p in probes if p[0] != 'publicationClaimedMissing'], report)
    (run / 'report.epub').unlink(); receipt = adaptor.read(run, 'verification.json'); receipt['evidence'] = {n: d for n, d in receipt['evidence'].items() if (run / n).exists()}
    receipt['artifacts'] = adaptor.artifacts(run, False); atomic_json(run / 'verification.json', receipt);
    report['publicationClaimedMissing'] = refused(lambda: adaptor.verify(run))['code']
    for p, data in saved.items(): p.write_bytes(data)
    assert adaptor.verify(run)['verified']


def lifecycle(directory, locations, report):
    directory.mkdir(parents=True); exe = locations['pandoc']; source = directory / 'source'; source.mkdir()
    for value in (True, 'en_US', 'english', 1, None):
        document = fx.document(source, language=None); document['epub'] = {'language': value}; target = directory / f'refused-{type(value).__name__}-{value}'
        out = refused(lambda: adaptor.run(document, target, executable=exe, timeout=60), 'INVALID_ARGUMENT')
        assert not target.exists() and out['location'] == '$.epub.language', out
    document = fx.document(source); extra = copy.deepcopy(document); extra['epub']['cover'] = 'x.png'
    assert refused(lambda: adaptor.run(extra, directory / 'extra', executable=exe, timeout=60), 'UNKNOWN_ARGUMENT')['location'] == '$.epub'
    # A total deadline too short for the native stages fails the run and never leaves a publication verified.
    tiny = directory / 'tiny'; started = time.time()
    try: adaptor.run(document, tiny, executable=exe, timeout=0.01)
    except SchemaxisError as error: timeout_code = error.fault.code; failed_after = round(time.time() - started, 2)
    else: raise AssertionError('a 10 ms deadline published an EPUB report')
    assert adaptor.read(tiny, 'result.json')['status'] == 'failed' and not adaptor.read(tiny, 'result.json')['verified']
    from unittest.mock import patch
    with patch.object(adaptor, 'cancellation_requested', return_value=True):
        cancelled = refused(lambda: adaptor.run(document, directory / 'cancelled', executable=exe, timeout=60), 'RUNNER_CANCELLED')['code']
    assert adaptor.read(directory / 'cancelled', 'result.json')['status'] == 'failed'
    graph = {'version': 'schemaxis.workflow/1', 'operations': [{'id': 'report', 'document': document}]}
    first = workflow.execute(graph, directory / 'workflow', locations=locations, timeout=120); verified = workflow.verify(directory / 'workflow'); assert verified['verified'] and verified['artifacts'] == 4, verified
    reused = workflow.execute(graph, directory / 'workflow', locations=locations, timeout=120, resume=True)['jobs'][0]['reused']; assert reused
    attempt = next((directory / 'workflow').glob('report/batch-0/attempt-*')); assert (attempt / 'report.epub.metadata.json').is_file()
    changed = copy.deepcopy(graph); changed['operations'][0]['document']['epub']['language'] = 'en'
    try: workflow.execute(changed, directory / 'workflow', locations=locations, timeout=120, resume=True)
    except SchemaxisError as error: resume_fault = error.fault.code
    else: raise AssertionError('a changed epub language resumed the retained workflow')
    report['lifecycle'] = {'refusedBeforeNative': ['boolean', 'underscore', 'full name', 'integer', 'null', 'unknown cover key'], 'tinyDeadline': timeout_code, 'secondsToFail': failed_after,
                           'cancelled': cancelled, 'workflow': first['status'], 'workflowArtifacts': 4, 'sidecar': True, 'unchangedReused': True, 'changedLanguageResume': resume_fault}


def genuine(paths, report):
    """Genuine earlier retained runs: verify in place and require every byte unchanged; never a rewrite."""
    out = {}
    for path in paths:
        path = Path(path).resolve(); before = tree_digests(path); result = adaptor.verify(path); assert result['verified'], result
        assert tree_digests(path) == before, 'retained evidence was modified'
        summary = adaptor.read(path, 'report-summary.json'); assert 'epub' not in result and 'epub' not in summary and result['artifacts'] == 3, path
        assert not (path / 'report.epub').exists() and 'epub' not in adaptor.read(path, 'authored.json')
        out['/'.join(path.parts[-5:])] = {'verified': True, 'runtime': result['runtime'], 'artifacts': 3, 'evidenceUnchanged': True}
    report['genuineEarlierRuns'] = out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pandoc', required=True, type=Path)
    parser.add_argument('--output-directory', required=True, type=Path)
    parser.add_argument('--genuine-run', action='append', default=[], type=Path, help='retained earlier run directory re-verified read-only (never modified)')
    args = parser.parse_args(); directory = args.output_directory.resolve(); directory.mkdir(parents=True, exist_ok=False)
    pandoc = args.pandoc.resolve(); locations = {'pandoc': str(pandoc)}
    version = probe('version', [str(pandoc), '--version']).decode().splitlines()[0]
    report = {'verified': False, 'runtime': version, 'pandocSha256': hashlib.sha256(pandoc.read_bytes()).hexdigest(), 'startedAtPid': os.getpid(), 'negative': {}}
    try:
        genuine(args.genuine_run, report)
        run = main_acceptance(directory / 'a', locations, report)
        language_matrix(directory / 'b', locations, report)
        budget_report(directory / 'c', locations, report)
        outline_shapes(directory / 'e', locations, report)
        forged(run, report['negative'])
        lifecycle(directory / 'd', locations, report)
        report['verified'] = True
    finally:
        direct = sum('pid' in p for p in PROCESSES); stages = sum('supervisorPid' in p for p in PROCESSES)
        report['processCounts'] = {'directNativeProbesWithNativePid': direct, 'adaptorStageSubmissionsWithSupervisorPid': stages, 'total': len(PROCESSES)}
        report['processes'] = PROCESSES; atomic_json(directory / 'acceptance.json', report)
    print(json.dumps({k: v for k, v in report.items() if k != 'processes'}, indent=2, ensure_ascii=False)); print('native processes recorded:', report['processCounts'])


if __name__ == '__main__': main()
