# mutexrule

Reconciles `MutexRule` resources (`nodeupgrade.redhat-na-ssa.github.io/v1alpha1`). ansible-operator runs it for every
MutexRule event and every 10 minutes (`watches.yaml`). It is not meant to be used outside the operator.

## What it does

1. **Namespace check.** If `POD_NAMESPACE` is set and the MutexRule is in a different namespace, it writes
   `Reconciled=False` (reason `NamespaceNotAllowed`) and stops.
2. **Validation** (`tasks/01-validate.yml`):
   - `spec.type` must be `kubernetes`.
   - `spec.jobName` must be set, `spec.jobSpec` must be an object, `spec.cleanUpJobSpec` must be an object when it
     is set, and `spec.timeoutSeconds` must be a positive integer.
   - `jobSpec`, and `cleanUpJobSpec` if set, are sent to the API server as a **server-side dry-run create** of a Job
     (`check_mode: true`, which kubernetes.core turns into `dryRun=All`) in `spec.jobNamespace`. When that is not set,
     the MutexRule's namespace is used. The API server applies its schema, defaulting, admission and RBAC checks.
     Nothing is created, changed or deleted.
3. **Status.** It writes `ValidConfig=True` (reason `ValidConfig`), or `ValidConfig=False` (reason `InvalidConfig`)
   with the error message. Conditions are merged by type, and the status is never wiped.

The `mutexrunconfig` role only uses MutexRules that report `ValidConfig=True`.

## Inputs

| Variable | Source |
| --- | --- |
| `_nodeupgrade_redhat_na_ssa_github_io_mutexrule_spec` | The MutexRule `spec`, passed by ansible-operator. |
| `ansible_operator_meta.name`, `.namespace` | The MutexRule's name and namespace, passed by ansible-operator. |
| `POD_NAMESPACE` (environment) | The operator's namespace (downward API in `config/manager/manager.yaml`). Unset means every namespace is allowed, as with `make run`. |

`vars/main.yml` defines `mutexrule_spec`, `mutexrule_job_namespace`, the RFC 3339 timestamp helper `mutexrule_now`
and the rescue message helper `mutexrule_failed_msg`. Nothing in it is meant to be overridden.

## Requirements

- ansible-core 2.18 or later (the `quay.io/operator-framework/ansible-operator:v1.42.3` base image).
- Collections `kubernetes.core` and `operator_sdk.util` (see `requirements.yml`).
- API access: `batch/jobs` `create` (dry run) in the job namespace, plus `get`, `update` and `patch` on
  `mutexrules/status`. The full list is in `config/rbac/role.yaml`.

## License

The repository has no license file yet; see `docs/HANDOFF.md`.
