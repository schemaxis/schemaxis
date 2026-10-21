# Contributing to Schemaxis

Thanks for your interest. Bug reports, adaptor improvements, documentation
fixes and new adaptors are all welcome.

## Before you start

- Read [AGENTS.md](AGENTS.md). It is the development guide for humans and AI
  coding agents alike.
- For anything larger than a small fix, open an issue first so we can agree on
  scope.
- New adaptors can live in their own package. See "External adaptor packages"
  in [docs/adaptor-development.md](docs/adaptor-development.md). An adaptor
  does not need to be merged into the core to be useful.

## Development setup

Schemaxis needs only Python 3.10 or newer at runtime.

```bash
git clone https://github.com/schemaxis/schemaxis.git
cd schemaxis
PYTHONPATH=src python3 -m unittest discover -s tests/unit -q
PYTHONPATH=src python3 -m schemaxis describe
```

Native qualification (tests/conformance and the examples) needs the relevant
applications installed. Record their locations with `schemaxis configure`;
never commit workstation paths.

## Conventions

- Canadian spelling, and "adaptor" consistently in prose and identifiers.
- Keep the host runtime dependency-free.
- Structured faults with a stable code, location and recovery hint.
- Do not loosen verification to make something pass.
- New native options need meaningful tests and a bounded native example.
- Run `python3 tools/release_gate.py` before opening a pull request.

## Commit messages and sign-off

Use one summary line where possible; keep any further lines to 80 characters
or fewer. Sign off each commit (`git commit -s`) to certify the
[Developer Certificate of Origin](https://developercertificate.org/): that you
wrote the change or have the right to submit it under the project's licence.
Do not add `Co-Authored-By` trailers.

## AI-assisted contributions

AI-assisted contributions are welcome. You are responsible for them: review
the change, run the tests, and make sure no proprietary third-party material
was copied in.

## Licence

By contributing, you agree that your contributions are licensed under the
Apache License 2.0 (see [LICENSE](LICENSE)).

See [Distribution boundary](docs/distribution.md) before proposing database
integration or CFD case-preparation features. General-purpose database adaptors,
geometry and meshing remain part of the core.
