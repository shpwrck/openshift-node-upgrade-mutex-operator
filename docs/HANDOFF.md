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
| CSV `containerImage` annotation | CSV base | `quay.io/jskrzypek/openshift-node-upgrade-mutex-operator` (no tag) | The operator image in the new registry, with a tag. `make bundle` does not update this field. |
| Image registry | `.envrc` `IMAGE_TAG_BASE` | `quay.io/jskrzypek/openshift-node-upgrade-mutex-operator` | The new registry. The Makefile default is the placeholder `example.com/...`, which `make release` refuses. |
| Manager image | `config/manager/kustomization.yaml` `images[controller]` | `quay.io/jskrzypek/openshift-node-upgrade-mutex-operator:0.2.66` | The new registry. `make bundle` and `make deploy` rewrite it on every run, so it only matters for a plain `kustomize build`. |
| Sample CatalogSource | `sample-manifests/catalogsource.yaml` | name `skrzypek-io`, display name and publisher of the original author, image `quay.io/jskrzypek/...-catalog:latest`, `registryPoll.interval: 1m` | A neutral name and publisher, the new catalog image with a pinned tag, and a poll interval of 10 minutes or more. A 1-minute poll starts a catalog pod every minute. |
| Released bundle images | `catalog-template.yaml` (124 references) and `catalog/openshift-node-upgrade-mutex-operator/catalog.yaml` (1116) | `quay.io/jskrzypek/...-bundle@...` and the related images of every released version | Either mirror the images to the new registry (`skopeo copy --all` keeps the digests), rewrite the references in the template and run `make catalog-render`, or keep them as published history. Either way the old images must stay pullable while clusters use catalogs that point at them. |
| Community catalogs | `operators/openshift-node-upgrade-mutex-operator/` in [k8s-operatorhub/community-operators](https://github.com/k8s-operatorhub/community-operators) and [redhat-openshift-ecosystem/community-operators-prod](https://github.com/redhat-openshift-ecosystem/community-operators-prod) | The package is published there with the original author as reviewer | Update the package's `ci.yaml` reviewers in both repositories. |
| Role metadata | `roles/*/meta/main.yml` | `license: NOASSERTION` | The license you choose (see below). |

### The API group: breaking to change

`openshift-optional.skrzypek.io` (and `domain: skrzypek.io` in `PROJECT`) is tied to the original author's domain. It
is the group of all three CRDs, and it appears in:

* the CRD names (`mutexrules.openshift-optional.skrzypek.io`, ...), the CSV, RBAC, samples, molecule tests and docs;
* the finalizer `openshift-optional.skrzypek.io/finalizer`;
* the node labels `mutexrule.openshift-optional.skrzypek.io/<rule>.<namespace>`;
* the MachineConfigPool annotations `openshift-optional.skrzypek.io/paused-by` and
  `openshift-optional.skrzypek.io/original-match-expressions`;
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
* **Registry and digests.** Choose the registry, mirror the published images, and decide whether releases record
  bundles by digest in the catalog (`make catalog-add BUNDLE_REF=<repo>@sha256:...`).
* **Version.** `.envrc` is at 0.3.0, because 0.2.67 and 0.2.68 are already published.
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
RBAC. None of these has MCO, so before relying on it, run on a non-production OpenShift 4.16+ cluster:

1. An install through OLM, in `OwnNamespace` and in `AllNamespaces` mode. Check that `WATCH_NAMESPACE` and
   `POD_NAMESPACE` are set and that CRs outside the operator namespace report `NamespaceNotAllowed`.
2. A real upgrade with at least two target nodes. Check that the pools are paused before MCO reaches them, that each
   node moves into the canary only after its Jobs, that MCO upgrades it there, and that nodes go back to their pool
   at the end without another reboot.
3. Aborting by deleting a MutexRunConfig in the middle of a run, and a restart of the operator pod mid-run.
4. A failing Job, a Job that times out, and a node that never reports the new version: `Degraded=True`, the pools
   stay paused, and the next reconcile retries.
5. The `release-image-version` label example in `sample-manifests/` (MachineConfig and NFD) on a current release.
6. `operator-sdk scorecard` against the bundle, and scraping the HTTPS metrics endpoint with the
   `openshift-node-upgrade-mutex-operator-metrics-reader` ClusterRole bound to the scraper (see the binding example
   in the Permissions section of `docs/USAGE.md`).
