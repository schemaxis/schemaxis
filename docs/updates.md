# Latest-release maintenance

Each app has one implementation in `src/schemaxis/adaptors/<app>/`. The target is
its latest **stable** upstream release, including a newer major release even when
an older LTS series remains maintained. Prereleases are excluded. Introduce parallel
runtime families only for an unavoidable divergence such as Python 2 versus Python 3,
with rationale and separate acceptance requirements. Input document versions remain
independent of upstream application versions.

The existing historical qualification baselines are preserved honestly. This policy
does not retroactively qualify today's latest releases. `upstream.json` in each app
folder owns its official release source, absorbed version, evidence references and
native acceptance requirements. Update the baseline only after the target release
passes the required checks; an installed version alone does not absorb an update.

```bash
schemaxis updates
schemaxis updates --app blender --app paraview
schemaxis updates --prepare evidence/updates
```

Choose a new or empty `--prepare` directory so older repair briefs cannot be mistaken
for current tasks. Both JSON and readable Markdown reports are written there.

The JSON report lists `updates` (confirmed unabsorbed releases with work estimates),
`attention` (failed, stale or manual checks) and `current` app IDs. Network calls
have timeouts, use official project sources and run concurrently. A failed lookup
never becomes “up to date”. An adaptor whose upstream releases cannot be read from
an official source is explicitly reported as a manual check.

Estimates are **low-confidence person-day ranges**, based on major/minor/patch
distance and declared operation count. They include likely review, repair and
qualification work, not elapsed download/build time. They cannot predict API changes;
ParaView's broad catalogue receives a larger allowance. Refine them after reproducing
failures against the target runtime.

The weekly `Upstream application updates` GitHub Actions workflow also supports
manual dispatch. It produces a job summary and a downloadable `application-updates`
artifact containing the report and one repair brief per pending app. It starts
running once this workflow is pushed to the repository's default branch and Actions
scheduling is enabled. It has read-only repository permissions and surfaces failed
release checks as failed jobs after preserving the report.

## Runtime compatibility profiles

Five identities are kept separate:

| Identity | Source |
| --- | --- |
| Core package | the installed `schemaxis` distribution version |
| Adaptor revision | the adaptor's conservative source digest, also used by qualification |
| Authored schema route | the input document `version`, for example `schemaxis/1` |
| Observed application | version, build and platform reported by the native process |
| Profile and qualification | `compatibility` in `upstream.json`, and `qualification.json` |

An adaptor may add a `compatibility` object to its `upstream.json`, beside
`absorbedVersion`. Each profile names exact numeric releases. Ranges, wildcards and
prefixes are rejected so that a profile cannot claim a release nobody has observed:

```json
"compatibility": {
  "protocol": "schemaxis.compatibility/1",
  "profiles": [{
    "id": "paraview-5.13.3", "status": "observed", "versions": ["5.13.3"],
    "routes": ["schemaxis/1"], "modes": ["serial"],
    "evidence": ["verification/…"], "scope": "…"
  }]
}
```

`observed` profiles need evidence and execution modes that the adaptor declares.
`unsupported` profiles need a `reason`. They record known-bad releases and do not
refuse execution. If two profiles claim the same route and release, the data is
rejected with `AMBIGUOUS_COMPATIBILITY_PROFILE`; profile order never decides.
`absorbedVersion` must have an observed profile for every declared route; a
missing or unsupported route prevents absorption regardless of profile order. Other faults use
`INVALID_COMPATIBILITY_PROFILE`. Adaptors without the object report `undeclared`.
They are not required to adopt profiles.

Selection reports one of `absent` (no identity recorded, as in earlier receipts),
`unavailable` (the runtime could not report it), `invalid` (malformed, another app,
or the launcher's `--version` disagrees with the in-process report), `unqualified`
(no profile names this release and route), `unsupported` or `observed`. The capability
for the requested mode is reported separately: `observed`, `unqualified` (the release
is observed, but not in this mode), `undeclared`, `unsupported` or `unknown`.

Identity fields other than `application` and `version` are optional, but when present
they must be well typed: `build`, `source` and `fault` are nonempty strings, and
`platform` maps any of `system`, `machine` and `python` to nonempty strings. A
malformed field, including a malformed `fault`, reports `invalid`, not `unavailable`.

A profile match is not qualification. Each report also includes the route's
development-kit qualification status (`source-current`, `stale` or `unknown`) with its
original reason and receipt scope, and the runtime versions recorded in that receipt.
`coversObservedVersion` checks release-number equality only. It establishes no
platform, build or plugin equivalence and no coverage of other operations, and a
profile match never upgrades the qualification status.

ParaView is the first adopter. It declares only its observed 5.13.3 serial baseline.
Each serial or MPI `pvbatch` receipt (`verification.json`) records `runtimeIdentity`,
and both `result.json` and `schemaxis verify` include a `compatibility` report.
Receipts that predate this field still verify and report `absent`. The identity is
self-reported and informative only. It does not change receipt verification or
execution, and profile-data faults are reported instead of raised.

Check profiles and preview a selection without starting an application:

```bash
schemaxis adaptor compatibility paraview
schemaxis adaptor compatibility paraview --app-version 5.13.4 --mode mpi
```

`--route` must be a route the requested adaptor declares (its default route when
omitted); another adaptor's or an unknown route is rejected with an
`UNSUPPORTED_VERSION` fault before a compatibility report is assembled. Only
structured `runtime.version` strings in a receipt count as recorded versions:
legacy free-text runtimes are never parsed, so `runtimeVersions` stays empty and
`coversObservedVersion` is `null` for them. A malformed `upstream.json` is an
`INVALID_COMPATIBILITY_PROFILE` fault.

`--app-version` supplies a hypothetical candidate, not a native observation. The
report sets `identitySource` to `supplied`, places the candidate under `candidate`
and leaves `observed` empty; its reason and scope say no runtime was started or
observed. A candidate can match the historically observed baseline without implying
that the installed runtime is that release. Receipts record native self-reports with
`identitySource` set to `native-self-report`; a receipt identity claiming
`source: supplied` is `invalid`.

To re-baseline after a release passes its native acceptance, add a profile for the
new release with its evidence. Advance `absorbedVersion` in the same change; add
`unsupported` profiles only when there is evidence. Do not duplicate the adaptor
or widen an existing profile to versions that have not been tested.

## AI-assisted absorption

`--prepare` creates an app-scoped task suitable for an AI coding agent. It identifies
the affected silo, official sources, baseline, host checks and native acceptance.
The agent should reproduce failures, repair code and declarations, run verification,
and leave a reviewable branch with updated evidence. It must keep the old baseline
when the target runtime is unavailable or native checks fail/skip.

Detection and task preparation are automated. **An AI repair runner is not connected
by default**: no particular AI service, credentials, native runner or installation
policy is assumed. Supply the generated brief to your chosen coding agent. The
scheduled job does not itself edit or merge code, download applications or claim an
upgrade passed. Native tests often need licensed software, a display, MPI or other
apps for handoffs; host CI alone cannot certify those results.
