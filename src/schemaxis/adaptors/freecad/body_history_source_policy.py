"""Closed native property roles for finite primitive-seeded Body sources.

These classes supplement the existing typed history vocabulary only for the
recompiled bodyHistory contract. Whole trusted reconstruction remains mandatory.
"""


def extend(prepared,properties,extensions,transient):
    common={'ExpressionEngine':'App::PropertyExpressionEngine','Label':'App::PropertyString',
            'Label2':'App::PropertyString','Placement':'App::PropertyPlacement','Shape':'Part::PropertyPartShape',
            'ShapeMaterial':'Materials::PropertyMaterial','Visibility':'App::PropertyBool'}
    attached={**common,'AttacherEngine':'App::PropertyEnumeration','AttacherType':'App::PropertyString',
              'AttachmentOffset':'App::PropertyPlacement','AttachmentSupport':'App::PropertyLinkSubList',
              'MapMode':'App::PropertyEnumeration','MapPathParameter':'App::PropertyFloat','MapReversed':'App::PropertyBool'}
    boolean={**common,'Base':'App::PropertyLink','Tool':'App::PropertyLink','Refine':'App::PropertyBool'}
    known={'box':('Part::Box',{**attached,**{p:'App::PropertyLength' for p in ('Length','Width','Height')}},['Part::AttachExtension']),
           'cylinder':('Part::Cylinder',{**attached,'Radius':'App::PropertyLength','Height':'App::PropertyLength',
                     **{p:'App::PropertyAngle' for p in ('Angle','FirstAngle','SecondAngle')}},['Part::AttachExtension','Part::PrismExtension']),
           'cone':('Part::Cone',{**attached,**{p:'App::PropertyLength' for p in ('Radius1','Radius2','Height')},'Angle':'App::PropertyAngle'},['Part::AttachExtension']),
           'cut':('Part::Cut',boolean,[]),'fuse':('Part::Fuse',boolean,[])}
    properties=dict(properties);extensions=dict(extensions);transient=dict(transient)
    for node in prepared['nodes']:
        if node['filter'] not in known:continue
        kind,props,ext=known[node['filter']]
        properties[kind]=props;extensions[kind]=ext
        transient[kind]={'_ElementMapVersion':'App::PropertyString',
                         **({'History':'Part::PropertyShapeHistory'} if node['filter'] in ('cut','fuse') else {})}
    return properties,extensions,transient
