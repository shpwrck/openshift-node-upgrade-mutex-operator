# OpenShift Node Upgrade Mutex Operator

During an OpenShift upgrade this operator holds back the worker nodes you choose and releases them one at a time.
For each node it first runs the Kubernetes Jobs you define, then lets the Machine Config Operator (MCO) upgrade the
node, waits until the node reports the new version, runs your cleanup Jobs and only then moves on to the next node.
Typical Jobs drain or fence an application, move a storage replica, or wait for an external system to agree.

It works with three custom resources:

* **MutexRule**: one Job to run before each node is upgraded, plus an optional cleanup Job to run after.
* **MutexTarget**: the MachineConfigPools whose nodes are upgraded this way.
* **MutexRunConfig**: ties rules to targets and names the *canary* MachineConfigPool that nodes are upgraded through.

> **Status: alpha.** The operator manages one cluster. It pauses MachineConfigPools and rewrites their node selectors
> during an upgrade. This version has been checked with linting, bundle and schema validation, and test runs against
> Kubernetes API servers that have no Machine Config Operator. It has **not been tested end to end on a live OpenShift
> upgrade**. Validate it on a non-production cluster before you rely on it.

## How it works

MCO upgrades the nodes of a MachineConfigPool once the pool is unpaused. The operator uses that:

1. When ClusterVersion `version` reports a new `status.desired.version` and a target node is behind it, the operator
   **pauses the target pools** and puts one **mutex label** per MutexRule on each target node that still needs the
   upgrade.
2. It changes the **node selectors**. A target pool keeps only nodes that still carry the mutex labels. The canary
   pool, which is not paused, picks up any target node that has lost them.
3. Once the control plane has finished (`status.history[0]` is `Completed` for that version), it works through the
   target nodes **one at a time**. It runs the MutexRule Jobs for the node, removes the node's mutex labels (so the
   node moves into the canary pool and MCO upgrades it), waits for the node to report the new version, then runs
   the cleanup Jobs.
4. After the last node it **restores** the original selectors, removes the labels and unpauses the pools it paused.

When something fails, the pools **stay paused**. No node is upgraded without its Jobs. The MutexRunConfig reports
`Degraded=True`, and the operator retries (see [Retries](#retries)). To give up instead, delete the MutexRunConfig
(see [Recovery](#recovery)).

## Prerequisites

### OpenShift version

OpenShift 4.16 or later (Kubernetes 1.29 or later). The operator reads `config.openshift.io/v1` ClusterVersion and
patches `machineconfiguration.openshift.io/v1` MachineConfigPools, so it does not work on plain Kubernetes.

### Release version label on every target node

The operator compares the version a node runs with the version the cluster is moving to. It reads the node's version
from the label

```
machineconfiguration.openshift.io/release-image-version=<x.y.z>     (for example 4.16.4)
```

OpenShift does not set this label. You have to maintain it. One way is a MachineConfig that writes the version from the
node's current MachineConfig into a Node Feature Discovery (NFD) feature file, together with an NFD instance that
publishes it as a label. Examples are in the repository:
[sample-manifests/machineconfig.yaml](https://github.com/shpwrck/openshift-node-upgrade-mutex-operator/blob/main/sample-manifests/machineconfig.yaml)
and
[sample-manifests/nodefeaturediscovery.yaml](https://github.com/shpwrck/openshift-node-upgrade-mutex-operator/blob/main/sample-manifests/nodefeaturediscovery.yaml).
Check that the label is right on your cluster before you rely on it.

The check **fails closed**. If any target node has no label, or a value that is not a semantic version, the
MutexRunConfig reports `NodeVersionsKnown=False` with the node names, and nothing is paused, labelled or run.

### A canary MachineConfigPool

The canary is an existing MachineConfigPool that target nodes pass through while they are upgraded. The operator checks
before every run that the canary:

* exists and is **not paused**;
* is **not** one of the target pools;
* has `nodeSelector.matchLabels` that select **every target node**, for example `node-role.kubernetes.io/worker: ""`;
* selects no node of another custom pool or of the `master` pool once the run has changed its selector. MCO refuses a
  node that matches two custom pools.

During a run the canary keeps those of its own `matchExpressions` that every target node already satisfies, for example
`node-role.kubernetes.io/infra DoesNotExist`. Other expressions, such as the `isCanary Exists` below, are left out for
the length of the run and put back afterwards. If validation reports an overlap with another pool, add an expression
that excludes that pool's nodes and that every target node satisfies.

The canary should render the same MachineConfigs as the target pools, so a node gets the same configuration in either
pool:

```yaml
apiVersion: machineconfiguration.openshift.io/v1
kind: MachineConfigPool
metadata:
  name: canary
spec:
  machineConfigSelector:
    matchLabels:
      machineconfiguration.openshift.io/role: worker
  nodeSelector:
    matchLabels:
      node-role.kubernetes.io/worker: ""
    matchExpressions:
      - key: isCanary
        operator: Exists
  paused: false
```

Use one canary per MutexRunConfig. Two MutexRunConfigs must not share a canary or a target pool.

### Permissions for the Jobs

Jobs run with the ServiceAccount set in their pod template (`default` when none is set), in `spec.jobNamespace` of the
MutexRule. The operator creates neither the namespace, nor the ServiceAccount, nor any RBAC the Jobs need.

## Installation

Install the operator from its catalog (OperatorHub, or a CatalogSource that serves the operator catalog image) into a
namespace of its own, for example `node-upgrade-mutex-operator`, the suggested namespace. Install it **once per
cluster**.

**Install modes.** Two modes are supported:

| Install mode | Watches | CRs outside the operator namespace |
| --- | --- | --- |
| `OwnNamespace` | the operator namespace only | ignored |
| `AllNamespaces` | all namespaces | get `Reconciled=False`, reason `NamespaceNotAllowed`; nothing else happens |

`SingleNamespace` and `MultiNamespace` are not supported. The manager reads `WATCH_NAMESPACE` from the
`olm.targetNamespaces` annotation that OLM sets, and reads its own namespace from `POD_NAMESPACE`. The roles only act
on CRs in `POD_NAMESPACE`, so a target namespace other than the operator's own would contain only CRs the operator
refuses.

**Create every MutexRule, MutexTarget and MutexRunConfig in the operator namespace**, and leave out the `namespace`
of the references in a MutexRunConfig. They default to the MutexRunConfig's namespace. A reference to another namespace
fails validation.

### Upgrading from 0.2.x

0.3.0 is published in the `alpha` channel as the upgrade of 0.2.68, with `skipRange: <0.3.0`, so every 0.2.x
Subscription is offered it. The common install needs no changes: the operator in its own namespace (for example
`node-upgrade-mutex-operator`, through the console, which creates an `OwnNamespace` OperatorGroup) with every
MutexRule, MutexTarget and MutexRunConfig in that same namespace keeps working, as long as the CRs pass the new
schemas (step 3 below). Three changes can break other installs:

* **Only CRs in the operator namespace are reconciled.** 0.2.x reconciled CRs in every namespace. 0.3.0 installed
  `OwnNamespace` no longer watches CRs in other namespaces, and their status keeps its 0.2.x values, so nothing shows
  that they stopped working. At the next OpenShift upgrade MCO upgrades their pools without pausing them or running
  their Jobs. References to MutexRules or MutexTargets in another namespace now fail validation.
* **`SingleNamespace` is no longer supported.** With an OperatorGroup whose `spec.targetNamespaces` names a namespace
  other than its own, the 0.3.0 CSV fails with reason `UnsupportedOperatorGroup`, and 0.2.x keeps running.
* **The CRDs now validate their fields.** Before OLM upgrades a CRD it checks every existing CR against the new schema.
  If one does not pass, the InstallPlan fails with `error validating existing CRs against new CRD's schema`, names the
  CR, and 0.2.x keeps running. Every kind needs `spec`. A MutexRule needs `jobName`, a DNS-1123 label of at most 52
  characters, and `jobSpec`; `jobNamespace`, when set, must be a DNS-1123 label. A MutexTarget needs at least one
  pool. A MutexRunConfig needs `canary.name` and at least one rule and one target reference, each with a `name`; rule
  names (at most 61 characters) and every reference `namespace` must be DNS-1123 labels.

Before you approve 0.3.0:

1. Set the Subscription to manual approval, so OLM waits for you. With `Automatic` approval it installs 0.3.0 as soon
   as the catalog serves it:

   ```sh
   oc patch subscription <name> -n <operator namespace> --type=merge -p '{"spec":{"installPlanApproval":"Manual"}}'
   ```

2. Upgrade only when no OpenShift upgrade is in progress and no 0.2.x run is half done. 0.2.x has no finalizer and does
   not record what it changed, so 0.3.0 can neither finish nor undo a 0.2.x run. No target pool should be paused,
   except by you, and this must print nothing:

   ```sh
   oc get nodes,mcp -o yaml | grep 'mutexrule.openshift-optional.skrzypek.io/'
   ```

   If it prints labels or `matchExpressions`, let the run finish, or put the pools' original `matchExpressions` back,
   remove the labels and unpause the pools by hand.
3. List the CRs in all namespaces, and check each one against the schema rules above:

   ```sh
   oc get mutexrules,mutextargets,mutexrunconfigs -A
   ```

   Recreate every CR that is outside the operator namespace inside it, with references that leave out `namespace`,
   then delete the old one.
4. If the OperatorGroup targets another namespace (`SingleNamespace`), make it `OwnNamespace`. OLM also retries a
   0.3.0 CSV that has already failed with `UnsupportedOperatorGroup` once the OperatorGroup changes:

   ```sh
   oc patch operatorgroup <name> -n <operator namespace> --type=merge -p '{"spec":{"targetNamespaces":["<operator namespace>"]}}'
   ```

5. Approve the InstallPlan. Afterwards `oc get mutexrunconfig -n <operator namespace>` must show every
   MutexRunConfig as `Validated` `True`. Fix any that is not before the next OpenShift upgrade: 0.3.0 checks more
   than 0.2.x did (see [Reconcile procedure](#reconcile-procedure)), and a MutexRunConfig that fails validation pauses
   nothing.

## Custom resources

All three kinds are `openshift-optional.skrzypek.io/v1alpha1`, namespaced, and in the `numo` category, so
`oc get numo` lists them all.

### MutexRule

One operation to run for each target node, as a `batch/v1` JobSpec. The operator validates the JobSpecs with a
server-side dry-run create in the job namespace (nothing is created) and reports `ValidConfig`.

| Field | Required | Description |
| --- | --- | --- |
| `spec.jobName` | yes | Prefix of the generated Jobs: `<jobName>-xxxxx` before the upgrade, `cleanup-<jobName>-xxxxx` after. A DNS-1123 label of at most 52 characters. |
| `spec.jobNamespace` | no | Namespace the Jobs run in. Defaults to the MutexRule's namespace. |
| `spec.jobSpec` | yes | `batch/v1` JobSpec run for each node before it is released for its upgrade. |
| `spec.cleanUpJobSpec` | no | `batch/v1` JobSpec run for each node after it reports the new version. |
| `spec.timeoutSeconds` | no | How long each Job of this rule may run. Default `3600`, minimum `1`. |
| `spec.type` | no | Only `kubernetes`, the default. |

The rule's **name must not contain `.`**, and `<name>.<namespace>` must be at most 63 characters. The node label is
`mutexrule.openshift-optional.skrzypek.io/<name>.<namespace>`. A MutexRunConfig that references a rule breaking this
fails validation.

```yaml
apiVersion: openshift-optional.skrzypek.io/v1alpha1
kind: MutexRule
metadata:
  name: drain-app
  namespace: node-upgrade-mutex-operator
spec:
  jobName: drain-app
  timeoutSeconds: 900
  jobSpec:
    backoffLimit: 2
    template:
      spec:
        serviceAccountName: drain-app      # needs the RBAC your command uses
        restartPolicy: Never
        containers:
          - name: drain
            image: registry.redhat.io/openshift4/ose-cli:latest
            command: ["/bin/sh", "-c"]
            args:
              - echo "preparing $(NODE_NAME) for rule $(MUTEX_RULE)"
  cleanUpJobSpec:
    template:
      spec:
        serviceAccountName: drain-app
        restartPolicy: Never
        containers:
          - name: undrain
            image: registry.redhat.io/openshift4/ose-cli:latest
            command: ["/bin/sh", "-c"]
            args:
              - echo "$(NODE_NAME) is upgraded"
```

### MutexTarget

A set of existing MachineConfigPools. The operator checks that they exist and lists their nodes in `status.nodes`. A
MutexTarget on its own changes nothing.

| Field | Required | Description |
| --- | --- | --- |
| `spec.machineConfigPools` | yes | Names of existing MachineConfigPools, at least one. Each needs a non-empty `nodeSelector`. |
| `status.nodes` | (status) | The nodes MCO assigns to these pools. A node belongs to the custom pool it matches, else to `master` if it matches master, else to `worker`. A worker node that sits in the canary or another custom pool is therefore not a node of a `worker` target. The list stays the same for the whole run. |

```yaml
apiVersion: openshift-optional.skrzypek.io/v1alpha1
kind: MutexTarget
metadata:
  name: workers
  namespace: node-upgrade-mutex-operator
spec:
  machineConfigPools:
    - worker
```

### MutexRunConfig

References the rules and targets and names the canary. This is the resource that changes the cluster.

| Field | Required | Description |
| --- | --- | --- |
| `spec.canary.name` | yes | The canary MachineConfigPool (see [Prerequisites](#a-canary-machineconfigpool)). |
| `spec.mutexRules[]` | yes | At least one item (at most 64), each `{name, namespace}`. `namespace` defaults to the MutexRunConfig's namespace: leave it out. Jobs run in this order. |
| `spec.mutexTargets[]` | yes | At least one item, each `{name, namespace}`, with `namespace` defaulting the same way. |
| `spec.skipTLSVerify` | no | **Deprecated, no effect.** Kept so existing resources stay valid. The version is read from ClusterVersion and no release image is pulled. |

```yaml
apiVersion: openshift-optional.skrzypek.io/v1alpha1
kind: MutexRunConfig
metadata:
  name: workers
  namespace: node-upgrade-mutex-operator
spec:
  canary:
    name: canary
  mutexRules:
    - name: drain-app
  mutexTargets:
    - name: workers
```

`oc get mutexrunconfig` shows the `Validated`, `Upgrade`, `Paused` and `Degraded` conditions at a glance. Add `-o wide`
to see the rules and targets.

## The Job contract

For every target node, the operator creates one Job per MutexRule from `jobSpec`, and adds to it:

* **Environment:** `NODE_NAME` (the node about to be upgraded) and `MUTEX_RULE` (the rule's name), added to every
  container and initContainer. Entries with the same names are replaced, and all other env is kept. Use them in
  `command`/`args` as `$(NODE_NAME)`.
* **Scheduling:** a `kubernetes.io/hostname NotIn [<node>]` expression, added to every required nodeSelectorTerm of the
  pod's node affinity, or as a new term. The pod never runs on the node it prepares, so it must be able to schedule on
  some other node. Pod affinity, pod anti-affinity and preferred terms are kept.
* **Metadata:** the label `openshift-optional.skrzypek.io/job-key` (a hash of MutexRunConfig, node, rule, phase and
  version) and the annotations `openshift-optional.skrzypek.io/mutexrunconfig`, `.../mutexrule`, `.../node`,
  `.../phase` (`pre` or `cleanup`) and `.../desired-version`.
* **Name:** `generateName: <jobName>-`, or `cleanup-<jobName>-` for cleanup Jobs, in `spec.jobNamespace`.

Order and timing:

1. The pre-upgrade Jobs of a node run **one after another**, in the order of `spec.mutexRules`. Each must reach
   `Complete` within the rule's `timeoutSeconds` (default 3600). A `Failed` Job stops the run at once.
2. The node's mutex labels are then removed. The node moves into the canary pool and MCO upgrades it. The operator
   waits up to 2 hours (120 checks, 60 seconds apart) for the node's `release-image-version` label to show the new
   version.
3. The cleanup Jobs of the rules that have a `cleanUpJobSpec` then run, in the same order and with the same timeout.

When a reconcile is interrupted and started again, the operator looks for a Job with the same `job-key` label. If it
finds one that has not failed, it waits for it or counts it as done, instead of starting another. A failed Job is not
reused, so the next reconcile starts a new one, and failed Jobs pile up while a failure is retried. Do not set
`ttlSecondsAfterFinished` shorter than a run, or a re-entered run will start the Job again; a value of a day or more
cleans up the failed ones. Jobs in the MutexRunConfig's namespace are owned by it and are garbage-collected when it
is deleted. Jobs in other namespaces are not.

## What the operator changes

| Object | Change | Restored |
| --- | --- | --- |
| Target MachineConfigPools | `spec.paused: true`, annotation `openshift-optional.skrzypek.io/paused-by: <namespace>/<name>`. Pools that are already paused are left as they are and not annotated. | Unpaused at the end of the run, but only pools whose `paused-by` names this MutexRunConfig. A pool an administrator paused stays paused. |
| Target and canary MachineConfigPools | `spec.nodeSelector.matchExpressions` changed for the run. The original list is saved as JSON in the annotation `openshift-optional.skrzypek.io/original-match-expressions`. | The saved list is put back and the annotation removed. `matchLabels` is never changed. |
| Target nodes | Label `mutexrule.openshift-optional.skrzypek.io/<rule>.<namespace>: ""` per MutexRule, only on nodes still behind the new version. | Removed when the node is released, and from any leftover node at the end of the run. |
| Jobs | Created as described above. | Never deleted by the operator. |

## Reconcile procedure

**MutexRule:** validates the type and fields, sends `jobSpec` and `cleanUpJobSpec` as server-side dry-run creates
(`dryRun=All`) to the job namespace and reports `ValidConfig`. Nothing is created or deleted.

**MutexTarget:** checks that the pools exist, computes the nodes MCO assigns to them from `matchLabels` and
`matchExpressions`, and reports `ValidConfig`, `NodeListGathered` and `status.nodes`. During a run it uses the saved
original selectors.

**MutexRunConfig:** every reconcile runs these steps in order. A step only runs when the ones before it succeeded.

1. **Namespace.** A MutexRunConfig outside the operator namespace gets `Reconciled=False` (`NamespaceNotAllowed`) and
   nothing else happens.
2. **Validate** (`ConfigValidated`). Rule and target references are resolved and must be in the operator namespace.
   Every MutexRule must report `ValidConfig=True`. Every MutexTarget must report `ValidConfig=True` and
   `NodeListGathered=True` and list at least one node. The canary must pass the checks in
   [Prerequisites](#a-canary-machineconfigpool). Then every APIService must be `Available` (`ClusterStateValidated`,
   3 attempts 10 seconds apart). Any failure here blocks the run, and nothing is changed.
3. **Check for an upgrade** (`UpgradeChecked`, `NodeVersionsKnown`, `UpgradeAvailable`, `UpgradeReady`). The target
   version is `status.desired.version` of ClusterVersion `version`. Every target node needs a semantic-version
   `release-image-version` label. A node is behind when its version is lower than the target. `UpgradeAvailable` is
   `True` while any target node is behind. `UpgradeReady` is `True` once, in addition, `status.history[0]` is
   `Completed` for the target version.
4. **Pause** (`TargetPoolsPaused`). As soon as an upgrade is available, before the control plane has finished, the
   target pools are paused and annotated with `paused-by`. The operator does not watch ClusterVersion. It notices the
   upgrade at its next reconcile, at most 10 minutes after the upgrade starts. That is normally well before the
   control plane finishes and MCO turns to the worker pools. A pool you pause yourself before the upgrade is used as
   it is, but the operator never unpauses it.
5. **Label** (`MutexRulesApplied`). Every target node that is behind gets the mutex labels. Nodes MCO is already
   updating through the canary are skipped.
6. **Re-point the pools** (`MCPUpdated`). The original `matchExpressions` are saved. Target pools get
   `<mutex label> Exists` per rule, and the canary gets its kept expressions plus `<mutex label> DoesNotExist` per rule.
7. **Run, node by node** (`JobRun`, `NodeUpgrade`), once `UpgradeReady` is `True`. A node already at the target version
   is skipped (`NodeUpgrade=True`, `NodeAlreadyUpgraded`). Otherwise the pre-upgrade Jobs run, the node's mutex labels
   are removed, the operator waits for the new version and the cleanup Jobs run (see [The Job contract](#the-job-contract)).
   A failure stops the run, and the remaining nodes are not touched.
8. **Finish.** When every node is done, or when no target node is behind any more, the selectors are restored, the
   run's labels removed and the pools this MutexRunConfig paused are unpaused. `MCPUpdated` becomes `False`
   (`SelectorsRestored`), and `UpgradeAvailable` and `UpgradeReady` become `False` (`UpgradeFinished`).
9. **Report** (`TargetPoolsPaused`, `Degraded`). Which pools this MutexRunConfig keeps paused, and whether that is
   because of a failure.

One reconcile works through all target nodes in turn, so it can run for hours. A MutexRunConfig is reconciled when
its spec changes, when one of its Jobs in its own namespace changes, and every 10 minutes. Changes to ClusterVersion,
nodes or pools are picked up at the next 10-minute reconcile. Status is merged condition by condition, so progress
survives a restart of the operator.

### Retries

ansible-operator counts every failed task as a failed reconcile, even one the role handles and reports in a
condition. A failed reconcile is retried with the controller-runtime backoff, not at the 10-minute period: first
after a few milliseconds, then doubling up to about 17 minutes between attempts, until a reconcile succeeds. This
applies to every failure the conditions report: an invalid MutexRule or MutexTarget, a missing reference, a failed
Job or a node that did not upgrade in time. A failed Job is started again on every retry.

## Conditions

`lastTransitionTime` is an RFC 3339 UTC time (`YYYY-MM-DDTHH:MM:SSZ`). It changes whenever a condition's status,
reason or message changes.

| Kind | Type | Status / reason | Meaning |
| --- | --- | --- | --- |
| all | `Reconciled` | `False` / `NamespaceNotAllowed` | The CR is outside the operator namespace and is ignored. |
| MutexRule | `ValidConfig` | `True` / `ValidConfig` | The JobSpecs passed the server-side dry run. |
| MutexRule | `ValidConfig` | `False` / `InvalidConfig` | The message has the API server's error. |
| MutexTarget | `ValidConfig` | `True` / `MachineConfigPoolFetchSucceeded`, `False` / `MachineConfigPoolFetchFailed` | The pools exist (or not). |
| MutexTarget | `NodeListGathered` | `True` / `MachineConfigPoolFetchSucceeded`, `False` / `MachineConfigPoolFetchFailed` | `status.nodes` is current. On `False` it is empty, for example because a pool's selector is empty. |
| MutexRunConfig | `ConfigValidated` | `True` / `FetchSucceeded` | References, rules, targets and canary are valid. |
| MutexRunConfig | `ConfigValidated` | `False` / `ValidationFailed`, `False` / `ClusterStateInvalid` | A check failed, or the APIService check did. Nothing is changed. |
| MutexRunConfig | `ClusterStateValidated` | `True` / `APIServicesUp`, `False` / `APIServicesDown` | Every APIService is `Available`, or the names of those that are not. |
| MutexRunConfig | `UpgradeChecked` | `True` / `CheckSucceeded`, `False` / `CheckFailed` | The upgrade check ran, or why it could not. |
| MutexRunConfig | `NodeVersionsKnown` | `True` / `VersionsKnown`, `False` / `VersionLabelMissing` | Every target node has a valid version label, or the nodes that do not. |
| MutexRunConfig | `UpgradeAvailable` | `True` / `UpgradeAvailable`, `False` / `UpgradeUnavailable`, `False` / `UpgradeFinished` | Whether a target node is behind the target version. |
| MutexRunConfig | `UpgradeReady` | `True` / `UpgradeReady`, `False` / `UpgradeNotReady`, `False` / `UpgradeFinished` | Whether nodes can be released: an upgrade is available and the control plane is done. |
| MutexRunConfig | `TargetPoolsPaused` | `True` / `Paused`, `False` / `NotPaused` | The pools this MutexRunConfig keeps paused, or why pausing failed. |
| MutexRunConfig | `MutexRulesApplied` | `True` / `ApplySucceeded`, `False` / `ApplyFailed` | The mutex labels are on the nodes that are behind. |
| MutexRunConfig | `MCPUpdated` | `True` / `UpdateSucceeded`, `False` / `UpdateFailed`, `False` / `SelectorsRestored` | The selectors are changed for the run, or restored. |
| MutexRunConfig | `JobRun` | `True` / `JobRunSucceeded`, `False` / `JobRunFailed` | The Jobs of the last node succeeded, or which Job failed and why. |
| MutexRunConfig | `NodeUpgrade` | `True` / `NodeUpgradeSucceeded`, `True` / `NodeAlreadyUpgraded`, `False` / `NodeUpgradeFailed` | The last node processed and its position ("Node is 2 of 5"). |
| MutexRunConfig | `Degraded` | `True` / `PoolsLeftPaused` | A step failed while pools are paused. They stay paused, and the message names the error and how to abort. |
| MutexRunConfig | `Degraded` | `False` / `RunInProgress`, `False` / `NoPoolsPaused` | A run is in progress, or nothing is paused by this MutexRunConfig. |

## Recovery

**To abort a run, delete the MutexRunConfig.** Its finalizer (`openshift-optional.skrzypek.io/finalizer`) runs the
restore before the object goes away. It puts back the saved node selectors, removes this run's mutex labels and
unpauses the pools that this MutexRunConfig paused. **MCO then upgrades the remaining nodes without running their
Jobs.** Delete MutexRunConfigs before you uninstall the operator, or the finalizer cannot run.

A delete does not interrupt a reconcile that is already running. The operator finishes the node it is working on (its
Jobs, up to `timeoutSeconds` each, and the wait for the new version, up to 2 hours), skips the remaining nodes and
then runs the finalizer. Use the manual steps below if that is too long to wait.

If the operator is gone or cannot run, do the same by hand, in this order:

1. Restore the selectors. For each MachineConfigPool that has the `original-match-expressions` annotation:

   ```sh
   oc get mcp -o custom-columns='NAME:.metadata.name,PAUSED:.spec.paused,PAUSED-BY:.metadata.annotations.openshift-optional\.skrzypek\.io/paused-by,SAVED:.metadata.annotations.openshift-optional\.skrzypek\.io/original-match-expressions'
   # put the SAVED JSON back (use [] when it is empty) and drop the annotation:
   oc patch mcp <pool> --type=merge -p '{"metadata":{"annotations":{"openshift-optional.skrzypek.io/original-match-expressions":null}},"spec":{"nodeSelector":{"matchExpressions":<SAVED JSON>}}}'
   ```

2. Remove the mutex labels, once per rule:

   ```sh
   oc get nodes -o name -l 'mutexrule.openshift-optional.skrzypek.io/<rule>.<namespace>'
   oc label nodes --all 'mutexrule.openshift-optional.skrzypek.io/<rule>.<namespace>-'
   ```

3. Unpause the pools whose `paused-by` names the MutexRunConfig:

   ```sh
   oc patch mcp <pool> --type=merge -p '{"metadata":{"annotations":{"openshift-optional.skrzypek.io/paused-by":null}},"spec":{"paused":false}}'
   ```

4. If the operator is uninstalled, remove the finalizer so the MutexRunConfig can be deleted:

   ```sh
   oc patch mutexrunconfig <name> -n <namespace> --type=merge -p '{"metadata":{"finalizers":null}}'
   ```

To **retry** after fixing the cause of a `Degraded=True`, do nothing: the next retry (see [Retries](#retries)), at
most about 17 minutes later, continues where the run stopped. A Job that failed is run again. To retry at once,
restart the operator pod (`oc delete pod -n <operator namespace> -l control-plane=controller-manager`). On start it
reconciles every resource, and a run in progress continues where it was (Jobs that already completed are reused).

## Permissions

The operator's ServiceAccount gets exactly these permissions (`config/rbac/role.yaml`, installed cluster-wide):

| API group | Resource | Verbs | Used for |
| --- | --- | --- | --- |
| `batch` | `jobs` | create, get, list, watch | Dry-run validation, creating MutexRule Jobs and following them. Never deleted, patched or updated. |
| core | `nodes` | get, list, watch, patch | Reading versions and pool membership. Adding and removing the mutex labels. |
| `machineconfiguration.openshift.io` | `machineconfigpools` | get, list, watch, patch | Reading selectors. Pausing, unpausing, changing `matchExpressions` and the two annotations. |
| `config.openshift.io` | `clusterversions` | get, list, watch | The target version and the control plane's progress. |
| `apiregistration.k8s.io` | `apiservices` | get, list, watch | The APIService health check. |
| `openshift-optional.skrzypek.io` | `mutexrules`, `mutextargets`, `mutexrunconfigs` | get, list, watch, update, patch | Watching and reading the CRs. Adding and removing the finalizer. |
| `openshift-optional.skrzypek.io` | `mutexrules/status`, `mutextargets/status`, `mutexrunconfigs/status` | get, update, patch | Writing status. |
| `openshift-optional.skrzypek.io` | `mutexrules/finalizers`, `mutexrunconfigs/finalizers` | update | Lets Jobs carry owner references with `blockOwnerDeletion` to these CRs. ansible-operator does not set that flag today; the rule is kept as in the operator-sdk scaffold. |
| `authentication.k8s.io` | `tokenreviews` | create | Authenticating scrapes of the metrics endpoint. |
| `authorization.k8s.io` | `subjectaccessreviews` | create | Authorizing scrapes of the metrics endpoint. |

For leader election it also gets `coordination.k8s.io` `leases` (all verbs) and `events` (create, patch) in its own
namespace (`config/rbac/leader_election_role.yaml`). With an `AllNamespaces` install, OLM grants these namespaced
permissions cluster-wide and adds get, list and watch on `namespaces`. The operator has no access to Secrets,
ConfigMaps, Pods or workloads.

**Metrics.** The manager serves `/metrics` over HTTPS on port 8443, behind the Service
`openshift-node-upgrade-mutex-operator-metrics-service` in the operator namespace. A scrape must send a bearer token
whose identity may `get` the `/metrics` URL. The ClusterRole `openshift-node-upgrade-mutex-operator-metrics-reader`
grants that. Bind it to the ServiceAccount that scrapes, for example:

```sh
oc create clusterrolebinding mutex-operator-metrics-reader \
  --clusterrole=openshift-node-upgrade-mutex-operator-metrics-reader \
  --serviceaccount=<scraper-namespace>:<scraper-serviceaccount>
```

The binding is accepted even when the ClusterRole name is wrong, and every scrape then gets `403 Forbidden`, so copy
the name exactly.

**Who controls the operator.** Anyone who can create or edit MutexRules, MutexTargets or MutexRunConfigs **in the
operator namespace** can pause MachineConfigPools, relabel nodes, and run Jobs in any namespace with any ServiceAccount
there. Grant write access to that namespace only to cluster administrators. OLM also creates `admin`, `edit` and `view`
aggregated roles for these CRDs in every namespace. That is why CRs outside the operator namespace are ignored.

## Limitations

* Alpha. The API (`v1alpha1`) may change. It has not been tested end to end on a live OpenShift upgrade.
* One operator per cluster, one MutexRunConfig per canary pool, and no target pool shared between MutexRunConfigs.
* Every target node needs the `release-image-version` label, which the operator does not maintain.
* Nodes are handled one at a time, so a large pool takes as long as its slowest Jobs plus one node upgrade per node.
  An upgraded node stays in the canary pool until the end of the run.
* A node that does not report the new version within 2 hours stops the run with the pools paused.
* A failure is retried with a backoff of up to about 17 minutes, and a failed Job is started again on each retry.
* Deleting a MutexRunConfig takes effect only after the node in progress is finished.
* Changes to ClusterVersion, nodes and pools are noticed at the next reconcile, at most 10 minutes later.
* `spec.jobNamespace` can be any namespace, and the Jobs can use any ServiceAccount in it. See the permissions section.
* MutexRule names must not contain `.`.
* `spec.skipTLSVerify` is deprecated and has no effect.

## More information

Source, issues and development notes:
[github.com/shpwrck/openshift-node-upgrade-mutex-operator](https://github.com/shpwrck/openshift-node-upgrade-mutex-operator).
