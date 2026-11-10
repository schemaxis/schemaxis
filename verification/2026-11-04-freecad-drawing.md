
## Private GUI publication and circular label follow-up

The complete drawing qualifier passed on commit `da506b9`, FreeCAD 1.1.4, with
source digest `sha256:bca6619596792ec6a5ec386fb23ffa7484adccd681b8f1a30e864bdedbdda649`.
Four FCStd/STEP/cylinder/triangle projects pass actual exports, independent
geometry/dimensions, native effective private-directory/display/configuration
readback, semantic attacks, portable edit/fresh reopen, workflow reuse/damage and
source removal. Publication now uses the finite installed drawing/publish worker
with private Xvfb, D-Bus, configuration, application data and temporary paths;
independent batch probes use the same private batch wrapper as the product.

Independent 100 dpi PDF raster inspection found that the first implementation
placed radius and diameter labels on the same ray. That numeric-positive but
visually defective result was retained. Automatic circular labels now use
opposite leader directions with reserved margins and preserve native standard
R/diameter prefixes. The final cylinder PDF visibly shows distinct, readable
R5.000 mm and diameter10.000 mm labels. The three other final raster images are
byte-identical to the separately inspected successful enclosure/STEP/triangle
sheets. Exact PDF/PNG digests and review observations are retained privately.
Broader drawing-family gaps and final integrated product acceptance remain open.
