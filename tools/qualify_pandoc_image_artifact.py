#!/usr/bin/env python3
"""Bounded native acceptance of a typed PNG hand-off from WebP decodeToPng into a Pandoc report image block.

The real libwebp dwebp (no cwebp anywhere in the configuration) decodes committed WebP files into a verified PNG
artifact; the real Pandoc 3.12.1 publishes it as an image block (source ``{"$artifact": "decode", "index": 0}``) in HTML, DOCX
and an optional EPUB 3. Every native launch passes through a logging wrapper that records its PID and arguments before ``exec``.
The proof is independent of the adaptors: this tool reads the PNG samples, the DOCX/EPUB media members (stdlib zipfile) and the
HTML data URI itself and compares them byte for byte with the producer's published PNG, and the pixels with hand-written
literals or a direct dwebp decode. Forged captures, forged media with every ordinary hash refreshed and changed producer
artifacts must be refused. Source-capture trust is unsigned semantic consistency, not signed authenticity. It certifies no Word,
device, reading-system or accessibility rendering, makes no EPUBCheck claim, and never registers a qualification receipt.
"""
import argparse
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import zipfile
import zlib

sys.path.insert(0, str(Path(__file__).resolve().parent))
from qualify_pandoc import refresh, refused  # noqa: E402
from schemaxis import workflow  # noqa: E402
from schemaxis.adaptors.pandoc import adaptor  # noqa: E402
from schemaxis.artifacts import atomic_json  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / 'examples/schemaxis/fixtures/webp'
PROCESSES = []
# Independent literal: the 4x3 RGBA picture inside decode-literal-rgba.webp, including RGB hidden under alpha 0.
LITERAL = [[(255, 0, 0, 255), (0, 255, 0, 255), (0, 0, 255, 255), (255, 255, 255, 255)],
           [(10, 20, 30, 128), (200, 100, 50, 64), (7, 8, 9, 0), (250, 251, 252, 0)],
           [(0, 0, 0, 255), (128, 128, 128, 255), (1, 2, 3, 1), (254, 253, 252, 254)]]
ALT = 'Decoded WebP: four by three picture'
WIDTH_MM = 40


def png_pixels(data):
    """This tool's own reader for IHDR/IDAT/IEND filter-none PNG: (width, height, channels, RGBA bytes)."""
    assert data[:8] == b'\x89PNG\r\n\x1a\n'
    offset, chunks = 8, []
    while offset < len(data):
        length, kind = struct.unpack_from('>I4s', data, offset)
        chunks.append((kind, data[offset + 8:offset + 8 + length]))
        assert zlib.crc32(kind + chunks[-1][1]) == struct.unpack_from('>I', data, offset + 8 + length)[0]
        offset += length + 12
    assert [k for k, _ in chunks] == [b'IHDR', b'IDAT', b'IEND'], [k for k, _ in chunks]
    width, height, depth, colour = struct.unpack('>IIBB', chunks[0][1][:10])
    channels = {2: 3, 6: 4}[colour]
    raw = zlib.decompress(chunks[1][1])
    stride = channels * width
    assert depth == 8 and len(raw) == (stride + 1) * height
    pixels = bytearray()
    for y in range(height):
        row = raw[y * (stride + 1):(y + 1) * (stride + 1)]
        assert row[0] == 0
        for x in range(width):
            pixel = row[1 + x * channels:1 + (x + 1) * channels]
            pixels += pixel + (b'\xff' if channels == 3 else b'')
    return width, height, channels, bytes(pixels)


def read_pam(data):
    head, _, body = data.partition(b'ENDHDR\n')
    fields = dict(line.split(b' ', 1) for line in head.split(b'\n')[1:] if line)
    width, height = int(fields[b'WIDTH']), int(fields[b'HEIGHT'])
    assert len(body) == 4 * width * height
    return width, height, body


def plain_png(width, height):
    """A valid plain RGBA PNG of different content, written here, used as the forgery payload."""
    def chunk(kind, body):
        return struct.pack('>I', len(body)) + kind + body + struct.pack('>I', zlib.crc32(kind + body))
    raw = b''.join(b'\0' + bytes(v for x in range(width) for v in (30 * y, 90 + x, 200 - y, 255)) for y in range(height))
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 6, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(raw)) + chunk(b'IEND', b''))


def wrapper(path, real, log):
    path.write_text('#!/bin/sh\necho "$$ $*" >> %s\nexec %s "$@"\n' % (log, real))
    path.chmod(0o700)
    return str(path)


def launches(log):
    return [dict(zip(('pid', 'arguments'), line.split(' ', 1))) for line in log.read_text().splitlines()] if log.exists() else []


def snapshot(directory):
    """Bytes and modification times of a whole tree."""
    return {str(p.relative_to(directory)): (hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns)
            for p in sorted(directory.rglob('*')) if p.is_file()}


def cli(name, arguments, out, environment, timeout=240):
    process = subprocess.Popen([sys.executable, '-m', 'schemaxis', *arguments], cwd=out, env=environment,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    stdout, stderr = process.communicate(timeout=timeout)
    PROCESSES.append({'name': name, 'pid': process.pid, 'timeoutSeconds': timeout, 'argv': ['python3', '-m', 'schemaxis', *[
        a if not a.startswith('/') else Path(a).name for a in arguments]], 'exitCode': process.returncode})
    return process.returncode, stdout, stderr


def workflow_document(source, epub=None, index=0):
    report = {'version': 'schemaxis.pandoc/1', 'operation': 'report', 'title': 'Decoded image report',
              'sections': [{'heading': 'Image', 'level': 1, 'content': [
                  {'kind': 'image', 'source': {'$artifact': 'decode', 'index': index}, 'alt': ALT, 'widthMm': WIDTH_MM}]}]}
    if epub: report['epub'] = {'language': epub}
    return {'version': 'schemaxis.workflow/1', 'operations': [
        {'id': 'decode', 'document': {'version': 'schemaxis.webp/1', 'operation': 'decodeToPng', 'source': str(source)}},
        {'id': 'report', 'document': report}]}


def producer_png(run):
    return next(Path(run).glob('decode/batch-*/attempt-*/image.png'))


def report_dir(run):
    return next(Path(run).glob('report/batch-*/attempt-*'))


def media(archive, pattern):
    with zipfile.ZipFile(archive) as z:
        return [(n, z.read(n)) for n in z.namelist() if re.search(pattern, n)]


def rewrite_member(archive, name, data):
    buffer = io.BytesIO()
    with zipfile.ZipFile(archive) as old, zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as new:
        if name not in old.namelist():
            raise AssertionError('Expected forged archive member is absent: ' + name)
        for item in old.infolist():
            new.writestr(item, data if item.filename == name else old.read(item.filename))
    Path(archive).write_bytes(buffer.getvalue())


def readback(run, expected_pixels, with_epub):
    """Independent comparison of every published copy with the producer's PNG bytes; returns counted evidence."""
    produced = producer_png(run).read_bytes()
    directory = report_dir(run)
    captured = (directory / 'image-0-0.png').read_bytes()
    assert captured == produced, 'captured PNG differs from the producer PNG'
    width, height, channels, pixels = png_pixels(produced)
    assert pixels == expected_pixels, 'decoded PNG samples differ from the literal'
    captures = json.loads((directory / 'captures.json').read_text())
    assert captures['image-0-0.png']['sha256'] == hashlib.sha256(produced).hexdigest()
    assert (captures['image-0-0.png']['width'], captures['image-0-0.png']['height']) == (width, height)
    html = (directory / 'report.html').read_text()
    uris = re.findall(r'src="data:image/png;base64,([A-Za-z0-9+/=]+)"', html)
    assert len(uris) == 1 and base64.b64decode(uris[0]) == produced, 'HTML data URI differs'
    assert html.count('<img ') == 1 and 'alt="%s"' % ALT in html and 'width:%gmm' % WIDTH_MM in html
    found = media(directory / 'report.docx', r'^word/media/')
    assert len(found) == 1 and found[0][1] == produced, 'DOCX media differs'
    document = zipfile.ZipFile(directory / 'report.docx').read('word/document.xml').decode()
    extent = re.findall(r'<wp:extent cx="(\d+)" cy="(\d+)"', document)
    assert len(extent) == 1 and abs(int(extent[0][0]) - WIDTH_MM * 36000) <= 1
    assert abs(int(extent[0][1]) - round(WIDTH_MM * 36000 * height / width)) <= 1
    assert document.count('descr="%s"' % ALT) == 1
    evidence = {'width': width, 'height': height, 'channels': channels, 'sha256': hashlib.sha256(produced).hexdigest(),
                'htmlDataUris': 1, 'docxMedia': 1, 'docxExtentEmu': [int(extent[0][0]), int(extent[0][1])]}
    if with_epub:
        found = media(directory / 'report.epub', r'^EPUB/media/')
        assert len(found) == 1 and found[0][1] == produced, 'EPUB media differs'
        with zipfile.ZipFile(directory / 'report.epub') as z:
            text = ''.join(z.read(n).decode() for n in z.namelist() if n.endswith('.xhtml'))
        assert text.count('<img ') == 1 and 'alt="%s"' % ALT in text
        evidence['epubMedia'] = 1
    return evidence


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pandoc', type=Path, required=True)
    parser.add_argument('--dwebp', type=Path, required=True)
    parser.add_argument('--output-directory', type=Path, required=True)
    args = parser.parse_args()
    out = args.output_directory.resolve()
    out.mkdir(parents=True, exist_ok=False)
    pandoc, dwebp = str(args.pandoc.resolve()), str(args.dwebp.resolve())
    dwebp_log, pandoc_log = out / 'dwebp-launches.log', out / 'pandoc-launches.log'
    logged_dwebp = wrapper(out / 'dwebp-logged', dwebp, dwebp_log)
    logged_pandoc = wrapper(out / 'pandoc-logged', pandoc, pandoc_log)
    environment = {k: v for k, v in os.environ.items() if not k.startswith('SCHEMAXIS_') and k != 'PATH'}
    environment.update({'PYTHONPATH': str(ROOT / 'src'), 'PATH': '/usr/bin:/bin'})
    locations = {'pandoc': logged_pandoc, 'dwebp': logged_dwebp}
    record = {'cases': {}}
    literal = bytes(v for row in LITERAL for pixel in row for v in pixel)

    # 1. Transparent (hidden RGB) and opaque pictures, with and without the optional EPUB, through the real CLI.
    direct = out / 'opaque.direct.pam'
    probe = subprocess.run([dwebp, str(FIXTURES / 'decode-swatch-rgb.webp'), '-pam', '-o', str(direct)], capture_output=True, timeout=60)
    assert probe.returncode == 0
    PROCESSES.append({'name': 'direct-dwebp-opaque', 'argv': ['dwebp', 'decode-swatch-rgb.webp', '-pam'], 'exitCode': probe.returncode})
    opaque_width, opaque_height, opaque = read_pam(direct.read_bytes())
    cases = (('transparent-epub', 'decode-literal-rgba.webp', 'en', literal), ('transparent', 'decode-literal-rgba.webp', None, literal),
             ('opaque-epub', 'decode-swatch-rgb.webp', 'fr-CA', opaque), ('opaque', 'decode-swatch-rgb.webp', None, opaque))
    for name, fixture, epub, expected in cases:
        run = out / name
        document = out / (name + '.json')
        atomic_json(document, workflow_document(FIXTURES / fixture, epub))
        code, stdout, stderr = cli('run-' + name, ['run', str(document), '--output-directory', str(run), '--dwebp', logged_dwebp, '--pandoc', logged_pandoc],
                                   out, environment)
        assert code == 0, (stdout[-400:], stderr[-400:])
        result = json.loads(stdout)
        report = next(j for j in result['jobs'] if j['operation'] == 'report')
        assert result['verified'] and report['result']['images'] == 1 and report['result']['verified']
        assert report['handoffs'][0]['sha256'] == hashlib.sha256(producer_png(run).read_bytes()).hexdigest()
        assert report['result']['artifacts'] == (4 if epub else 3)
        listing = json.loads((report_dir(run) / 'verification.json').read_text())['artifacts']
        assert [Path(a['file']).name for a in listing] == ['report.html', 'report.docx', 'report-summary.json'] + (['report.epub'] if epub else [])
        evidence = readback(run, expected, bool(epub))
        before = snapshot(run)
        code, _, stderr = cli('verify-' + name, ['verify', str(run)], out, {**environment, 'SCHEMAXIS_PANDOC': pandoc, 'SCHEMAXIS_DWEBP': dwebp})
        assert code == 0, stderr[-400:]
        assert snapshot(run) == before, 'read-only verification changed the tree'
        evidence['readOnlyVerifyTreeUnchanged'] = True
        evidence['pandocRuntime'] = report['result']['runtime']
        record['cases'][name] = evidence
    assert not any('cwebp' in line['arguments'] for line in launches(dwebp_log))

    # Python-API verification below resolves the trusted explicit executables from this process's own environment only.
    os.environ.update({'SCHEMAXIS_PANDOC': pandoc, 'SCHEMAXIS_DWEBP': dwebp})

    # 2. Reuse, modified source and changed producer artifacts, through the Python workflow API.
    source = out / 'source.webp'
    shutil.copyfile(FIXTURES / 'decode-literal-rgba.webp', source)
    graph = workflow_document(source, 'en')
    life = out / 'lifecycle'
    first = workflow.execute(graph, life, locations=locations, timeout=120)
    assert workflow.verify(life)['verified']
    resumed = workflow.execute(graph, life, locations=locations, timeout=120, resume=True)
    assert all(job['reused'] for job in resumed['jobs']), [j['reused'] for j in resumed['jobs']]
    first_png = producer_png(life).read_bytes()
    shutil.copyfile(FIXTURES / 'decode-swatch-rgb.webp', source)
    changed = workflow.execute(graph, life, locations=locations, timeout=120, resume=True)
    assert not any(job['reused'] for job in changed['jobs']), 'modified source reused'
    assert workflow.verify(life)['verified'] and readback(life, opaque, True)['sha256'] != hashlib.sha256(first_png).hexdigest()
    record['lifecycle'] = {'baseline': first['status'], 'unchangedReused': True, 'modifiedSourceReused': False}

    # 3. Forgeries (the originals stay verified): producer artifact, captured copy, DOCX and EPUB media, ordinary hashes refreshed.
    forged = {}
    replacement = plain_png(4, 3)
    adaptor.png(replacement, 'forgery replacement')
    assert replacement != producer_png(life).read_bytes()

    def fresh(label):
        # Each forgery gets its own real run, forged in place: the recorded launcher paths forbid relocating a run.
        run = out / ('forged-' + label)
        workflow.execute(graph, run, locations=locations, timeout=120)
        assert workflow.verify(run)['verified'], 'control: the untouched run verifies'
        return run, report_dir(run)

    graph = workflow_document(FIXTURES / 'decode-literal-rgba.webp', 'en')
    run, directory = fresh('captured-png')
    (directory / 'image-0-0.png').write_bytes(replacement); refresh(directory)
    forged['captured PNG replaced, hashes refreshed'] = refused(lambda: adaptor.verify(directory))['code']
    run, directory = fresh('docx-media')
    rewrite_member(directory / 'report.docx', 'word/media/rId10.png', replacement); refresh(directory)
    forged['DOCX media replaced, hashes refreshed'] = refused(lambda: adaptor.verify(directory))['code']
    run, directory = fresh('epub-media')
    name = media(directory / 'report.epub', r'^EPUB/media/')[0][0]
    rewrite_member(directory / 'report.epub', name, replacement); refresh(directory)
    forged['EPUB media replaced, hashes refreshed'] = refused(lambda: adaptor.verify(directory))['code']
    run, directory = fresh('html-uri')
    html = (directory / 'report.html').read_text()
    (directory / 'report.html').write_text(re.sub(r'base64,[A-Za-z0-9+/=]+', 'base64,' + base64.b64encode(replacement).decode(), html, count=1)); refresh(directory)
    forged['HTML data URI replaced, hashes refreshed'] = refused(lambda: adaptor.verify(directory))['code']
    run, directory = fresh('producer')
    producer_png(run).write_bytes(replacement)
    forged['producer PNG replaced after verification'] = refused(lambda: workflow.verify(run))['code']
    record['forgeries'] = forged

    # 4. Refusals before any Pandoc launch: a text publication (the decode summary) is not a PNG; the original run still verifies.
    refused_runs = {}
    launched = len(launches(pandoc_log))
    document = out / 'summary-as-image.json'
    atomic_json(document, workflow_document(FIXTURES / 'decode-literal-rgba.webp', None, index=1))
    code, stdout, stderr = cli('run-summary-as-image', ['run', str(document), '--output-directory', str(out / 'summary-as-image'),
                                                         '--dwebp', logged_dwebp, '--pandoc', logged_pandoc], out, environment)
    assert code != 0 and b'INVALID_REPORT_IMAGE' in stdout + stderr, (stdout[-300:], stderr[-300:])
    assert len(launches(pandoc_log)) == launched, 'Pandoc launched for a non-PNG hand-off'
    refused_runs['decode summary JSON as image'] = 'INVALID_REPORT_IMAGE'
    record['refusals'] = refused_runs

    # 5. A literal PNG path report is unchanged: the decoded PNG selected by path.
    literal_report = {'version': 'schemaxis.pandoc/1', 'operation': 'report', 'title': 'Literal path',
                      'sections': [{'heading': 'Image', 'level': 1, 'content': [
                          {'kind': 'image', 'source': str(producer_png(out / 'transparent')), 'alt': ALT, 'widthMm': WIDTH_MM}]}]}
    result = adaptor.run(literal_report, out / 'literal-path', executable=logged_pandoc, timeout=120)
    assert result['verified'] and result['images'] == 1
    record['literalPath'] = {'verified': True}

    record['dwebpLaunches'] = launches(dwebp_log)
    record['pandocLaunches'] = launches(pandoc_log)
    record['processes'] = PROCESSES
    record['runtime'] = {'dwebp': subprocess.run([dwebp, '-version'], capture_output=True, text=True).stdout.strip(),
                         'pandoc': subprocess.run([pandoc, '--version'], capture_output=True, text=True).stdout.splitlines()[0]}
    atomic_json(out / 'qualification-record.json', record)
    print(json.dumps({'status': 'passed', 'cases': sorted(record['cases']), 'forgeries': len(forged),
                      'dwebpLaunches': len(record['dwebpLaunches']), 'pandocLaunches': len(record['pandocLaunches'])}, indent=2))


if __name__ == '__main__':
    main()
