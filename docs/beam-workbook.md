# Cantilever stress table to a checked workbook

The [editable workflow](../examples/schemaxis/calculix-to-calc.json) combines a
bounded CalculiX cantilever with Calc's numeric workbook and named requirements.
Configure each native executable in your private Schemaxis configuration, then
run the workflow using the usual `schemaxis run` command.

The beam is 0.4 m long with a 0.02 m square section, Young's modulus 210 GPa,
Poisson ratio 0.3 and a −100 N end-face load in the z direction. It must satisfy
an absolute area-mean tip displacement limit of 0.0008 m and a sampled interior
normal-stress limit of 20 MPa. CalculiX's separate axial/transverse refinement,
beam-theory comparison and native reaction equilibrium checks apply first.

The workbook imports the verified interior Gauss-point table. Its four named
checks require the expected 1,280 samples, compressive and tensile extrema within
the declared intervals, and opposing extrema that reconcile within 10 Pa. These
checks apply independently to recalculated XLSX and reopened ODS values. The
column names explicitly carry SI units; CSV itself has no unit type system.

The [acceptance recipe](../tools/qualify_beam_workbook.py) reads native workbook
caches independently, checks their count/minimum/maximum against the captured
stress CSV, compares the beam's displacement and support reactions with literal
analytic expectations, and exercises reuse. Tightening the beam limit blocks the
workbook entirely. Tightening only the workbook stress limit preserves the
successful beam result but fails the consumer's acceptance.

```bash
PYTHONPATH=src python3 tools/qualify_beam_workbook.py \
  --config /absolute/path/to/private-config.json \
  --output-directory /absolute/path/to/fresh-evidence
```

The fixed sample count belongs to this fixture's mesh. Change it deliberately
when changing the mesh. The checks concern sampled interior normal stress and
area-mean tip displacement. They do not certify clamp/surface peak stress, yield,
fatigue, an arbitrary structural model or all mesh sizes. A passing numerical
check and a satisfied serviceability requirement are separate decisions.
