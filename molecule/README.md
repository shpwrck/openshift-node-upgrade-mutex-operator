# Molecule tests

Two scenarios deploy the operator from `config/testing` and check it end to
end. `tests/Scenarios.md` lists what each one covers.

| Scenario | Cluster | Use it for |
| --- | --- | --- |
| `kind` | a new kind cluster (1 control plane, 2 workers) with fake OpenShift APIs | the full run: simulated upgrade and finalizer; runs in CI (`.github/workflows/e2e.yaml`) |
| `default` | whatever `KUBECONFIG` points at, e.g. an OpenShift test cluster where the operator and its CRDs are not installed by any method | checks that are safe on a real cluster; never simulates an upgrade |

## Requirements

- Python 3.11 to 3.13 and `pip install -r molecule/requirements.txt`
  (molecule 25, ansible-core 2.18, the kubernetes client). The collections
  in `requirements.yml` are installed by molecule's dependency step.
- kustomize (`make kustomize` puts it in `bin/`; pass its path as
  `KUSTOMIZE_PATH`).
- `kind`: kind, and docker or podman. Without docker, kind's podman provider
  is used (`KIND_EXPERIMENTAL_PROVIDER=podman`). Rootless podman needs a
  cgroup v2 host with the cpu controller delegated to the user
  (https://kind.sigs.k8s.io/docs/user/rootless/).
- `default`: an operator image the cluster can pull (`OPERATOR_IMAGE`), and
  for the MutexRunConfig checks a `canary` MachineConfigPool (see the README).
  The cluster must not have the operator or its CRDs installed by any method
  (OLM, `make install`, `make deploy`, kustomize), see below.

No registry login is needed: the image builds from public base images, and
the cluster pulls the sample Job image from registry.access.redhat.com
anonymously.

## Run

```sh
export KUSTOMIZE_PATH=$PWD/bin/kustomize-v5.8.3   # after: make kustomize

# Fake OpenShift on kind (builds the image with CONTAINER_TOOL, default podman)
molecule test -s kind
CONTAINER_TOOL=docker molecule test -s kind

# A real cluster without the operator; destroy deletes only the CRDs converge created
OPERATOR_IMAGE=quay.io/<org>/openshift-node-upgrade-mutex-operator:<tag> molecule test -s default
```

The `default` scenario's destroy, which `molecule test` also runs first,
deletes the operator's CRDs, and deleting a CRD deletes every MutexRule,
MutexTarget and MutexRunConfig in the cluster. converge therefore labels the
CRDs it creates with
`molecule.openshift-optional.skrzypek.io/test-namespace=<TEST_OPERATOR_NAMESPACE>`,
and prepare, converge and destroy refuse to run when an operator CRD exists
without that label (the operator is installed some other way, or by a run
with another `TEST_OPERATOR_NAMESPACE`) or when a MutexRule, MutexTarget or
MutexRunConfig exists outside the test namespace (and the
`<TEST_OPERATOR_NAMESPACE>-foreign` namespace of the namespace boundary
check). On a cluster without the CRDs, both checks pass.

`molecule converge -s kind` then `molecule verify -s kind` keeps the cluster
for debugging (`molecule destroy -s kind` removes it); verify can be re-run on
the same cluster. A failed verify prints the CRs, pools, ClusterVersion, node
labels, Jobs, pods and the operator log.

| Variable | Scenario | Default | Meaning |
| --- | --- | --- | --- |
| `TEST_OPERATOR_NAMESPACE` | both | `osdk-test` | namespace the operator and the test CRs run in |
| `KUSTOMIZE_PATH` | both | `kustomize` | kustomize binary |
| `OPERATOR_IMAGE` | both | kind: `localhost/mutex-operator:molecule` | image to deploy (kind: to build and load) |
| `OPERATOR_PULL_POLICY` | default | `Always` | manager imagePullPolicy |
| `OPERATOR_BUILD` | kind | `true` | `false` loads an `OPERATOR_IMAGE` built beforehand |
| `CONTAINER_TOOL` | kind | `podman` | builds and saves the image (`podman` or `docker`) |
| `KIND`, `KIND_CLUSTER_NAME`, `KIND_NODE_IMAGE` | kind | `kind`, `osdk-test`, kind's default | kind binary, cluster name, node image |
| `E2E_CHECK_JOB_LOGS` | kind | `true` | read the Job pod logs to check that `$(NODE_NAME)` expanded |

## How the kind scenario fakes OpenShift

`prepare` installs CRDs for `machineconfigpools.machineconfiguration.openshift.io`
and `clusterversions.config.openshift.io` (status subresource, no schema),
the `master`, `worker` and README `canary` pools, a ClusterVersion `version`
at a completed 4.16.4, and labels and annotates the nodes like OpenShift
does (`default/tasks/fake_reset.yml`): `node-role.kubernetes.io/master` or
`/worker`, the `machineconfiguration.openshift.io/release-image-version`
label NFD would publish, and the MCO annotations of a node that is not
updating (`machineconfiguration.openshift.io/state: Done`, and
`currentConfig` and `desiredConfig` both `rendered-<master|worker>-<hash>`).
There is no MCO: for each released node the verify playbook plays its part
(`default/tasks/upgrade_node.yml`). It sets `desiredConfig` to the canary's
rendered config and `state` to `Working`, sets the release-image-version
label to the new version and checks that no cleanup Job has started yet,
then sets `state` to `Done` and `currentConfig` to the `desiredConfig`. The
kind nodes report `Ready` themselves. The MutexRunConfigs it creates carry
the annotation
`ansible.sdk.operatorframework.io/reconcile-period: 15s`, so the operator
notices the ClusterVersion change quickly (it does not watch ClusterVersion).

molecule never edits tracked files: the image, pull policy and namespace go
into a throwaway kustomize overlay in `$MOLECULE_EPHEMERAL_DIRECTORY`.

Lint: `yamllint -c hack/yamllint.yaml molecule/` and
`ansible-lint -c molecule/.ansible-lint --project-dir . molecule/`, from the
repository root.
