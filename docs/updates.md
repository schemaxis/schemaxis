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
