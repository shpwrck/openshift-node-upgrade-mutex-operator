# Handing the repository over

This file is for the organization that takes over the repository: what to do first, where everything lives, the
decisions made for the handoff and the ones left open, and the code changes known to be needed. It is not part of
`README.md` or the OperatorHub description. What was tested, and what still needs a live cluster, is in the test
matrix, [tests/Scenarios.md](../tests/Scenarios.md).

## Takeover checklist

Steps 1 to 3 had to be done before the first public release. They are done; each has a check.

1. **License.** Done: Apache License 2.0 ([LICENSE](../LICENSE)). Check: `grep -n 'license:' roles/*/meta/main.yml`
   prints `Apache-2.0` three times.
2. **API group.** Done: `nodeupgrade.redhat-na-ssa.github.io` ([The API group](#the-api-group)). Check:
   `git grep -n 'openshift-optional'` prints only the 0.2.x text that section lists.
3. **Repository URL and owner strings.** Done: everything points at the new repository
   ([Where it lives](#where-it-lives)). Check: `make docs-lint` passes, and the `git grep` in that section prints only
   lines of this file.
4. **Repository settings.** Set them as in [Repository settings](#repository-settings) before anyone pushes a tag.
5. **First release.** Push the tag `v0.3.0-rc2` on the default branch, as in DEVELOPMENT,
   [Releasing](DEVELOPMENT.md#releasing). The release workflow publishes the operator, bundle and catalog images to
   `ghcr.io/redhat-na-ssa` and pushes the branch `release/v0.3.0-rc2`. Merge the pull request from that branch before
   you push another tag. Check that clusters can pull the images without credentials:
   `podman pull --authfile /dev/null ghcr.io/redhat-na-ssa/openshift-node-upgrade-mutex-operator-catalog:v0.3.0-rc2`.
6. **First install.** Install the rc on a non-production OpenShift cluster from that catalog image, as in USAGE,
   [Quick start](USAGE.md#quick-start). Look at the operator's description in the console once (test row S43): each
   diagram should be a link "Diagram (opens on GitHub): ...", the tables and code blocks should render, and links to
   repository files should open at the tag `v0.3.0-rc2`.
7. **Live tests.** No live run has used the new API group or an image from `ghcr.io/redhat-na-ssa` (row S44). Run at
   least a z-stream upgrade with two target nodes (S14 to S16) with the rc. Then run the open rows you rely on, for
   example the stuck node (S24), the manual restore (S28), an abort on the shipped design (S25) and a minor upgrade
   (S39).
8. **Docs after the release.** Until the first release, USAGE says that nothing is released yet. Once `v0.3.0-rc2`
   (or `v0.3.0`) is in the catalog, update the status and Install text in `docs/USAGE.md`, and the tested
   environments after step 7, then run `make document`.
9. **Open decisions and known gaps.** Go through [Decisions left to the new owner](#decisions-left-to-the-new-owner)
   and [Known gaps](#known-gaps). File issues for the ones you keep. This file travels with the repository; issues in
   the old repository did not move.
10. **Community catalogs.** Decide what happens to the old listings ([The community catalogs](#the-community-catalogs)).
11. **Final release.** When the rc has passed, push `v0.3.0`, merge its `release/v0.3.0` pull request, then bump the
    version with `make increment` in a pull request.

## Repository settings

The workflows need these settings. Set them before the first tag: a tag `v*` pushed on the default branch publishes a
release.

* **Actions.** Allow GitHub Actions for the repository. The workflows use only `actions/checkout` and
  `actions/setup-python`, pinned by commit SHA. If the organization allows only selected actions, allow those two.
* **Workflow permissions.** `ci.yaml` and `e2e.yaml` run with `contents: read`. The release job in `release.yaml` asks
  for `contents: write` (to push `release/<tag>`) and `packages: write` (to push to `ghcr.io`) itself, so the default
  `GITHUB_TOKEN` permissions can stay read-only. It uses no other secret.
* **Branch protection on `main`.** Require a pull request and the status checks `Lint` and `Build and validate`, the
  two jobs of `ci.yaml`. Do not require `Molecule on kind` (`e2e.yaml`). It runs only when a pull request touches
  `roles/`, `config/`, `molecule/` or a few other paths, so on other pull requests it never reports and would block
  the merge.
* **Tags.** Limit who can create tags that match `v*`, for example with a tag ruleset, because such a tag publishes a
  release with the workflow's token.
* **`release/*` branches.** The release workflow creates and force-pushes `release/<tag>` with `GITHUB_TOKEN`. A rule
  on those branches must still let it push. The workflow does not open the pull request; a maintainer opens it from
  the link in the run's summary, so Actions need no right to create pull requests.
* **Packages.** The first release creates the packages `openshift-node-upgrade-mutex-operator`, `-bundle` and
  `-catalog` under `ghcr.io/redhat-na-ssa`. They take the repository's visibility, public, when the organization's
  package settings allow public packages. Check that after the first release (checklist step 5).
* **Issues.** Keep them enabled. The CSV has no maintainers, and the docs name the repository's issues as the place
  for support.

## Where it lives

The repository moved to
[github.com/redhat-na-ssa/openshift-node-upgrade-mutex-operator](https://github.com/redhat-na-ssa/openshift-node-upgrade-mutex-operator)
as a new repository, not a GitHub transfer. The old URLs do not redirect, and the old issues and pull requests did not
move. Everything in the repository points at the new home. After editing `docs/USAGE.md` or `docs/DEVELOPMENT.md`,
run `make document` to regenerate `README.md` and the CSV description.

| What | Set in | Value |
| --- | --- | --- |
| Repository URL | `REPO_URL` in the Makefile, the only source for links. The docs link to repository files with relative links, which `README.md` keeps. `make document` turns them into links to `REPO_URL` at `main` in the CSV description, and writes `REPO_URL` into the CSV `repository` annotation and into the `spec.links` entry with that same URL. `make bundle` points the bundle CSV's links at the tag `v<VERSION>`. Only the repository root, its issues and URLs inside commands are written out in full in the docs | `https://github.com/redhat-na-ssa/openshift-node-upgrade-mutex-operator` |
| Images | `IMAGE_TAG_BASE` (where `make release` pushes) and `IMAGE_SOURCE` (the `org.opencontainers.image.source` label) in `.envrc`. Copies: the CSV base `containerImage` annotation (`make bundle` sets the bundle's to the image it deploys), `config/manager/kustomization.yaml`, the sample CatalogSource and the Install text in USAGE. The Makefile default is the placeholder `example.com/...`, which `make release` refuses | `ghcr.io/redhat-na-ssa/openshift-node-upgrade-mutex-operator`, `-bundle` and `-catalog` |
| Release workflow | `.github/workflows/release.yaml` sets `IMAGE_TAG_BASE`, `IMAGE_SOURCE` and `REPO_URL` from the repository it runs in, so a release needs no edit | `ghcr.io/<repository owner>/...` and the repository's URL |
| Provider | the CSV `provider` annotation and `spec.provider` | Red Hat NA SSA, `https://github.com/redhat-na-ssa` |
| Maintainers | the CSV `spec.maintainers` | None. The organization has no public contact address, and the bundle validator needs an e-mail on every entry. OperatorHub shows the provider and the repository, whose issues are the contact. To name maintainers, add `{name, email}` entries; a team alias is better than a person |
| License | `LICENSE`; `license` in `roles/*/meta/main.yml` | Apache-2.0 |
| Catalog | `catalog-template.yaml` and `catalog/openshift-node-upgrade-mutex-operator/catalog.yaml` | Only the package entry (`make catalog-reset`). Nothing can be installed from it until the first release from this repository adds its bundle |

The old homes, for reference. Do not use them:

| Old | Now |
| --- | --- |
| `github.com/shpwrck/openshift-node-upgrade-mutex-operator` | The original repository. Its URLs do not redirect here |
| `quay.io/jskrzypek/openshift-node-upgrade-mutex-operator`, `-bundle` and `-catalog` | Gone. They held every 0.1.x and 0.2.x image ([Old versions](#old-versions)) |
| `ghcr.io/shpwrck/openshift-node-upgrade-mutex-operator`, `-bundle` and `-catalog` | Only the pre-release `0.3.0-rc1`, with the old API group, published while the release workflow was tested in the old repository. It is not in this repository's catalog |

To check that nothing points at an old owner:

```sh
make docs-lint
git grep -nE '(github\.com|ghcr\.io)/[A-Za-z0-9-]+/openshift-node-upgrade-mutex-operator' | grep -vi redhat-na-ssa
```

`make docs-lint` fails on any `github.com`, `raw.githubusercontent.com` or `ghcr.io` path of this repository with
another owner, outside this file. The `git grep` should print only lines of this file.

### The API group

The API group was renamed for the handoff, from `openshift-optional.skrzypek.io` (tied to the original author's
domain) to `nodeupgrade.redhat-na-ssa.github.io` (the GitHub Pages domain of the receiving organization), with
`domain: redhat-na-ssa.github.io` and `group: nodeupgrade` in `PROJECT`. It is the group of all three CRDs, and it
appears in:

* the CRD names (`mutexrules.nodeupgrade.redhat-na-ssa.github.io`, ...), the CSV, RBAC, samples, molecule tests and
  docs;
* the diagram sources `docs/diagrams/*.mmd` and the SVGs rendered from them;
* the finalizer `nodeupgrade.redhat-na-ssa.github.io/finalizer`;
* the node labels `mutexrule.nodeupgrade.redhat-na-ssa.github.io/<rule>.<namespace>` and
  `mutexrule.nodeupgrade.redhat-na-ssa.github.io/release`;
* the node annotations `nodeupgrade.redhat-na-ssa.github.io/labelled-by` and
  `nodeupgrade.redhat-na-ssa.github.io/released-by`;
* the MachineConfigPool annotations `nodeupgrade.redhat-na-ssa.github.io/paused-by`,
  `nodeupgrade.redhat-na-ssa.github.io/original-match-expressions`, `nodeupgrade.redhat-na-ssa.github.io/modified-by`,
  `nodeupgrade.redhat-na-ssa.github.io/release-labelled-at` and `nodeupgrade.redhat-na-ssa.github.io/restored-at`;
* the Job label `nodeupgrade.redhat-na-ssa.github.io/job-key` and the Job annotations
  `nodeupgrade.redhat-na-ssa.github.io/mutexrunconfig`, `.../mutexrule`, `.../node`, `.../phase` and
  `.../desired-version`;
* the variable names ansible-operator derives from it (`_nodeupgrade_redhat_na_ssa_github_io_<kind>_spec`) in the
  roles;
* the label `molecule.nodeupgrade.redhat-na-ssa.github.io/test-namespace` that the `default` molecule scenario puts on
  the CRDs it creates.

The old group is left only where the docs describe 0.2.x: USAGE, [Moving from 0.2.x](USAGE.md#moving-from-02x) (and
so `README.md` and the CSV description), and this file.

0.3.0 is the first version with this group. 0.2.x and every earlier build, the 0.3.0-rc1 pre-release included, used
the old group: their CRs, labels and annotations are not read by 0.3.0, so there is no in-place upgrade from them, and
the catalog's `skipRange` starts at `0.3.0-0` (`CATALOG_SKIP_FROM` in the Makefile) so that OLM never offers 0.3.0 as
an upgrade of them. The roles still carry the code that takes over the state of earlier builds of the same group (the
selector of an earlier canary design, mutex labels without `labelled-by`). With the new group nothing older than
0.3.0 can leave such state, so that code only matters for runs of 0.3.0 builds from before a later change. Changing
the group again creates a new API in the same way.

The live tests ran with the old group. In `roles/` the rename changed only names and the license metadata (commit
b6f0d75), and the kind E2E passed with it (test row S44).

## Decisions made for the handoff

| Decision | Result | Where it shows |
| --- | --- | --- |
| License | Apache License 2.0. Nothing to decide unless the organization requires another license or a `NOTICE` file | `LICENSE`, `roles/*/meta/main.yml` |
| API group | `nodeupgrade.redhat-na-ssa.github.io` | [The API group](#the-api-group) |
| Repository | A new repository at `https://github.com/redhat-na-ssa/openshift-node-upgrade-mutex-operator`, not a transfer: the old URLs do not redirect | `REPO_URL` in the Makefile |
| Registry | `ghcr.io/redhat-na-ssa`, published by the release workflow. The old registry, `quay.io/jskrzypek`, is gone, so 0.1.x and 0.2.x can no longer be installed or mirrored | `.envrc`, [Old versions](#old-versions) |
| Catalog | Started afresh. The first release from this repository is `v0.3.0-rc2`. `0.3.0-rc1` (old group, old repository) is not in it and should not be used | `catalog-template.yaml` |
| Upgrade from 0.2.x | None in OLM: moving is a reinstall. The catalog's `skipRange` starts at `0.3.0-0` | `CATALOG_SKIP_FROM` in the Makefile, [The move from 0.2.x](#the-move-from-02x) |
| Maintainers and provider | No maintainers in the CSV; the provider is Red Hat NA SSA | [Where it lives](#where-it-lives) |
| Version | 0.3.0, because 0.2.67 and 0.2.68 were already published | `.envrc` |

## Decisions left to the new owner

* **The community catalogs.** What to do with the old listings, and whether to publish 0.3.0 there
  ([The community catalogs](#the-community-catalogs)).
* **Digests in the catalog.** Decide whether releases record bundles by digest in the catalog. `make release` records
  them by tag. Pinning by digest takes the step-by-step sequence under Releasing in `docs/DEVELOPMENT.md`, which
  passes the pushed bundle's digest to `make catalog-add`.
* **Supported OpenShift range.** `com.redhat.openshift.versions: v4.16` in `custom-annotations.yaml` and
  `minKubeVersion: 1.29.0` in the CSV base. Only 4.21 z-stream upgrades ran live (test rows S39 and S40). Raise both
  values together once 4.16 leaves its last support phase (see the
  [OpenShift life cycle policy](https://access.redhat.com/support/policy/updates/openshift)).
* **Signing and SBOM.** The release workflow pushes the images unsigned, with no SBOM and no provenance attestation.
* **SECURITY.md and CODEOWNERS.** Neither exists. Without a `SECURITY.md` or GitHub's private vulnerability
  reporting, the only route to report a vulnerability is a public issue.
* **Templating of CR values.** ansible-operator's `markUnsafe: true` in `watches.yaml` would stop string values from
  CRs from being templated. It is not enabled, because it has not been tested end to end (Known gaps G6).
* **Job namespaces.** `MutexRule.spec.jobNamespace` accepts any namespace, and the Jobs can use any ServiceAccount
  there. Only users who can write in the operator namespace can use it. An allow-list, or a namespaced Role for Jobs,
  would narrow it.
* **A suspend switch.** Today the only way to stop a run is to delete the MutexRunConfig, and then the remaining nodes
  upgrade without their Jobs (Known gaps G9).
* **The `master` pool as a target.** Nothing refuses it today (Known gaps G7).
* **The disconnected annotation.** The CSV says `features.operators.openshift.io/disconnected: "false"`. The operator
  is expected to work disconnected, but that is untested (test row S42). Keep the annotation until it is tested.
* **How much of USAGE goes into the CSV.** `make document` puts all of `docs/USAGE.md` into the CSV `spec.description`,
  so the console shows the whole user guide, also on a disconnected cluster. In exchange, USAGE has to follow the
  console rules (no blockquotes or alerts, no raw HTML, no h5 or h6), and its diagrams reach the console only as
  links. A short description that links to the repository is the alternative.
* **Release notes.** No GitHub Release or changelog is created (Known gaps G15). The notes for 0.3.0 should point to
  USAGE, [Moving from 0.2.x](USAGE.md#moving-from-02x), which is also in the CSV description.

## Known gaps

Code changes found while the docs were reviewed for the handoff. They are not made yet. Priority: **high** means a node
can be upgraded without its Jobs, a run can hang without a clear signal, or a security question is open; **medium**
means operations, status or test coverage; **low** means naming and convenience. Paths are relative to the repository
root. File names without a directory, and `07:` for `07-run-job.yml`, are in `roles/mutexrunconfig/tasks/`.

| ID | Gap | Evidence | Proposed fix | Priority |
| --- | --- | --- | --- | --- |
| G1 | `timeoutSeconds` does not stop a Job. It is how long the operator waits for each Job in one attempt (checked every 10 s). On expiry the run stops, but the Job keeps running, and the next retry waits for the same Job again | `07:127-148` (poll, then fail); `07:92-99` (re-use of a Job that has not failed) | On expiry delete the Job, or default `jobSpec.activeDeadlineSeconds` to `timeoutSeconds` when it is not set | high |
| G2 | `NODE_NAME` and `MUTEX_RULE` are appended to each container's env, so a user env value that refers to `$(NODE_NAME)` is not expanded | `07:39-57`; `roles/mutexrunconfig/vars/main.yml:120-127` | Put the injected entries first | low |
| G3 | `ValidConfig` checks less than a Job run needs. It is a server-side dry run of a Job, run as the operator, so no Pod is checked: a missing ServiceAccount, an SCC or Pod Security denial, a quota, the Job ServiceAccount's RBAC, an image that cannot be pulled and scheduling all show up only during the upgrade, often as a Job that stays Running until `timeoutSeconds` (G1) | `roles/mutexrule/tasks/01-validate.yml:32-53` | Also dry-run a Pod from the Job template in `jobNamespace`, so that at least a missing ServiceAccount or an SCC denial shows up | medium |
| G4 | A MutexRule does not check its own name. The node label needs a name without `.` and `<name>.<namespace>` of at most 63 characters, but only a MutexRunConfig that references the rule checks that | `roles/mutexrunconfig/tasks/01-validate.yml:33-55`; `roles/mutexrule/tasks/01-validate.yml:16-30` | The same check in the `mutexrule` role, reported as `ValidConfig=False` | low |
| G5 | The status lags the run. `TargetPoolsPaused` and `Degraded` are written at the end of a reconcile, which can last hours; the pause step writes `TargetPoolsPaused` only when it fails. There are no Events and no field for the current node | `09-report.yml:62-80`; `03-pause-machine-config-pools.yml:27-50`; no Event in `roles/` | Write `TargetPoolsPaused=True` in `03`; add a progress condition or `status.currentNode` with a printer column; emit Events | medium |
| G6 | String values from CRs may be evaluated as Ansible templates inside the operator pod. Not verified either way | `watches.yaml` sets no `markUnsafe` on any of the three kinds | Set `markUnsafe: true`, and add a molecule case with `{{` in a Job argument | high |
| G7 | The `master` pool, or any pool with control-plane nodes, is accepted as a target pool. What a run then does is untested | `roles/mutexrunconfig/tasks/01-validate.yml:184-228` (target pools are checked to exist and not to be in use by another MutexRunConfig, nothing more); `roles/mutextarget/tasks/02-gather-nodes.yml:91-95` | Refuse `master` and any pool that selects control-plane nodes | medium |
| G8 | Nothing checks that the canary renders the same MachineConfigs as the target pools. If it does not, each node is updated to the canary's config and again, without its Jobs, when the pools are unpaused at the end | `roles/mutexrunconfig/tasks/01-validate.yml:153-182` (the canary checks) compare no `machineConfigSelector` or `spec.configuration.source` | Report a warning, or refuse, when the canary's rendered `spec.configuration.source` differs from a target pool's | high |
| G9 | There is no suspend switch. Deleting the MutexRunConfig is the only stop, and it lets the remaining nodes upgrade without Jobs | `config/crd/bases/nodeupgrade.redhat-na-ssa.github.io_mutexrunconfigs.yaml:81-176` (no `suspend` in `spec`) | A `spec.suspend` field that keeps the pools paused and starts no new Job | medium |
| G10 | The canary's own nodes have no automated test: the kind cluster has no canary node, and the settle time is 300 s | `molecule/kind/kind-config.yaml:6-9`; `roles/mutexrunconfig/defaults/main.yml:29` | A third kind worker labelled `isCanary`, a lower `mutexrunconfig_label_settle_seconds` for the test, and asserts on `CanaryMembersLabelled`, the hold selector, the re-point after the settle time and the `restored-at` cleanup | medium |
| G11 | The manual restore exists only as shell and jq steps in USAGE, and the current version never ran on a live cluster (test row S28) | USAGE, [The operator is gone in the middle of a run](USAGE.md#the-operator-is-gone-in-the-middle-of-a-run); no script in `hack/` | `hack/restore-by-hand.sh <namespace> <name> [--dry-run]`, tested in the kind scenario with the operator scaled to 0 | medium |
| G12 | The gate fact is named `UpgradabilityChecked`, the condition `UpgradeChecked` | `roles/mutexrunconfig/tasks/main.yml:76,141,148,156`; `02-check-for-upgrade.yml:195,203,208,220` | Rename the fact | low |
| G13 | `make deploy` installs into `openshift-node-upgrade-mutex-operator-system`, while the docs and samples use `node-upgrade-mutex-operator`, so the sample CRs get `NamespaceNotAllowed` | `config/default/kustomization.yaml:2` | Set the namespace to `node-upgrade-mutex-operator` | low |
| G14 | No CRD schema test against the oldest declared Kubernetes version. The schema tests against Kubernetes 1.29 and 1.34 were local tooling, and the kind E2E uses kind's default node image | `minKubeVersion: 1.29.0` in the CSV base; `molecule/kind/molecule.yml:57` | A CI matrix over `KIND_NODE_IMAGE` with the minimum and the current Kubernetes version | medium |
| G15 | The release workflow does not guard the catalog chain. It does not refuse while an earlier `release/<tag>` is unmerged, so a tag pushed then leaves that version out of the catalog. It creates no GitHub Release. `bundles/<VERSION>` is not kept, so publishing to the community catalogs needs a regenerated bundle | `.github/workflows/release.yaml:93-107`; `.gitignore:20-22` | Refuse while an unmerged `release/*` branch exists; create a draft GitHub Release; attach `bundles/<VERSION>` to it | medium |
| G16 | A Job is not told the phase or the version, and Jobs cannot be selected by node or phase: those are annotations, and the only label is the job key | `roles/mutexrunconfig/vars/main.yml:120-127`; `07:108-117` | Inject `MUTEX_PHASE` and `MUTEX_DESIRED_VERSION`; add node and phase labels (a hash where a node name is too long for a label value) | low |
| G17 | A Job author cannot see the Job the operator would create without running an upgrade | no such target in the Makefile | `make render-job`, built on the logic of `07` | low |
| G18 | Two embedded assets have no source file: the MachineConfig script exists only in a comment and as a base64 data URL, and the icon only as base64 | `sample-manifests/machineconfig.yaml:25-108,126`; `spec.icon` in the CSV base; `catalog-template.yaml` | Commit both sources and a target that encodes them | low |
| G19 | The molecule scenario named `default` runs against whatever `KUBECONFIG` points at, and a plain `molecule test` picks it. It is guarded, but the name invites mistakes | `molecule/default/molecule.yml:1-19`; the guard in `molecule/default/tasks/olm_guard.yml` | Rename it to `cluster`, or make `kind` the default | low |

## Old versions

### Where the old versions are

| Versions | Listed in | Images | Can be installed |
| --- | --- | --- | --- |
| 0.1.0 to 0.2.68, 124 bundles | The project's old catalog image on `quay.io/jskrzypek`. Its files are in the history of `catalog-template.yaml` and `catalog/`, before the commit that started a fresh catalog (`git log -- catalog-template.yaml`) | `quay.io/jskrzypek` | No: the registry is gone |
| 0.1.22 to 0.2.66: 9 versions in k8s-operatorhub/community-operators, 10 in redhat-openshift-ecosystem/community-operators-prod (also 0.2.14), channel `alpha` | The community catalogs ([below](#the-community-catalogs)) | The bundles are built by the community pipelines, but their CSVs run the operator image from `quay.io/jskrzypek` (checked for 0.1.22 and 0.2.66) | Listed, but the operator image cannot be pulled |
| 0.3.0-rc1 | No catalog of this repository. Published from the old repository to `ghcr.io/shpwrck` | old API group | Do not use it |
| 0.3.0-rc2 | This repository's catalog, after its first release | `ghcr.io/redhat-na-ssa` | After the release |

A 0.2.x operator that is still installed keeps running only while its pod can start from an image already on its
node. If the pod has to pull the image again, for example on another node, it cannot start, and its pools are no
longer held at the next OpenShift upgrade. Point such users to the reinstall below.

### The move from 0.2.x

0.3.0 has a new API group, so 0.2.x installs move by reinstalling (USAGE,
[Moving from 0.2.x](USAGE.md#moving-from-02x)). The project's own catalog offers 0.3.0 as an upgrade of nothing
older. Do not publish 0.3.0 to the community catalogs in the channel of 0.2.x (`alpha`). Their
`updateGraph: semver-mode` would make it the upgrade of 0.2.66, and `Automatic` 0.2.x installs would switch to an API
that ignores their CRs, so their pools would no longer be held at the next OpenShift upgrade. Publish it there in a
new channel (set `CHANNELS` and `DEFAULT_CHANNEL` for `make bundle`), or not at all. The reinstall as written now has
not been run (test row S38).

### The community catalogs

The package `operators/openshift-node-upgrade-mutex-operator/` is listed in
[k8s-operatorhub/community-operators](https://github.com/k8s-operatorhub/community-operators) (OperatorHub.io) and
[redhat-openshift-ecosystem/community-operators-prod](https://github.com/redhat-openshift-ecosystem/community-operators-prod)
(the community catalog in the OpenShift console). In both, its `ci.yaml` lists the original author as the only
reviewer. Every version there is 0.2.66 or older and cannot be installed any more (see the table above). Decide:

* who reviews the package there: update `reviewers` in both `ci.yaml` files;
* what happens to the old versions: users can still find them, but an install fails when the operator image is
  pulled. Removing or deprecating them is a change in those repositories;
* whether to publish 0.3.0 there, in a new channel only ([The move from 0.2.x](#the-move-from-02x)). Copy the bundle
  as described under Releasing in `docs/DEVELOPMENT.md`.

## Test status

[tests/Scenarios.md](../tests/Scenarios.md) is the single test matrix: what CI and molecule check, what ran live on
OpenShift, on which design and version, and what is still open. Checklist step 7 names the rows to run first.
