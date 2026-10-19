"""Trusted native attribute/table mapping; imported only in the QGIS subprocess."""
import json
from pathlib import Path
import attribute_contract as contract


def apply(layer, node, snapshot, directory, project):
    from qgis.core import QgsFeature, QgsGeometry, QgsVectorLayer, QgsWkbTypes
    options = node['options']; operation = node['filter']; location = node['id'] + '.options'
    snap = snapshot(layer); rows = [feature['attributes'] for feature in snap['features']]
    if operation == 'summariseAttributes':
        table = contract.summarise(rows, snap['fields'], options, location)
        (directory / ('summary-' + node['id'] + '.json')).write_text(json.dumps(table, indent=2, ensure_ascii=False, allow_nan=False) + '\n')
        (directory / ('summary-' + node['id'] + '.csv')).write_text(contract.csv_text(table))
        native = write_table(table, directory / ('summary-' + node['id'] + '.gpkg'), project)
        project.addMapLayer(native)
        return layer, table
    identities = set(contract.select(rows, snap['fields'], options, location))
    output = QgsVectorLayer(QgsWkbTypes.displayString(layer.wkbType()) + '?crs=' + layer.crs().authid(), node['id'], 'memory')
    provider = output.dataProvider()
    contract.require(provider.addAttributes(list(layer.fields())), 'cannot copy selected fields', location)
    output.updateFields(); features = []
    for source in layer.getFeatures():
        if source[options['idField']] not in identities: continue
        feature = QgsFeature(output.fields()); feature.setAttributes(source.attributes()); feature.setGeometry(QgsGeometry(source.geometry()))
        features.append(feature)
    contract.require(provider.addFeatures(features)[0], 'cannot populate selected features', location)
    output.updateExtents()
    return output, {'memberIds': sorted(identities)}


def native_rows(table):
    return [[json.dumps(row[c['name']], ensure_ascii=False, separators=(',', ':')) if c['name'] == 'memberIds'
             else row[c['name']] for c in table['columns']] for row in table['rows']]


def write_table(table, path, project):
    from qgis.core import QgsField, QgsFeature, QgsVectorLayer, QgsVectorFileWriter
    from qgis.PyQt.QtCore import QVariant
    native = QgsVectorLayer('None', path.stem, 'memory'); provider = native.dataProvider()
    types = {'string': QVariant.String, 'string[]': QVariant.String, 'boolean': QVariant.Bool,
             'integer': QVariant.LongLong, 'number': QVariant.Double}
    contract.require(provider.addAttributes([QgsField(c['name'], types[c['type']]) for c in table['columns']]), 'cannot create summary fields', path.name)
    native.updateFields(); features = []
    for row in native_rows(table):
        feature = QgsFeature(native.fields()); feature.setAttributes(row); features.append(feature)
    contract.require(provider.addFeatures(features)[0], 'cannot populate summary table', path.name)
    options = QgsVectorFileWriter.SaveVectorOptions(); options.driverName = 'GPKG'; options.layerName = 'summary'; options.fileEncoding = 'UTF-8'
    result = QgsVectorFileWriter.writeAsVectorFormatV3(native, str(path), project.transformContext(), options)
    contract.require(result[0] == QgsVectorFileWriter.NoError, 'cannot export summary table: ' + str(result), path.name)
    reopened = QgsVectorLayer(str(path) + '|layername=summary', path.stem, 'ogr')
    check_table(reopened, table)
    return reopened


def check_table(layer, table):
    from qgis.PyQt.QtCore import QVariant
    contract.require(layer.isValid() and not layer.isSpatial(), 'summary must reopen as a nonspatial table', layer.name())
    names = [field.name() for field in layer.fields() if field.name() != 'fid']
    contract.require(names == [c['name'] for c in table['columns']], 'summary table fields differ', layer.name())
    rows = []
    for feature in layer.getFeatures():
        row = []
        for name in names:
            value = feature[name]
            if value is None or isinstance(value, QVariant) and value.isNull(): value = None
            row.append(value)
        rows.append(row)
    # Database storage order is irrelevant; group identity and member ID array order are semantic.
    key = lambda row: json.dumps(row, sort_keys=True, ensure_ascii=False)
    contract.require(sorted(rows, key=key) == sorted(native_rows(table), key=key), 'summary table values differ', layer.name())
    return {'columns': names, 'rows': sorted(rows, key=key), 'spatial': False}
