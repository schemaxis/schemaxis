"""Trusted MuPDF scripts; authored input contributes JSON values, never code."""
import json

PREFLIGHT = r'''
var doc = mupdf.Document.openDocument("source.pdf").asPDF();
if (!doc) throw new Error("PDF_REQUIRED");
if (doc.getTrailer().get("Encrypt") || doc.needsPassword()) throw new Error("ENCRYPTED_PDF");
var count = doc.countPages();
if (doc.wasRepaired()) throw new Error("PDF_REPAIRED");
if (count < 1 || count > 128) throw new Error("PDF_PAGE_LIMIT");
var pages = [];
for (var i = 0; i < config.pages.length; ++i) {
  var number = config.pages[i];
  if (number > count) throw new Error("PDF_PAGE_RANGE");
  var page = doc.loadPage(number - 1);
  var object = doc.findPage(number - 1);
  var box = function(name) {
    var o = object.getInheritable(name);
    if (!o || o.isNull()) return null;
    return [o.get(0).asNumber(),o.get(1).asNumber(),o.get(2).asNumber(),o.get(3).asNumber()];
  };
  var bounds = page.getBounds("CropBox");
  var width = bounds[2]-bounds[0], height = bounds[3]-bounds[1];
  if (!(width > 0 && height > 0 && width <= 14400 && height <= 14400)) throw new Error("PDF_GEOMETRY_LIMIT");
  pages.push({page:number,bounds:bounds,mediaBox:box("MediaBox"),cropBox:box("CropBox"),
    userUnit: object.get("UserUnit") ? object.get("UserUnit").asNumber() : 1,
    inheritedRotation:object.getInheritable("Rotate") ? object.getInheritable("Rotate").asNumber() : 0});
}
'''


def source(prepared, stage):
    config = {key: prepared[key] for key in ('pages', 'dpi', 'rotation')}
    script = 'var config = ' + json.dumps(config, ensure_ascii=True, allow_nan=False) + ';\n' + PREFLIGHT
    if stage == 'inspect':
        return script + 'if (doc.wasRepaired()) throw new Error("PDF_REPAIRED");\nprint(JSON.stringify({pageCount:count,pages:pages}));\n'
    # Never enable PDF JavaScript, execute actions, follow links, load attachments,
    # or accept authored paths in MuPDF. Rendering uses one fixed local file.
    script += '''
var total = 0;
var textTotal = 0;
var s = config.dpi / 72;
var matrices = [[s,0,0,s,0,0],[0,s,-s,0,0,0],[-s,0,0,-s,0,0],[0,-s,s,0,0,0]];
var matrix = matrices[config.rotation / 90];
for (var i = 0; i < pages.length; ++i) {
  var b = mupdf.Rect.transform(pages[i].bounds, matrix);
  var w = Math.ceil(b[2]-0.001)-Math.floor(b[0]+0.001);
  var h = Math.ceil(b[3]-0.001)-Math.floor(b[1]+0.001);
  total += w*h;
  if (w<1 || h<1 || w>4096 || h>4096 || total>16777216) throw new Error("PDF_PIXEL_LIMIT");
}
for (var i = 0; i < pages.length; ++i) {
  var page = doc.loadPage(pages[i].page - 1);
  var pix = page.toPixmap(matrix, mupdf.ColorSpace.DeviceRGB, false, true, "View", "CropBox");
  pix.setResolution(config.dpi, config.dpi);
  var name = "page-" + ("000"+(i+1)).slice(-3);
  pages[i].pixelBounds = pix.getBounds();
  pages[i].resolution = [pix.getXResolution(),pix.getYResolution()];
  pages[i].text = page.toStructuredText("preserve-whitespace").asText();
  textTotal += pages[i].text.length;
  if (pages[i].text.length>1048576 || textTotal>4194304) throw new Error("PDF_TEXT_LIMIT");
'''
    if stage == 'render':
        script += '  pix.saveAsPNG(name + ".png");\n'
    else:
        script += '  pix.saveAsPNM(name + ".pnm");\n'
    return script + '}\nif (doc.wasRepaired()) throw new Error("PDF_REPAIRED");\nprint(JSON.stringify({pageCount:count,pages:pages}));\n'
