# Handing the repository over

This file is for the organization that takes over the repository: where everything lives now, the decisions made
for the handoff and the ones left open, and what still needs a live cluster. It is not part of `README.md` or the
OperatorHub description.

## Where it lives

The repository moved to
[github.com/redhat-na-ssa/openshift-node-upgrade-mutex-operator](https://github.com/redhat-na-ssa/openshift-node-upgrade-mutex-operator)
as a new repository, not a GitHub transfer, so the old URLs (`github.com/shpwrck/...`) do not redirect. Everything
points at the new home. After editing anything under `docs/`, run `make document` to regenerate `README.md` and the
CSV description.

| What | Where | Value |
| --- | --- | --- |
| Repository links | `docs/USAGE.md` (`README.md` and the CSV `spec.description` are generated from it), the CSV `repository` annotation and `spec.links` | `https://github.com/redhat-na-ssa/openshift-node-upgrade-mutex-operator` |
| Provider | the CSV `provider` annotation and `spec.provider` | Red Hat NA SSA, `https://github.com/redhat-na-ssa` |
| Maintainers | the CSV `spec.maintainers` | None: the organization has no public contact address, and the bundle validator needs an e-mail on every entry. OperatorHub shows the provider and the repository, whose issues are the contact. To name maintainers, add `{name, email}` entries (a team alias is better than a person). |
| Images | `.envrc` `IMAGE_TAG_BASE` and `IMAGE_SOURCE`, the CSV base `containerImage` annotation, the `config/manager` image, the sample CatalogSource | `ghcr.io/redhat-na-ssa/openshift-node-upgrade-mutex-operator`, `-bundle` and `-catalog`, published by the release workflow (`.github/workflows/release.yaml`), which takes the registry from the repository it runs in. `make bundle` sets the bundle's `containerImage` to the image it deploys. The Makefile default is the placeholder `example.com/...`, which `make release` refuses. |
| Catalog | `catalog-template.yaml` and `catalog/openshift-node-upgrade-mutex-operator/catalog.yaml` | Fresh (`make catalog-reset`): only the package entry until the first release from this repository adds its bundle. |

The old images on `quay.io/jskrzypek` (the 0.1.x and 0.2.x operator, bundle and catalog images) are gone, so those
versions can no longer be installed. Their catalog files are in the history of `catalog-template.yaml` and `catalog/`
(`git log -- catalog-template.yaml`). While the release workflow was being tested in the old repository, a
pre-release `0.3.0-rc1` with the old API group was published to `ghcr.io/shpwrck`; it is not in this catalog and
should not be used.

Left for the new owner:

* **Community catalogs.** `operators/openshift-node-upgrade-mutex-operator/` in
  [k8s-operatorhub/community-operators](https://github.com/k8s-operatorhub/community-operators) and
  [redhat-openshift-ecosystem/community-operators-prod](https://github.com/redhat-openshift-ecosystem/community-operators-prod)
  lists the original author as reviewer in its `ci.yaml`: update the reviewers in both, and read "The move from
  0.2.x" (below) before publishing 0.3.0 there.
* **The `ghcr.io` packages.** The first release from this repository creates them under `ghcr.io/redhat-na-ssa`. They
  take the repository's visibility (public) when the organization allows public packages; check that after the first
  release (`docs/DEVELOPMENT.md`, Releasing).

Nothing in `sample-manifests/` or in the Makefile defaults is owner-specific.

### The API group

The API group was renamed for the handoff, from `openshift-optional.skrzypek.io` (tied to the original author's
domain) to `nodeupgrade.redhat-na-ssa.github.io` (the GitHub Pages domain of the receiving organization), with
`domain: redhat-na-ssa.github.io` and `group: nodeupgrade` in `PROJECT`. It is the group of all three CRDs, and it
appears in:

* the CRD names (`mutexrules.nodeupgrade.redhat-na-ssa.github.io`, ...), the CSV, RBAC, samples, molecule tests and
  docs;
* the finalizer `nodeupgrade.redhat-na-ssa.github.io/finalizer`;
* the node labels `mutexrule.nodeupgrade.redhat-na-ssa.github.io/<rule>.<namespace>` and
  `mutexrule.nodeupgrade.redhat-na-ssa.github.io/release`;
* the node annotations `nodeupgrade.redhat-na-ssa.github.io/labelled-by` and
  `nodeupgrade.redhat-na-ssa.github.io/released-by`;
* the MachineConfigPool annotations `nodeupgrade.redhat-na-ssa.github.io/paused-by`,
  `nodeupgrade.redhat-na-ssa.github.io/original-match-expressions`, `nodeupgrade.redhat-na-ssa.github.io/modified-by`,
  `nodeupgrade.redhat-na-ssa.github.io/release-labelled-at` and `nodeupgrade.redhat-na-ssa.github.io/restored-at`;
* the Job label and annotations `nodeupgrade.redhat-na-ssa.github.io/*`;
* the variable names ansible-operator derives from it (`_nodeupgrade_redhat_na_ssa_github_io_<kind>_spec`) in the
  roles.

0.3.0 is the first version with this group. 0.2.x and every earlier build, the 0.3.0-rc1 pre-release included, used
the old group: their CRs, labels and annotations are not read by 0.3.0, so there is no in-place upgrade from them
(USAGE, [Moving from 0.2.x](USAGE.md#moving-from-02x)), and the catalog's `skipRange` starts at `0.3.0-0`
(`CATALOG_SKIP_FROM` in the Makefile) so that OLM never offers 0.3.0 as an upgrade of them. The roles still carry the
code that takes over the state of earlier builds of the same group (the selector of an earlier canary design, mutex
labels without `labelled-by`); with the new group nothing older than 0.3.0 can leave such state, so that code only
matters for runs of 0.3.0 builds from before a later change. Changing the group again creates a new API in the same
way.

## Decisions left to the new owner

* **License.** Apache License 2.0 (`LICENSE`), chosen by the original author for the handoff; the role metadata says
  `Apache-2.0`. Nothing to decide unless the organization requires another license or a `NOTICE` file.
* **API group.** Done: `nodeupgrade.redhat-na-ssa.github.io` (see above).
* **Digests in the catalog.** Releases go to `ghcr.io/redhat-na-ssa` through the release workflow. Decide whether
  releases record bundles by digest in the catalog. `make release` records them by tag; pinning by digest takes the step-by-step
  sequence under "Releasing" in `docs/DEVELOPMENT.md`, which passes the pushed bundle's digest to `make catalog-add`.
* **Version.** `.envrc` is at 0.3.0, because 0.2.67 and 0.2.68 are already published.
* **The move from 0.2.x.** 0.3.0 has a new API group, so 0.2.x installs move by reinstalling (USAGE,
  [Moving from 0.2.x](USAGE.md#moving-from-02x)); the project's own catalog offers 0.3.0 as an upgrade of nothing
  older. Do not publish 0.3.0 to the community catalogs in the channel of 0.2.x (`alpha`): their
  `updateGraph: semver-mode` would make it the upgrade of 0.2.66, and `Automatic` 0.2.x installs would switch to an API
  that ignores their CRs, so their pools would no longer be held at the next OpenShift upgrade. Publish it there in a
  new channel (set `CHANNELS` and `DEFAULT_CHANNEL` for `make bundle`), or not at all. The release notes for 0.3.0
  should point to [Moving from 0.2.x](USAGE.md#moving-from-02x), which is also in the CSV description.
* **Job namespaces.** `MutexRule.spec.jobNamespace` accepts any namespace, and the Jobs can use any ServiceAccount
  there. Only users who can write in the operator namespace can use it. An allow-list, or a namespaced Role for Jobs,
  would narrow it.
* **Templating of CR values.** ansible-operator's `markUnsafe: true` in `watches.yaml` would stop string values from
  CRs from being templated. It is not enabled, because it has not been tested end to end.
* **Supported OpenShift range.** `com.redhat.openshift.versions: v4.16` and `minKubeVersion: 1.29.0`. Raise both
  together once 4.16 leaves its last support phase (see the
  [OpenShift life cycle policy](https://access.redhat.com/support/policy/updates/openshift)).

## What still needs a live OpenShift cluster

This refresh was checked with lint, `operator-sdk bundle validate` (operatorframework suite), `opm validate`, CRD
schema tests against Kubernetes 1.29 and 1.34 API servers, the roles against a fake API server, and the operator image
running against a plain Kubernetes 1.29 API server with stub MachineConfigPool and ClusterVersion CRDs and the shipped
RBAC. None of these has MCO. It was then run on one small OpenShift 4.21 cluster (one control-plane node that also
runs workloads, two workers), installed through OLM with test builds of this branch: installs and an OLM upgrade,
rehearsals that made a node look behind without a real upgrade, and three z-stream upgrades (4.21.20 → 4.21.21 →
4.21.22 → 4.21.23). The first upgrade still had the earlier canary design, which excluded the held nodes instead of
selecting the released ones; MCO's stale node view after an API outage took a held node into that canary, and it
rebooted without its Jobs. That led to the release-label canary, which the last two upgrades ran. Each item below says
what those runs covered ("Live run") and what is still open; run the open parts on a non-production OpenShift 4.16+
cluster before relying on it:

1. An install through OLM, in `OwnNamespace` and in `AllNamespaces` mode. Check that `WATCH_NAMESPACE` and
   `POD_NAMESPACE` are set and that CRs outside the operator namespace report `NamespaceNotAllowed`.
   **Live run** (a build from before the release-label canary): both modes as described; OLM refuses
   `SingleNamespace` (`UnsupportedOperatorGroup`).
2. A real upgrade with at least two target nodes. Check that the pools are paused before MCO reaches them, that each
   node moves into the canary only after its Jobs, that MCO upgrades it there, and that each node goes back to its
   paused pool after its cleanup Jobs, with no reboot then or when the pools are unpaused at the end. Check that no
   target node gets a canary `desiredConfig` before its release patch, also while the kube-apiserver rolls out. Check
   also that the cleanup Jobs of a node start only after MCO reports the node
   `machineconfiguration.openshift.io/state: Done` with `currentConfig` equal to `desiredConfig` and the node is
   `Ready`, even when its `release-image-version` label changes earlier.
   **Live run:** two upgrades with the release-label canary, with an admin MachineConfig applied or deleted during a
   node's update (so the canary re-rendered under it) and the operator pod deleted during the node's wait. Every point
   above held; the cleanup waited for `Done` on the canary's latest rendered config, also through a node that booted
   its old OS image once (a transient RHCOS SELinux finalize failure, recovered by touching MCD's
   `/run/machine-config-daemon-force`). A rehearsal showed the gate needs the canary's rendered config too: a node can
   be `Done` on its old pool's config, with its label already at the target version, before MCO moves it.
3. Aborting by deleting a MutexRunConfig in the middle of a run, and a restart of the operator pod mid-run: a node
   released before the restart resumes at the wait and gets its cleanup Jobs before any other node starts. With two
   MutexRunConfigs, check that the second waits until the first has finished its nodes, and that deleting the
   waiting one also waits (USAGE, "One MutexRunConfig at a time").
   **Live run:** the restart (the released node resumed at the wait and got its cleanup Jobs first) in both
   release-label upgrades; the abort and two MutexRunConfigs one after the other on an earlier build. **Still open:**
   deleting the waiting one.
4. A failing Job, a Job that times out, and a node that never finishes its upgrade: `Degraded=True`, the pools
   stay paused, and the next reconcile retries.
   **Live run** (an earlier build): a failing pre-upgrade Job, a Job timeout and a failing cleanup Job, each with
   `Degraded=True`, the pools still paused and a retry that reused or recreated the Job as documented. **Still
   open:** a node that never finishes its upgrade.
5. A custom target pool, for example `apps`, with the sample canary: `ConfigValidated=False` names the `worker` pool
   nodes that the canary's `matchLabels` select, and nothing is paused or patched. After adding the suggested
   expression, such as `node-role.kubernetes.io/app Exists`, to the canary, the run goes ahead and the `worker` pool
   nodes stay where they are. The check takes each node's pool from the `rendered-<pool>-<hash>` name in its
   `machineconfiguration.openshift.io/currentConfig` annotation.
   **Live run:** the refusal (with real `currentConfig` names) and the suggested expression. **Still open:** a full run
   on such a pool with the sample canary (a run on `apps` was done only with a canary of its own, next to a second
   MutexRunConfig on `worker`, on an earlier build).
6. The `release-image-version` label example in `sample-manifests/` (MachineConfig and NFD) on a current release.
   **Live run:** it labelled the workers with each new version after their upgrade reboots, before MCO marked them
   `Done` (which is why the node wait checks more than the label).
7. `operator-sdk scorecard` against the bundle, and scraping the HTTPS metrics endpoint with the
   `openshift-node-upgrade-mutex-operator-metrics-reader` ClusterRole bound to the scraper (see the binding example
   in the Permissions section of `docs/USAGE.md`).
   **Live run:** scorecard 6/6 passed; the metrics endpoint answered 403 without the binding and 200 with it.
8. The move from 0.2.68 to 0.3.0, following "Moving from 0.2.x" in `docs/USAGE.md` (save the CRs, uninstall 0.2.x,
   install 0.3.0 from the `ghcr.io` catalog, create the CRs again under the new group).
   **Live run:** only of the earlier in-place OLM upgrade, before the API group changed, with a failed InstallPlan and
   its recovery. **Still open:** the reinstall as written now.
9. A run whose canary has nodes of its own (with the sample canary, a worker node with `isCanary`; with a custom
   target pool such as `apps`, also `node-role.kubernetes.io/app=canary`). The molecule tests have no such node. Check
   that they stay in the canary at the start and at the end of the run: the first reconcile reports `MCPUpdated=False`
   (`CanaryMembersLabelled`), and the canary then has its own `matchExpressions` plus one `DoesNotExist` per mutex
   label and the `nodeupgrade.redhat-na-ssa.github.io/release-labelled-at` annotation. The pools are re-pointed only
   at a reconcile at least 5 minutes (`mutexrunconfig_label_settle_seconds`) later, also when the operator pod
   restarts in between. After the run the nodes keep the release label until a reconcile at least 5 minutes after the
   time in the canary's `nodeupgrade.redhat-na-ssa.github.io/restored-at` annotation, normally the one 10 minutes
   after the run (the reconcile right after it keeps the label), and then the annotation goes as well. Check that MCO
   never moves them into `worker`, also while the kube-apiserver rolls out at the start of the run, and that deleting
   the MutexRunConfig in the middle of a run moves them through `worker` at most once (the finalizer has a single
   pass). **Live run:** one canary node of its own with the sample canary. The label, the hold selector and
   `release-labelled-at` came in the first reconcile, during the kube-apiserver rollout; the operator restarted before
   the re-point, and the reconcile after the restart waited again; the pools were re-pointed 13 minutes later. The
   node never left the canary; MCO upgraded it there; its label and `restored-at` went at a reconcile 5 minutes after
   the restore. **Still open:** the mid-run delete, and the custom-pool variant.
10. A target node that is already at the new version while another target node is upgraded. On a build before the
    release-label canary such a node moving into the re-pointed canary made the in-flight guard report one spurious
    `NodeUpgradeFailed`. The release-label canary removes the cause (a node that is not behind never gets the release
    label), but this was not run again.
11. The manual steps in "Recovery" in `docs/USAGE.md` as written now. An earlier version, without the release-label
    and canary-annotation steps, was run live and restored everything.
