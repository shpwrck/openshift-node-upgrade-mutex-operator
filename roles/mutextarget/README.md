# mutextarget

Reconciles `MutexTarget` resources (`nodeupgrade.redhat-na-ssa.github.io/v1alpha1`). ansible-operator runs it for every
MutexTarget event and every 10 minutes (`watches.yaml`). It is not meant to be used outside the operator. It
reads MachineConfigPools and Nodes and never changes them.

## What it does

1. **Namespace check** (`tasks/main.yml`). If `POD_NAMESPACE` is set and the MutexTarget is in a different
   namespace, it writes `Reconciled=False` (reason `NamespaceNotAllowed`) and stops.
2. **Validation** (`tasks/01-validate.yml`). `spec.machineConfigPools` must not be empty, and every pool in it must
   exist. On success it writes `ValidConfig=True` (reason `MachineConfigPoolFetchSucceeded`). On failure it writes
   `ValidConfig=False` (reason `MachineConfigPoolFetchFailed`) and an empty `status.nodes`, so a stale node list
   never survives.
3. **Node list** (`tasks/02-gather-nodes.yml`):
   - Every pool's `nodeSelector` is turned into a label selector, using both `matchLabels` and `matchExpressions`
     (`In`, `NotIn`, `Exists`, `DoesNotExist`).
   - While a MutexRunConfig run has changed a pool's selector, the role uses the original `matchExpressions`, read
     from the pool's `nodeupgrade.redhat-na-ssa.github.io/original-match-expressions` annotation. The list therefore
     stays the same for the whole run.
   - Each node is assigned to one pool, in imitation of MCO (see the next section): a custom pool it matches, else
     `master`, else `worker`. A worker-labelled node that sits in the canary, infra or another custom pool is
     therefore not a node of the `worker` target.
   - An empty or unsupported selector on a target pool is an error, because an empty label selector would select
     every node.
   - The nodes are written, sorted, to `status.nodes`, with `NodeListGathered=True`. On failure it writes `False`
     (reason `MachineConfigPoolFetchFailed`) and an empty list.

The `mutexrunconfig` role only uses MutexTargets that report `ValidConfig=True` and `NodeListGathered=True` and have
a non-empty `status.nodes`.

## How MCO assigns a node to a pool

A node can match the selectors of several pools. MCO then picks one pool for it. This is `GetPoolsForNode` in
[pkg/helpers/helpers.go](https://github.com/openshift/machine-config-operator/blob/release-4.21/pkg/helpers/helpers.go)
of the Machine Config Operator, the same on the `release-4.16` and `release-4.21` branches:

| The node matches | MCO puts it in |
| --- | --- |
| `worker` only | `worker` |
| one custom pool, with or without `worker` | the custom pool |
| `master`, with or without `worker` | `master` |
| `master` and one custom pool | `master`; MCO logs that it defaults to master and ignores the custom pool |
| two or more custom pools (with or without `master`) | no pool: MCO refuses the node ("belongs to N custom roles") |

`tasks/02-gather-nodes.yml:89-96` follows this table except in two cases:

- A node that matches `master` and a custom target pool: the role picks the custom pool and lists that control-plane
  node in `status.nodes`, while MCO keeps it in `master`.
- A node that matches two custom pools, one of them a target: the role lists it in `status.nodes`, while MCO manages
  it in no pool.

The comment at `tasks/02-gather-nodes.yml:10-13` describes the role's rule, not MCO's. So a target pool should never
select control-plane nodes, and no node should match two custom pools. [DESIGN.md](../../docs/DESIGN.md) lists the other
places that depend on MCO's choice.

## Inputs

| Variable | Source |
| --- | --- |
| `_nodeupgrade_redhat_na_ssa_github_io_mutextarget_spec` | The MutexTarget `spec`, passed by ansible-operator. |
| `ansible_operator_meta.name`, `.namespace` | The MutexTarget's name and namespace, passed by ansible-operator. |
| `POD_NAMESPACE` (environment) | The operator's namespace. Unset means every namespace is allowed. |

`vars/main.yml` holds the annotation and label names the MutexRunConfig role uses, the selector builder
`mutextarget_selector`, the timestamp helper `mutextarget_now` and the rescue message helper. Nothing in it is meant
to be overridden. `mutextarget_annotation_original_expressions` and `mutextarget_label_prefix` are copies of the
`mutexrunconfig` role's names (`roles/mutexrunconfig/vars/main.yml`), and `mutextarget_selector` is a copy of its
selector builder. Change them together.

## Requirements

- ansible-core 2.18 or later (the `quay.io/operator-framework/ansible-operator:v1.42.3` base image).
- Collections `kubernetes.core` and `operator_sdk.util` (see `requirements.yml`).
- API access: `get` and `list` on `machineconfigpools` and `nodes`, and `get`, `update` and `patch` on
  `mutextargets/status` (see `config/rbac/role.yaml`).

## License

Apache-2.0, like the rest of the repository: see [LICENSE](../../LICENSE).
