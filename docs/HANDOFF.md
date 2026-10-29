# Handing the repository over

This file is for the organization that takes over the repository. It lists every owner-specific string that has to
change after the transfer, the decisions this refresh left to the new owner, and what still needs a live cluster.
It is not part of `README.md` or the OperatorHub description.

## Strings to change after the transfer

GitHub redirects the old repository URLs after a transfer, so nothing breaks on the day of the move. Change these
when convenient. After editing anything under `docs/`, run `make document` to regenerate `README.md` and the CSV
description.

| What | Where | Today | Change to |
| --- | --- | --- | --- |
| Repository links | `docs/USAGE.md`: links to `sample-manifests/` and "More information". `README.md` and the CSV `spec.description` are generated from it. | `https://github.com/shpwrck/openshift-node-upgrade-mutex-operator` | The new repository URL |
| CSV `repository` annotation and `spec.links` | `config/manifests/bases/openshift-node-upgrade-mutex-operator.clusterserviceversion.yaml` | same URL | The new repository URL |
| CSV `spec.maintainers` | CSV base | the original author's name and e-mail | The new maintainers (a team alias is better than a person) |
| CSV `provider` annotation and `spec.provider` | CSV base | the original author's name, `https://github.com/shpwrck` | The new organization |
| Image registry and image label | `.envrc` `IMAGE_TAG_BASE` and `IMAGE_SOURCE` | `ghcr.io/shpwrck/openshift-node-upgrade-mutex-operator` and `https://github.com/shpwrck/openshift-node-upgrade-mutex-operator` | The new owner's `ghcr.io` package and repository URL, for releases by hand. The release workflow (`.github/workflows/release.yaml`) needs no change: it takes both from the repository it runs in. After the move its first release creates new, private packages under `ghcr.io/<new owner>`: make them public (`docs/DEVELOPMENT.md`, Releasing), and check that the organization's package creation setting allows public packages. The `ghcr.io/shpwrck` packages stay with that account and lose their repository link. The Makefile default is the placeholder `example.com/...`, which `make release` refuses. |
| CSV `containerImage` annotation | CSV base | `ghcr.io/shpwrck/openshift-node-upgrade-mutex-operator` (no tag) | The new registry. Only the base needs it: `make bundle` sets the annotation in the bundle to the operator image it deploys. |
| Manager image | `config/manager/kustomization.yaml` `images[controller]` | `ghcr.io/shpwrck/openshift-node-upgrade-mutex-operator:0.3.0` | The new registry. `make bundle` and `make deploy` rewrite it on every run, so it only matters for a plain `kustomize build`. |
| Catalog | `catalog-template.yaml` and `catalog/openshift-node-upgrade-mutex-operator/catalog.yaml` | Started afresh for the move to `ghcr.io` (`make catalog-reset`): only the package entry until the release workflow adds the first bundle. A pre-release published while the workflow was tested in the old repository (`ghcr.io/shpwrck/...-bundle:v0.3.0-rc<n>`) may be listed. | Nothing, unless such pre-release entries are listed: then run `make catalog-reset`, commit, and release from the new repository. |
| 0.1.x and 0.2.x images | `quay.io/jskrzypek/openshift-node-upgrade-mutex-operator`, `-bundle` and `-catalog` (the old catalog files are in the history of `catalog-template.yaml` and `catalog/`, before the commit that ran `make catalog-reset`: `git log -- catalog-template.yaml`) | 124 released bundles, referenced by tag (`...-bundle:v<version>`) in the old catalog. That catalog's rendered file also has 248 references to the operator image (each CSV's `containerImage` annotation and its `relatedImages` entry), 620 `github.com/shpwrck` URLs, 372 copies of the original author's name and 124 of the author's e-mail, all read from inside the bundle images. | They go away with the old registry. To keep them installable, mirror them before then (for example `skopeo copy --all docker://quay.io/jskrzypek/...-bundle:vX docker://<new registry>/...-bundle:vX`, which keeps the tags and digests) together with the operator images; the URLs, the name and the e-mail inside them stay unless those bundles are rebuilt. Every one of them also lists `gcr.io/kubebuilder/kube-rbac-proxy` in its `relatedImages` (70 by the `v0.15.0` tag, 54 by digest), which may stop being pullable. 0.3.0 is the first version without it. |
| Community catalogs | `operators/openshift-node-upgrade-mutex-operator/` in [k8s-operatorhub/community-operators](https://github.com/k8s-operatorhub/community-operators) and [redhat-openshift-ecosystem/community-operators-prod](https://github.com/redhat-openshift-ecosystem/community-operators-prod) | The package is published there with the original author as reviewer | Update the package's `ci.yaml` reviewers in both repositories. |
| Role metadata | `roles/*/meta/main.yml` | `license: NOASSERTION` | The license you choose (see below). |

Apart from the API group (below), nothing in `sample-manifests/` (the sample CatalogSource included) or in the
Makefile defaults has to change: they already use neutral names and `example.com/...` placeholders.

### The API group: breaking to change

`openshift-optional.skrzypek.io` (and `domain: skrzypek.io` in `PROJECT`) is tied to the original author's domain. It
is the group of all three CRDs, and it appears in:

* the CRD names (`mutexrules.openshift-optional.skrzypek.io`, ...), the CSV, RBAC, samples, molecule tests and docs;
* the finalizer `openshift-optional.skrzypek.io/finalizer`;
* the node labels `mutexrule.openshift-optional.skrzypek.io/<rule>.<namespace>` and
  `mutexrule.openshift-optional.skrzypek.io/release`;
* the node annotations `openshift-optional.skrzypek.io/labelled-by` and `openshift-optional.skrzypek.io/released-by`;
* the MachineConfigPool annotations `openshift-optional.skrzypek.io/paused-by`,
  `openshift-optional.skrzypek.io/original-match-expressions`, `openshift-optional.skrzypek.io/modified-by`,
  `openshift-optional.skrzypek.io/release-labelled-at` and `openshift-optional.skrzypek.io/restored-at`;
* the Job label and annotations `openshift-optional.skrzypek.io/*`;
* the variable names ansible-operator derives from it (`_openshift_optional_skrzypek_io_<kind>_spec`) in the roles.

Changing it creates a new API. Existing MutexRules, MutexTargets and MutexRunConfigs are not migrated. A run in
progress under the old operator would leave paused pools, labels and annotations that the new operator does not
recognize. If you change it, ship it as a new major version, tell users to finish or delete every MutexRunConfig
first (its finalizer restores the cluster), and recreate the CRs under the new group. Decide this before any wider
release. The longer the group is published, the more users it breaks.

## Decisions left to the new owner

* **License.** The repository has no `LICENSE` file, so the code has no stated license. The role metadata says
  `NOASSERTION` until one is chosen. Add the file, update `roles/*/meta/main.yml`, and mention it in the docs.
* **API group.** See above.
* **Registry and digests.** Releases go to `ghcr.io/<repository owner>` through the release workflow. Decide
  whether to mirror the 0.1.x and 0.2.x images (on `quay.io/jskrzypek`, which goes away), and whether releases record
  bundles by digest in the catalog. `make release` records them by tag; pinning by digest takes the step-by-step
  sequence under "Releasing" in `docs/DEVELOPMENT.md`, which passes the pushed bundle's digest to `make catalog-add`.
* **Version.** `.envrc` is at 0.3.0, because 0.2.67 and 0.2.68 are already published.
* **The 0.2.x to 0.3.0 upgrade.** In the project's own catalog 0.3.0 is the first entry of a new catalog image
  (`skipRange: <0.3.0`, no `replaces`). 0.2.x installs get it only after they point their CatalogSource at that image
  (USAGE, "Upgrading from 0.2.x"), and with `Automatic` approval then take it at once. 0.3.0 drops `SingleNamespace`,
  reconciles only CRs in the operator namespace, and its CRDs validate fields that 0.2.x accepted freely. Publishing
  `bundles/0.3.0` to the community catalogs makes it the upgrade of 0.2.66 there (their `updateGraph: semver-mode`),
  which `Automatic` 0.2.x installs take unattended; publishing it there in a new channel instead, so that 0.2.x users
  opt in, is the alternative. The release notes for 0.3.0 should point to
  [Upgrading from 0.2.x](USAGE.md#upgrading-from-02x) in `docs/USAGE.md`, which is also in the CSV description.
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
8. An OLM upgrade from 0.2.68 to 0.3.0 with CRs in the operator namespace, following "Upgrading from 0.2.x" in
   `docs/USAGE.md`.
   **Live run** (with the old catalog, where 0.3.0 replaced 0.2.68 in the same catalog image): including a failed
   InstallPlan and the recovery now documented there; the CRs survived and were reconciled. **Still open:** the
   upgrade by pointing an existing 0.2.x CatalogSource at the fresh `ghcr.io` catalog (no 0.2.x bundles, 0.3.0 offered
   through its `skipRange`).
9. A run whose canary has nodes of its own (with the sample canary, a worker node with `isCanary`; with a custom
   target pool such as `apps`, also `node-role.kubernetes.io/app=canary`). The molecule tests have no such node. Check
   that they stay in the canary at the start and at the end of the run: the first reconcile reports `MCPUpdated=False`
   (`CanaryMembersLabelled`), and the canary then has its own `matchExpressions` plus one `DoesNotExist` per mutex
   label and the `openshift-optional.skrzypek.io/release-labelled-at` annotation. The pools are re-pointed only at a
   reconcile at least 5 minutes (`mutexrunconfig_label_settle_seconds`) later, also when the operator pod restarts in
   between. After the run the nodes keep the release label until a reconcile at least 5 minutes after the time in the
   canary's `openshift-optional.skrzypek.io/restored-at` annotation, normally the one 10 minutes after the run (the
   reconcile right after it keeps the label), and then the annotation goes as well. Check that MCO never
   moves them into `worker`, also while the kube-apiserver rolls out at the start of the run, and that deleting the
   MutexRunConfig in the middle of a run moves them through `worker` at most once (the finalizer has a single pass).
   **Live run:** one canary node of its own with the sample canary. The label, the hold selector and
   `release-labelled-at` came in the first reconcile, during the kube-apiserver rollout; the operator restarted before
   the re-point, and the reconcile after the restart waited again; the pools were re-pointed 13 minutes later. The node
   never left the canary; MCO upgraded it there; its label and `restored-at` went at a reconcile 5 minutes after the
   restore. **Still open:** the mid-run delete, and the custom-pool variant.
10. A target node that is already at the new version while another target node is upgraded. On a build before the
    release-label canary such a node moving into the re-pointed canary made the in-flight guard report one spurious
    `NodeUpgradeFailed`. The release-label canary removes the cause (a node that is not behind never gets the release
    label), but this was not run again.
11. The manual steps in "Recovery" in `docs/USAGE.md` as written now. An earlier version, without the release-label
    and canary-annotation steps, was run live and restored everything.
