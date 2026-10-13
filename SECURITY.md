# Security policy

Schemaxis runs native applications on behalf of humans and AI agents, so its
input boundaries matter. Authored input must never be able to select module
paths, execute arbitrary Python or reach native reflection.

## Reporting a vulnerability

Please report suspected vulnerabilities privately by email to
d.gaden.schemaxis@gmail.com rather than in a public issue. Include the Schemaxis
version, the affected adaptor and a minimal reproducing input if you can.

You should receive an acknowledgement within one week. Fixes are released as a
patch version and credited in the changelog unless you prefer otherwise.

## Supported versions

Only the latest released minor version receives security fixes during the 0.x
preview.
