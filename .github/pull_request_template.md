## What and why

<!-- What does this change, and why? Link the issue it fixes. -->

## How it was tested

- [ ] `make lint` and `shellcheck hack/*.sh`
- [ ] `make docs-lint diagrams-check`
- [ ] `make document`, with `README.md` and the CSV base committed if they changed
- [ ] `make bundle bundle-validate verify-manifests` (for CRD, CSV, RBAC or `config/` changes)
- [ ] The E2E check, or `molecule test -s kind` (for changes to `roles/`, `watches.yaml`, `Dockerfile`,
      `requirements.yml`, `config/`, `molecule/` or `sample-manifests/`)
- [ ] A live OpenShift run: version and what was run, or "not run"

## What else changed with it

Tick what applies. The lists are in "Making a change" in `docs/DEVELOPMENT.md`.

- [ ] A role: its README, `docs/DESIGN.md` (gates, annotations, invariants, MCO assumptions), and the reconcile
      procedure and conditions in `docs/USAGE.md`
- [ ] A CRD field: the CRD, the CSV `specDescriptors`, `config/samples/` and the field tables in `docs/USAGE.md`
- [ ] Permissions: `config/rbac/role.yaml` and the permissions table in `docs/USAGE.md`
- [ ] Defaults or timings: `roles/mutexrunconfig/defaults/main.yml`, its README and the timings in `docs/USAGE.md`
- [ ] A condition reason or message: `docs/USAGE.md` and the molecule assertions
- [ ] Tests: the molecule assertions and `tests/Scenarios.md`
- [ ] Diagrams: the `.mmd` and the `.svg` from `make diagrams`, each embed followed by a text equivalent
- [ ] Documentation only: relative links, and the console rules for `docs/USAGE.md`
