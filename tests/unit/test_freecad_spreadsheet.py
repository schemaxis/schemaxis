"""Spreadsheet quantities, dependency intent and independent driver intervals."""
import copy
import unittest
from schemaxis.adaptors.freecad import adaptor, spreadsheet
from schemaxis.core.faults import SchemaxisError


def design():
    return {'version':'schemaxis.freecad/1','spreadsheet':{
      'inputs':{'stock':{'value':3,'minimum':2,'maximum':5,'unit':'cm'},
                'wall':{'value':.1,'minimum':.05,'maximum':.2,'unit':'in'}},
      'formulas':{'inner':{'terms':{'stock':1,'wall':-2}},
                  'length':{'terms':{'inner':2},'offset':{'value':10,'unit':'mm'}}}},
      'nodes':[{'id':'block','filter':'box','options':{'width':10},
                'drive':{'length':{'terms':{'length':1}},'height':{'terms':{'wall':1}}}}],
      'output':'block'}


class SpreadsheetTests(unittest.TestCase):
    def test_units_formula_chain_and_authored_intent(self):
        doc=design();original=copy.deepcopy(doc);p=adaptor.plan(doc)
        self.assertEqual(doc,original)
        self.assertAlmostEqual(p['nodes'][0]['options']['length'],59.84)
        self.assertAlmostEqual(p['nodes'][0]['options']['height'],2.54)
        self.assertEqual(p['spreadsheet']['cells'],{'stock':'B2','wall':'B3','inner':'B4','length':'B5'})
        self.assertEqual(p['spreadsheet']['expanded']['length'],{'terms':{'stock':2,'wall':-4},'offset':10})
        self.assertEqual(spreadsheet.contents(p['spreadsheet'])['B5'],'=2 * dim_inner + 10 mm')
        self.assertEqual(p['parameters']['wall']['maximum'],5.08)

    def test_correlated_alias_bounds_use_independent_inputs(self):
        doc=design();doc['spreadsheet']={'inputs':{'x':{'value':20,'minimum':10,'maximum':30,'unit':'mm'}},
          'formulas':{'double':{'terms':{'x':2}},'plus':{'terms':{'x':1},'offset':{'value':5,'unit':'mm'}}}}
        doc['nodes'][0]['drive']={'length':{'terms':{'double':1,'plus':-1}},'height':{'terms':{'x':1}}}
        p=adaptor.plan(doc)
        self.assertEqual(p['nodes'][0]['options']['length'],15)
        doc['nodes'][0]['drive']['length']['offset']=-5
        with self.assertRaises(SchemaxisError):adaptor.plan(doc)

    def test_cycles_missing_references_unused_and_cancelled_drivers_refused(self):
        for change in [lambda s:s['formulas']['inner']['terms'].__setitem__('length',1),
                       lambda s:s['formulas']['inner']['terms'].__setitem__('external',1),
                       lambda s:s['inputs'].__setitem__('unused',{'value':1,'minimum':.5,'maximum':2,'unit':'mm'})]:
            d=design();change(d['spreadsheet'])
            with self.subTest(change=change),self.assertRaises(SchemaxisError):adaptor.plan(d)
        d=design();d['spreadsheet']['formulas']['cancel']={'terms':{'stock':1,'inner':-1,'wall':-2}}
        d['nodes'][0]['drive']['length']={'terms':{'cancel':1},'offset':10}
        with self.assertRaises(SchemaxisError):adaptor.plan(d)
        d=design();d['spreadsheet']['formulas']['length']={'terms':{'inner':1,'stock':-1},'offset':{'value':20,'unit':'mm'}}
        # stock is syntactically referenced but algebraically cancels from all targets.
        with self.assertRaises(SchemaxisError):adaptor.plan(d)

    def test_no_native_expression_paths_or_ambiguous_quantity_units(self):
        for value in ['App.ActiveDocument.X',True,float('nan'),float('inf'),10**1000]:
            d=design();d['spreadsheet']['inputs']['stock']['value']=value
            with self.subTest(value=repr(value)[:30]),self.assertRaises(SchemaxisError):adaptor.plan(d)
        for unit in ['inch','ft','__import__(x)','deg',None,{}]:
            d=design();d['spreadsheet']['inputs']['stock']['unit']=unit
            with self.subTest(unit=unit),self.assertRaises(SchemaxisError):adaptor.plan(d)
        for alias in ['Other.alias','_hidden','x'*65]:
            d=design();d['spreadsheet']['inputs'][alias]=d['spreadsheet']['inputs'].pop('stock')
            with self.subTest(alias=alias),self.assertRaises(SchemaxisError):adaptor.plan(d)
        d=design();d['parameters']={'x':{'kind':'length','value':1,'minimum':.5,'maximum':2}}
        with self.assertRaises(SchemaxisError):adaptor.plan(d)


    def test_native_cell_grammar_refuses_coforged_equivalent_current_values(self):
        table,params=spreadsheet.prepare(design()['spreadsheet'])
        raw=spreadsheet.contents(table)
        texts={cell:(text if text.startswith('=') else '=' + text if cell in table['cells'].values() else "'"+text) for cell,text in raw.items()}
        spreadsheet.verify_contents(table,texts)
        for cell,text in [('B2','=30 mm + 0 mm'),('B4','=1 * dim_stock + -2 * dim_wall + 0 mm # hidden'),
                          ('B5','=1 * dim_inner + 34.92 mm'),('B5','=sin(dim_inner)'),('A2',"'other")]:
            mutated=dict(texts);mutated[cell]=text
            with self.subTest(cell=cell,text=text),self.assertRaises(SchemaxisError):spreadsheet.verify_contents(table,mutated)
        texts['B2']='=30 mm';spreadsheet.verify_contents(table,texts)

    def test_entire_saved_sheet_object_refuses_transients_extensions_and_role_changes(self):
        from xml.etree import ElementTree as E
        table,_=spreadsheet.prepare(design()['spreadsheet'])
        obj=E.Element('Object',name='SchemaxisParameters');container=E.SubElement(obj,'Properties',Count='7',TransientCount='0')
        for name,typ in spreadsheet.PERSISTENT.items():
            prop=E.SubElement(container,'Property',name=name,type=typ,status=str(spreadsheet.PROPERTY_STATUS[name]))
            if name=='ExpressionEngine':E.SubElement(prop,'ExpressionEngine',count='0')
            elif name in ('Label','Label2'):E.SubElement(prop,'String',value=spreadsheet.LABEL if name=='Label' else '')
            elif name=='Visibility':E.SubElement(prop,'Bool',value='false')
            elif name in ('columnWidths','rowHeights'):E.SubElement(prop,'ColumnInfo' if name=='columnWidths' else 'RowInfo',Count='0')
            else:
                content=spreadsheet.contents(table);cells=E.SubElement(prop,'Cells',Count=str(len(content)),xlink='1');E.SubElement(cells,'XLinks',count='0')
                inverse={cell:alias for alias,cell in table['cells'].items()}
                for cell,text in content.items():
                    alias=inverse.get(cell)
                    attrs={'address':cell,'content':text if text.startswith('=') else '='+text if alias else "'"+text}
                    if alias:attrs.update(alias='dim_'+alias,displayUnit=table['inputs'][alias]['unit'] if alias in table['inputs'] else 'mm')
                    E.SubElement(cells,'Cell',attrs)
        spreadsheet.verify_saved_object(table,obj)
        touched=copy.deepcopy(obj);p=touched.find("./Properties/Property[@name='Visibility']");p.set('status',str(int(p.get('status'))|1))
        spreadsheet.verify_saved_object(table,touched)
        def transient(o):
            p=o[0];p.set('TransientCount','1');E.SubElement(E.SubElement(p,'_Property',name='Proxy',type='App::PropertyPythonObject',status='1'),'Python',value='marker')
        def extension(o):
            o.set('Extensions','True');E.SubElement(o,'Extensions',Count='0')
        def role(o):o.find("./Properties/Property[@name='cells']").set('status','0')
        for mutate in (transient,extension,role):
            changed=copy.deepcopy(obj);mutate(changed)
            with self.subTest(mutate=mutate),self.assertRaises(SchemaxisError):spreadsheet.verify_saved_object(table,changed)
