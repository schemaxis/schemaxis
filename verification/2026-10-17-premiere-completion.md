# Premiere named-track layout strengthening — 17 October 2026

Status: implemented host-side and documented; native unqualified. Existing
`sequenceContract` remains supported. `sequenceLayout` adds complete ordered named
video tracks, explicit source/timeline ranges, gaps/overlays, empty tracks and
named minimum-active-track coverage gates. No native editing or export.

## Completion review

| Checklist | Result for changed scope |
| --- | --- |
| registration | Existing `schemaxis.premiere/1` document route, two declared operations; original transport/runtime/support limits retained. Layout publishes observation and independent report. |
| schema | Complete typed nested track/clip/requirement declarations; operation-specific root fields rejected; schema parity and authored composition tests. |
| semantics | Exact integer ticks, half-open boundaries, complete unique names/order, within-track non-overlap, bounds, positive durations, exact source/timeline lengths, selected-track requirement validity. No rounding, fractional rates or arbitrary authored code. |
| native-mapping | Public UXP VideoTrack name/index/isMuted/getTrackItems plus existing Sequence and VideoClipTrackItem queries. Two complete observations and active identity checks retained. No native readback qualification on this host. |
| execution | Existing fresh nonce/hash/expiry job lifecycle reused. Layout report rebuilt from observed tick intervals on reopening; failed coverage retains missing frames and fails result. Baseline/variant/tampering tested with actual companion and fixed host DOM doubles, explicitly not native. |
| discovery | Adaptor-owned curated layout/gap/intersection phrases, ambiguous inspection and negative rendering cases across capability/Add/Help/adaptor projections. Root owns generated projection integration. |
| guidance | Every new operation/nested field/schema alternative has reviewed conceptual guidance, units/defaults/bounds/mistakes. Audit: 40 reviewed, 2 attributed, zero pending/stale. |
| help | Local guide covers complete-track intent, native preparation, faults/recovery, report meaning and native limits. Generated references/packaged Help are root integration outputs. |
| examples | Editable baseline and independent held-out layout, semantic overlap-invalid fixture and Studio template. Native prerequisite paths intentionally require replacement; host examples are usable without file reads. |
| tests | Legacy host transport regression plus layout schema/planning/semantics, literal DOM mapping, independent gap/overlay oracle, altered report/observation/response/plan/authored rejection, real Linux unavailable failure. Details below. |
| qualification | No native receipt. Real local runner fails NATIVE_ENVIRONMENT_UNAVAILABLE on Linux; do not count Node doubles or a passing host conformance as native success. |
| maintenance | Stable application release source corrected to catch 26.5.2 patch release, checked 17 October. API minimum remains 26.5.0. absorbedVersion remains null. Explicit opt-in native layout acceptance recipe retained. |

## Independent semantic oracle

Planner derives exact ticks from authored frames; verifier separately rasterises
observed intervals into at most 8 × 600 boolean frame cells. The Node DOM fixture
contains fixed literal native ticks and never derives observed ranges from the
request. Baseline Base occupancy is 8 frames with gap `[4,6)`; Overlay occupancy
is 4 with gaps `[0,3)`, `[7,10)`; Reserved occupancy is zero. Their union covers
all ten frames; both are active at frame 3. Held-out Overlay `[4,6)` has only two
occupied frames and no intersection, but preserves union coverage. Base-only
coverage fails with literal missing frames `[4,5]` and a failed result.

Tests reject zero lengths, overlaps, extra fields, duplicate/unknown track names,
invalid thresholds, sequence-end inconsistency, off-grid boundaries by one tick,
source/timeline/duration mismatch, muted tracks, disabled clips, stale responses,
changed request or sequence and oversized native tracks. Adjacent boundaries and
an empty declared track are accepted. Exact layout comparison occurs before a
coverage decision; a gate cannot hide a different native cut.

## Native availability and upstream basis

Linux is outside the supported Adobe host platforms. Native execution of the new
layout through the ordinary runner records `NATIVE_ENVIRONMENT_UNAVAILABLE`;
no licences, installation or system changes were attempted. Run
`tools/qualify_premiere_layout.py` on Windows/macOS with an independently prepared
saved project and the supplied panel before claiming native acceptance. The
native recipe also checks a failure gate and retained evidence mutation.

Reviewed public sources on 17 October 2026:

- [Stable release notes](https://helpx.adobe.com/premiere/desktop/whats-new/release-notes.html): latest listed stable application 26.5.2; application patch tracking replaces API-only release tracking.
- [UXP changelog](https://developer.adobe.com/premiere-pro/uxp/changelog/): API baseline 26.5.0 includes host applicationPath.
- [VideoTrack](https://developer.adobe.com/premiere-pro/uxp/ppro-reference/classes/videotrack): name, index, mute and bounded clip/transition arrays.
- [VideoClipTrackItem](https://developer.adobe.com/premiere-pro/uxp/ppro-reference/classes/videocliptrackitem): exact source/timeline/duration queries and disabled/reversal state.
- [System requirements](https://helpx.adobe.com/premiere/desktop/get-started/technical-requirements/adobe-premiere-pro-technical-requirements.html): Windows/macOS native hosts.

An editorial interval does not prove visible footage. Opacity, masks, effects,
source bytes, rendered output and intermediate time remapping remain uninspected.
Equal endpoint lengths do not prove constant intermediate playback. The panel
never changes the project. Concurrent edits can escape two matching observations;
this is not an atomic snapshot or a signed attestation against local fabrication.

## Verification commands and retained evidence

Worker ran 16 host unit tests (10 legacy, 6 new), including actual UXP companion
Node execution with fixed DOM doubles; all passed. Guidance audit passes with
zero pending/stale addresses. Host conformance and final admission pass. Root regenerated references and
packaged Help, passed the targeted Studio Help/adaptor-search suite, independently
reviewed the changed planner/observer and reran all 16 Premiere tests successfully.
These checks do not change native-unqualified status. Bulk evidence is retained
in `evidence/programme-20261017/premiere-host-final/qualification.json`,
`premiere-admission-final.json`, `premiere-tests-final.txt`,
`premiere-help-search.log`, `premiere-guidance-final.txt`, and the real failed
`premiere-native-unavailable` run.

```sh
PYTHONPATH=src python3 -m unittest discover -s tests/unit -p 'test_premiere*.py' -q
PYTHONPATH=src python3 tools/studio_guidance.py --app premiere --check
PYTHONPATH=src python3 -m schemaxis adaptor conform schemaxis.premiere/1 --output-directory evidence/programme-20261017/premiere-host
PYTHONPATH=src python3 -m schemaxis readiness --app premiere --admission --check
```
