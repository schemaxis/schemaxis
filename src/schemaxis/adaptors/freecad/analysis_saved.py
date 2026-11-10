"""Host inspection of generated FEM persistence before any native restoration."""
import hashlib
import math
from zipfile import ZipFile
from schemaxis.errors import fail
from .document_xml import Document,read_member

PROXIES={'Material':('femobjects.material_common','MaterialCommon'),'Mesh':('femobjects.mesh_gmsh','MeshGmsh'),
    'Solver':('femobjects.solver_ccxtools','SolverCcxTools'),'CCX_Results':('femobjects.result_mechanical','ResultMechanical'),
    'CCX_Results_Mesh':('femobjects.mesh_result','MeshResult')}


def types(prepared):
    return {'Solid':'Part::Feature','Analysis':'Fem::FemAnalysis','Material':'App::MaterialObjectPython','Mesh':'Fem::FemMeshShapeBaseObjectPython','Solver':'Fem::FemSolverObjectPython',
        'CCX_Results':'Fem::FemResultObjectPython','CCX_Results_Mesh':'Fem::FemMeshObjectPython','Pipeline_CCX_Results':'Fem::FemPostPipeline','ccx_dat_file':'App::TextDocument',
        **{'Support'+str(i):'Fem::ConstraintDisplacement' for i in range(len(prepared['supports']))},**{'Load'+str(i):'Fem::ConstraintForce' if x['kind']=='force' else 'Fem::ConstraintPressure' for i,x in enumerate(prepared['loads'])}}


def payloads(path):
    """Bind non-XML geometry, mesh and result payloads to native-created bytes."""
    from .assembly_sources import check_archive
    check_archive(path,str(path),code='VERIFICATION_FAILED')
    with ZipFile(path) as archive:
        return {info.filename:hashlib.sha256(read_member(archive,info.filename,128*1024*1024)).hexdigest() for info in archive.infolist() if info.filename not in ('Document.xml','GuiDocument.xml')}


def safe_to_open(prepared,path):
    """Only fixed trusted FEM proxy classes with their null state may restore.

    Input CAD is never restored as a project. This inspection concerns only the
    adaptor-created analysis, and rejects authored or forged executable payloads
    before FreeCAD can instantiate a proxy or extension.
    """
    from .assembly_sources import check_archive
    check_archive(path,str(path),code='VERIFICATION_FAILED');xml=Document(path);expected=types(prepared)
    if xml.types!=expected:fail('VERIFICATION_FAILED','Saved FEM object membership/type differs')
    extensions={'Analysis':['App::GroupExtension'],'Material':['App::SuppressibleExtensionPython'],
        'Mesh':['App::SuppressibleExtension'],'CCX_Results_Mesh':['App::SuppressibleExtension'],'Pipeline_CCX_Results':['Fem::FemPostGroupExtension'],
        **{'Support'+str(i):['App::SuppressibleExtension'] for i in range(len(prepared['supports']))},
        **{'Load'+str(i):['App::SuppressibleExtension'] for i in range(len(prepared['loads']))}}
    for record in xml.root.findall('./ObjectData/Object'):
        name=record.get('name')
        if [c.get('type') for c in record.findall('./Extensions/Extension')]!=extensions.get(name,[]):fail('VERIFICATION_FAILED','Saved FEM extension membership differs',name)
        props=xml.properties[name]
        for prop in record.findall('./Properties/_Property'):
            if len(prop):fail('VERIFICATION_FAILED','Transient FEM property contains a payload',name)
        for prop,key in ((p,p.get('name')) for p in props.values()):
            kind=prop.get('type')
            if kind=='App::PropertyPythonObject':
                if key!='Proxy' or name not in PROXIES or len(prop)!=1 or prop[0].tag!='Python':fail('VERIFICATION_FAILED','Saved FEM has an unreviewed Python object',name)
                module,cls=PROXIES[name]
                if prop[0].attrib!={'value':'bnVsbA==','encoded':'yes','module':module,'class':cls}:fail('VERIFICATION_FAILED','Saved FEM proxy class/state is outside the trusted whitelist',name)
            elif 'Python' in kind or 'XLink' in kind or 'File' in kind or kind=='App::PropertyPath' and prop.find('Path') is not None and prop.find('Path').get('value') not in ('',):
                fail('VERIFICATION_FAILED','Saved FEM has an undeclared executable/external-resource property',name+'.'+key)
        if name in PROXIES and 'Proxy' not in props:fail('VERIFICATION_FAILED','Saved FEM is missing its trusted proxy',name)
        if xml.engine(name):fail('VERIFICATION_FAILED','Saved FEM has undeclared expressions',name)
    with ZipFile(path) as archive:
        members=set(archive.namelist())
        for child in xml.root.iter():
            file=child.get('file')
            if file and (file not in members or '/' in file or '\\' in file):fail('VERIFICATION_FAILED','Saved FEM payload refers outside its archive')
        from .document_xml import parse_xml
        for member in members:
            if member.endswith('.vtu'):
                vtk=parse_xml(read_member(archive,member,128*1024*1024),member)
                if vtk.tag!='VTKFile' or vtk.get('type')!='UnstructuredGrid' or any('Source' in c.attrib or 'href' in c.attrib for c in vtk.iter()):fail('VERIFICATION_FAILED','Saved FEM result has an external or unsupported VTK source')
    # Every object link remains inside this one generated analysis document.
    for child in xml.root.iter():
        if child.tag in ('Link','LinkSub'):
            target=child.get('obj') if child.tag=='Link' and 'obj' in child.attrib else child.get('value')
            if target and target not in expected:fail('VERIFICATION_FAILED','Saved FEM refers outside its owned document',target)
    return xml


def verify(prepared,path,observed,expected_payloads=None):
    from .adaptor import close
    from .history import equivalent
    xml=safe_to_open(prepared,path)
    if not isinstance(expected_payloads,dict) or not expected_payloads or payloads(path)!=expected_payloads:fail('VERIFICATION_FAILED','Saved FEM geometry/mesh/result payload changed after native generation')
    material=xml.child('Material','Material','Map','App::PropertyMap')
    if material.get('count')!=str(len(material)) or {v.get('key'):v.get('value') for v in material}!=observed['material']:fail('VERIFICATION_FAILED','Saved FEM material map differs')
    if xml.links('Analysis','Group')!=observed['analysisGroup']:fail('VERIFICATION_FAILED','Saved FEM analysis group differs')
    if xml.link('Mesh','Shape')!='Solid' or not close(xml.number('Mesh','CharacteristicLengthMax'),prepared['mesh']['sizeMM']) or not xml.boolean('Mesh','SecondOrderLinear'):fail('VERIFICATION_FAILED','Saved mesh shape/size/geometry order differs')
    def enum(name,prop,wanted,choices):
        value=xml.properties[name][prop]
        if value.get('type')!='App::PropertyEnumeration' or [c.tag for c in value]!=['Integer','CustomEnumList']:
            fail('VERIFICATION_FAILED','Saved FEM enumeration structure differs',name+'.'+prop)
        items=value[1]
        if value[0].attrib!={'value':str(wanted),'CustomEnum':'true'} or items.get('count')!=str(len(choices)) or [c.tag for c in items]!=['Enum']*len(choices) or [c.get('value') for c in items]!=choices:
            fail('VERIFICATION_FAILED','Saved FEM enumeration meaning differs',name+'.'+prop)
    enum('Mesh','ElementDimension',3,['From Shape','1D','2D','3D']);enum('Mesh','ElementOrder',prepared['mesh']['order']-1,['1st','2nd'])
    enum('Solver','AnalysisType',0,['static','frequency','thermomech','check','buckling'])
    enum('Solver','GeometricalNonlinearity',0,['linear','nonlinear']);enum('Solver','MaterialNonlinearity',0,['linear','nonlinear'])
    enum('Solver','ModelSpace',0,['3D','plane stress','plane strain','axisymmetric'])
    if xml.boolean('Solver','SplitInputWriter'):fail('VERIFICATION_FAILED','Saved solver uses undeclared split inputs')
    def references(name):
        value=xml.child(name,'References','LinkSubList','App::PropertyLinkSubList')
        if value.get('count')!=str(len(value)):fail('VERIFICATION_FAILED','Saved geometric-reference count differs',name)
        return [[c.get('obj'),[c.get('sub')]] for c in value]
    def vector(name,prop):
        value=xml.child(name,prop,'PropertyVector','App::PropertyVector');return [float(value.get('value'+a)) for a in 'XYZ']
    for name,support in observed['supports'].items():
        actual=[]
        for a in 'xyz':actual.append(None if xml.boolean(name,a+'Free') else xml.number(name,a+'Displacement','App::PropertyDistance'))
        if references(name)!=support['references'] or not equivalent(actual,support['displacementMM']) or xml.boolean(name,'Suppressed'):fail('VERIFICATION_FAILED','Saved support geometry or displacement differs',name)
        if any(xml.boolean(name,'has'+a+'Formula') for a in 'XYZ') or xml.boolean(name,'EnableAmplitude'):fail('VERIFICATION_FAILED','Saved support has undeclared formula/time dependence',name)
    for name,load in observed['loads'].items():
        if references(name)!=load['references'] or xml.boolean(name,'Suppressed') or xml.boolean(name,'EnableAmplitude'):fail('VERIFICATION_FAILED','Saved load geometry or temporal dependence differs',name)
        sign=-1 if xml.boolean(name,'Reversed') else 1
        if load['kind']=='force':
            size=xml.number(name,'Force','App::PropertyForce')/1000*sign;actual=[v*size for v in vector(name,'DirectionVector')]
            if not close(actual,load['forceN']):fail('VERIFICATION_FAILED','Saved force vector/units differ',name)
        elif not close(xml.number(name,'Pressure','App::PropertyPressure')/1000*sign,load['pressureMPa']):fail('VERIFICATION_FAILED','Saved pressure magnitude/units differ',name)
    from .gui_state import verify as verify_gui
    verify_gui(path,{name:name in ('Solid','Pipeline_CCX_Results') for name in xml.types})
    return True
