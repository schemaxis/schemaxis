# CFD post-processing tutorial inputs

Read the [step-by-step user guide](../../docs/cfd-postprocessing.md) first. These
are complete **Schemaxis ParaView** inputs (`schemaxis/1`), not ParaView state files.

| File | Start here when… | Planned outputs at its sample one-time settings |
| --- | --- | --- |
| [01-read-case.json](01-read-case.json) | You want to check your reader, fields and first image. | 1 PNG |
| [02-reusable.json](02-reusable.json) | You want reusable case settings, dimension-driven slices, overview/detail windows, two appearances, an iso-surface orbit, a profile and domain integrals. | 16 PNGs, 4 geometry files, 2 CSVs |
| [03-spaced-slices.json](03-spaced-slices.json) | You want a physical slice spacing rather than a fixed slice count. | 16 PNGs, 4 geometry files |
| [04-streamlines.json](04-streamlines.json) | You want line seeds, a streamline geometry export and tubes for display. | 1 PNG, 1 geometry file |

Copy an input into your own study folder. Configure `settings.case`, `caseType`,
`times`, actual field names and ranges. Replace the illustrative dimensions,
iso-value and seed/sample positions with values appropriate to your case. The
examples assume Z up. `Reconstructed Case` is explicit; change it for decomposed
results. The `.foam` marker does not contain the underlying mesh or fields.

Use [paraview.authored.schema.json](../../docs/generated/paraview.authored.schema.json)
for the **whole file**. The analytics/composition schemas describe fragments and
are already incorporated in the full schema. The spelling is `$analytic`, singular.

From the repository root, host-only checks need no native application or case:

```bash
PYTHONPATH=src python3 -m schemaxis plan examples/cfd-postprocess/01-read-case.json
PYTHONPATH=src python3 -m schemaxis plan examples/cfd-postprocess/02-reusable.json
```

Those checks do not prove your files exist or that the example is physically
meaningful for your data. Run and inspect the small reader example before the
larger study. Native execution needs ParaView and fresh output directories as
shown in the guide. Latest-time selection is optional; the default explicit
`[1.0]` is only a placeholder for an actual saved solution time.

These inputs have schema/host-plan verification. No new native CFD qualification
is claimed for them. Existing evidence and target-version acceptance limits are
in the [handoff guide](../../docs/cfd-guide.md). For a broader choice of filters,
readers and writers, see the [CFD operation directory](../../docs/cfd-operations.md).
