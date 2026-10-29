# Contributing

Thank you for helping with the OpenShift Node Upgrade Mutex Operator. This file is the short version. The full
maintainer guide is [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md), and the internals are in
[docs/DESIGN.md](docs/DESIGN.md).

## Before you start

- Read [docs/USAGE.md](docs/USAGE.md) up to the Safety model. The operator pauses MachineConfigPools and decides when
  nodes reboot, so a small change can stop an upgrade or reboot a node without its Jobs.
- For a bug or an idea, open an issue at
  https://github.com/redhat-na-ssa/openshift-node-upgrade-mutex-operator/issues first. Say which version you run and
  include the MutexRunConfig's conditions (`oc get mutexrunconfig <name> -o yaml`).
- Support is best effort.

## Making the change

1. Work on a branch and keep each pull request to one change.
2. Follow the checklist for your kind of change in
   [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md#making-a-change): a role, a CRD field, permissions, defaults, a
   condition, or the documentation.
3. Edit `docs/*.md`, never `README.md`, and keep the rules for `docs/USAGE.md`, which the OpenShift console also shows
   ([Documentation and diagrams](docs/DEVELOPMENT.md#documentation-and-diagrams)).
4. Run the checks CI runs:

   ```sh
   make lint
   shellcheck hack/*.sh
   make docs-lint diagrams-check
   make document                 # then commit README.md and the CSV base if they changed
   make bundle bundle-validate verify-manifests   # do not commit its change to config/manager/kustomization.yaml
   ```

5. For a change to `roles/`, `config/`, `molecule/` or `sample-manifests/`, the E2E check runs the molecule `kind`
   scenario on the pull request. You can run it yourself: see
   [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md#running-and-testing).
6. If you tried the change on a live OpenShift cluster, say so in the pull request, with the OpenShift version, and
   add the result to [tests/Scenarios.md](tests/Scenarios.md). If you did not, say that too.

The pull request template repeats these steps as a checklist.

## Reviews and releases

A maintainer reviews a pull request and merges it into `main`. The **Lint** and **Build and validate** checks must
pass. Releases are cut by maintainers from tags on `main`: see [Releasing](docs/DEVELOPMENT.md#releasing).

## License

The repository is licensed under Apache-2.0 ([LICENSE](LICENSE)). Unless you say otherwise, a contribution you submit
is under the same license (section 5 of the license).

The repository has no security policy (`SECURITY.md`) yet; [docs/HANDOFF.md](docs/HANDOFF.md) lists it among the
decisions for the owner. Until there is one, do not put the details of a vulnerability in a public issue: open an
issue that asks the maintainers for a private contact.
