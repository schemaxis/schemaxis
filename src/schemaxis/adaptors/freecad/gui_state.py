"""Persist the minimal native view state needed for first-open Body visibility.

FreeCADCmd writes App.Visibility but no GuiDocument.xml. FreeCAD 1.1 GUI restore
creates view providers with all members hidden in that case. This bounded native
XML record supplies only visibility, leaving camera and visual styles at defaults.
Assemblies may also name installed Assembly joint view providers; their state is
the same base64 JSON null that FreeCAD's own GUI save writes.
"""
import os
from pathlib import Path
import shutil
import tempfile
from xml.etree import ElementTree as ET
from zipfile import ZipFile

# Only the installed Assembly workbench view providers may be restored by name.
PROXY_CLASSES = {'ViewProviderJoint', 'ViewProviderGroundedJoint'}
PROXY_MODULE = 'JointObject'
PROXY_STATE = 'bnVsbA=='


def serialize(visibility, proxies=None):
    proxies = proxies or {}
    if set(proxies) - set(visibility) or set(proxies.values()) - PROXY_CLASSES:
        raise ValueError('GUI proxy record differs from the controlled joint view providers')
    root=ET.Element('Document',{'SchemaVersion':'1'})
    data=ET.SubElement(root,'ViewProviderData',{'Count':str(len(visibility))})
    for name,visible in visibility.items():
        provider=ET.SubElement(data,'ViewProvider',{'name':name,'expanded':'0'})
        props=ET.SubElement(provider,'Properties',{'Count':'2' if name in proxies else '1','TransientCount':'0'})
        prop=ET.SubElement(props,'Property',{'name':'Visibility','type':'App::PropertyBool','status':'1'})
        ET.SubElement(prop,'Bool',{'value':'true' if visible else 'false'})
        if name in proxies:
            prop=ET.SubElement(props,'Property',{'name':'Proxy','type':'App::PropertyPythonObject'})
            ET.SubElement(prop,'Python',{'value':PROXY_STATE,'encoded':'yes','module':PROXY_MODULE,'class':proxies[name]})
    return ET.tostring(root,encoding='utf-8',xml_declaration=True)


def persist(path,visibility,proxies=None):
    """Atomically add native-format view state before artifact hashes are recorded."""
    path=Path(path)
    payload=serialize(visibility,proxies)
    with tempfile.NamedTemporaryFile(prefix=path.name+'.',suffix='.tmp',dir=path.parent,delete=False) as temp:
        temporary=Path(temp.name)
    try:
        with ZipFile(path) as source, ZipFile(temporary,'w') as target:
            for info in source.infolist():
                if info.filename=='GuiDocument.xml':continue
                with source.open(info) as reader,target.open(info,'w') as writer:
                    shutil.copyfileobj(reader,writer)
            target.writestr('GuiDocument.xml',payload)
        os.replace(temporary,path)
    finally:
        temporary.unlink(missing_ok=True)


def verify(path,visibility,proxies=None):
    proxies=proxies or {}
    from .document_xml import read_member, parse_xml
    with ZipFile(path) as archive:
        root=parse_xml(read_member(archive,'GuiDocument.xml',1024*1024),'GuiDocument.xml')
    if root.tag!='Document' or root.attrib!={'SchemaVersion':'1'} or len(root)!=1 or root[0].tag!='ViewProviderData':
        raise ValueError('GUI state document differs')
    data=root[0]
    if data.attrib!={'Count':str(len(visibility))} or len(data)!=len(visibility):
        raise ValueError('GUI view-provider count differs')
    observed={};observed_proxies={}
    for provider in data:
        name=provider.get('name')
        if provider.tag!='ViewProvider' or name in observed or name not in visibility or provider.attrib!={'name':name,'expanded':'0'}:
            raise ValueError('GUI view-provider identity differs')
        count='2' if name in proxies else '1'
        if len(provider)!=1 or provider[0].tag!='Properties' or provider[0].attrib!={'Count':count,'TransientCount':'0'}:
            raise ValueError('GUI property membership differs')
        props=provider[0]
        if len(props)!=int(count) or props[0].tag!='Property' or props[0].attrib!={'name':'Visibility','type':'App::PropertyBool','status':'1'}:
            raise ValueError('GUI visibility property type differs')
        prop=props[0]
        if len(prop)!=1 or prop[0].tag!='Bool' or len(prop[0]) or set(prop[0].attrib)!={'value'} or prop[0].get('value') not in ('true','false'):
            raise ValueError('GUI visibility value malformed')
        observed[name]=prop[0].get('value')=='true'
        if name in proxies:
            prop=props[1]
            if (prop.tag!='Property' or prop.attrib!={'name':'Proxy','type':'App::PropertyPythonObject'} or len(prop)!=1
                    or prop[0].tag!='Python' or len(prop[0])
                    or prop[0].attrib!={'value':PROXY_STATE,'encoded':'yes','module':PROXY_MODULE,'class':proxies[name]}):
                raise ValueError('GUI joint view-provider proxy differs')
            observed_proxies[name]=proxies[name]
    if observed!=visibility:raise ValueError('GUI visibility differs from selected output')
    if observed_proxies!=proxies:raise ValueError('GUI joint view-provider membership differs')
