"""Typed workbook grammar: exact text, number and blank cells with independent ODS/XLSX readback.

Unlike the numeric reader this one keeps cell types: a text cell that looks like a number or
formula must come back as text, a blank must stay blank, and nothing may be a formula except
the fixed Summary set. Rich text, hyperlinks, macros, external references, data styles and
merged cells are rejected rather than ignored.
"""
import math
import re
import statistics
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile, ZIP_DEFLATED
from schemaxis.errors import fail
from .workbook import NS, X, METRICS, MIME, tag, column, formula, xml
from .typed_table import numeric_columns, column_scale, metric_close, DIGIT_TOLERANCE

HEADER = ('Column', *METRICS, 'MISSING')
FORMULA_METRICS = (*METRICS, 'COUNTBLANK')
MAX_COLUMNS = 64
MAX_ROWS = 10001
MAX_XML = 48 * 1024 * 1024  # a 100,000-cell typed workbook is far smaller than the shared 128 MiB ceiling
DRAWING = 'urn:oasis:names:tc:opendocument:xmlns:drawing:1.0'
FORBIDDEN_ODS_NAMESPACES = (DRAWING, 'urn:oasis:names:tc:opendocument:xmlns:script:1.0',
                            'urn:oasis:names:tc:opendocument:xmlns:datastyle:1.0',
                            'urn:oasis:names:tc:opendocument:xmlns:form:1.0')
XLINK = '{http://www.w3.org/1999/xlink}'
FORBIDDEN_SHEET_ELEMENTS = ('hyperlinks', 'drawing', 'legacyDrawing', 'mergeCells', 'dataValidations', 'tableParts',
                            'extLst', 'picture', 'oleObjects', 'controls')
RELATIONSHIPS = '{http://schemas.openxmlformats.org/package/2006/relationships}'
R = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id'


def expected(table):
    count = len(table['rows'])
    data = [[c['name'] for c in table['columns']]] + [list(row) for row in table['rows']]
    summary = [list(HEADER)]
    for index in numeric_columns(table):
        present = [row[index] for row in table['rows'] if row[index] is not None]
        summary.append([table['columns'][index]['name'], len(present), math.fsum(present), statistics.fmean(present),
                        min(present), max(present), statistics.stdev(present), count - len(present)])
    return {'Data': data, 'Summary': summary}


def summary_formula(table, row, metric, *, odf=False):
    return formula(numeric_columns(table)[row - 1], len(table['rows']), FORMULA_METRICS[metric - 1], odf=odf)


def fill_paragraph(paragraph, value):
    """Write exact text; every run of spaces becomes text:s so ODF whitespace collapsing cannot change it."""
    last = None
    for part in re.split('( +)', value):
        if not part:
            continue
        if part[0] == ' ':
            last = ET.SubElement(paragraph, tag('text', 's'), {tag('text', 'c'): str(len(part))})
        elif last is None:
            paragraph.text = part
        else:
            last.tail = part


def write_ods(path, table):
    root = ET.Element(tag('office', 'document-content'), {tag('office', 'version'): '1.3',
                      'xmlns:of': 'urn:oasis:names:tc:opendocument:xmlns:of:1.2'})
    sheet = ET.SubElement(ET.SubElement(root, tag('office', 'body')), tag('office', 'spreadsheet'))
    for name, rows in expected(table).items():
        tab = ET.SubElement(sheet, tag('table', 'table'), {tag('table', 'name'): name})
        for ri, row in enumerate(rows):
            native_row = ET.SubElement(tab, tag('table', 'table-row'))
            for ci, value in enumerate(row):
                if name == 'Summary' and ri and ci:
                    # Deliberately absent caches: native Calc must calculate every formula.
                    cell = ET.SubElement(native_row, tag('table', 'table-cell'),
                                         {tag('table', 'formula'): summary_formula(table, ri, ci, odf=True)})
                elif value is None:
                    ET.SubElement(native_row, tag('table', 'table-cell'))
                elif isinstance(value, str):
                    cell = ET.SubElement(native_row, tag('table', 'table-cell'), {tag('office', 'value-type'): 'string'})
                    fill_paragraph(ET.SubElement(cell, tag('text', 'p')), value)
                else:
                    ET.SubElement(native_row, tag('table', 'table-cell'),
                                  {tag('office', 'value-type'): 'float', tag('office', 'value'): format(value, '.17g')})
    manifest = ET.Element(tag('manifest', 'manifest'), {tag('manifest', 'version'): '1.3'})
    for name, media in (('/', MIME), ('content.xml', 'text/xml')):
        ET.SubElement(manifest, tag('manifest', 'file-entry'),
                      {tag('manifest', 'full-path'): name, tag('manifest', 'media-type'): media})
    with ZipFile(path, 'w', ZIP_DEFLATED) as archive:
        archive.writestr('mimetype', MIME, compress_type=0)
        archive.writestr('content.xml', ET.tostring(root, encoding='utf-8', xml_declaration=True))
        archive.writestr('META-INF/manifest.xml', ET.tostring(manifest, encoding='utf-8', xml_declaration=True))


def reject(message, **observed):
    fail('VERIFICATION_FAILED', message, **observed)


def bounded_xml(archive, name):
    if archive.getinfo(name).file_size > MAX_XML:
        reject('spreadsheet XML exceeds the typed workbook bound', member=name, maximumBytes=MAX_XML)
    return xml(archive, name)


def flatten(element, depth=0):
    """Exact cell text: literal text, text:s space runs and formatting-only spans; anything else is rejected."""
    out = element.text or ''
    for child in element:
        if child.tag == tag('text', 's') and not len(child):
            count = int(child.get(tag('text', 'c'), '1'))
            if not 1 <= count <= 4096:
                reject('invalid space run in cell text')
            out += ' ' * count
        elif child.tag == tag('text', 'span') and depth < 4:
            out += flatten(child, depth + 1)
        else:
            reject('cell text contains unsupported rich content such as a hyperlink, tab or line break',
                   element=child.tag.rsplit('}', 1)[-1])
        out += child.tail or ''
    return out


def ods_cell(cell):
    kind = cell.get(tag('office', 'value-type'))
    native = cell.get('{urn:org:documentfoundation:names:experimental:calc:xmlns:calcext:1.0}value-type')
    if any(child.tag != tag('text', 'p') for child in cell) or len(cell.findall('text:p', NS)) > 1:
        reject('cell contains content other than one paragraph')
    for attribute in cell.attrib:
        if attribute.startswith(XLINK) or attribute.rsplit('}', 1)[-1] in (
                'number-columns-spanned', 'number-rows-spanned', 'content-validation-name', 'string-value'):
            reject('cell uses a link, merge, validation or alternate string value')
    if native is not None and native != kind:
        reject('cell value types disagree', declared=kind, native=native)
    if kind == 'float':
        value = float(cell.get(tag('office', 'value')))
        if not math.isfinite(value):
            reject('numeric cell is not finite')
        return value
    if kind == 'string':
        paragraph = cell.find('text:p', NS)
        return '' if paragraph is None else flatten(paragraph)
    if kind is None:
        return None
    reject('unexpected spreadsheet cell type', type=kind)


def read_ods(path):
    with ZipFile(path) as archive:
        if any(n.split('/')[0] in ('Basic', 'Scripts', 'Dialogs', 'Pictures') or n.startswith('Object ')
               for n in archive.namelist()):
            reject('ODS contains macros, embedded objects or pictures')
        root = bounded_xml(archive, 'content.xml')
    for element in root.iter():
        if not isinstance(element.tag, str) or element.tag.partition('}')[0].lstrip('{') in FORBIDDEN_ODS_NAMESPACES:
            reject('ODS content uses drawing, form, script or data-style markup')
        if any(a.startswith(XLINK) for a in element.attrib) or element.tag == tag('text', 'a'):
            reject('ODS content contains a hyperlink or external reference')
    scripts = root.find('.//office:scripts', NS)
    if scripts is not None and len(scripts):
        reject('ODS contains scripts')
    values, formulas = {}, {}
    for sheet in root.findall('.//table:table', NS):
        name = sheet.get(tag('table', 'name'))
        if name in values:
            reject('duplicate worksheet', sheet=name)
        rows, fs, empty_rows = [], [], 0
        for row in sheet.findall('table:table-row', NS):
            cells, marks, gap = [], [], 0
            for cell in row:
                if cell.tag != tag('table', 'table-cell'):
                    reject('worksheet row contains covered or foreign cells')
                value, mark = ods_cell(cell), cell.get(tag('table', 'formula'))
                count = int(cell.get(tag('table', 'number-columns-repeated'), '1'))
                if count < 1:
                    reject('invalid repeated cell count')
                if value is None and mark is None:
                    gap += count
                    continue
                if count > MAX_COLUMNS or len(cells) + gap + count > MAX_COLUMNS:
                    reject('too many spreadsheet columns')
                cells.extend([None] * gap + [value] * count)
                marks.extend([None] * gap + [mark] * count)
                gap = 0
            repeat = int(row.get(tag('table', 'number-rows-repeated'), '1'))
            if repeat < 1:
                reject('invalid repeated row count')
            if not cells:
                empty_rows += repeat
                continue
            if repeat > MAX_ROWS or len(rows) + empty_rows + repeat > MAX_ROWS:
                reject('too many spreadsheet rows')
            rows.extend([[]] * empty_rows)
            fs.extend([[]] * empty_rows)
            empty_rows = 0
            rows.extend([cells] * repeat)
            fs.extend([marks] * repeat)
        values[name], formulas[name] = rows, fs
    return values, formulas


def unescape(text):
    """OOXML escapes control and underscore sequences as _xHHHH_."""
    return re.sub(r'_x([0-9A-Fa-f]{4})_', lambda m: chr(int(m[1], 16)), text)


def string_item(element):
    """Exact text of a shared/inline string. Font-fallback runs (r/rPr/t) only format; phonetic text is rejected."""
    parts = []
    for child in element:
        if child.tag == '{%s}t' % X['s']:
            parts.append(child.text or '')
        elif child.tag == '{%s}r' % X['s']:
            inner = [c for c in child if c.tag != '{%s}rPr' % X['s']]
            if len(inner) != 1 or inner[0].tag != '{%s}t' % X['s']:
                reject('string run contains content other than text')
            parts.append(inner[0].text or '')
        else:
            reject('shared or inline string has phonetic or unsupported content')
    return unescape(''.join(parts))


def cell_position(reference):
    match = re.fullmatch(r'([A-Z]{1,2})([1-9][0-9]*)', reference or '')
    if not match:
        reject('invalid cell reference', reference=reference)
    number = 0
    for char in match[1]:
        number = number * 26 + ord(char) - 64
    return int(match[2]), number


def general_formats(archive):
    styles = bounded_xml(archive, 'xl/styles.xml')
    codes = {n.get('numFmtId'): n.get('formatCode') for n in styles.findall('s:numFmts/s:numFmt', X)}
    return [(x.get('numFmtId') == '0' or codes.get(x.get('numFmtId')) == 'General')
            for x in styles.findall('s:cellXfs/s:xf', X)]


def read_xlsx(path):
    with ZipFile(path) as archive:
        names = archive.namelist()
        if any(n.startswith(('xl/externalLinks/', 'xl/media/', 'xl/drawings/', 'xl/embeddings/', 'xl/activeX/',
                             'xl/ctrlProps/')) or 'vbaProject' in n or n.startswith('xl/comments') for n in names):
            reject('XLSX contains external links, macros, drawings, comments or embedded objects')
        for name in names:
            if name.endswith('.rels'):
                for relation in bounded_xml(archive, name):
                    if relation.get('TargetMode') == 'External':
                        reject('XLSX contains an external relationship')
        shared = []
        if 'xl/sharedStrings.xml' in names:
            shared = [string_item(item) for item in bounded_xml(archive, 'xl/sharedStrings.xml').findall('s:si', X)]
        workbook = bounded_xml(archive, 'xl/workbook.xml')
        if workbook.find('s:externalReferences', X) is not None or workbook.find('s:definedNames', X) is not None:
            reject('XLSX workbook defines names or external references')
        relations = {item.get('Id'): item.get('Target') for item in bounded_xml(archive, 'xl/_rels/workbook.xml.rels')}
        general = general_formats(archive)
        values, formulas = {}, {}
        for sheet in workbook.findall('s:sheets/s:sheet', X):
            name, target = sheet.get('name'), relations[sheet.get(R)]
            if '..' in target.split('/') or target.startswith('/') or ':' in target:
                reject('unexpected worksheet location')
            root = bounded_xml(archive, 'xl/' + target)
            if any(root.find('s:' + element, X) is not None for element in FORBIDDEN_SHEET_ELEMENTS):
                reject('worksheet contains links, drawings, merged cells or validation', sheet=name)
            rows, fs, last = [], [], 0
            for row in root.findall('s:sheetData/s:row', X):
                number = int(row.get('r'))
                if number <= last or number > MAX_ROWS:
                    reject('worksheet rows are unordered or exceed the bound', sheet=name)
                rows.extend([[]] * (number - last - 1))
                fs.extend([[]] * (number - last - 1))
                cells, marks, previous = [], [], 0
                for cell in row.findall('s:c', X):
                    at_row, at_column = cell_position(cell.get('r'))
                    if at_row != number or at_column <= previous or at_column > MAX_COLUMNS:
                        reject('worksheet cells are unordered or exceed the bound', sheet=name, cell=cell.get('r'))
                    kind, raw = cell.get('t'), cell.findtext('s:v', None, X)
                    mark, inline = cell.findtext('s:f', None, X), cell.find('s:is', X)
                    if raw is None and inline is None and mark is None:
                        continue
                    cells.extend([None] * (at_column - 1 - len(cells)))
                    marks.extend([None] * (at_column - 1 - len(marks)))
                    if kind == 's':
                        value = shared[int(raw)]
                    elif kind == 'inlineStr':
                        value = string_item(inline)
                    elif kind in (None, 'n') and raw is not None:
                        value = float(raw)
                        if not math.isfinite(value):
                            reject('numeric cell is not finite', sheet=name, cell=cell.get('r'))
                        style = int(cell.get('s', '0'))
                        if style >= len(general) or not general[style]:
                            reject('number cell has a non-General number format', sheet=name, cell=cell.get('r'))
                    else:
                        reject('unexpected spreadsheet cell type', sheet=name, cell=cell.get('r'), type=kind)
                    cells.append(value)
                    marks.append(mark)
                    previous = at_column
                rows.append(cells)
                fs.append(marks)
                last = number
            if name in values:
                reject('duplicate worksheet', sheet=name)
            values[name], formulas[name] = rows, fs
        return values, formulas


def _pad(rows, width):
    return [list(row) + [None] * (width - len(row)) if len(row) <= width else None for row in rows]


def same(observed, wanted, *, exact=False):
    if wanted is None or isinstance(wanted, str):
        return type(observed) is type(wanted) and observed == wanted
    if type(observed) is not float:
        return False
    if exact:
        return observed == wanted
    return math.isclose(observed, wanted, rel_tol=DIGIT_TOLERANCE, abs_tol=0.0)


def verify_workbook(path, table, *, full=False):
    odf = Path(path).suffix == '.ods'
    values, formulas = (read_ods if odf else read_xlsx)(path)
    wanted = expected(table)
    if list(values) != ['Data', 'Summary']:
        reject('worksheets differ from Data and Summary', path=str(path), sheets=list(values))
    width = {'Data': len(table['columns']), 'Summary': len(HEADER)}
    observed = {}
    scales = [column_scale([row[i] for row in table['rows'] if row[i] is not None]) for i in numeric_columns(table)]
    for sheet, rows in wanted.items():
        padded = _pad(values[sheet], width[sheet])
        if None in padded or len(padded) != len(rows):
            reject('worksheet shape differs from the typed table', path=str(path), sheet=sheet,
                   rows=len(values[sheet]), expectedRows=len(rows))
        observed[sheet] = padded
        for ri, row in enumerate(rows):
            for ci, cell in enumerate(row):
                got = padded[ri][ci]
                summary = sheet == 'Summary' and ri and ci
                if summary and ci in (1, 7):
                    ok = same(got, cell, exact=True)  # COUNT and MISSING are whole numbers
                elif summary:
                    ok = metric_close(got, cell, scales[ri - 1], derived=ci in (2, 3, 6))
                else:
                    ok = same(got, cell)
                if not ok:
                    reject('typed cell differs from the declared table', path=str(path),
                           cell=f'{sheet}.{column(ci)}{ri + 1}',
                           observed=got if not isinstance(got, str) else got[:64],
                           expected=cell if not isinstance(cell, str) else cell[:64])
    for sheet, rows in formulas.items():
        for ri, row in enumerate(rows):
            for ci, actual in enumerate(row):
                wanted_formula = (summary_formula(table, ri, ci, odf=odf) if sheet == 'Summary' and ri and ci else None)
                # OOXML uses !; ODF may quote a sheet name. Both are fixed names here.
                normal = actual.replace("'Data'", 'Data').replace('Data!', 'Data.') if isinstance(actual, str) else actual
                if odf and isinstance(normal, str):
                    normal = normal.replace('[$Data.', '[Data.').replace(':.', ':Data.')
                if normal != wanted_formula:
                    reject('spreadsheet formula differs', path=str(path), cell=f'{sheet}.{column(ci)}{ri + 1}')
    return observed if full else observed['Summary']
