# mutextarget

Reconciles `MutexTarget` resources (`openshift-optional.skrzypek.io/v1alpha1`). ansible-operator runs it for every
MutexTarget event and every 10 minutes (`watches.yaml`). It is not meant to be used outside the operator. It
reads MachineConfigPools and Nodes and never changes them.

## What it does

1. **Namespace check.** If `POD_NAMESPACE` is set and the MutexTarget is in a different namespace, it writes
   `Reconciled=False` (reason `NamespaceNotAllowed`) and stops.
2. **Validation** (`tasks/01-validate.yml`). `spec.machineConfigPools` must not be empty, and every pool in it must
   exist. On success it writes `ValidConfig=True` (reason `MachineConfigPoolFetchSucceeded`). On failure it writes
   `ValidConfig=False` (reason `MachineConfigPoolFetchFailed`) and an empty `status.nodes`, so a stale node list
   never survives.
3. **Node list** (`tasks/02-gather-nodes.yml`):
   - Every pool's `nodeSelector` is turned into a label selector, using both `matchLabels` and `matchExpressions`
     (`In`, `NotIn`, `Exists`, `DoesNotExist`).
   - While a MutexRunConfig run has changed a pool's selector, the role uses the original `matchExpressions`, read
     from the pool's `openshift-optional.skrzypek.io/original-match-expressions` annotation. The list therefore
     stays the same for the whole run.
   - A node is assigned to a pool the way MCO assigns it: the custom pool it matches first, then `master`, then
     `worker`. A worker-labelled node that sits in the canary, infra or another custom pool is not a node of the
     `worker` target.
   - An empty or unsupported selector on a target pool is an error, because an empty label selector would select
     every node.
   - The nodes are written, sorted, to `status.nodes`, with `NodeListGathered=True`. On failure it writes `False`
     (reason `MachineConfigPoolFetchFailed`) and an empty list.

The `mutexrunconfig` role only uses MutexTargets that report `ValidConfig=True` and `NodeListGathered=True` and have
a non-empty `status.nodes`.

## Inputs

| Variable | Source |
| --- | --- |
| `_openshift_optional_skrzypek_io_mutextarget_spec` | The MutexTarget `spec`, passed by ansible-operator. |
| `ansible_operator_meta.name`, `.namespace` | The MutexTarget's name and namespace, passed by ansible-operator. |
| `POD_NAMESPACE` (environment) | The operator's namespace. Unset means every namespace is allowed. |

`vars/main.yml` holds the annotation and label names the MutexRunConfig role uses, the selector builder
`mutextarget_selector`, the timestamp helper `mutextarget_now` and the rescue message helper. Nothing in it is meant
to be overridden.

## Requirements

- ansible-core 2.18 or later (the `quay.io/operator-framework/ansible-operator:v1.42.3` base image).
- Collections `kubernetes.core` and `operator_sdk.util` (see `requirements.yml`).
- API access: `get` and `list` on `machineconfigpools` and `nodes`, and `get`, `update` and `patch` on
  `mutextargets/status` (see `config/rbac/role.yaml`).

## License

The repository has no license file yet; see `docs/HANDOFF.md`.
