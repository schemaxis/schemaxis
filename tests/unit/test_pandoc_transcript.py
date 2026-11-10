"""Transcript/caption publication through the closed Pandoc report: planning, table semantics and forged readback."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from schemaxis.adaptors.pandoc import adaptor
from schemaxis.adaptors.pandoc.inspection import ast_report, html_report
from schemaxis.core.faults import SchemaxisError

sys.path.insert(0, str(Path(__file__).parent))
import pandoc_docx_fixture as fixture  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
COLUMNS = ['Start (ms)', 'End (ms)', 'Text']
ROWS = [['0', '1250', 'Hello, world.'], ['1250', '3000', 'a < b & c > d']]
MODEL = [{'kind': 'heading', 'level': 1, 'text': 'Transcript'},
         {'kind': 'paragraph', 'text': 'Timestamps are in milliseconds.'},
         {'kind': 'table', 'rows': [COLUMNS, *ROWS]}]
STYLE = 'p {margin: 0}'


def html(head=None, body=None):
    def cells(tag, values): return ''.join('<%s>%s</%s>' % (tag, v, tag) for v in values)
    head = head or ('<thead><tr>' + cells('th', COLUMNS) + '</tr></thead>')
    body = body or ('<tbody>' + ''.join('<tr>' + cells('td', [escape(v) for v in r]) + '</tr>' for r in ROWS) + '</tbody>')
    return ('<!DOCTYPE html>\n<html><head><title>Report</title><style>' + STYLE + '</style></head><body>'
            '<header><h1>Report</h1></header><h1>Transcript</h1><p>Timestamps are in milliseconds.</p><table>' + head + body + '</table></body></html>')


def escape(value): return value.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def cell(text, extra=''):
    return '<w:tc><w:tcPr/><w:p><w:pPr><w:pStyle w:val="Compact"/></w:pPr><w:r><w:t xml:space="preserve">%s</w:t></w:r>%s</w:p></w:tc>' % (escape(text), extra)


def row(values, header=False):
    return '<w:tr>' + ('<w:trPr><w:tblHeader w:val="on"/></w:trPr>' if header else '') + ''.join(cell(v) for v in values) + '</w:tr>'


def table(rows=None, grid=3):
    rows = rows or [row(COLUMNS, True), *[row(r) for r in ROWS]]
    return '<w:tbl><w:tblPr/><w:tblGrid>' + '<w:gridCol w:w="1"/>' * grid + '</w:tblGrid>' + ''.join(rows) + '</w:tbl>'


def docx(body_table=None, extra=None):
    document = ('<w:p><w:pPr><w:pStyle w:val="Title"/></w:pPr><w:r><w:t>Report</w:t></w:r></w:p>'
                '<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>Transcript</w:t></w:r></w:p>'
                '<w:p><w:r><w:t>Timestamps are in milliseconds.</w:t></w:r></w:p>%s<w:p/><w:sectPr/>' % (body_table or table()))
    return fixture.build(document, change=extra)


def transcript(rows=None, **table_fields):
    return {'version': adaptor.VERSION, 'operation': 'report', 'title': 'Meeting transcript', 'sections': [
        {'heading': 'Transcript', 'content': [{'kind': 'paragraph', 'text': 'Timestamps are in milliseconds.'},
            {'kind': 'table', 'columns': COLUMNS, 'rows': ROWS if rows is None else rows, **table_fields}]}]}


class TranscriptPlanning(unittest.TestCase):
    def fault(self, document, code, location=None):
        with self.assertRaises(SchemaxisError) as caught: adaptor.plan(document)
        self.assertEqual(caught.exception.fault.code, code)
        if location: self.assertEqual(caught.exception.fault.location, location)

    def test_shipped_example_is_a_valid_literal_millisecond_transcript(self):
        document = json.loads((ROOT/'examples/schemaxis/pandoc-transcript.json').read_text())
        plan = adaptor.plan(document)
        table = next(b for s in plan['sections'] for b in s['content'] if b['kind'] == 'table')
        self.assertEqual(table['columns'][:2], ['Start (ms)', 'End (ms)'])
        for start, end, *_ in table['rows']:
            self.assertTrue(start.isascii() and start.isdigit() and end.isascii() and end.isdigit() and int(start) <= int(end))
        self.assertIn(['1250', '3000'], [r[:2] for r in table['rows']])

    def test_timestamps_stay_literal_text(self):
        plan = adaptor.plan(transcript([['0', '1250', 'x'], ['007', '1.50', '1e3']]))
        self.assertEqual(plan['sections'][0]['content'][1]['rows'][1][:3], ['007', '1.50', '1e3'])

    def test_multiline_control_and_whitespace_text_is_refused_with_location(self):
        for label, text in {'newline': 'two\nlines', 'carriage return': 'a\rb', 'tab': 'a\tb', 'NUL': 'a\x00b', 'escape': 'a\x1bb',
                            'C1 control': 'a\x85b', 'line separator': 'a b', 'paragraph separator': 'a b',
                            'non-breaking space': 'a b', 'ideographic space': 'a　b', 'double space': 'a  b',
                            'trailing space': 'a ', 'lone surrogate': 'a\ud800b'}.items():
            with self.subTest(label): self.fault(transcript([['0', '1', text]]), 'INVALID_REPORT_TEXT', '$.sections[0].content[1].cells[1][2]')

    def test_unsupported_formatting_characters_are_refused(self):
        hostile = {'right-to-left override': '\u202e', 'left-to-right embedding': '\u202a', 'pop directional formatting': '\u202c',
                   'right-to-left isolate': '\u2067', 'pop directional isolate': '\u2069', 'word joiner': '\u2060',
                   'byte order mark': '\ufeff', 'invisible separator': '\u2063', 'interlinear annotation': '\ufff9',
                   'stray tag character': '\U000e0041', 'language tag': '\U000e0001', 'noncharacter': '\ufdd0',
                   'astral noncharacter': '\U0001fffe', 'mongolian vowel separator': '\u180e',
                   'zero-width space in Latin text': 'a\u200bb', 'zero-width space in Hebrew': '\u05e9\u200b\u05dc',
                   'leading zero-width space': '\u200b\u0e01', 'trailing zero-width space': '\u0e01\u200b',
                   'doubled zero-width space': '\u0e01\u200b\u200b\u0e02', 'zero-width space beside a space': '\u0e01\u200b \u0e02'}
        for label, character in hostile.items():
            text = character if len(character) > 1 else 'safe' + character + 'text'
            with self.subTest(label): self.fault(transcript([['0', '1', text]]), 'INVALID_REPORT_TEXT', '$.sections[0].content[1].cells[1][2]')

    def test_malformed_emoji_tag_sequences_are_refused(self):
        flag = '\U0001f3f4' + ''.join(chr(0xe0000 + ord(c)) for c in 'gbeng') + '\U000e007f'
        for label, text in {'missing cancel tag': flag[:-1], 'tags without the black flag': flag[1:], 'tags after another emoji': '\U0001f600' + flag[1:],
                            'too few tags': '\U0001f3f4\U000e0067\U000e007f', 'uppercase tag letter': flag.replace('\U000e0067', '\U000e0047'),
                            'trailing stray tag': flag + '\U000e0041'}.items():
            with self.subTest(label): self.fault(transcript([['0', '1', text]]), 'INVALID_REPORT_TEXT')

    def test_legitimate_multilingual_dialogue_is_accepted(self):
        flags = ''.join('\U0001f3f4' + ''.join(chr(0xe0000 + ord(c)) for c in code) + '\U000e007f' for code in ('gbeng', 'gbsct', 'gbwls'))
        for text in ['Bonjour, ça va ? Très bien.', 'こんにちは世界', 'שלום\u200f עולם', 'ab \u05e9\u05dc\u05d5\u05dd\u200e cd', 'سلام\u200c دنیا', 'می\u200cخواهم', 'عربي\u061c abc',
                     'नमस्ते', 'क्\u200dष', '👩\u200d🔬 says hi', 'England ' + flags, 'สวัสดี\u200bครับ', 'សួស្តី\u200bអ្នក', 'မင်္ဂလာ\u200bပါ', 'a < b & c > d']:
            with self.subTest(text): adaptor.plan(transcript([['0', '1', text]]))

    def test_ragged_and_oversized_transcripts_are_refused(self):
        self.fault(transcript([['0', '1']]), 'INVALID_REPORT_TABLE')
        self.fault(transcript([['0', '1', 'x']] * 65), 'INVALID_ARGUMENT')


class TranscriptTableSemantics(unittest.TestCase):
    def refused(self, action, fragment=None):
        with self.assertRaises(SchemaxisError) as caught: action()
        self.assertEqual(caught.exception.fault.code, 'VERIFICATION_FAILED')
        if fragment: self.assertIn(fragment, caught.exception.fault.message)

    def html(self, source, model=None):
        approved = hashlib.sha256(STYLE.encode()).hexdigest()
        with patch('schemaxis.adaptors.pandoc.inspection.QUALIFIED_STYLESHEET_SHA256', approved):
            html_report(source, 'Report', model or MODEL)

    def docx(self, data, model=None): fixture.check(data, 'Report', model or MODEL)

    def test_reference_shapes_are_accepted(self):
        self.html(html()); self.docx(docx())

    def test_html_header_row_semantics(self):
        body = ''.join('<tr>' + ''.join('<td>%s</td>' % escape(v) for v in r) + '</tr>' for r in [COLUMNS, *ROWS])
        for label, source in {
                'header demoted to body': html('<thead></thead>', '<tbody>' + body + '</tbody>'),
                'no header group': html('', '<tbody>' + body + '</tbody>'),
                'header cells are data cells': html('<thead><tr>' + ''.join('<td>%s</td>' % v for v in COLUMNS) + '</tr></thead>'),
                'body cells are header cells': html(body=('<tbody><tr><th>0</th><th>1250</th><th>Hello, world.</th></tr>'
                                                          '<tr><th>1250</th><th>3000</th><th>a &lt; b &amp; c &gt; d</th></tr></tbody>')),
                'two header rows': html('<thead><tr>' + ''.join('<th>%s</th>' % v for v in COLUMNS) + '</tr><tr><th>0</th><th>1250</th><th>Hello, world.</th></tr></thead>',
                                        '<tbody><tr><td>1250</td><td>3000</td><td>a &lt; b &amp; c &gt; d</td></tr></tbody>'),
                'nested element in cell': html(body=('<tbody><tr><td>0</td><td>1250</td><td>Hello, world.<img src="data:image/png;base64,AA=="></td></tr>'
                                                     '<tr><td>1250</td><td>3000</td><td>a &lt; b &amp; c &gt; d</td></tr></tbody>')),
                'paragraph in cell': html(body=('<tbody><tr><td>0</td><td>1250</td><td><p>Hello, world.</p></td></tr>'
                                                '<tr><td>1250</td><td>3000</td><td>a &lt; b &amp; c &gt; d</td></tr></tbody>')),
                'nested table': html(body=('<tbody><tr><td>0</td><td>1250</td><td><table><tbody><tr><td>Hello, world.</td></tr></tbody></table></td></tr>'
                                           '<tr><td>1250</td><td>3000</td><td>a &lt; b &amp; c &gt; d</td></tr></tbody>'))}.items():
            with self.subTest(label): self.refused(lambda: self.html(source))

    def test_html_text_is_compared_exactly_not_after_whitespace_normalisation(self):
        for label, old, new in [('doubled space', '<p>Timestamps are', '<p>Timestamps  are'), ('non-breaking space', 'Timestamps are', 'Timestamps are'),
                                ('leading newline', '<p>Timestamps', '<p>\nTimestamps'), ('heading newline', '<h1>Transcript', '<h1>Trans\ncript')]:
            with self.subTest(label): self.refused(lambda: self.html(html().replace(old, new, 1)))

    def test_html_forged_cells_and_order(self):
        for label, source in {'timestamp changed': html().replace('<td>1250</td>', '<td>1260</td>', 1),
                              'unit label changed': html().replace('Start (ms)', 'Start (s)'),
                              'columns swapped': html().replace('<th>Start (ms)</th><th>End (ms)</th>', '<th>End (ms)</th><th>Start (ms)</th>'),
                              'row dropped': html().replace('<tr><td>1250</td><td>3000</td><td>a &lt; b &amp; c &gt; d</td></tr>', ''),
                              'text escaped differently': html().replace('a &lt; b', 'a <b>b</b'),
                              'zero-width inserted': html().replace('Hello', 'Hel​lo')}.items():
            with self.subTest(label): self.refused(lambda: self.html(source))

    def test_docx_header_row_and_cell_structure(self):
        header_missing = [row(COLUMNS), *[row(r) for r in ROWS]]
        header_on_body = [row(COLUMNS, True), row(ROWS[0], True), row(ROWS[1])]
        grid = table(grid=2)
        two_paragraphs = table([row(COLUMNS, True), row(ROWS[0]).replace('Hello, world.</w:t></w:r></w:p>', 'Hello,</w:t></w:r></w:p><w:p><w:r><w:t> world.</w:t></w:r></w:p>'),
                                row(ROWS[1])])
        for label, data in {
                'header flag absent': docx(table(header_missing)),
                'header flag on a body row': docx(table(header_on_body)),
                'grid width differs': docx(grid),
                'cell split across paragraphs': docx(two_paragraphs),
                'nested table in cell': docx(table([row(COLUMNS, True), row(ROWS[0]).replace('</w:p></w:tc>', '</w:p><w:tbl/></w:tc>', 1), row(ROWS[1])])),
                'extra table child': docx(table().replace('<w:tblGrid>', '<w:bookmarkStart/><w:tblGrid>', 1)),
                'hidden run property': docx(table().replace('<w:r><w:t xml:space="preserve">Hello', '<w:r><w:rPr><w:color w:val="FFFFFF"/></w:rPr><w:t xml:space="preserve">Hello', 1)),
                'symbol run content': docx(table().replace('Hello, world.</w:t></w:r>', 'Hello, world.</w:t></w:r><w:r><w:sym w:font="Wingdings" w:char="F04A"/></w:r>', 1)),
                'ruby run content': docx(table().replace('Hello, world.</w:t></w:r>', 'Hello, world.</w:t></w:r><w:r><w:noBreakHyphen/></w:r>', 1)),
                'attribute on text': docx(table().replace('<w:t xml:space="preserve">Hello', '<w:t w:rsid="1" xml:space="preserve">Hello', 1))}.items():
            with self.subTest(label): self.refused(lambda: self.docx(data))

    def test_docx_east_asian_font_hint_is_the_only_accepted_run_property(self):
        model = [*MODEL[:2], {'kind': 'table', 'rows': [COLUMNS, ['0', '1250', '你好。'], ROWS[1]]}]
        hinted = table([row(COLUMNS, True), row(['0', '1250', '你好。']), row(ROWS[1])]).replace(
            '<w:r><w:t xml:space="preserve">你好。', '<w:r><w:rPr><w:rFonts w:hint="eastAsia"/></w:rPr><w:t xml:space="preserve">你好。', 1)
        self.docx(docx(hinted), model)
        for label, properties in {'other hint': '<w:rFonts w:hint="cs"/>', 'font name': '<w:rFonts w:hint="eastAsia" w:ascii="Wingdings"/>',
                                  'colour': '<w:color w:val="FFFFFF"/>', 'size': '<w:sz w:val="1"/>', 'both': '<w:rFonts w:hint="eastAsia"/><w:vanish/>'}.items():
            with self.subTest(label):
                self.refused(lambda: self.docx(docx(hinted.replace('<w:rFonts w:hint="eastAsia"/>', properties)), model))

    def test_docx_forged_cells_and_units(self):
        for label, old, new in [('timestamp', '>1250<', '>1260<'), ('unit label', 'Start (ms)', 'Start (s)'), ('line break in text', 'Hello, world.', 'Hello,\nworld.'),
                                ('zero-width', 'Hello', 'Hel​lo')]:
            with self.subTest(label): self.refused(lambda: self.docx(docx(table().replace(old, new, 1))))

    def test_docx_styles_part_cannot_hide_text(self):
        styles = b'<w:styles xmlns:w="%s"><w:style w:styleId="Compact"><w:rPr><w:vanish/></w:rPr></w:style></w:styles>' % W.encode()
        self.refused(lambda: self.docx(docx(extra={'word/styles.xml': styles})), 'word/styles.xml differs')

    def readback(self, table_block=None):
        def para(text): return {'t': 'Para', 'c': [{'t': 'Str', 'c': text.split(' ')[0]}, *[x for w in text.split(' ')[1:] for x in ({'t': 'Space'}, {'t': 'Str', 'c': w})]]}
        def cells(values): return [['', [], []], [[['', [], []], {'t': 'AlignDefault'}, 1, 1, [para(v)]] for v in values]]
        def make(head, bodies, foot=None):
            return {'t': 'Table', 'c': [['', [], []], [None, []], [], [['', [], []], head], bodies, [['', [], []], foot or []]]}
        block = table_block or make([cells(COLUMNS)], [[['', [], []], 0, [], [cells(r) for r in ROWS]]])
        return {'meta': {'title': {'t': 'MetaInlines', 'c': [{'t': 'Str', 'c': 'Report'}]}}, 'blocks': [
            {'t': 'Header', 'c': [1, ['', [], []], [{'t': 'Str', 'c': 'Transcript'}]]}, para('Timestamps are in milliseconds.'), block]}, make, cells

    def test_native_ast_readback_header_structure(self):
        value, make, cells = self.readback()
        ast_report(value, Path('/nonexistent'), 'Report', MODEL)
        bodies = [[['', [], []], 0, [], [cells(r) for r in ROWS]]]
        for label, block in {
                'header demoted': make([], [[['', [], []], 0, [], [cells(COLUMNS), *[cells(r) for r in ROWS]]]]),
                'two header rows': make([cells(COLUMNS), cells(ROWS[0])], [[['', [], []], 0, [], [cells(ROWS[1])]]]),
                'footer row': make([cells(COLUMNS)], [[['', [], []], 0, [], [cells(ROWS[0])]]], [cells(ROWS[1])]),
                'two bodies': make([cells(COLUMNS)], [[['', [], []], 0, [], [cells(ROWS[0])]], [['', [], []], 0, [], [cells(ROWS[1])]]]),
                'row-head column': make([cells(COLUMNS)], [[['', [], []], 1, [], [cells(r) for r in ROWS]]]),
                'intermediate head': make([cells(COLUMNS)], [[['', [], []], 0, [cells(COLUMNS)], [cells(r) for r in ROWS]]])}.items():
            forged, *_ = self.readback(block)
            with self.subTest(label): self.refused(lambda: ast_report(forged, Path('/nonexistent'), 'Report', MODEL))
        self.assertEqual(len(bodies), 1)


if __name__ == '__main__': unittest.main()
