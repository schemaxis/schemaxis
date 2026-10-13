# ngspice linear circuits through the document adaptor kit

The reviewed document scaffold now delivers `schemaxis.ngspice/1`: DC voltage
sweeps of resistor networks, linear AC sweeps of RC networks, and first-order RC
step responses. Shared source/property authoring, typed table/text inspection,
workflow reuse and the Calc handoff all use ordinary registry contracts. No
application-specific framework routing or host dependency was added.

The [official release page](https://ngspice.sourceforge.io/news.html) identified
**ngspice 47** (11 August 2026) as stable. Its source archive was downloaded from
the official distribution and compiled into an isolated ignored prefix. Native
`--version` reports ngspice-47. The [guide](../docs/ngspice.md) documents exact
operations, limits, SI units, phase convention, losses and recovery. No arbitrary
netlists, imported KiCad projects, semiconductors, device models, inductors or
general transient networks are exposed.

## Fresh native and independent checks

Nine native kit cases pass:

- A 1 kΩ / 2 kΩ divider gives 10/3 V from 5 V; equal resistors give 2.5 V.
- A first-order RC filter at ωRC=1 has response (1−j)/2: magnitude √(1/2),
  phase −45°. Doubling capacitance gives (1−2j)/5 at the same frequency.
- RC charging follows 5(1−exp(−t/RC)); doubling R doubles the time constant.
- A signed divider sweep from −5 V to zero retains correct polarity and endpoint.
- A balanced resistive bridge has equal half-source midpoint voltages.
- A two-stage RC ladder at ωRC=1 has output −j/3 and midpoint (1−j)/3.

Independent host complex nodal equations check every native voltage for DC/AC,
including unselected nodes. Analytic first-order dynamics check the entire RC
curve. Sample coordinates/counts, all CSV phasor conversions and summary data are
verified. The host separately parses saved ASCII raw data, and a second native
process reopens it. A forged raw-file digest cannot hide changed variable names.
All **108 missing/tampered evidence probes** and both lifecycle checks pass.

Native investigation caught a real boundary: ngspice 47 emits one sample for a
requested two-point linear AC sweep. The host now requires **3–512 AC points**;
it never treats a missing endpoint as success. AC allows at most fifteen selected
probes so four columns per probe fit the shared 64-column table contract. DC/RC
still allow two points. Nonrepresentable sample spacing is rejected before launch.

ngspice → Calc passes both divider variants and complete numeric workbook
readback; all jobs reuse on unchanged resume. The deterministic public context,
source/property, plan/execute/inspect loop checks all nine cases and rejects a
floating circuit. A real terminal-console patch edits the same durable document,
rejects the old plan as stale and changes the verified output from **10/3 to 2.5 V**.
The final public/human sequence made **180 requests / 145,773 response bytes**. This is
protocol/procedure evidence, not an autonomous-model evaluation.

## Shared release support and provenance

Ngspice's whole-number release required the narrow stable-version parser change
recorded in [the refresh evidence](2026-09-28-whole-number-releases.md). All thirteen
previously qualified routes were freshly rerun and recorded after that shared
source change; no receipt digest was edited to imply freshness. Ngspice adds the
fourteenth source-current native route. The experimental case-preparation route
remains host-qualified only.

Bulk evidence is under `evidence/ngspice-complete-acceptance/` and
`evidence/adaptor-extension-refresh/`. Earlier failed/two-point probes remain
retained. User configuration and PATH are unchanged.

```sh
PYTHONPATH=src python3 tools/qualify_ngspice.py \
  --config /path/to/private-config.json --output-directory new-acceptance
PYTHONPATH=src python3 -m schemaxis adaptor record new-acceptance/native/qualification.json
PYTHONPATH=src python3 -m schemaxis readiness --admission --check
PYTHONPATH=src python3 tools/qualify_adaptor_migration.py --output-directory new-host
PYTHONPATH=src python3 -m unittest discover -s tests/unit -q
```

## Final verification hardening and packaging

A saved `result.json` containing a JSON array, null, boolean or string previously
raised `AttributeError` instead of a structured verification fault. Gmsh, Cantera
and ngspice now report `VERIFICATION_FAILED` for those malformed envelopes.
Twelve probes on real native directories pass, and restoring the original bytes
restores successful verification. The three affected native kits were freshly
rerun and recorded under `evidence/adaptor-result-hardening/` after the source fix.
This supersedes their earlier source fingerprints, without changing successful
workflow semantics or independent numerical tolerances.

The final wheel builds and installs in an isolated target. Installed-package
planning and offline verification pass for Gmsh faces, Cantera TP equilibrium and
ngspice AC response, including malformed-result rejection. All required package
resources are present. See `evidence/adaptor-extension-package-check.json`.

The final signed-source probe exposed a coordinate-roundoff bug for a DC sweep
ending at zero: its absolute allowance had been scaled only by the stop value.
The allowance now uses the full interval, preserving the existing relative
coordinate tolerance and independent voltage tolerances. A permanent 101-point
negative-to-zero kit case and host rejection of a materially shifted coordinate
cover the fix. Negative AC amplitude and negative RC-step probes also pass.

## Final catalogue checks

**759 unit tests passed, 22 skipped (781 total)** in 199.744 seconds
on the final code. Both progressive capability protocol tests pass (61.042 seconds).
All **56 generated references** are current; all **thirteen adaptors / fifteen routes**
pass development admission and host conformance. Fourteen source-current native
receipts cover **43 cases, 460 integrity probes and 28 lifecycle probes**, with the
twelve malformed-result shape checks retained separately. The latest ngspice
release monitor reports 47 current.

Logs: `evidence/adaptor-extension-unit-verified.log`,
`evidence/adaptor-extension-protocol.log`,
`evidence/adaptor-extension-admission-final.json` and
`evidence/adaptor-extension-final-status.json`. The first full circuit run
failed one obsolete hard-coded count of non-node routes; the registry-based check
and all later final checks pass. Skips remain distinct from native qualification.
