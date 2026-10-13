"""Small, closed spreadsheet grammar and independent ODS/XLSX readback."""
import math
import statistics
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile, ZIP_DEFLATED
from schemaxis.errors import fail
from schemaxis.tabular import close

NS = {'office':'urn:oasis:names:tc:opendocument:xmlns:office:1.0',
      'table':'urn:oasis:names:tc:opendocument:xmlns:table:1.0',
      'text':'urn:oasis:names:tc:opendocument:xmlns:text:1.0',
      'manifest':'urn:oasis:names:tc:opendocument:xmlns:manifest:1.0'}
X = {'s':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
METRICS = ('COUNT', 'SUM', 'AVERAGE', 'MIN', 'MAX', 'STDEV')
MIME = 'application/vnd.oasis.opendocument.spreadsheet'
for prefix,uri in NS.items():ET.register_namespace(prefix,uri)


def tag(prefix,name):return '{'+NS[prefix]+'}'+name


def column(index):
    result='';index+=1
    while index:index,remainder=divmod(index-1,26);result=chr(65+remainder)+result
    return result


def expected(table):
    data=[table['columns']]+table['rows']
    summary=[['Column',*METRICS]]
    for index,name in enumerate(table['columns']):
        values=[row[index] for row in table['rows']]
        summary.append([name,len(values),math.fsum(values),statistics.fmean(values),min(values),max(values),statistics.stdev(values)])
    return {'Data':data,'Summary':summary}


def formula(index,count,metric,*,odf=False):
    col=column(index)
    return f'of:={metric}([Data.{col}2:Data.{col}{count+1}])' if odf else f'{metric}(Data.{col}2:{col}{count+1})'


def write_ods(path,table):
    root=ET.Element(tag('office','document-content'),{tag('office','version'):'1.3',
                    'xmlns:of':'urn:oasis:names:tc:opendocument:xmlns:of:1.2'})
    sheet=ET.SubElement(ET.SubElement(root,tag('office','body')),tag('office','spreadsheet'))
    for name,rows in expected(table).items():
        tab=ET.SubElement(sheet,tag('table','table'),{tag('table','name'):name})
        for ri,row in enumerate(rows):
            native_row=ET.SubElement(tab,tag('table','table-row'))
            for ci,value in enumerate(row):
                attrs={}
                if name=='Summary' and ri and ci:
                    # Deliberately absent caches: native Calc must calculate every formula.
                    attrs[tag('table','formula')]=formula(ri-1,len(table['rows']),METRICS[ci-1],odf=True)
                elif isinstance(value,str):attrs[tag('office','value-type')]='string'
                else:attrs.update({tag('office','value-type'):'float',tag('office','value'):format(value,'.17g')})
                cell=ET.SubElement(native_row,tag('table','table-cell'),attrs)
                if isinstance(value,str):ET.SubElement(cell,tag('text','p')).text=value
    manifest=ET.Element(tag('manifest','manifest'),{tag('manifest','version'):'1.3'})
    for name,media in (('/',MIME),('content.xml','text/xml')):
        ET.SubElement(manifest,tag('manifest','file-entry'),{tag('manifest','full-path'):name,tag('manifest','media-type'):media})
    with ZipFile(path,'w',ZIP_DEFLATED) as archive:
        archive.writestr('mimetype',MIME,compress_type=0)
        archive.writestr('content.xml',ET.tostring(root,encoding='utf-8',xml_declaration=True))
        archive.writestr('META-INF/manifest.xml',ET.tostring(manifest,encoding='utf-8',xml_declaration=True))


def xml(archive,name):
    entry=archive.getinfo(name)
    if entry.file_size>128*1024*1024:fail('RESOURCE_LIMIT','spreadsheet XML exceeds 128 MiB')
    data=archive.read(name)
    if b'<!DOCTYPE' in data or b'<!ENTITY' in data:fail('INVALID_WORKBOOK','XML entities are unsupported')
    return ET.fromstring(data)


def read_ods(path):
    with ZipFile(path) as archive:root=xml(archive,'content.xml')
    values={};formulas={}
    for sheet in root.findall('.//table:table',NS):
        name=sheet.get(tag('table','name'))
        if name in values:fail('INVALID_WORKBOOK','duplicate worksheet')
        rows=[];fs=[];empty_rows=0
        for row in sheet.findall('table:table-row',NS):
            cells=[];f=[];empty_cells=0
            for cell in row.findall('table:table-cell',NS):
                kind=cell.get(tag('office','value-type'))
                if kind=='float':value=float(cell.get(tag('office','value')))
                elif kind=='string':value=''.join(cell.itertext())
                elif kind is None:value=None
                else:fail('INVALID_WORKBOOK','unexpected spreadsheet cell type')
                count=int(cell.get(tag('table','number-columns-repeated'),'1'))
                # LibreOffice uses huge repeated empty tails. Ignore only truly empty cells.
                if count<1:fail('INVALID_WORKBOOK','invalid repeated cell count')
                if value is None and cell.get(tag('table','formula')) is None:
                    empty_cells+=count;continue
                if not 1<=count<=64 or len(cells)+empty_cells+count>64:fail('RESOURCE_LIMIT','too many spreadsheet columns')
                cells.extend([None]*empty_cells);f.extend([None]*empty_cells);empty_cells=0
                cells.extend([value]*count);f.extend([cell.get(tag('table','formula'))]*count)
            count=int(row.get(tag('table','number-rows-repeated'),'1'))
            if count<1:fail('INVALID_WORKBOOK','invalid repeated row count')
            if not cells:
                empty_rows+=count;continue
            if not 1<=count<=10001 or len(rows)+empty_rows+count>10001:fail('RESOURCE_LIMIT','too many spreadsheet rows')
            rows.extend([[]]*empty_rows);fs.extend([[]]*empty_rows);empty_rows=0
            rows.extend([cells]*count);fs.extend([f]*count)
        values[name]=rows;formulas[name]=fs
    return values,formulas


def read_xlsx(path):
    with ZipFile(path) as archive:
        shared=[]
        if 'xl/sharedStrings.xml' in archive.namelist():
            shared=[''.join(item.itertext()) for item in xml(archive,'xl/sharedStrings.xml').findall('s:si',X)]
        workbook=xml(archive,'xl/workbook.xml')
        relations={item.get('Id'):item.get('Target') for item in xml(archive,'xl/_rels/workbook.xml.rels')}
        values={};formulas={}
        for sheet in workbook.findall('s:sheets/s:sheet',X):
            name=sheet.get('name');rid=sheet.get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id')
            target=relations[rid]
            if '..' in target.split('/') or target.startswith('/') or ':' in target:fail('INVALID_WORKBOOK','unexpected worksheet location')
            rows=[];fs=[]
            for row in xml(archive,'xl/'+target).findall('s:sheetData/s:row',X):
                cells=[];f=[]
                if len(rows)>=10001 or int(row.get('r'))!=len(rows)+1:fail('INVALID_WORKBOOK','noncontiguous worksheet rows')
                for cell in row.findall('s:c',X):
                    if len(cells)>=64 or cell.get('r')!=column(len(cells))+str(len(rows)+1):fail('INVALID_WORKBOOK','noncontiguous worksheet cells')
                    kind=cell.get('t');raw=cell.findtext('s:v',None,X)
                    if kind=='s':value=shared[int(raw)]
                    elif kind=='inlineStr':value=''.join(cell.find('s:is',X).itertext())
                    elif kind in (None,'n'):value=float(raw)
                    else:fail('INVALID_WORKBOOK','unexpected spreadsheet cell type')
                    cells.append(value);f.append(cell.findtext('s:f',None,X))
                rows.append(cells);fs.append(f)
            if name in values:fail('INVALID_WORKBOOK','duplicate worksheet')
            values[name]=rows;formulas[name]=fs
        return values,formulas


def verify_workbook(path,table,*,full=False):
    odf=Path(path).suffix=='.ods'
    values,formulas=(read_ods if odf else read_xlsx)(path)
    if not close(values,expected(table)):fail('VERIFICATION_FAILED','spreadsheet data or recalculated summaries differ',str(path))
    for name,rows in formulas.items():
        for ri,row in enumerate(rows):
            for ci,actual in enumerate(row):
                wanted=formula(ri-1,len(table['rows']),METRICS[ci-1],odf=odf) if name=='Summary' and ri and ci else None
                # OOXML uses !; ODF may quote a sheet name. Both are fixed names here.
                normal=actual.replace("'Data'",'Data').replace('Data!','Data.') if isinstance(actual,str) else actual
                if odf and isinstance(normal,str):normal=normal.replace('[$Data.','[Data.').replace(':.',':Data.')
                if normal!=wanted:fail('VERIFICATION_FAILED','spreadsheet formula differs',str(path))
    return values if full else values['Summary']
