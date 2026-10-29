# Handing the repository over

This file is for the organization that takes over the repository: what to do first, where everything lives, the
decisions made for the handoff and the ones left open, and the code changes known to be needed. It is not part of
`README.md` or the OperatorHub description. What was tested, and what still needs a live cluster, is in the test
matrix, [tests/Scenarios.md](../tests/Scenarios.md).

## Takeover checklist

Steps 1 to 3 had to be done before the first release from this repository, `v0.3.0-rc2`. They are done; each has a
check. What else must hold before `v0.3.0-rc2`, and before the first final release `v0.3.0`, is in
[Release gates](#release-gates).

1. **License.** Done: Apache License 2.0 ([LICENSE](../LICENSE)). Check: `grep -n 'license:' roles/*/meta/main.yml`
   prints `Apache-2.0` three times.
2. **API group.** Done: `nodeupgrade.redhat-na-ssa.github.io` ([The API group](#the-api-group)). Check:
   `git grep -n 'openshift-optional'` prints only the 0.2.x text that section lists.
3. **Repository URL and owner strings.** Done: everything points at the new repository
   ([Where it lives](#where-it-lives)). Check: `make docs-lint` passes, and the `git grep` in that section prints only
   lines of this file.
4. **Repository settings.** Set them as in [Repository settings](#repository-settings) before anyone pushes a tag.
5. **First release.** Once the gates [before v0.3.0-rc2](#before-v030-rc2) hold, push the tag `v0.3.0-rc2` on the
   default branch, as in DEVELOPMENT, [Releasing](DEVELOPMENT.md#releasing). The release workflow publishes the
   operator, bundle and catalog images to `ghcr.io/redhat-na-ssa` and pushes the branch `release/v0.3.0-rc2`. Merge
   the pull request from that branch before you push another tag. Check that clusters can pull the images without
   credentials:
   `podman pull --authfile /dev/null ghcr.io/redhat-na-ssa/openshift-node-upgrade-mutex-operator-catalog:v0.3.0-rc2`.
6. **First install.** Install the rc on a non-production OpenShift cluster from that catalog image, as in USAGE,
   [Quick start](USAGE.md#quick-start). Look at the operator's description in the console once (test row S43): each
   diagram should be a link "Diagram (opens on GitHub): ...", the tables and code blocks should render, and links to
   repository files should open at the tag `v0.3.0-rc2`.
7. **Live tests.** No live run has used the new API group or an image from `ghcr.io/redhat-na-ssa` (row S44). Run at
   least a z-stream upgrade with two target nodes (S14 to S16) with the rc. Then run the open rows you rely on, for
   example the stuck node (S24), the manual restore (S28), an abort on the shipped design (S25) and a minor upgrade
   (S39).
8. **Docs after each release.** After `v0.3.0-rc2`, and after every release from then on, make the updates in
   DEVELOPMENT, [After each release](DEVELOPMENT.md#after-each-release), in a pull request. They include marking the
   release gates that now hold as Done, and after step 7 the tested environments.
9. **Open decisions and known gaps.** Go through [Decisions left to the new owner](#decisions-left-to-the-new-owner)
   and [Known gaps](#known-gaps); [Release gates](#release-gates) says which of them block which release. File issues
   for the ones you keep. This file travels with the repository; issues in the old repository did not move.
10. **Community catalogs.** Decide what happens to the old listings ([The community catalogs](#the-community-catalogs)).
11. **Final release.** Once the gates [before v0.3.0](#before-v030) hold, the written release notes among them, push
    `v0.3.0` and merge its `release/v0.3.0` pull request. Then publish the GitHub Release for the tag `v0.3.0` with
    those notes, make the updates of step 8, and bump the version with `make increment` in a pull request.

## Release gates

Two releases are planned, and each has gates that must hold before its tag is pushed:

* **`v0.3.0-rc2`** is the first release from this repository. It is a pre-release: it publishes public images and a
  catalog that anyone can install, but it does not move `:latest`. Its purpose is the live test of the release
  process, the images on `ghcr.io/redhat-na-ssa` and the new API group (checklist steps 5 to 7).
* **`v0.3.0`** is the first final release. It moves `:latest`, and it is the version that USAGE tells 0.2.x users to
  reinstall to.

Every other open decision and known gap can follow in a later release; the last table says why.

In the last column of the first two tables, "Done" means that the gate held when this file was last changed. Any
other text there is what still has to hold. The pull request that meets a gate changes its entry to Done, so check
the entries that are not Done yourself before you push a tag. The release workflow checks none of them
(DEVELOPMENT, [Before you tag](DEVELOPMENT.md#before-you-tag)).

### Before v0.3.0-rc2

| Gate | Why it blocks | Done when |
| --- | --- | --- |
| License, API group and repository URL (checklist steps 1 to 3) | The API group cannot change after a release without creating a new API. Every release links to `REPO_URL` and labels its images with the repository | Done |
| `CATALOG_SKIP_FROM` is `0.3.0-rc2` | A catalog entry keeps the `skipRange` it was added with. One that starts at `0.3.0-0` also covers `0.3.0-rc1`, which uses the old API group, so OLM would offer an in-place upgrade from it to a version that ignores its CRs | Done (Makefile) |
| G6 cannot be reached from outside the operator namespace | `AllNamespaces` is a supported install mode, and in it the `mutexrunconfig` role read a MutexRunConfig from any namespace before its namespace check, so a template expression in it could be evaluated as an Ansible template in the operator pod. That is outside the trust model in USAGE, Who controls the operator | Done: `markUnsafe: true` (`watches.yaml:11`, `:19`, `:34`) and the namespace check first (`roles/mutexrunconfig/tasks/main.yml:34-64`), with the molecule case ([Known gaps](#known-gaps) G6). Its first run is part of the CI gate below |
| Repository settings (checklist step 4), the tag rule above all | Pushing a `v*` tag publishes a release with the workflow's token | The settings are made |
| Private vulnerability reporting is enabled (repository Settings, Security) | From this tag on, anyone can install the operator from a public catalog. Without it the only way to report a vulnerability is a public issue. It is a setting; the policy text can follow with `SECURITY.md` | Enabled |
| CI passed on the commit to tag, including `Molecule on kind` | `release.yaml` checks the tag and the branch, not CI. `Molecule on kind` runs only on pull requests that touch its paths | `Lint` and `Build and validate` passed on it, and `Molecule on kind` passed in a run started by hand (`e2e.yaml`, Run workflow) on the default branch at that commit |

### Before v0.3.0

| Gate | Why it blocks | Done when |
| --- | --- | --- |
| The rc passed on a live cluster | No live run has used the new API group or an image from `ghcr.io/redhat-na-ssa` (test row S44), and the final release is the one users are pointed to | Checklist steps 6 and 7: an install from the rc's catalog image, the console check (S43), and a z-stream upgrade with two target nodes (S14 to S16) |
| The `release/v0.3.0-rc2` pull request is merged | The next release starts from the template on the default branch, so without it rc2 drops out of the catalog (G15) | Merged |
| G1: `timeoutSeconds` does not stop a Job | Changing what a field means after the final release changes what users' MutexRules do. It does not block the rc: a timeout fails closed (the run stops and the pools stay paused, S22), and USAGE and JOBS describe it, with `activeDeadlineSeconds` as the bound | The fix is merged, or the decision to keep today's meaning is written here; either way USAGE and JOBS describe what ships |
| G8: nothing checks that the canary renders the same MachineConfigs as the target pools | It is the known way a configuration mistake makes the shipped design reboot nodes without their Jobs, and only a manual `diff` in USAGE guards against it. It does not block the rc: USAGE states the requirement and the check (The canary pool, [Check before every upgrade](USAGE.md#check-before-every-upgrade)), and the rc is tested by people who run them | At least a warning condition when the canary's rendered `spec.configuration.source` differs from a target pool's |
| `SECURITY.md` | Production users of a final release need the supported versions and how a report is handled | A `SECURITY.md` that names the supported versions and the private reporting route |
| Release notes | 0.2.x users must reinstall: there is no upgrade edge to 0.3.0, and the workflow creates no GitHub Release (G15) | Notes that point to USAGE, [Moving from 0.2.x](USAGE.md#moving-from-02x), are written, to be published as the GitHub Release for `v0.3.0` once the tag exists (checklist step 11) |

### Not a release gate

| Item | Why it can wait |
| --- | --- |
| The community catalogs | Releases to this repository's catalog do not touch them. Publishing 0.3.0 there is optional, and only in a new channel ([The move from 0.2.x](#the-move-from-02x)) |
| Digests in the catalog | A choice per release: later entries can be recorded by digest without changing earlier ones |
| Supported OpenShift range | USAGE states the declared range (4.16 and later) and the tested one (4.21 z-stream). Both values move together when 4.16 leaves support |
| Signing, SBOM and provenance | They can be added to the release workflow in any release without changing the API or the catalog, and USAGE, Supply chain, says they are missing. If the organization's policy requires them for every published image, they block `v0.3.0-rc2` instead |
| `CODEOWNERS` and CSV maintainers | They route reviews and contact. Branch protection already requires a pull request and the checks, and the repository's issues are the contact |
| Job namespaces, the `master` pool as a target (G7), a suspend switch (G9) | USAGE documents each: writers of the operator namespace count as cluster-admin, `master` is not supported as a target, and deleting the MutexRunConfig is the only stop. An allow-list, a refusal or a new optional field can come in any release |
| The disconnected annotation | It stays `"false"` until test row S42 has run. Changing it is a CSV edit |
| How much of USAGE goes into the CSV | The CSV description can change in any release; S43 checks today's on the rc |
| Compatibility paths | No build with the current group reaches them, so removing them changes nothing a user sees |
| The other known gaps (G2 to G5, G10 to G22) | Each fails closed, is documented in USAGE, or concerns status, tests, naming, packaging or convenience |

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
  on those branches must still let it push. Its one commit is authored as the person who pushed the tag, with their
  GitHub no-reply address, and is not signed, so the rule must not require signed commits. The workflow does not open
  the pull request; a maintainer opens it from the link in the run's summary, so Actions need no right to create pull
  requests.
* **Packages.** The first release creates the packages `openshift-node-upgrade-mutex-operator`, `-bundle` and
  `-catalog` under `ghcr.io/redhat-na-ssa`. They take the repository's visibility, public, when the organization's
  package settings allow public packages. Check that after the first release (checklist step 5).
* **Issues.** Keep them enabled. The CSV has no maintainers, and the docs name the repository's issues as the place
  for support.

## Where it lives

The repository moved to
[github.com/redhat-na-ssa/openshift-node-upgrade-mutex-operator](https://github.com/redhat-na-ssa/openshift-node-upgrade-mutex-operator)
as a new repository, not a GitHub transfer. It starts from one commit, a snapshot of the code at the move. The
development history up to the move is in the original repository (the first of the old homes below) and was not
transferred. The old URLs do not redirect, and the old issues and pull requests did not move. Everything in the
repository points at the new home. After editing `docs/USAGE.md` or `docs/DEVELOPMENT.md`, run `make document` to
regenerate `README.md` and the CSV description.

| What | Set in | Value |
| --- | --- | --- |
| Repository URL | `REPO_URL` in the Makefile, the only source for links. The docs link to repository files with relative links, which `README.md` keeps. `make document` turns them into links to `REPO_URL` at `main` in the CSV description, and writes `REPO_URL` into the CSV `repository` annotation and into the `spec.links` entry with that same URL. `make bundle` points the bundle CSV's links at the tag `v<VERSION>`. Only the repository root, its issues and URLs inside commands are written out in full in the docs | `https://github.com/redhat-na-ssa/openshift-node-upgrade-mutex-operator` |
| Images | `IMAGE_TAG_BASE` (where `make release` pushes) and `IMAGE_SOURCE` (the `org.opencontainers.image.source` label) in `.envrc`. Copies: the CSV base `containerImage` annotation (`make bundle` sets the bundle's to the image it deploys), `config/manager/kustomization.yaml`, the sample CatalogSource and the Install text in USAGE. The Makefile default is the placeholder `example.com/...`, which `make release` refuses | `ghcr.io/redhat-na-ssa/openshift-node-upgrade-mutex-operator`, `-bundle` and `-catalog` |
| Release workflow | `.github/workflows/release.yaml` sets `IMAGE_TAG_BASE`, `IMAGE_SOURCE` and `REPO_URL` from the repository it runs in, so a release needs no edit | `ghcr.io/<repository owner>/...` and the repository's URL |
| Provider | the CSV `provider` annotation and `spec.provider` | Red Hat NA SSA, `https://github.com/redhat-na-ssa` |
| Maintainers | the CSV `spec.maintainers` | None. The organization has no public contact address, and the bundle validator needs an e-mail on every entry. OperatorHub shows the provider and the repository, whose issues are the contact. To name maintainers, add `{name, email}` entries; a team alias is better than a person |
| License | `LICENSE`; `license` in `roles/*/meta/main.yml` | Apache-2.0 |
| Catalog | `catalog-template.yaml` and `catalog/openshift-node-upgrade-mutex-operator/catalog.yaml` | Started with only the package entry (`make catalog-reset`). Each release adds its bundle, through its merged `release/<tag>` pull request. Until the first release from this repository, `v0.3.0-rc2`, nothing can be installed from it |

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

0.3.0 is the first version with this group, and 0.3.0-rc2 the first build with it to be released. 0.2.x and every
earlier build, the 0.3.0-rc1 pre-release included, used the old group: their CRs, labels and annotations are not read
by 0.3.0, so there is no in-place upgrade from them. The catalog's `skipRange` therefore starts at `0.3.0-rc2`
(`CATALOG_SKIP_FROM` in the Makefile), so that OLM never offers 0.3.0 as an upgrade of them. It must not start lower:
`0.3.0-0` sorts before `0.3.0-rc1`, so a range from it would offer an in-place upgrade from rc1.

The roles still carry code that takes over the state of earlier builds (the selector of an earlier canary design,
mutex labels without `labelled-by`). Every build that wrote such state used the old group, so with the new group only
a hand-made label or annotation can reach that code (DESIGN, [Compatibility paths](DESIGN.md#compatibility-paths)).
Changing the group again creates a new API in the same way.

The live tests ran with the old group. In `roles/` the rename changed only names and the license metadata (build E in
the test matrix, [The builds](../tests/Scenarios.md#the-builds)), and the kind E2E passed with it (test row S44).

## Decisions made for the handoff

| Decision | Result | Where it shows |
| --- | --- | --- |
| License | Apache License 2.0. Nothing to decide unless the organization requires another license or a `NOTICE` file | `LICENSE`, `roles/*/meta/main.yml` |
| API group | `nodeupgrade.redhat-na-ssa.github.io` | [The API group](#the-api-group) |
| Repository | A new repository at `https://github.com/redhat-na-ssa/openshift-node-upgrade-mutex-operator`, not a transfer: the old URLs do not redirect | `REPO_URL` in the Makefile |
| Registry | `ghcr.io/redhat-na-ssa`, published by the release workflow. The old registry, `quay.io/jskrzypek`, is gone, so 0.1.x and 0.2.x can no longer be installed or mirrored | `.envrc`, [Old versions](#old-versions) |
| Catalog | Started afresh. The first release from this repository is `v0.3.0-rc2`. `0.3.0-rc1` (old group, old repository) is not in it and should not be used | `catalog-template.yaml` |
| Upgrade from 0.2.x | None in OLM: moving is a reinstall. The catalog's `skipRange` starts at `0.3.0-rc2`, so it covers neither 0.2.x nor `0.3.0-rc1` | `CATALOG_SKIP_FROM` in the Makefile, [The move from 0.2.x](#the-move-from-02x) |
| Maintainers and provider | No maintainers in the CSV; the provider is Red Hat NA SSA | [Where it lives](#where-it-lives) |
| Version | 0.3.0, because 0.2.67 and 0.2.68 were already published | `.envrc` |
| Templated CR values | `markUnsafe: true` on the three kinds: string values in CRs are never evaluated as Ansible templates (Known gaps G6) | `watches.yaml`, USAGE, [Templated CR values](USAGE.md#templated-cr-values) |

## Decisions left to the new owner

[Release gates](#release-gates) says which of these must be settled before a release.

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
  reporting, the only route to report a vulnerability is a public issue. Private vulnerability reporting is a gate for
  `v0.3.0-rc2`, and `SECURITY.md` one for `v0.3.0`.
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
* **Compatibility paths.** The code that handles state of earlier builds can no longer be reached by any build with
  the current group. Remove it, or keep it as a guard against hand edits (DESIGN,
  [Compatibility paths](DESIGN.md#compatibility-paths)).
* **Release notes.** No GitHub Release or changelog is created (Known gaps G15). The notes for 0.3.0 should point to
  USAGE, [Moving from 0.2.x](USAGE.md#moving-from-02x), which is also in the CSV description.

## Known gaps

Code changes found while the docs were reviewed for the handoff. A gap stays in this table until the pull request
that fixes it removes its row or records the fix in it. Priority: **high** means a node can be upgraded without its
Jobs, a run can hang without a clear signal, or a security question is open; **medium** means operations, status or
test coverage; **low** means naming and convenience. Paths are relative to the repository root. File names without a
directory, and `07:` for `07-run-job.yml`, are in `roles/mutexrunconfig/tasks/`. G1 and G8 are
[release gates](#release-gates); G6 was one and is fixed.

| ID | Gap | Evidence | Proposed fix | Priority |
| --- | --- | --- | --- | --- |
| G1 | `timeoutSeconds` does not stop a Job. It is how long the operator waits for each Job in one attempt (checked every 10 s). On expiry the run stops, but the Job keeps running, and the next retry waits for the same Job again | `07:127-148` (poll, then fail); `07:92-99` (re-use of a Job that has not failed) | On expiry delete the Job, or default `jobSpec.activeDeadlineSeconds` to `timeoutSeconds` when it is not set | high |
| G2 | `NODE_NAME` and `MUTEX_RULE` are appended to each container's env, so a user env value that refers to `$(NODE_NAME)` is not expanded | `07:39-57`; `roles/mutexrunconfig/vars/main.yml:120-127` | Put the injected entries first | low |
| G3 | `ValidConfig` checks less than a Job run needs. It is a server-side dry run of a Job, run as the operator, so no Pod is checked: a missing ServiceAccount, an SCC or Pod Security denial, a quota, the Job ServiceAccount's RBAC, an image that cannot be pulled and scheduling all show up only during the upgrade, often as a Job that stays Running until `timeoutSeconds` (G1) | `roles/mutexrule/tasks/01-validate.yml:32-53` | Also dry-run a Pod from the Job template in `jobNamespace`, so that at least a missing ServiceAccount or an SCC denial shows up | medium |
| G4 | A MutexRule does not check its own name. The node label needs a name without `.` and `<name>.<namespace>` of at most 63 characters, but only a MutexRunConfig that references the rule checks that | `roles/mutexrunconfig/tasks/01-validate.yml:33-55`; `roles/mutexrule/tasks/01-validate.yml:16-30` | The same check in the `mutexrule` role, reported as `ValidConfig=False` | low |
| G5 | The status lags the run. `TargetPoolsPaused` and `Degraded` are written at the end of a reconcile, which can last hours; the pause step writes `TargetPoolsPaused` only when it fails. There are no Events and no field for the current node | `09-report.yml:62-80`; `03-pause-machine-config-pools.yml:27-50`; no Event in `roles/` | Write `TargetPoolsPaused=True` in `03`; add a progress condition or `status.currentNode` with a printer column; emit Events | medium |
| G6 | Fixed. String values from CRs could be evaluated as Ansible templates inside the operator pod, in `AllNamespaces` mode also those of a MutexRunConfig in any namespace, because the `mutexrunconfig` role read its CR before the namespace check. `watches.yaml` now sets `markUnsafe: true` on the three kinds, and the namespace check of the `mutexrunconfig` role runs before its first read of the CR | `watches.yaml:11`, `:19`, `:34`; `main.yml:34-64` (the namespace check and the stop, which use only `ansible_operator_meta` and `state`) runs before `main.yml:66-70` (the first read of the CR). With `markUnsafe`, ansible-operator v1.42.3 passes every string value of the CR wrapped as `{"__ansible_unsafe": ...}` (ansible-operator-plugins `internal/ansible/runner/runner.go`, `makeParameters` and `markUnsafe`). Checked with the offline harness (tests/Scenarios.md, [How it is tested](../tests/Scenarios.md#how-it-is-tested)), with the CRs passed as ansible-operator passes them with `markUnsafe`, also through `ansible-runner`. The build before the fix evaluated template expressions in a MutexRunConfig in another namespace (in a normal and a finalizer run) and in MutexRule and MutexRunConfig values in the operator namespace (MutexTargets were not probed). The fix evaluated none, and all 181 harness scenarios passed as before. The finalizer of a MutexRunConfig in the operator namespace read the MutexTargets it named in other namespaces and restored their pools; it now reads only those in the operator namespace (`vars/main.yml:201-206`, test row S46). Not yet run through ansible-operator itself: the molecule case runs in `Molecule on kind`, `mutexrunconfig_test.yml` (a canary name that is a template expression, test row S45) and `finalizer_test.yml` (template expressions in a Job argument) | Done | high |
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
| G18 | Two embedded assets have no source file: the MachineConfig script exists only in a comment and as a base64 data URL, and the icon only as base64 | `sample-manifests/machineconfig.yaml:41-124` (the script in a comment), `:142` (the data URL); `spec.icon` in the CSV base; `catalog-template.yaml` | Commit both sources and a target that encodes them | low |
| G19 | The molecule scenario named `default` runs against whatever `KUBECONFIG` points at, and a plain `molecule test` picks it. It is guarded, but the name invites mistakes | `molecule/default/molecule.yml:1-19`; the guard in `molecule/default/tasks/olm_guard.yml` | Rename it to `cluster`, or make `kind` the default | low |
| G20 | A MutexTarget's `status.nodes` does not follow MCO in two cases. MCO keeps a node that matches `master` and a custom pool in `master`, and manages a node that matches two custom pools in no pool; the role lists both under their custom pool. So a control-plane node can become a target node of a custom pool | `roles/mutextarget/tasks/02-gather-nodes.yml:89-96`; MCO `GetPoolsForNode` (DESIGN, [What the operator assumes about MCO](DESIGN.md#what-the-operator-assumes-about-mco)) | Follow MCO: put a `master` match first, and leave out nodes that match two custom pools, with a condition that names them | medium |
| G21 | The `NodeUpgradeFailed` message repeats itself in the common case ("`<node>` did not finish its upgrade: `<node>` did not finish its upgrade to ..."), and it is also used when MCO started updating another target node, where "did not finish its upgrade" is wrong | `06-execute-jobs.yml:146-152`, `:294-299`, `:393` | Word the inner messages so the prefix reads once, and give the guard its own message or reason | low |
| G22 | The operator image keeps the labels of its base image, so it describes itself as UBI 9 Minimal: `name` `ubi9/ubi-minimal`, `vendor` and `maintainer` `Red Hat, Inc.`, `version` `9.8`, the UBI `summary`, `description` and `io.k8s.display-name`, and the `org.opencontainers.image.created` and `.revision` of the UBI build | `Dockerfile` sets only `org.opencontainers.image.licenses`, and `make` adds only `org.opencontainers.image.source`; `podman image inspect --format '{{json .Config.Labels}}'` on a built image | Set `name`, `summary`, `description`, `io.k8s.display-name`, `io.k8s.description` and `version` for the operator, the two `org.opencontainers.image` labels at build time, and `vendor` and `maintainer` once the organization has chosen them | low |

## Old versions

### Where the old versions are

| Versions | Listed in | Images | Can be installed |
| --- | --- | --- | --- |
| 0.1.0 to 0.2.68, 124 bundles | The project's old catalog image on `quay.io/jskrzypek`. Its template and rendered catalog were not carried over: this repository's catalog was started afresh ([Where it lives](#where-it-lives)) | `quay.io/jskrzypek` | No: the registry is gone |
| 0.1.22 to 0.2.66: 9 versions in k8s-operatorhub/community-operators, 10 in redhat-openshift-ecosystem/community-operators-prod (also 0.2.14), channel `alpha` | The community catalogs ([below](#the-community-catalogs)) | The bundles are built by the community pipelines, but their CSVs run the operator image from `quay.io/jskrzypek` (checked for 0.1.22 and 0.2.66) | Listed, but the operator image cannot be pulled |
| 0.3.0-rc1 | No catalog of this repository. Published from the old repository to `ghcr.io/shpwrck` | old API group | Do not use it |
| 0.3.0-rc2 and later | This repository's catalog, which each release adds to; 0.3.0-rc2 is the first | `ghcr.io/redhat-na-ssa` | Each version once it is released |

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
