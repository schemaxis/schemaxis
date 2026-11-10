"""Strict reader for Tesseract's TSV output and its text/TSV agreement policy.

The native files are untrusted. The reader accepts exactly one page, a fixed header, tab-delimited records of twelve fields,
a consecutive block/paragraph/line/word hierarchy, boxes inside the page and their parents, and native confidence text with
at most six decimals. Nothing is repaired or reordered.
"""
import re
import unicodedata

from schemaxis.errors import fail

HEADER = ['level', 'page_num', 'block_num', 'par_num', 'line_num', 'word_num', 'left', 'top', 'width', 'height', 'conf', 'text']
MAX_WORDS = 5000
MAX_TEXT_CHARACTERS = 100000
INTEGER = re.compile(r'(0|[1-9][0-9]{0,6})')
CONFIDENCE = re.compile(r'(?:0|[1-9][0-9]{0,2})(?:\.[0-9]{1,6})?')
READING_ORDER = ('Words are read in native TSV record order (block, paragraph, line, word); words in a line are joined by one space, '
                 'lines by one newline. The native text file must equal this after dropping blank lines and collapsing runs of '
                 'spaces; paragraph separators and trailing whitespace are the only tolerated differences.')


def refuse(message, location='native.tsv', **observed):
    fail('OCR_OUTPUT_INVALID', message, location, **observed)


def whole(value):
    return INTEGER.fullmatch(value) is not None


def inside(inner, outer):
    return inner[0] >= outer[0] and inner[1] >= outer[1] and inner[0] + inner[2] <= outer[0] + outer[2] and inner[1] + inner[3] <= outer[1] + outer[3]


def word_text(value, location):
    if not value or value != value.strip() or any(unicodedata.category(c) in ('Cc', 'Cf', 'Cs', 'Co', 'Cn', 'Zs', 'Zl', 'Zp') for c in value):
        refuse('word text must be nonempty without surrounding, control, format or space characters', location)
    try:
        value.encode('utf-8')
    except UnicodeEncodeError:
        refuse('word text is not valid Unicode scalar text', location)
    return value


def parse(data, width, height):
    """Native TSV bytes to a checked page structure; raises OCR_OUTPUT_INVALID for any deviation."""
    try:
        text = data.decode('utf-8')
    except UnicodeDecodeError:
        refuse('native TSV is not UTF-8')
    if text.startswith('\ufeff') or '\r' in text or not text.endswith('\n') or '\n\n' in text:
        refuse('native TSV must use LF-terminated nonblank records without a byte-order mark')
    rows = text[:-1].split('\n')
    if rows[0].split('\t') != HEADER:
        refuse('native TSV header differs from the twelve expected columns', 'native.tsv:1')
    if len(rows) < 2:
        refuse('native TSV has no page record', 'native.tsv:2')
    page_box = (0, 0, width, height)
    blocks, current = [], {'block': None, 'paragraph': None, 'line': None}
    words, line_texts, count = [], [], 0
    for number, row in enumerate(rows[1:], 2):
        where = 'native.tsv:%d' % number
        fields = row.split('\t')
        if len(fields) != 12:
            refuse('record must have exactly twelve tab-separated fields', where, fields=len(fields))
        if not all(whole(v) for v in fields[:10]):
            refuse('level, hierarchy and box fields must be canonical nonnegative integers', where)
        level, page, block, paragraph, line, word, left, top, box_width, box_height = (int(v) for v in fields[:10])
        box = (left, top, box_width, box_height)
        if number == 2:
            if (level, page, block, paragraph, line, word) != (1, 1, 0, 0, 0, 0) or box != page_box or fields[10] != '-1' or fields[11] != '':
                refuse('first record must be the page record covering exactly the image at top-left origin with conf -1', where, box=list(box), expected=list(page_box))
            continue
        if page != 1 or not 2 <= level <= 5:
            refuse('only level 2-5 records of page 1 may follow the page record', where, level=level, page=page)
        if box_width < 1 or box_height < 1 or not inside(box, page_box):
            refuse('box must have positive size and lie inside the image', where, box=list(box))
        if level < 5:
            if fields[10] != '-1' or fields[11] != '':
                refuse('structural record must have conf -1 and empty text', where)
        if level == 2:
            if (paragraph, line, word) != (0, 0, 0) or block != len(blocks) + 1:
                refuse('block records must number 1.. consecutively with zero lower fields', where)
            current = {'block': {'index': block, 'box': box, 'paragraphs': []}, 'paragraph': None, 'line': None}
            blocks.append(current['block'])
        elif level == 3:
            parent = current['block']
            if parent is None or (line, word) != (0, 0) or block != parent['index'] or paragraph != len(parent['paragraphs']) + 1 or not inside(box, parent['box']):
                refuse('paragraph record must follow its block, number consecutively and lie inside it', where)
            current['paragraph'] = {'index': paragraph, 'box': box, 'lines': []}
            parent['paragraphs'].append(current['paragraph'])
            current['line'] = None
        elif level == 4:
            parent = current['paragraph']
            if parent is None or word != 0 or block != current['block']['index'] or paragraph != parent['index'] or line != len(parent['lines']) + 1 or not inside(box, parent['box']):
                refuse('line record must follow its paragraph, number consecutively and lie inside it', where)
            current['line'] = {'index': line, 'box': box, 'words': []}
            parent['lines'].append(current['line'])
        else:
            parent = current['line']
            if parent is None or (block, paragraph, line) != (current['block']['index'], current['paragraph']['index'], parent['index']) or word != len(parent['words']) + 1 or not inside(box, parent['box']):
                refuse('word record must follow its line, number consecutively and lie inside it', where)
            if not CONFIDENCE.fullmatch(fields[10]) or float(fields[10]) > 100:
                refuse('word confidence must be native decimal text from 0 to 100 with at most six decimals', where, confidence=fields[10][:20])
            text_value = word_text(fields[11], where)
            count += 1
            if count > MAX_WORDS:
                fail('OCR_RESOURCE_LIMIT', 'more than %d words' % MAX_WORDS, 'native.tsv')
            entry = {'index': count - 1, 'block': block, 'paragraph': paragraph, 'line': line, 'word': word,
                     'box': {'left': left, 'top': top, 'width': box_width, 'height': box_height},
                     'confidence': float(fields[10]), 'confidenceText': fields[10], 'text': text_value}
            parent['words'].append(entry)
            words.append(entry)
    for block in blocks:
        for paragraph in block['paragraphs']:
            for line in paragraph['lines']:
                if not line['words']:
                    refuse('line record has no word records', 'native.tsv', block=block['index'], line=line['index'])
                line_texts.append(' '.join(w['text'] for w in line['words']))
            if not paragraph['lines']:
                refuse('paragraph record has no line records', 'native.tsv')
        if not block['paragraphs']:
            refuse('block record has no paragraph records', 'native.tsv')
    if sum(len(w['text']) for w in words) > MAX_TEXT_CHARACTERS:
        fail('OCR_RESOURCE_LIMIT', 'word text exceeds %d characters' % MAX_TEXT_CHARACTERS, 'native.tsv')
    return {'words': words, 'lines': line_texts, 'blocks': len(blocks),
            'paragraphs': sum(len(b['paragraphs']) for b in blocks), 'lineCount': len(line_texts)}


def native_lines(data):
    """Native text bytes to normalized lines (blank lines dropped, space runs collapsed)."""
    try:
        text = data.decode('utf-8')
    except UnicodeDecodeError:
        refuse('native text is not UTF-8', 'native.txt')
    if '\r' in text or '\f' in text or '\t' in text or '\ufeff' in text or any(unicodedata.category(c) == 'Cc' and c != '\n' for c in text):
        refuse('native text contains carriage return, tab, form feed, byte-order mark or control characters', 'native.txt')
    return [re.sub(r' +', ' ', line).strip() for line in text.split('\n') if line.strip()]


def agree(parsed, text_bytes):
    """The documented text/TSV agreement policy; returns the canonical text published from the TSV words."""
    if native_lines(text_bytes) != parsed['lines']:
        refuse('native text disagrees with the TSV words under the reading-order policy', 'native.txt', policy=READING_ORDER)
    return ''.join(line + '\n' for line in parsed['lines'])
