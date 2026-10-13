# Changelog

All notable changes are recorded here. Versions follow
[semantic versioning](https://semver.org/); during 0.x, minor versions may
change input contracts, with migration notes.

## 0.4.0 (unreleased): first public preview

- First public release under the Apache License 2.0.
- External adaptor packages: adaptors can be installed as separate
  distributions through the `schemaxis.adaptors` entry-point group.
- Release evidence runner (`tools/release_evidence.py`) for reproducible,
  verified showcase runs.
- Release gate (`tools/release_gate.py`) checks the tree and built archives
  for private or machine-specific content.
