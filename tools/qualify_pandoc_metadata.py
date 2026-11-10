#!/usr/bin/env python3
"""Bounded native acceptance of the Pandoc report `metadata` declaration (authors and description in HTML, DOCX and EPUB 3).

Runs the real Pandoc against the multilingual fixture report with a bounded declaration, then reopens each retained publication with string,
regular-expression and zipfile literals only (no adaptor inspector) and compares it with literals written here. Also covers the exact
absent-field controls (byte-identical to the committed earlier fixtures), partial and boundary declarations, refreshed-hash forgeries of every
format and receipt, and the lifecycle. It never registers a qualification receipt, never installs anything and never writes into a retained
run passed with --genuine-run (those are only re-verified, then compared byte for byte). A bounded proof: not EPUBCheck, not Word or a reader.
"""
import argparse
import copy
import hashlib
import html
import io
import json
import os
from pathlib import Path
import re
import sys
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tests/unit'))
from qualify_pandoc import refused, tree_digests  # noqa: E402
from qualify_pandoc_epub import PROCESSES, epub_edit, forgeries, json_edit, native, probe, refresh  # noqa: E402
import pandoc_epub_fixture as earlier  # noqa: E402
import pandoc_metadata_fixture as fx  # noqa: E402
from schemaxis import workflow  # noqa: E402
from schemaxis.adaptors.pandoc import adaptor  # noqa: E402
from schemaxis.artifacts import atomic_json  # noqa: E402
from schemaxis.core.faults import SchemaxisError  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
FILES = ('report.html', 'report.docx', 'reopened.json', 'report.epub', 'epub-reopened.json')
# Independent literals, written here and not derived from the adaptor or the fixture builder.
HTML_META = ['<meta name="author" content="Zoë Müller" />', '<meta name="author" content="李雷 (Li Lei)" />',
             '<meta name="author" content="Rob &amp; &lt;b&gt; &quot;Q&quot; O&#39;Neil" />',
             '<meta name="description" content="Résumé des mesures — 校准 &amp; &lt;test&gt; &quot;quoted&quot; &#39;single&#39;; العربية." />']
HTML_BLOCK = ['<p class="author">Zoë Müller</p>', '<p class="author">李雷 (Li Lei)</p>', '<p class="author">Rob &amp; &lt;b&gt; &quot;Q&quot; O&#39;Neil</p>']
CREATOR = 'Zoë Müller; 李雷 (Li Lei); Rob & <b> "Q" O\'Neil'
DESCRIPTION = 'Résumé des mesures — 校准 & <test> "quoted" \'single\'; العربية.'


def literal_html(path, authors, description, report):
    text = path.read_text(encoding='utf-8')
    metas = re.findall(r'<meta name="(author|description)" content="([^"]*)" />', text)
    assert [(n, html.unescape(c)) for n, c in metas] == [*[('author', a) for a in authors], *([('description', description)] if description else [])], metas
    header = re.search(r'<header id="title-block-header">(.*?)</header>', text, re.S)[1]
    assert [html.unescape(a) for a in re.findall(r'<p class="author">(.*?)</p>', header)] == authors
    # The description is metadata only: no visible element of the body is the description text.
    visible = [html.unescape(t) for t in re.findall(r'<(?:p|h\d|td|th)[^>]*>(.*?)</(?:p|h\d|td|th)>', text.split('<body>')[1], re.S)]
    assert description is None or description not in visible, 'the description is visible in the body'
    report['html'] = {'metaElements': len(metas), 'visibleAuthorLines': len(authors), 'descriptionVisibleInBody': False}


def literal_docx(path, authors, description, report):
    with zipfile.ZipFile(path) as archive:
        core = archive.read('docProps/core.xml').decode(); document = archive.read('word/document.xml').decode()
    creator = html.unescape(re.search(r'<dc:creator>(.*?)</dc:creator>', core)[1]); found = re.search(r'<dc:description>(.*?)</dc:description>', core)
    assert creator == '; '.join(authors) and (html.unescape(found[1]) if found else None) == (description or None), (creator, found)
    styles = re.findall(r'<w:pStyle w:val="(\w+)" />', document)
    assert styles[:1 + len(authors)] == ['Title', *['Author'] * len(authors)] and styles.count('Author') == len(authors), styles
    report['docx'] = {'creator': creator, 'description': bool(found), 'authorParagraphs': len(authors)}


def literal_epub(path, authors, description, report):
    with zipfile.ZipFile(path) as archive:
        opf = archive.read('EPUB/content.opf').decode(); page = archive.read('EPUB/text/title_page.xhtml').decode()
    creators = re.findall(r'<dc:creator id="epub-creator-(\d+)">(.*?)</dc:creator>', opf)
    assert [(int(n), html.unescape(a)) for n, a in creators] == list(enumerate(authors, 1)), creators
    assert re.findall(r'<meta refines="#epub-creator-(\d+)" property="role" scheme="marc:relators">(\w+)</meta>', opf) == [(str(n), 'aut') for n in range(1, len(authors) + 1)]
    found = re.findall(r'<dc:description>(.*?)</dc:description>', opf); assert [html.unescape(d) for d in found] == ([description] if description else [])
    assert [html.unescape(a) for a in re.findall(r'<p class="author">(.*?)</p>', page)] == authors
    report['epub'] = {'creators': len(creators), 'roles': 'aut', 'description': bool(found), 'titlePageAuthorLines': len(authors)}


def literals(run, authors, description, report):
    report.clear(); literal_html(run / 'report.html', authors, description, report); literal_docx(run / 'report.docx', authors, description, report)
    if (run / 'report.epub').exists(): literal_epub(run / 'report.epub', authors, description, report)
    return report


def main_acceptance(directory, locations, report):
    directory.mkdir(parents=True); source = directory / 'source'; source.mkdir()
    run = directory / 'metadata'; result = native(fx.document(source), run, locations)
    assert result['artifacts'] == 4 and result['metadata'] == {'authors': 3, 'description': True, 'characters': sum(map(len, fx.AUTHORS)) + len(fx.DESCRIPTION), 'formats': ['html', 'docx', 'epub']}, result
    report['literals'] = literals(run, fx.AUTHORS, fx.DESCRIPTION, {})
    for name in FILES: assert (run / name).read_bytes() == (fx.FIXTURE / name).read_bytes(), f'{name} differs from the committed genuine fixture'
    assert adaptor.read(run, 'captures.json')['metadata'] == adaptor.metadata_capture(fx.metadata()) and adaptor.read(run, 'report-summary.json')['metadata']['formats'] == ['html', 'docx', 'epub']
    report['fixtureMatchesNativeOutput'] = True
    # The earlier fixture (no metadata) is what Pandoc still writes byte for byte when the field is absent, and its run carries no metadata member anywhere.
    plain = directory / 'plain'; plain_source = directory / 'plain-source'; plain_source.mkdir(); plain_result = native(earlier.document(plain_source), plain, locations)
    assert 'metadata' not in plain_result and 'metadata' not in adaptor.read(plain, 'captures.json') and 'metadata' not in adaptor.read(plain, 'report-summary.json') and 'metadata' not in adaptor.read(plain, 'plan.json')
    for name in FILES: assert (plain / name).read_bytes() == (earlier.FIXTURE / name).read_bytes(), f'absent-field {name} differs from the committed earlier fixture'
    for name in ('report.html', 'report.docx'): assert b'class="author"' not in (plain / name).read_bytes() and b'Author' not in (plain / name).read_bytes()
    report['absentField'] = {'artifacts': 3 + 1, 'outputsIdenticalToEarlierFixture': list(FILES), 'planCaptureSummaryHaveNoMetadata': True}
    # A changed declaration changes plan, capture and every format (author order, a name, the description).
    changed = {}
    for label, edit in (('reordered', lambda m: m['authors'].reverse()), ('renamed', lambda m: m['authors'].__setitem__(0, 'Zoë Müllers')), ('description', lambda m: m.update(description=m['description'] + '!'))):
        value = fx.metadata(); edit(value); document = fx.document(source, value); out = directory / f'changed-{label}'; native(document, out, locations)
        changed[label] = {'plan': adaptor.read(out, 'plan.json') != adaptor.read(run, 'plan.json'), 'capture': adaptor.read(out, 'captures.json')['metadata'] != adaptor.read(run, 'captures.json')['metadata'],
                          'formats': [n for n in ('report.html', 'report.docx', 'report.epub') if (out / n).read_bytes() != (run / n).read_bytes()]}
        assert changed[label]['plan'] and changed[label]['capture'] and changed[label]['formats'] == ['report.html', 'report.docx', 'report.epub'], (label, changed[label])
        literals(out, value['authors'], value['description'], {})
    report['changedDeclaration'] = changed
    return run


def matrix(directory, locations, report):
    """Partial, single, boundary and Unicode declarations, each through the real writers, readers and inspectors, with and without an EPUB."""
    directory.mkdir(parents=True); source = directory / 'source'; source.mkdir(); rows = {}
    cases = {'authors-only': {'authors': ['A. Example', 'B. Auteur']}, 'description-only': {'description': 'Summary & <notes>.'}, 'single-author': {'authors': ['Solo']},
             'eight-authors': {'authors': [f'Author {n}' for n in range(1, 9)], 'description': 'x'}, 'longest-author': {'authors': ['a' * 100]},
             'longest-description': {'description': ' '.join(['wörd'] * 199) + ' wörd'[:5]}, 'unicode': {'authors': ['José Ångström', 'François Œuvre', 'محمد'], 'description': 'Ünïcödé — 日本語 🙂 "q" \'s\''}}
    assert len(cases['longest-description']['description']) <= 1000
    for label, declared in cases.items():
        for with_epub in (True, False):
            document = fx.document(source, declared, fx.fx.LANGUAGE if with_epub else None); out = directory / f'{label}-{"epub" if with_epub else "plain"}'
            result = native(document, out, locations); assert result['metadata']['formats'] == ['html', 'docx', *(['epub'] if with_epub else [])]
            literals(out, declared.get('authors', []), declared.get('description'), {})
            rows[f'{label}/{"epub" if with_epub else "plain"}'] = {'artifacts': result['artifacts']}
    report['matrix'] = rows


def docx_edit(run, pattern, repl, member='docProps/core.xml', count=1):
    def action():
        path = run / 'report.docx'
        with zipfile.ZipFile(path) as old: items = [(i, old.read(i.filename)) for i in old.infolist()]
        buffer = io.BytesIO(); found = 0
        with zipfile.ZipFile(buffer, 'w') as new:
            for info, data in items:
                if info.filename == member: data, n = re.subn(pattern, repl, data.decode(), count=count); found += n; data = data.encode()
                new.writestr(info, data)
        assert found, (member, pattern); path.write_bytes(buffer.getvalue())
    return action


def text_edit(run, name, pattern, repl):
    def action():
        text, n = re.subn(pattern, repl, (run / name).read_text(encoding='utf-8'), count=1); assert n, (name, pattern); (run / name).write_text(text, encoding='utf-8')
    return action


def forged(run, plain, report):
    opf, page = 'EPUB/content.opf', 'EPUB/text/title_page.xhtml'
    def epub_regex(member, pattern, repl):
        def change(members):
            out = []; found = 0
            for name, body in members:
                if name == member: body, n = re.subn(pattern.encode(), repl.encode(), body, count=1); found += n
                out.append((name, body))
            assert found, (member, pattern); return out
        return change
    def meta(name, mutate): return json_edit(run, name, mutate)
    probes = [
        ('htmlAuthorMetaRemoved', text_edit(run, 'report.html', r'  <meta name="author" content="Zoë Müller" />\n', ''), 'HTML author/description metadata differs'),
        ('htmlAuthorMetaStale', text_edit(run, 'report.html', r'content="李雷 \(Li Lei\)"', 'content="李雷"'), 'HTML author/description metadata differs'),
        ('htmlAuthorMetaReordered', text_edit(run, 'report.html', r'(  <meta name="author" content="Zoë Müller" />\n)(  <meta name="author" content="李雷 \(Li Lei\)" />\n)', r'\2\1'), 'HTML author/description metadata differs'),
        ('htmlDescriptionRemoved', text_edit(run, 'report.html', r'  <meta name="description" content="[^"]*" />\n', ''), 'HTML author/description metadata differs'),
        ('htmlDescriptionStale', text_edit(run, 'report.html', r'content="Résumé', 'content="Resume'), 'HTML author/description metadata differs'),
        ('htmlExtraAuthorMeta', text_edit(run, 'report.html', r'(  <meta name="description")', '  <meta name="author" content="Mallory" />\n\\1'), 'HTML author/description metadata differs'),
        ('htmlVisibleAuthorRemoved', text_edit(run, 'report.html', r'<p class="author">Zoë Müller</p>\n', ''), 'HTML title block differs'),
        ('htmlVisibleAuthorForged', text_edit(run, 'report.html', r'<p class="author">Zoë Müller</p>', '<p class="author">Mallory</p>'), 'HTML visible author list differs'),
        ('htmlAuthorLineRestyled', text_edit(run, 'report.html', r'<p class="author">Zoë Müller</p>', '<p class="author" style="display:none">Zoë Müller</p>'), 'unexpected HTML content/attribute'),
        ('htmlAuthorLineWithLink', text_edit(run, 'report.html', r'<p class="author">Zoë Müller</p>', '<p class="author"><a href="https://example.test">Zoë Müller</a></p>'), 'HTML'),
        ('docxCreatorStale', docx_edit(run, r'<dc:creator>Zoë Müller', '<dc:creator>Zoe Muller'), 'DOCX core properties differ'),
        ('docxCreatorSemicolonSplit', docx_edit(run, r'; 李雷', ';李雷'), 'DOCX core properties differ'),
        ('docxCreatorEmpty', docx_edit(run, r'<dc:creator>[^<]*</dc:creator>', '<dc:creator></dc:creator>'), 'DOCX core properties differ'),
        ('docxDescriptionRemoved', docx_edit(run, r'<dc:description>[^<]*</dc:description>', ''), 'DOCX core properties differ'),
        ('docxDescriptionStale', docx_edit(run, r'<dc:description>Résumé', '<dc:description>Resume'), 'DOCX core properties differ'),
        ('docxKeywordsInjected', docx_edit(run, r'<cp:keywords></cp:keywords>', '<cp:keywords>secret</cp:keywords>'), 'DOCX core properties differ'),
        ('docxAuthorParagraphRemoved', docx_edit(run, r'<w:p>\s*<w:pPr>\s*<w:pStyle w:val="Author" />\s*</w:pPr>\s*<w:r><w:t xml:space="preserve">Zoë Müller</w:t></w:r>\s*</w:p>', '', 'word/document.xml'), 'DOCX visible author list differs'),
        ('docxAuthorParagraphForged', docx_edit(run, r'(<w:pStyle w:val="Author" />\s*</w:pPr>\s*<w:r><w:t xml:space="preserve">)Zoë Müller', r'\1Mallory', 'word/document.xml'), 'DOCX visible author list differs'),
        ('docxAuthorStyleDemoted', docx_edit(run, r'w:val="Author"', 'w:val="BodyText"', 'word/document.xml'), 'DOCX'),
        ('readbackAuthorForged', meta('reopened.json', lambda v: v['meta']['author']['c'][0]['c'].__setitem__(0, {'t': 'Str', 'c': 'Mallory'})), 'DOCX native readback authors differ'),
        ('readbackAuthorDropped', meta('reopened.json', lambda v: v['meta'].pop('author')), 'DOCX native readback metadata differs'),
        ('readbackDescriptionInjected', meta('reopened.json', lambda v: v['meta'].update(description={'t': 'MetaInlines', 'c': [{'t': 'Str', 'c': 'x'}]})), 'DOCX native readback metadata differs'),
        ('epubCreatorStale', epub_edit(run, epub_regex(opf, '>Zoë Müller</dc:creator>', '>Zoe Muller</dc:creator>')), 'EPUB'),
        ('epubCreatorReordered', epub_edit(run, epub_regex(opf, r'(    <dc:creator id="epub-creator-1">[^\n]*\n[^\n]*\n)(    <dc:creator id="epub-creator-2">[^\n]*\n[^\n]*\n)', r'\2\1')), 'EPUB'),
        ('epubCreatorRoleChanged', epub_edit(run, epub_regex(opf, '>aut</meta>', '>edt</meta>')), 'EPUB'),
        ('epubDescriptionRemoved', epub_edit(run, epub_regex(opf, r'    <dc:description>[^\n]*\n', '')), 'EPUB'),
        ('epubDescriptionStale', epub_edit(run, epub_regex(opf, '<dc:description>Résumé', '<dc:description>Resume')), 'EPUB'),
        ('epubTitlePageAuthorRemoved', epub_edit(run, epub_regex(page, r'  <p class="author">Zoë Müller</p>\n', '')), 'EPUB'),
        ('epubTitlePageAuthorForged', epub_edit(run, epub_regex(page, r'>Zoë Müller</p>', '>Mallory</p>')), 'EPUB'),
        ('epubTitlePageLink', epub_edit(run, epub_regex(page, r'<p class="author">Zoë Müller</p>', '<p class="author"><a href="https://example.test">Zoë Müller</a></p>')), 'EPUB'),
        ('epubReadbackOrderNotReversed', meta('epub-reopened.json', lambda v: v['meta']['author']['c'].reverse()), 'native EPUB readback authors differ'),
        ('epubReadbackDescriptionForged', meta('epub-reopened.json', lambda v: v['meta']['description']['c'].__setitem__(0, {'t': 'Str', 'c': 'x'})), 'native EPUB readback description differs'),
        ('epubReadbackAuthorDropped', meta('epub-reopened.json', lambda v: v['meta'].pop('author')), 'native EPUB readback metadata differs'),
        ('captureForged', meta('captures.json', lambda v: v['metadata']['authors'].__setitem__(0, 'Mallory')), 'captured metadata record differs'),
        ('captureRemoved', meta('captures.json', lambda v: v.pop('metadata')), 'capture membership differs'),
        ('captureDigestForged', meta('captures.json', lambda v: v['metadata'].update(sha256='0' * 64)), 'captured metadata record differs'),
        ('summaryForged', meta('report-summary.json', lambda v: v['metadata'].update(authors=2)), 'report summary differs'),
        ('summaryRemoved', meta('report-summary.json', lambda v: v.pop('metadata')), 'report summary differs'),
        ('authoredChanged', meta('authored.json', lambda v: v['metadata']['authors'].reverse()), 'effective report plan differs'),
        ('planMetadataRemoved', meta('plan.json', lambda v: v.pop('metadata')), 'effective report plan differs'),
        ('authoredSemicolonAuthor', meta('authored.json', lambda v: v['metadata']['authors'].__setitem__(0, 'A;B')), 'semicolon')]
    probes = [p for p in probes if p[0] != 'authoredSemicolonAuthor']  # refresh() re-plans authored.json, which the semicolon rule rejects before verify; covered by the host test
    forgeries(run, probes, report)
    # An absent declaration refuses injected metadata in every format of an otherwise genuine earlier-style run.
    injected = [('legacyHtmlAuthorMeta', text_edit(plain, 'report.html', r'(  <title>)', '  <meta name="author" content="Mallory" />\n\\1'), 'HTML author/description metadata differs'),
                ('legacyHtmlDescriptionMeta', text_edit(plain, 'report.html', r'(  <title>)', '  <meta name="description" content="x" />\n\\1'), 'HTML author/description metadata differs'),
                ('legacyDocxCreator', docx_edit(plain, r'<dc:creator></dc:creator>', '<dc:creator>Mallory</dc:creator>'), 'DOCX core properties differ'),
                ('legacyDocxDescription', docx_edit(plain, r'(<dc:creator></dc:creator>)', r'\1<dc:description>x</dc:description>'), 'DOCX core properties differ'),
                ('legacyEpubCreator', epub_edit(plain, lambda m: [(n, b.replace(b'    <meta property="dcterms:modified"', b'    <dc:creator id="epub-creator-1">Mallory</dc:creator>\n    <meta property="dcterms:modified"') if n == opf else b) for n, b in m]), 'EPUB'),
                ('legacyCapture', json_edit(plain, 'captures.json', lambda v: v.update(metadata={'authors': ['x']})), 'capture membership differs'),
                ('legacySummary', json_edit(plain, 'report-summary.json', lambda v: v.update(metadata={'authors': 1})), 'report summary differs')]
    forgeries(plain, injected, report)


def lifecycle(directory, locations, report):
    directory.mkdir(parents=True); exe = locations['pandoc']; source = directory / 'source'; source.mkdir(); refused_cases = {}
    bad = {'boolean-authors': {'authors': True}, 'string-authors': {'authors': 'A'}, 'boolean-author': {'authors': [True]}, 'number-description': {'description': 1}, 'empty-object': {},
           'unknown-key': {'authors': ['A'], 'keywords': ['x']}, 'semicolon': {'authors': ['A; B']}, 'duplicate': {'authors': ['A', 'A']}, 'newline': {'description': 'a\nb'},
           'nine-authors': {'authors': [f'a{n}' for n in range(9)]}, 'long-author': {'authors': ['a' * 101]}, 'long-description': {'description': 'a' * 1001}, 'bidi': {'authors': ['a‮b']}}
    for label, value in bad.items():
        document = fx.document(source, value); target = directory / f'refused-{label}'
        try: adaptor.run(document, target, executable=exe, timeout=60)
        except SchemaxisError as error: refused_cases[label] = {'code': error.fault.code, 'location': error.fault.location}
        else: raise AssertionError(f'{label} was accepted')
        assert not target.exists(), label
    document = fx.document(source); graph = {'version': 'schemaxis.workflow/1', 'operations': [{'id': 'report', 'document': document}]}
    first = workflow.execute(graph, directory / 'workflow', locations=locations, timeout=120); verified = workflow.verify(directory / 'workflow'); assert verified['verified'] and verified['artifacts'] == 4, verified
    assert workflow.execute(graph, directory / 'workflow', locations=locations, timeout=120, resume=True)['jobs'][0]['reused']
    changed = copy.deepcopy(graph); changed['operations'][0]['document']['metadata']['authors'].reverse()
    try: workflow.execute(changed, directory / 'workflow', locations=locations, timeout=120, resume=True)
    except SchemaxisError as error: resume_fault = error.fault.code
    else: raise AssertionError('changed metadata resumed the retained workflow')
    report['lifecycle'] = {'refusedBeforeNative': refused_cases, 'workflow': first['status'], 'workflowArtifacts': 4, 'unchangedReused': True, 'changedMetadataResume': resume_fault}


def genuine(paths, report):
    """Genuine earlier retained runs: verify in place and require every byte unchanged; never a rewrite."""
    out = {}
    for path in paths:
        path = Path(path).resolve(); before = tree_digests(path); result = adaptor.verify(path); assert result['verified'], result
        assert tree_digests(path) == before and 'metadata' not in result and 'metadata' not in adaptor.read(path, 'captures.json'), path
        out['/'.join(path.parts[-5:])] = {'verified': True, 'runtime': result['runtime'], 'artifacts': result['artifacts'], 'evidenceUnchanged': True}
    report['genuineEarlierRuns'] = out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pandoc', required=True, type=Path)
    parser.add_argument('--output-directory', required=True, type=Path)
    parser.add_argument('--genuine-run', action='append', default=[], type=Path, help='retained earlier run directory re-verified read-only (never modified)')
    args = parser.parse_args(); directory = args.output_directory.resolve(); directory.mkdir(parents=True, exist_ok=False)
    pandoc = args.pandoc.resolve(); locations = {'pandoc': str(pandoc)}
    version = probe('version', [str(pandoc), '--version']).decode().splitlines()[0]
    report = {'verified': False, 'runtime': version, 'pandocSha256': hashlib.sha256(pandoc.read_bytes()).hexdigest(), 'negative': {}}
    try:
        genuine(args.genuine_run, report)
        run = main_acceptance(directory / 'a', locations, report)
        plain = directory / 'a' / 'plain'
        matrix(directory / 'b', locations, report)
        forged(run, plain, report['negative'])
        lifecycle(directory / 'd', locations, report)
        report['verified'] = True
    finally:
        report['processCounts'] = {'directNativeProbesWithNativePid': sum('pid' in p for p in PROCESSES), 'adaptorStageSubmissionsWithSupervisorPid': sum('supervisorPid' in p for p in PROCESSES), 'total': len(PROCESSES)}
        report['processes'] = PROCESSES; atomic_json(directory / 'acceptance.json', report)
    print(json.dumps({k: v for k, v in report.items() if k != 'processes'}, indent=2, ensure_ascii=False)); print('native processes recorded:', report['processCounts'])


if __name__ == '__main__': main()
