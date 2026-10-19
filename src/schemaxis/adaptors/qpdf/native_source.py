"""Trusted MuPDF observer script; authored input contributes validated JSON numbers and fixed file names, never code."""
import json

OBSERVER = r'''
var docs = {}, records = [], pixels = 0, text = 0, s = config.dpi / 72;
var M = [s, 0, 0, s, 0, 0];
function open(file) {
  if (!docs[file]) {
    var d = mupdf.Document.openDocument(file).asPDF();
    if (!d) throw new Error("PDF_REQUIRED");
    if (d.needsPassword() || d.getTrailer().get("Encrypt")) throw new Error("ENCRYPTED_PDF");
    if (d.wasRepaired()) throw new Error("PDF_REPAIRED");
    docs[file] = d;
  }
  return docs[file];
}
function box(o, name) {
  var v = o.get(name);          // page-local only: boxes and UserUnit never inherit
  if (!v || v.isNull()) return null;
  return [v.get(0).asNumber(), v.get(1).asNumber(), v.get(2).asNumber(), v.get(3).asNumber()];
}
for (var i = 0; i < config.jobs.length; ++i) {
  var j = config.jobs[i], doc = open(j.file), count = doc.countPages();
  if (j.page < 1 || j.page > count) throw new Error("PDF_PAGE_RANGE");
  var obj = doc.findPage(j.page - 1);
  var inherited = obj.getInheritable("Rotate");
  var local = obj.get("Rotate");
  var record = {page: j.page, pageCount: count, originalRotate: inherited && !inherited.isNull() ? inherited.asNumber() : 0};
  // In-memory only: the captured PDF is never saved or modified. The page-local Rotate is set before the page is loaded.
  if (j.rotation !== null) obj.put("Rotate", doc.newInteger(j.rotation));
  var page = doc.loadPage(j.page - 1);
  var bounds = page.getBounds("CropBox");
  var unit = obj.get("UserUnit");
  record.bounds = bounds;
  record.userUnit = unit && !unit.isNull() ? unit.asNumber() : null;
  record.mediaBox = box(obj, "MediaBox");
  record.cropBox = box(obj, "CropBox");
  var effective = obj.getInheritable("Rotate");
  record.rotation = effective && !effective.isNull() ? effective.asNumber() : 0;
  var t = mupdf.Rect.transform(bounds, M);
  var w = Math.ceil(t[2] - t[0] - 0.001), h = Math.ceil(t[3] - t[1] - 0.001);
  pixels += w * h;
  record.predicted = [w, h];
  if (!(w >= 1 && h >= 1 && w <= config.maxSide && h <= config.maxSide && pixels <= config.maxPixels)) throw new Error("PDF_PIXEL_LIMIT");
  var pix = page.toPixmap([M[0], M[1], M[2], M[3], -t[0], -t[1]], mupdf.ColorSpace.DeviceRGB, false, true, "View", "CropBox");
  var pb = pix.getBounds();
  record.pixmap = [pb[2] - pb[0], pb[3] - pb[1]];
  if (record.pixmap[0] !== w || record.pixmap[1] !== h) throw new Error("PDF_PIXEL_MISMATCH");
  pix.saveAsPNM(j.output);
  record.text = page.toStructuredText("preserve-whitespace").asText();
  text += record.text.length;
  if (record.text.length > config.maxPageText || text > config.maxText) throw new Error("PDF_TEXT_LIMIT");
  // Restore page-local state so repeated jobs for one page cannot leak into each other.
  if (j.rotation !== null) { if (local && !local.isNull()) obj.put("Rotate", local); else obj["delete"]("Rotate"); }
  records.push(record);
}
for (var f in docs) if (docs[f].wasRepaired()) throw new Error("PDF_REPAIRED");
print(JSON.stringify(records));
'''


def source(jobs, dpi, max_side, max_pixels, max_page_text, max_text):
    """jobs: [{'file','page','rotation'|None,'output'}] with fixed names validated by the caller."""
    config = {'dpi': dpi, 'maxSide': max_side, 'maxPixels': max_pixels, 'maxPageText': max_page_text,
              'maxText': max_text, 'jobs': jobs}
    return 'var config = ' + json.dumps(config, ensure_ascii=True, allow_nan=False, sort_keys=True) + ';\n' + OBSERVER
