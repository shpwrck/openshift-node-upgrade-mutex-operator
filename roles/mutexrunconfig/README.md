# mutexrunconfig

Reconciles `MutexRunConfig` resources (`openshift-optional.skrzypek.io/v1alpha1`). ansible-operator runs it for every
MutexRunConfig event and every 10 minutes (`watches.yaml`). On deletion the `openshift-optional.skrzypek.io/finalizer`
finalizer runs it once more with `state: absent`. It is not meant to be used outside the operator.

The user-facing description of the procedure, its conditions and recovery is in `docs/USAGE.md`. This file maps that
procedure to the task files.

## Task files

| File | Step |
| --- | --- |
| `tasks/main.yml` | Namespace check (`Reconciled=False NamespaceNotAllowed` outside `POD_NAMESPACE`), gate facts, finalizer branch, then the steps below. Each gate is set to false at the top of its rescue and to true as the last task of its block. |
| `00-resolve-references.yml` | Normalises `spec.mutexRules` and `spec.mutexTargets`. A missing `namespace` becomes the MutexRunConfig's namespace. Builds each rule's node label `mutexrule.openshift-optional.skrzypek.io/<rule>.<namespace>`. |
| `01-validate.yml` | Read-only checks, reported as `ConfigValidated`: references, label keys, the operator namespace, the rules' `ValidConfig`, the targets' `ValidConfig`/`NodeListGathered`/`status.nodes`, and the canary (exists, unpaused, not a target, its `matchLabels` select every target node, no overlap with other custom pools or master). Then the APIService health gate (`ClusterStateValidated`). |
| `02-check-for-upgrade.yml` | Reads ClusterVersion `version`. The desired version is `status.desired.version`, and the control plane is done when `status.history[0]` is `Completed` for it. Every target node must carry a semver `machineconfiguration.openshift.io/release-image-version` label (`NodeVersionsKnown`). Writes `UpgradeAvailable` (a target node is behind), `UpgradeReady` (and the control plane is done) and `UpgradeChecked`. |
| `03-pause-machine-config-pools.yml` | Pauses the target pools that are not paused yet and marks them with `openshift-optional.skrzypek.io/paused-by: <namespace>/<name>`. |
| `04-apply-mutex-rules-as-labels.yml` | Labels every target node that is behind with one mutex label per rule. Nodes MCO is already updating through the canary are skipped. |
| `05-modify-machineconfigpool.yml` | Saves each pool's original `matchExpressions` in `openshift-optional.skrzypek.io/original-match-expressions`. Target pools then get `<label> Exists` per rule. The canary gets the expressions every target node satisfies plus `<label> DoesNotExist` per rule. |
| `06-execute-jobs.yml` | Runs once per target node, one node at a time: the pre-upgrade Jobs, then removing the node's mutex labels, then waiting for the node to report the desired version, then the cleanup Jobs. A node that is already upgraded is skipped. |
| `07-run-job.yml` | Runs one Job: injects `NODE_NAME`/`MUTEX_RULE` and the hostname `NotIn` affinity, reuses a Job with the same `openshift-optional.skrzypek.io/job-key` label, creates it with `generateName`, and polls until it is Complete or Failed or `timeoutSeconds` runs out. |
| `08-restore.yml` | Restores the saved selectors, removes this run's mutex labels and unpauses only the pools whose `paused-by` names this MutexRunConfig. It is used at the end of a run and by the finalizer. |
| `09-report.yml` | Writes `TargetPoolsPaused` and `Degraded` (`PoolsLeftPaused`, `RunInProgress` or `NoPoolsPaused`). |

A failure never unpauses a pool. The pools stay paused, `Degraded=True` explains why, and the next reconcile
retries. Deleting the MutexRunConfig is the way to abort.

## Inputs

| Variable | Source |
| --- | --- |
| `_openshift_optional_skrzypek_io_mutexrunconfig_spec`, `_openshift_optional_skrzypek_io_mutexrunconfig` | The MutexRunConfig spec and full object, passed by ansible-operator. |
| `ansible_operator_meta.name`, `.namespace` | The MutexRunConfig's name and namespace. |
| `state` | `absent` when the finalizer runs (`watches.yaml`). |
| `POD_NAMESPACE` (environment) | The operator's namespace. Unset means every namespace is allowed. |

### Defaults (`defaults/main.yml`)

| Variable | Default | Meaning |
| --- | --- | --- |
| `mutexrunconfig_node_upgrade_retries` / `_delay` | `120` / `60` | How long to wait (retries × seconds, 2 hours by default) for a released node to report the desired version. |
| `mutexrunconfig_job_timeout_seconds` | `3600` | Job timeout used when a MutexRule has no `spec.timeoutSeconds`. |
| `mutexrunconfig_job_poll_delay` | `10` | Seconds between Job status polls. |
| `mutexrunconfig_apiservice_retries` / `_delay` | `3` / `10` | Attempts at the APIService health check, and the delay between them. |

No CRD field exposes these. To change them for the whole operator, set them under `vars:` of the MutexRunConfig
entry in `watches.yaml` and rebuild the image.

## Requirements

- ansible-core 2.18 or later (the `quay.io/operator-framework/ansible-operator:v1.42.3` base image).
- Collections `kubernetes.core` and `operator_sdk.util` (see `requirements.yml`). No `oc` binary and no Python
  libraries beyond those in the base image are needed.
- API access as listed in `config/rbac/role.yaml`.

## License

The repository has no license file yet; see `docs/HANDOFF.md`.
