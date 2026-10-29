# OpenShift Node Upgrade Mutex Operator

During an OpenShift upgrade this operator holds back the worker nodes you choose and releases them one at a time.
For each node it first runs the Kubernetes Jobs you define, then lets the Machine Config Operator (MCO) upgrade the
node, waits until the node has finished its upgrade, runs your cleanup Jobs and only then moves on to the next node.
Typical Jobs drain or fence an application, move a storage replica, or wait for an external system to agree.

It works with three custom resources:

* **MutexRule**: one Job to run before each node is upgraded, plus an optional cleanup Job to run after.
* **MutexTarget**: the MachineConfigPools whose nodes are upgraded this way.
* **MutexRunConfig**: ties rules to targets and names the *canary* MachineConfigPool that nodes are upgraded through.

> **Status: alpha.** The operator manages one cluster. It pauses MachineConfigPools and rewrites their node selectors
> during an upgrade. This version has been checked with linting, bundle and schema validation, test runs against
> Kubernetes API servers that have no Machine Config Operator, and on **one small OpenShift 4.21 cluster** (one
> control-plane node, two workers) through three z-stream upgrades; `docs/HANDOFF.md` lists what those runs covered
> and what is still open. Validate it on a non-production cluster of your own before you rely on it.

## How it works

MCO upgrades the nodes of a MachineConfigPool once the pool is unpaused. The operator uses that:

1. When ClusterVersion `version` reports a new `status.desired.version` and a target node is behind it, the operator
   **pauses the target pools** and puts one **mutex label** per MutexRule on each target node that still needs the
   upgrade.
2. It changes the **node selectors**. The canary pool, which is not paused, selects only nodes that carry the
   operator's **release label** with this MutexRunConfig's value: the target nodes it has released, and its own nodes
   from before the run. Each target pool selects its nodes except the released ones. A node that MCO has not yet seen
   released therefore stays in its paused pool. When the canary's own nodes are given the release label, the
   selectors are changed only at a later reconcile at least 5 minutes after that, normally the next one, so MCO sees
   the label first. The time is recorded on the canary, so a retry or a restart of the operator waits too. Until then
   the canary keeps its own selector and leaves out the nodes that carry mutex labels.
3. Once the control plane has finished (`status.history[0]` is `Completed` for that version), it works through the
   target nodes **one at a time**. It runs the MutexRule Jobs for the node, then one patch removes the node's mutex
   labels and adds the release label (so the node moves into the canary pool and MCO upgrades it). It waits until the
   node has finished its upgrade (it reports the new version, MCO reports it done, and it is `Ready`), then runs the
   cleanup Jobs and removes the release label, so the node goes back to its own pool, which is still paused.
4. After the last node it **restores** the original selectors, removes the labels and unpauses the pools it paused.
   The canary's own nodes keep the release label until a reconcile at least 5 minutes later, normally about 10 minutes
   after the run ends. The upgraded nodes then switch from the canary's rendered config to their own pool's, with no
   reboot when the canary renders the same MachineConfigs as their pool.

When something fails during a run, the pools **stay paused**. No node is upgraded without its Jobs. The
MutexRunConfig reports `Degraded=True`, and the operator retries (see [Retries](#retries)). To give up instead, delete
the MutexRunConfig (see [Recovery](#recovery)).

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

The label decides which nodes are behind. The operator does not trust it alone to show that a node has finished its
upgrade: it also waits for MCO to report the node done and for the node to be `Ready` (see
[The Job contract](#the-job-contract)).

OpenShift does not set this label. You have to maintain it. One way is a MachineConfig whose script writes the release
version of the MachineConfig the node has booted into to a Node Feature Discovery (NFD) feature file, together with an
NFD instance that publishes it as a label. The script publishes a version only when the booted OS image matches the
one named in `/etc/machine-config-daemon/currentconfig`, the config the Machine Config Daemon expects the node to run.
It uses `rpm-ostree` for that check, so it needs RHCOS nodes. When a release keeps the same OS image, the label can
change shortly before the node reboots. Examples are in the repository:
[sample-manifests/machineconfig.yaml](https://github.com/shpwrck/openshift-node-upgrade-mutex-operator/blob/main/sample-manifests/machineconfig.yaml)
and
[sample-manifests/nodefeaturediscovery.yaml](https://github.com/shpwrck/openshift-node-upgrade-mutex-operator/blob/main/sample-manifests/nodefeaturediscovery.yaml).
If the cluster already runs NFD, keep its NodeFeatureDiscovery instead of applying the sample, and make sure its
`workerConfig` enables the local source: `core.labelSources` and `core.featureSources` (and the deprecated
`core.sources`, if set) are unset or list `local` or `all`. Check that the label is right on your cluster before you
rely on it.

The check **fails closed**. If any target node has no label, or a value that is not a semantic version, the
MutexRunConfig reports `NodeVersionsKnown=False` with the node names, and nothing is paused, labelled or run.

### A canary MachineConfigPool

The canary is an existing MachineConfigPool that target nodes pass through while they are upgraded. The operator checks
before every run that the canary:

* exists and is **not paused**;
* is **not** one of the target pools;
* has `nodeSelector.matchLabels` that select **every target node**, for example `node-role.kubernetes.io/worker: ""`;
* with its `matchLabels` and the `matchExpressions` it keeps during a run (see below), selects no node outside the
  canary itself and the target pools, so no node of the `worker` pool either when `worker` is not a target pool. A node
  that matches its whole selector and is not a target node counts as one of the canary's own nodes;
* has no node that carries the release label (see [What the operator changes](#what-the-operator-changes)) with the
  value of another MutexRunConfig, or of one that no longer exists;
* is not already paused or re-pointed by another MutexRunConfig (its `paused-by` or `modified-by` annotation names
  another one). The same applies to the target pools.

During a run the canary keeps those of its own `matchExpressions` that every target node already satisfies, for
example `node-role.kubernetes.io/infra DoesNotExist`. Other expressions, such as the `isCanary Exists` below, are left
out for the length of the run and put back afterwards. If validation reports that the canary's `matchLabels` and kept
`matchExpressions` select other nodes, add an expression that every target node satisfies and those nodes do not. The
message names one when it can find it. During a run, an expression you add to the canary's `matchExpressions` is added
to the saved original, so it is kept for the rest of the run and stays after the restore. With the sample canary below
and a custom target pool, for example `apps` with `matchLabels` `node-role.kubernetes.io/app: ""`, the `matchLabels`
and kept expressions select every node of the `worker` pool, so validation refuses the canary until you add
`node-role.kubernetes.io/app Exists`. The canary keeps that expression outside runs too, so nodes in the
canary that lack the label move out of it. To keep such a node in the canary, give it the label with a value the
target pool does not select, for example `node-role.kubernetes.io/app=canary`. With the empty value it would also
match `apps`, and MCO refuses a node that matches two custom pools.

The nodes that are in the canary when a run starts (they match its `matchLabels` and `matchExpressions` and are not
target nodes) get the release label, so they stay in the canary during the run. Before the operator gives them the
label, it records the time in the canary's annotation `nodeupgrade.redhat-na-ssa.github.io/release-labelled-at` and,
in the same patch, gives the canary its own `matchExpressions` plus `<mutex label> DoesNotExist` for each MutexRule.
That selects the canary's own nodes whatever their release label, and none of the nodes the run holds. The canary's
selector is changed for the run only at a later reconcile at least 5 minutes after that time, normally the next one,
10 minutes later. The time is recorded again after the last of these label changes (and the target nodes are labelled
before it is first recorded), so a reconcile that labels many nodes does not shorten the wait, and MCO has seen the
label by then: after an API outage MCO's controller reads the nodes again 60 to 90 seconds after the API is back and
renders their pools about 2 minutes later. The time is kept in the cluster, so a retry after a failure, a restart of
the operator or any other early reconcile waits as well. The nodes keep the label until a reconcile at least 5 minutes
after the one that restores the canary's selector, normally the one 10 minutes later (a reconcile right after the run,
such as one its last Jobs trigger, keeps the label); that restore records its time in the canary's annotation
`nodeupgrade.redhat-na-ssa.github.io/restored-at`. One case remains: an API outage that begins right after the time is
recorded and lasts longer than 5 minutes, followed by MCO's delay in reading the nodes again once the API is back, can
still move one of the canary's own nodes through the `worker` pool once, which is unpaused when `worker` is not a
target pool. The finalizer has a similar case (see [Recovery](#recovery)). A node you add to the canary during a run
gets the label at the next reconcile and joins the canary then, and a node you take out of it keeps the label, and its
place in the canary, until then.

A target node the run still holds (it carries mutex labels) does not get the release label, because its Jobs have not
run. Do not change the labels of a node the run holds until the run has ended:

* With target pool `worker`, a held node that you give the canary's labels on top of its own is dropped by its
  MutexTarget, stays in the paused `worker` pool until the end of the run, and is then upgraded through the canary
  without its Jobs.
* With a custom target pool, a held node leaves its paused pool as soon as it stops matching that pool's selector, for
  example when you set `node-role.kubernetes.io/app=canary` on it. Matching no other custom pool, it falls into
  `worker`, which upgrades it at once without its Jobs when `worker` is not a target, possibly at the same time as the
  node the run is upgrading. The run then stops with `ConfigValidated` `False`, naming the node in pool `worker`, until
  you remove the node's mutex labels and its `nodeupgrade.redhat-na-ssa.github.io/labelled-by` annotation. The node then
  joins the canary as one of its own nodes.
* With a custom target pool, a held node that keeps that pool's label and only gets the canary's labels added stays a
  target node and is upgraded with its Jobs, but after the run MCO refuses it, because it matches two custom pools.

Validation fails while a node of the canary carries the release label with a value other than this
MutexRunConfig's, because the canary would not select that node during a run. The value belongs to another
MutexRunConfig, or was left by one that no longer exists. The message names the nodes and values and the `oc label`
command that removes the label.

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

Use one canary per MutexRunConfig. Two MutexRunConfigs must not share a canary or a target pool. Validation refuses a
canary or target pool that another MutexRunConfig has paused or re-pointed, so a shared pool is caught as soon as one
of them starts a run.

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

In `AllNamespaces` mode the operator puts its finalizer on CRs outside its namespace too. Delete those CRs before you
switch to `OwnNamespace`, or their deletion hangs on the finalizer. `SingleNamespace` and `MultiNamespace` are not
supported. The manager reads `WATCH_NAMESPACE` from the
`olm.targetNamespaces` annotation that OLM sets, and reads its own namespace from `POD_NAMESPACE`. The roles only act
on CRs in `POD_NAMESPACE`, so a target namespace other than the operator's own would contain only CRs the operator
refuses.

**Create every MutexRule, MutexTarget and MutexRunConfig in the operator namespace**, and leave out the `namespace`
of the references in a MutexRunConfig. They default to the MutexRunConfig's namespace. A reference to another namespace
fails validation.

### Moving from 0.2.x

0.3.0 is a new API. Its group is `nodeupgrade.redhat-na-ssa.github.io` (0.2.x used `openshift-optional.skrzypek.io`),
and so are its node labels, pool and node annotations and finalizer. 0.3.0 does not read 0.2.x CRs, labels or
annotations, so it cannot take over from 0.2.x in place: an OLM upgrade from 0.2.x would leave the 0.2.x CRs behind
and protect nothing until the new CRs exist. The project's own catalog (on `ghcr.io`) therefore starts afresh, without
the 0.2.x bundles, and offers 0.3.0 as an upgrade of nothing older than 0.3.0. Move by reinstalling: save the 0.2.x
CRs, uninstall 0.2.x, install 0.3.0, and create the CRs again under the new group. A 0.2.x install from a community
catalog moves the same way: if that catalog offers 0.3.0 as an upgrade, do not approve it (set the Subscription to
`Manual` approval first).

What changes for the CRs you create again:

* **Only CRs in the operator namespace are reconciled.** 0.2.x reconciled CRs in every namespace. Create the 0.3.0 CRs
  in the operator namespace, with references that leave out `namespace`: references to MutexRules or MutexTargets in
  another namespace fail validation, and a CR in another namespace only gets `Reconciled=False NamespaceNotAllowed`.
* **`SingleNamespace` is no longer supported.** With an OperatorGroup whose `spec.targetNamespaces` names a namespace
  other than its own, the 0.3.0 CSV fails with reason `UnsupportedOperatorGroup`. Use `OwnNamespace` (the console's
  default for a namespace of its own) or `AllNamespaces`.
* **The CRDs validate their fields.** Every kind needs `spec`. A MutexRule needs `jobName`, a DNS-1123 label of at most
  52 characters, and `jobSpec`; `jobNamespace`, when set, must be a DNS-1123 label. A MutexTarget needs at least one
  pool. A MutexRunConfig needs `canary.name` and at least one rule and one target reference, each with a `name`; rule
  names (at most 61 characters) and every reference `namespace` must be DNS-1123 labels.
* **The canary must not reach other nodes.** 0.3.0 refuses a canary whose `matchLabels` and kept `matchExpressions`
  select nodes outside the canary and the target pools, for example the nodes of an `infra` pool. With a custom target
  pool (not `worker`), for example `apps`, and the sample canary, they select the nodes of the `worker` pool, so
  `ConfigValidated` stays `False` until the canary gets an expression such as `node-role.kubernetes.io/app Exists`.
  The `ConfigValidated` message names the expression when it can find one. See
  [A canary MachineConfigPool](#a-canary-machineconfigpool).

Jobs may also run longer than before. 0.2.x stopped the run when a Job had not completed within 2 minutes, the default
wait of the Ansible `k8s` module it used. 0.3.0 waits for each Job up to the rule's `spec.timeoutSeconds`, 3600 by
default. Set `timeoutSeconds` on every MutexRule that needs another limit. There is no operator-wide setting.

To move:

1. Choose a time when no OpenShift upgrade is in progress and no 0.2.x run is half done. 0.2.x has no finalizer and
   does not record what it changed, so nothing can finish or undo a 0.2.x run after it is uninstalled. No target pool
   should be paused, except by you, and this must print nothing:

   ```sh
   oc get nodes,mcp -o yaml | grep 'mutexrule.openshift-optional.skrzypek.io/'
   ```

   If it prints labels or `matchExpressions`, let the run finish, or put the pools' original `matchExpressions` back,
   remove the labels and unpause the pools by hand.
2. Save the 0.2.x CRs, in every namespace:

   ```sh
   oc get mutexrules.openshift-optional.skrzypek.io,mutextargets.openshift-optional.skrzypek.io,mutexrunconfigs.openshift-optional.skrzypek.io -A -o yaml > mutex-0.2.x.yaml
   ```

3. Uninstall 0.2.x: delete its Subscription and CSV, then its CRDs, which also deletes the 0.2.x CRs (0.2.x has no
   finalizer, so nothing hangs):

   ```sh
   oc delete subscriptions.operators.coreos.com <name> -n <operator namespace>
   oc delete csv <0.2.x CSV name> -n <operator namespace>
   oc delete crd mutexrules.openshift-optional.skrzypek.io mutextargets.openshift-optional.skrzypek.io mutexrunconfigs.openshift-optional.skrzypek.io
   ```

4. Install 0.3.0 as described in [Installation](#installation), from a CatalogSource that serves
   `ghcr.io/<owner>/openshift-node-upgrade-mutex-operator-catalog` (`:latest`, or `:v<version>`). If the
   OperatorGroup targets another namespace (`SingleNamespace`), make it `OwnNamespace` first.
5. Create the CRs again from `mutex-0.2.x.yaml`, with `apiVersion: nodeupgrade.redhat-na-ssa.github.io/v1alpha1`,
   in the operator namespace, without `status` and the server-set `metadata` fields, and checked against the schema
   rules above. Start from the samples (`config/samples/`).
6. Afterwards `oc get mutexrunconfig -n <operator namespace>` must show every MutexRunConfig as `Validated` `True`.
   Fix any that is not before the next OpenShift upgrade: 0.3.0 checks more than 0.2.x did (see
   [Reconcile procedure](#reconcile-procedure)), and a MutexRunConfig that fails validation pauses nothing.

## Custom resources

All three kinds are `nodeupgrade.redhat-na-ssa.github.io/v1alpha1`, namespaced, and in the `numo` category, so
`oc get numo` lists them all.

### MutexRule

One operation to run for each target node, as a `batch/v1` JobSpec. The operator validates the JobSpecs with a
server-side dry-run create in the job namespace (nothing is created) and reports `ValidConfig`.

| Field | Required | Description |
| --- | --- | --- |
| `spec.jobName` | yes | Prefix of the generated Jobs: `<jobName>-xxxxx` before the upgrade, `cleanup-<jobName>-xxxxx` after. A DNS-1123 label of at most 52 characters. |
| `spec.jobNamespace` | no | Namespace the Jobs run in. Defaults to the MutexRule's namespace. |
| `spec.jobSpec` | yes | `batch/v1` JobSpec run for each node before it is released for its upgrade. |
| `spec.cleanUpJobSpec` | no | `batch/v1` JobSpec run for each node after it has finished its upgrade. |
| `spec.timeoutSeconds` | no | How long each Job of this rule may run. Default `3600`, minimum `1`. |
| `spec.type` | no | Only `kubernetes`, the default. |

The rule's **name must not contain `.`**, and `<name>.<namespace>` must be at most 63 characters. The node label is
`mutexrule.nodeupgrade.redhat-na-ssa.github.io/<name>.<namespace>`. A MutexRunConfig that references a rule breaking
this fails validation.

```yaml
apiVersion: nodeupgrade.redhat-na-ssa.github.io/v1alpha1
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
apiVersion: nodeupgrade.redhat-na-ssa.github.io/v1alpha1
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
apiVersion: nodeupgrade.redhat-na-ssa.github.io/v1alpha1
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
* **Metadata:** the label `nodeupgrade.redhat-na-ssa.github.io/job-key` (a hash of MutexRunConfig, node, rule, phase and
  version) and the annotations `nodeupgrade.redhat-na-ssa.github.io/mutexrunconfig`, `.../mutexrule`, `.../node`,
  `.../phase` (`pre` or `cleanup`) and `.../desired-version`.
* **Name:** `generateName: <jobName>-`, or `cleanup-<jobName>-` for cleanup Jobs, in `spec.jobNamespace`.

Order and timing:

1. The pre-upgrade Jobs of a node run **one after another**, in the order of `spec.mutexRules`. Each must reach
   `Complete` within the rule's `timeoutSeconds` (default 3600). A `Failed` Job stops the run at once.
2. One patch then removes the node's mutex labels and adds the release label. The node moves into the canary pool
   and MCO upgrades it. The operator waits up to 2 hours (120 checks, 60 seconds apart) until the node has finished
   its upgrade: its `release-image-version` label shows the new version, its annotation
   `machineconfiguration.openshift.io/state` is `Done` with `machineconfiguration.openshift.io/currentConfig` equal to
   `.../desiredConfig`, that config is a rendered config of the canary (`rendered-<canary>-<hash>`), and its `Ready`
   condition is `True`. The label alone is not enough: it can show the new version before the node has rebooted, and
   the canary's config shows that MCO has moved the node into the canary and finished there.
3. The cleanup Jobs of the rules that have a `cleanUpJobSpec` then run, in the same order and with the same timeout.
   Then one patch removes the release label and `released-by` (below), and the node goes back to its own pool, which
   is still paused. Only then does the operator turn to the next node.

When a reconcile is interrupted and started again, the operator looks for a Job with the same `job-key` label. If it
finds one that has not failed, it waits for it or counts it as done, instead of starting another. A failed Job is not
reused, so the next reconcile starts a new one, and failed Jobs pile up while a failure is retried. A released node
carries the annotation `nodeupgrade.redhat-na-ssa.github.io/released-by` and the release label until its cleanup Jobs
have completed: one patch sets both and one patch removes both. A retry or a restart of the operator therefore resumes
that node at the wait and runs its cleanup Jobs (it starts a failed one again and waits for one that still runs)
before it touches the next node, also when it was the last node. Do not set `ttlSecondsAfterFinished` shorter than a
run, or a re-entered run will start the Job again; a value of a day or more cleans up the failed ones. Jobs in the
MutexRunConfig's namespace are owned by it and are garbage-collected when it is deleted. Jobs in other namespaces are
not.

## What the operator changes

`<value>` below is the value of the release label: the SHA-1 of `<namespace>/<name>` of the MutexRunConfig, as 40
lowercase hex characters, because a label value cannot contain `/`. To compute it:
`printf '%s' "<namespace>/<name>" | sha1sum | cut -c1-40`.

| Object | Change | Restored |
| --- | --- | --- |
| Target MachineConfigPools | `spec.paused: true`, annotation `nodeupgrade.redhat-na-ssa.github.io/paused-by: <namespace>/<name>`. Pools that are already paused are left as they are and not annotated. | At the end of the run, and by the finalizer, every pool whose `paused-by` names this MutexRunConfig is unpaused and loses the annotation. A pool an administrator paused stays paused. |
| Target and canary MachineConfigPools | `spec.nodeSelector.matchExpressions` changed for the run: a target pool gets `mutexrule.nodeupgrade.redhat-na-ssa.github.io/release NotIn (<value>)` added to its expressions, and the canary gets its kept expressions plus `mutexrule.nodeupgrade.redhat-na-ssa.github.io/release In (<value>)` (before that, from the patch that comes before its own nodes get the release label until it is re-pointed, its own expressions plus one `DoesNotExist` per mutex label). The original list is saved as JSON in the annotation `nodeupgrade.redhat-na-ssa.github.io/original-match-expressions`, and the annotation `nodeupgrade.redhat-na-ssa.github.io/modified-by: <namespace>/<name>` names the MutexRunConfig that changed it. | At the end of the run, and by the finalizer, the saved list is put back on every pool whose `modified-by` names this MutexRunConfig, also when its MutexTarget is gone or someone else paused the pool, and both annotations are removed. `matchLabels` is never changed. |
| Canary MachineConfigPool | Annotation `nodeupgrade.redhat-na-ssa.github.io/release-labelled-at: <time>` (UTC, `YYYY-MM-DDTHH:MM:SSZ`): written, with `modified-by`, before the release label of one of the canary's own nodes is added (or this MutexRunConfig's value is taken from a node) at the start of a run. The pools are re-pointed at a later reconcile once it is 5 minutes old; an empty time, one without that format or one later than the operator's clock counts as just written and is written again. Annotation `nodeupgrade.redhat-na-ssa.github.io/restored-at: <time> <namespace>/<name>`: written in the patch that restores the canary's selector when a node still carries the release label. | `release-labelled-at` is removed when the canary is re-pointed and whenever its selector is restored. `restored-at` is removed after the release labels, at least 5 minutes after the restore, and by the finalizer. A `restored-at` that names another MutexRunConfig is left alone. |
| Target nodes | Label `mutexrule.nodeupgrade.redhat-na-ssa.github.io/<rule>.<namespace>: ""` per MutexRule and annotation `nodeupgrade.redhat-na-ssa.github.io/labelled-by: <namespace>/<name>`, only on nodes still behind the new version. When the node is released, the same patch sets the annotation `nodeupgrade.redhat-na-ssa.github.io/released-by: <namespace>/<name>\|<version>` and the label `mutexrule.nodeupgrade.redhat-na-ssa.github.io/release: <value>`. | The mutex labels and `labelled-by` are removed when the node is released. At the end of the run, and by the finalizer, the mutex labels are removed from the nodes whose `labelled-by` names this MutexRunConfig, which also lose that annotation, and from target nodes without any `labelled-by`. A node whose `labelled-by` names another MutexRunConfig keeps its labels. `released-by` and the release label are removed together once the node's cleanup Jobs have completed, and at the end of the run and by the finalizer, which does not run the cleanup Jobs. |
| Nodes in the canary before the run | Label `mutexrule.nodeupgrade.redhat-na-ssa.github.io/release: <value>` at the start of the run, at least 5 minutes before the canary's selector is changed, so they stay in the canary. | Removed by a reconcile at least 5 minutes after the one that restores the canary's selector, normally the one 10 minutes later (a later one while validation or the upgrade check fails), and by the finalizer right after it restores the canary's selector. A release label with another MutexRunConfig's value is never removed. |
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
   `NodeListGathered=True` and list at least one node. The canary and the target pools must exist, and none of them may
   be paused or re-pointed by another MutexRunConfig (its `paused-by` or `modified-by` annotation names another one).
   The canary must pass the checks in [Prerequisites](#a-canary-machineconfigpool), among them that its `matchLabels`
   and kept `matchExpressions` select no node outside the canary and the target pools and that none of its nodes
   carries another value of the release label. A run whose canary was renamed in `spec.canary.name` is refused while
   the former canary still carries the run's selector. Then every APIService must be `Available`
   (`ClusterStateValidated`, 3 attempts 10 seconds apart). Any failure here blocks the run, and nothing is changed.
3. **Check for an upgrade** (`UpgradeChecked`, `NodeVersionsKnown`, `UpgradeAvailable`, `UpgradeReady`). The target
   version is `status.desired.version` of ClusterVersion `version`. Every target node needs a semantic-version
   `release-image-version` label. A node is behind when its version is lower than the target. `UpgradeAvailable` is
   `True` while any target node is behind, and also while a node this run released still needs its cleanup Jobs (its
   `released-by` annotation names this MutexRunConfig, for any version, so a node released before the cluster moved
   on to a newer version still counts). `UpgradeReady` is `True` once, in
   addition, `status.history[0]` is `Completed` for the target version.
4. **Pause** (`TargetPoolsPaused`). As soon as an upgrade is available, before the control plane has finished, the
   target pools are paused and annotated with `paused-by`. The operator does not watch ClusterVersion. It notices the
   upgrade at its next reconcile, at most 10 minutes after the upgrade starts, unless another MutexRunConfig is
   working through its nodes (see [One MutexRunConfig at a time](#one-mutexrunconfig-at-a-time)). That is normally
   well before the control plane finishes and MCO turns to the worker pools. A pool you pause yourself before the
   upgrade is used as it is, but the operator never unpauses it.
5. **Label** (`MutexRulesApplied`). Every target node that is behind gets the mutex labels and the `labelled-by`
   annotation, and the same patch removes any release label from it (nodes without this MutexRunConfig's value come
   first). Nodes MCO is already updating through the canary, and nodes this run has already released, are skipped. The
   nodes this run has released and the canary's own nodes (never a node the run holds) get the release label with this
   MutexRunConfig's value, and every other node loses that value. While the canary does not select on that value yet,
   one patch of the canary comes before a release label change that canary membership depends on (one of the canary's
   own nodes gets the value, or a node loses it): it records the time in `release-labelled-at`, sets `modified-by` and
   saves the canary's `matchExpressions`, and a canary that still has its own selector gets its own `matchExpressions`
   plus `mutexrule.nodeupgrade.redhat-na-ssa.github.io/<rule>.<namespace> DoesNotExist` for each MutexRule. That
   selector keeps the nodes the run holds out of the canary and does not depend on the release label. After those
   release label changes the time is recorded again.
6. **Re-point the pools** (`MCPUpdated`). The original `matchExpressions` are saved, and `modified-by` names this
   MutexRunConfig. The canary comes first: it gets its kept expressions plus
   `mutexrule.nodeupgrade.redhat-na-ssa.github.io/release In (<value>)`. Then each target pool gets
   `mutexrule.nodeupgrade.redhat-na-ssa.github.io/release NotIn (<value>)` added to its expressions. MCO resets the
   selector of its built-in `worker` pool at once, so on `worker` the expression does not stay; there MCO's own rule
   keeps a node that matches a custom pool (the canary, once the node carries the release label) out of `worker`.
   Custom target pools keep it. While the canary's `release-labelled-at` annotation (step 5) is less than 5 minutes
   old, and in the reconcile that wrote it, the pools are not re-pointed: `MCPUpdated` is `False`
   (`CanaryMembersLabelled`), no node is processed, and a later reconcile, normally the next one 10 minutes later,
   re-points the pools and removes the annotation. A reconcile that comes earlier, such as a retry after a failure or
   the first one after a restart of the operator, waits again. Until then the canary keeps the selector step 5 gave
   it.
7. **Run, node by node** (`JobRun`, `NodeUpgrade`), once `UpgradeReady` is `True`. Nodes this run has already released
   come first and resume at the wait. Target nodes MCO is already updating (`desiredConfig` differs from
   `currentConfig`, for example because the update started before the pools were paused) come next: before anything
   else the operator waits, with the same timeout, until MCO reports the node `Done` and `Ready`, so no other node
   goes down meanwhile. A node whose update does not finish, for example because its MCO daemon is degraded, stops the
   run before any other node (`NodeUpgrade=False`, `NodeUpgradeFailed`). After the wait the node is handled with what
   the operator read before it: a node that was behind still gets its pre-upgrade Jobs, is released and gets its
   cleanup Jobs, also when MCO has meanwhile brought it to the target version. A target node that MCO starts updating
   while the reconcile runs stops the run too, before the next node is taken down, and the next reconcile waits for it
   first. A node already at the target version without a `released-by` annotation for this run is skipped
   (`NodeUpgrade=True`, `NodeAlreadyUpgraded`). Otherwise the pre-upgrade Jobs run, one patch removes the node's mutex
   labels, sets `released-by` and adds the release label, the operator waits until the node has finished its upgrade
   (version label, MCO state `Done`, `currentConfig` equal to `desiredConfig` and a rendered config of the canary,
   `Ready`), the cleanup Jobs run, and one patch removes `released-by` and the release label, so the node goes back to
   its paused pool (see [The Job contract](#the-job-contract)). A failure stops the run, and the remaining nodes are
   not touched.
8. **Finish.** When every node is done, or when no target node is behind any more and no released node still needs
   its cleanup Jobs, the selectors are restored, the canary last, then the run's mutex labels and its node
   annotations are removed and the pools this MutexRunConfig paused are unpaused. `MCPUpdated` becomes `False`
   (`SelectorsRestored`). When the run has worked through every node, `UpgradeAvailable` and `UpgradeReady` become
   `False` (`UpgradeFinished`). The release labels stay on the canary's own nodes, where no pool selects on them any
   more, and the patch that restores the canary records the time in its `restored-at` annotation. A reconcile that
   finds no selector to restore and a `restored-at` at least 5 minutes old, normally the one 10 minutes later,
   removes the labels and then the annotation. A reconcile right after the run, such as one its last Jobs trigger,
   keeps them.
9. **Report** (`TargetPoolsPaused`, `Degraded`). Which pools this MutexRunConfig keeps paused, which target pools
   someone else has paused, and whether a failure left pools paused or re-pointed by this MutexRunConfig.

One reconcile works through all target nodes in turn, so it can run for hours. A MutexRunConfig is reconciled when
its spec changes, when one of its Jobs in its own namespace changes, and every 10 minutes. Changes to ClusterVersion,
nodes or pools are picked up at the next 10-minute reconcile. Status is merged condition by condition, so progress
survives a restart of the operator. On a cluster with a single control-plane node, the operator pod restarts during
each API outage of an upgrade (the kube-apiserver rollouts and the reboot of the control-plane node), because it
loses its leader election. A restart count above 0 is expected there, and the run resumes after each restart.

### One MutexRunConfig at a time

The operator reconciles MutexRunConfigs one at a time (`--max-concurrent-reconciles=1`, set in
`config/manager/manager.yaml` and applied per kind). While one MutexRunConfig works through its nodes, no other
MutexRunConfig is reconciled: their 10-minute reconciles, their retries and their finalizers wait until that
reconcile returns, and their status is not updated in the meantime. MutexRules and MutexTargets are reconciled by
workers of their own and are not held up. In practice:

* Several MutexRunConfigs upgrade their nodes one after another, so an upgrade of several pools takes the sum of
  their runs. A MutexRunConfig that has already paused its pools keeps them paused while it waits, so none of its
  nodes is upgraded without its Jobs.
* A MutexRunConfig that is created or changed during another one's run is validated, and its pools are paused, only
  after that run ends.
* Deleting a MutexRunConfig while another one works through its nodes takes effect only after that whole run. To
  abort sooner, use the manual steps in [Recovery](#recovery).
* Do not start another OpenShift upgrade while a MutexRunConfig is still working through its nodes. Until that run
  ends, the other MutexRunConfigs do not notice the new upgrade and do not pause their pools.

### Retries

ansible-operator counts every failed task as a failed reconcile, even one the role handles and reports in a
condition. A failed reconcile is retried with the controller-runtime backoff, not at the 10-minute period: first
after a few milliseconds, then doubling up to about 17 minutes between attempts, until a reconcile succeeds. This
applies to every failure the conditions report: an invalid MutexRule or MutexTarget, a missing reference, a failed
Job or a node that did not finish its upgrade in time. A failed Job is started again on every retry.

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
| MutexRunConfig | `UpgradeAvailable` | `True` / `UpgradeAvailable`, `False` / `UpgradeUnavailable`, `False` / `UpgradeFinished` | Whether a target node is behind the target version, or was released and still needs its cleanup Jobs. |
| MutexRunConfig | `UpgradeReady` | `True` / `UpgradeReady`, `False` / `UpgradeNotReady`, `False` / `UpgradeFinished` | Whether nodes can be released: an upgrade is available and the control plane is done. |
| MutexRunConfig | `TargetPoolsPaused` | `True` / `Paused`, `False` / `NotPaused` | The pools this MutexRunConfig keeps paused and, named separately, the target pools paused by someone else, which it never unpauses. `False` when no such pool is paused. |
| MutexRunConfig | `MutexRulesApplied` | `True` / `ApplySucceeded`, `False` / `ApplyFailed` | The mutex labels are on the nodes that are behind. |
| MutexRunConfig | `MCPUpdated` | `True` / `UpdateSucceeded`, `False` / `UpdateFailed`, `False` / `CanaryMembersLabelled`, `False` / `SelectorsRestored` | The selectors are changed for the run, or restored. `CanaryMembersLabelled`: the release label of the canary's own nodes (or of the named nodes) changed in this reconcile or less than 5 minutes ago, as recorded in the canary's `release-labelled-at` annotation, so the pools are re-pointed, and the first node is processed, at a later reconcile (never the one that recorded the time), normally the next one; meanwhile the canary leaves out the nodes the run holds. |
| MutexRunConfig | `JobRun` | `True` / `JobRunSucceeded`, `False` / `JobRunFailed` | The Jobs of the last node succeeded, or which Job failed and why. |
| MutexRunConfig | `NodeUpgrade` | `True` / `NodeUpgradeSucceeded`, `True` / `NodeAlreadyUpgraded`, `False` / `NodeUpgradeFailed` | The last node processed and its position ("Node is 2 of 5"). `NodeAlreadyUpgraded`: the node already runs the target version and has no Jobs left, because it was never behind or its Jobs, cleanup included, are done. `NodeUpgradeFailed`: the node did not finish its upgrade in time, and the message says which of the version label, the MCO state, `currentConfig` and `Ready` it is still missing; or MCO started updating another target node during the reconcile, so the run stopped before this node was touched, and the message names that node. |
| MutexRunConfig | `Degraded` | `True` / `PoolsLeftPaused` | A step failed while this MutexRunConfig holds pools paused or re-pointed. Everything stays as it is, and the message names the pools (also target pools paused by someone else), the error and, unless the MutexRunConfig is being deleted, how to abort. |
| MutexRunConfig | `Degraded` | `False` / `RunInProgress`, `False` / `NoPoolsPaused` | A run is in progress, or nothing is paused or re-pointed by this MutexRunConfig. After a failure, the `NoPoolsPaused` message carries the last error. |

## Recovery

**To abort a run, delete the MutexRunConfig.** Its finalizer (`nodeupgrade.redhat-na-ssa.github.io/finalizer`) runs the
restore before the object goes away. It puts back the saved node selectors, the canary last, removes this run's mutex
labels, its release label and its `labelled-by` and `released-by` node annotations, and unpauses the pools that this
MutexRunConfig paused. **MCO then upgrades the remaining nodes without running their Jobs.** The finalizer does not
run the pending cleanup Jobs of a node that was already released: it only removes the node's `released-by` annotation
and release label. Run that cleanup yourself if you need it. The finalizer also removes the release label from the
canary's own nodes right after it restores the canary's selector (that patch also removes `release-labelled-at`),
and then the canary's `restored-at` annotation. If MCO's view of the pools lags that restore at that moment, it can
move such a node through the `worker` pool once, which is unpaused when `worker` is not a target pool.
Delete MutexRunConfigs before you uninstall the operator, or the finalizer cannot run.

A delete does not interrupt a reconcile that is already running. If the deleted MutexRunConfig is the one working
through its nodes, the operator finishes the node it is working on (its Jobs, up to `timeoutSeconds` each, and the
wait for the node to finish its upgrade, up to 2 hours), skips the remaining nodes and then runs the finalizer. If
another MutexRunConfig is working through its nodes, the finalizer waits until that whole run has ended (see
[One MutexRunConfig at a time](#one-mutexrunconfig-at-a-time)). Use the manual steps below if that is too long to
wait. They change only what the deleted MutexRunConfig changed, so they leave the running one's pools and nodes alone.

If the operator is gone or cannot run, do the same by hand, in this order. The commands need `jq` and `sha1sum`. They
select the pools by the deleted MutexRunConfig's `modified-by`, `paused-by` and `restored-at` annotations, and the
nodes by its `labelled-by` and `released-by` annotations, by its value of the release label and by its MutexTargets'
`status.nodes`. To see what a step would change, run its `oc get ... | jq` part on its own (in step 2, everything but
the last line, without the `|` at the end). First set the MutexRunConfig:

```sh
ns=<namespace>   # namespace of the deleted MutexRunConfig
name=<name>      # its name
mrc="$ns/$name"
rel=$(printf '%s' "$mrc" | sha1sum | cut -c1-40)   # its value of the release label
```

If the MutexRunConfig no longer exists, for example when a `ConfigValidated` message names a pool whose `modified-by`
or `paused-by` value is a MutexRunConfig that is gone, set `ns` and `name` from that value and leave out step 4. Steps
1 and 3 work as they are. In step 2, set `labels` and `targets` this way instead, because the MutexRunConfig cannot
be read:

```sh
labels=$(oc get nodes -o json | jq -c --arg mrc "$mrc" '[.items[].metadata
  | select((.annotations // {})["nodeupgrade.redhat-na-ssa.github.io/labelled-by"] == $mrc)
  | .labels // {} | keys[] | select(startswith("mutexrule.nodeupgrade.redhat-na-ssa.github.io/"))
  | select(. != "mutexrule.nodeupgrade.redhat-na-ssa.github.io/release")] | unique')
targets='[]'
```

1. Restore the selectors of the pools whose `modified-by` names it, and remove that annotation,
   `original-match-expressions` and `release-labelled-at`. The canary, the pool with an `In` expression on the release
   label, comes last, so a released node does not drop into an unpaused `worker` pool between the two patches:

   ```sh
   for pool in $(oc get mcp -o json | jq -r --arg mrc "$mrc" '.items
       | sort_by([(.spec.nodeSelector.matchExpressions // [])[] | select(.operator == "In"
                  and .key == "mutexrule.nodeupgrade.redhat-na-ssa.github.io/release")] | length > 0) | .[]
       | select(.metadata.annotations["nodeupgrade.redhat-na-ssa.github.io/modified-by"] == $mrc) | .metadata.name'); do
     oc patch mcp "$pool" --type=merge -p "$(oc get mcp "$pool" -o json | jq -c '{
       metadata: {annotations: {"nodeupgrade.redhat-na-ssa.github.io/original-match-expressions": null,
                                "nodeupgrade.redhat-na-ssa.github.io/modified-by": null,
                                "nodeupgrade.redhat-na-ssa.github.io/release-labelled-at": null}},
       spec: {nodeSelector: {matchExpressions:
         (.metadata.annotations["nodeupgrade.redhat-na-ssa.github.io/original-match-expressions"] | fromjson
          | if length > 0 then . else null end)}}}')"
   done
   ```

2. Remove every mutex label from the nodes whose `labelled-by` names it and its mutex labels from the nodes of its
   MutexTargets that have no `labelled-by` at all, remove the release label from every node where it has this
   MutexRunConfig's value, and remove its `labelled-by` and `released-by` annotations. A node whose `labelled-by`
   names another MutexRunConfig keeps its mutex labels, and another MutexRunConfig's release value is left alone:

   ```sh
   # the mutex label of each MutexRule of the MutexRunConfig
   labels=$(oc get mutexrunconfig "$name" -n "$ns" -o json | jq -c --arg ns "$ns" '[.spec.mutexRules[]
     | "mutexrule.nodeupgrade.redhat-na-ssa.github.io/\(.name).\(if (.namespace // "") == "" then $ns else .namespace end)"]')
   # the nodes of its MutexTargets
   targets=$(for t in $(oc get mutexrunconfig "$name" -n "$ns" -o json | jq -r '.spec.mutexTargets[].name'); do
     oc get mutextarget "$t" -n "$ns" --ignore-not-found -o json; done | jq -s -c '[.[].status.nodes[]?]')
   oc get nodes -o json | jq -r --arg mrc "$mrc" --arg rel "$rel" \
       --argjson labels "$labels" --argjson targets "$targets" '
     .items[] | .metadata as $m | ($m.annotations // {}) as $a
     | ($a["nodeupgrade.redhat-na-ssa.github.io/labelled-by"] == $mrc) as $ours
     | ([($m.labels // {}) | keys[] | select(startswith("mutexrule.nodeupgrade.redhat-na-ssa.github.io/"))
         | select(. != "mutexrule.nodeupgrade.redhat-na-ssa.github.io/release")
         | select($ours or (. as $k | $a["nodeupgrade.redhat-na-ssa.github.io/labelled-by"] == null
                            and any($labels[]; . == $k) and any($targets[]; . == $m.name)))]
        + (if ($m.labels // {})["mutexrule.nodeupgrade.redhat-na-ssa.github.io/release"] == $rel
           then ["mutexrule.nodeupgrade.redhat-na-ssa.github.io/release"] else [] end)) as $drop
     | [if $ours then "nodeupgrade.redhat-na-ssa.github.io/labelled-by" else empty end,
        if ($a["nodeupgrade.redhat-na-ssa.github.io/released-by"] // "" | startswith($mrc + "|"))
        then "nodeupgrade.redhat-na-ssa.github.io/released-by" else empty end] as $unmark
     | select(($drop + $unmark) | length > 0)
     | {metadata: {labels: ($drop | map({(.): null}) | add // {}),
                   annotations: ($unmark | map({(.): null}) | add // {})}} as $patch
     | "\($m.name) \($patch | tojson)"' |
   while read -r node patch; do oc patch node "$node" --type=merge -p "$patch"; done
   ```

3. Unpause the pools whose `paused-by` names it, and remove that annotation. Then remove the `restored-at` annotation
   that names it from the canary:

   ```sh
   for pool in $(oc get mcp -o json | jq -r --arg mrc "$mrc" '.items[]
       | select(.metadata.annotations["nodeupgrade.redhat-na-ssa.github.io/paused-by"] == $mrc) | .metadata.name'); do
     oc patch mcp "$pool" --type=merge -p '{"metadata":{"annotations":{"nodeupgrade.redhat-na-ssa.github.io/paused-by":null}},"spec":{"paused":false}}'
   done
   for pool in $(oc get mcp -o json | jq -r --arg mrc "$mrc" '.items[]
       | select(.metadata.annotations["nodeupgrade.redhat-na-ssa.github.io/restored-at"] // null
                | . != null and (. == $mrc or endswith(" " + $mrc)))
       | .metadata.name'); do
     oc patch mcp "$pool" --type=merge -p '{"metadata":{"annotations":{"nodeupgrade.redhat-na-ssa.github.io/restored-at":null}}}'
   done
   ```

4. If the operator is uninstalled, remove the finalizer so the MutexRunConfig can be deleted. Do this last, because
   step 2 reads the MutexRunConfig:

   ```sh
   oc patch mutexrunconfig "$name" -n "$ns" --type=merge -p '{"metadata":{"finalizers":null}}'
   ```

To **retry** after fixing the cause of a `Degraded=True`, do nothing: the next retry (see [Retries](#retries)), at
most about 17 minutes later, continues where the run stopped. A Job that failed is run again. To retry at once,
delete the operator pod. On start it reconciles every resource, and a run in progress continues where it was (Jobs
that already completed are reused). `oc rollout restart` does not work here: OLM reverts it on the Deployment it
manages, and the old pod keeps running.

```sh
oc delete pod -n <operator namespace> -l app.kubernetes.io/name=openshift-node-upgrade-mutex-operator
```

## Permissions

The operator's ServiceAccount gets exactly these permissions (`config/rbac/role.yaml`, installed cluster-wide):

| API group | Resource | Verbs | Used for |
| --- | --- | --- | --- |
| `batch` | `jobs` | create, get, list, watch | Dry-run validation, creating MutexRule Jobs and following them. Never deleted, patched or updated. |
| core | `nodes` | get, list, watch, patch | Reading versions, pool membership, the MCO state and `Ready`. Adding and removing the mutex labels, the release label and the `labelled-by` and `released-by` annotations. |
| `machineconfiguration.openshift.io` | `machineconfigpools` | get, list, watch, patch | Reading selectors. Pausing, unpausing, changing `matchExpressions` and the five annotations (`paused-by`, `original-match-expressions`, `modified-by`, `release-labelled-at`, `restored-at`). |
| `config.openshift.io` | `clusterversions` | get, list, watch | The target version and the control plane's progress. |
| `apiregistration.k8s.io` | `apiservices` | get, list, watch | The APIService health check. |
| `nodeupgrade.redhat-na-ssa.github.io` | `mutexrules`, `mutextargets`, `mutexrunconfigs` | get, list, watch, update, patch | Watching and reading the CRs. Adding and removing the finalizer. |
| `nodeupgrade.redhat-na-ssa.github.io` | `mutexrules/status`, `mutextargets/status`, `mutexrunconfigs/status` | get, update, patch | Writing status. |
| `nodeupgrade.redhat-na-ssa.github.io` | `mutexrules/finalizers`, `mutexrunconfigs/finalizers` | update | Lets Jobs carry owner references with `blockOwnerDeletion` to these CRs. ansible-operator does not set that flag today; the rule is kept as in the operator-sdk scaffold. |
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

* Alpha. The API (`v1alpha1`) may change. Live testing so far is one small OpenShift 4.21 cluster (see
  `docs/HANDOFF.md` for what it covered).
* One operator per cluster, one MutexRunConfig per canary pool, and no target pool shared between MutexRunConfigs.
  Validation refuses a canary or target pool that another MutexRunConfig has paused or re-pointed.
* Every target node needs the `release-image-version` label, which the operator does not maintain.
* Nodes are handled one at a time, so a large pool takes as long as its slowest Jobs plus one node upgrade per node.
  An upgraded node returns to its own pool, which is still paused, after its cleanup Jobs, and takes that pool's
  rendered config when the pool is unpaused at the end of the run.
* MutexRunConfigs are reconciled one at a time. With several of them, the pools are upgraded one MutexRunConfig after
  another, so plan the maintenance window for the sum of their runs. While one works through its nodes, the others
  are not reconciled at all (see [One MutexRunConfig at a time](#one-mutexrunconfig-at-a-time)).
* A node that does not finish its upgrade within 2 hours stops the run with the pools paused.
* Editing the MutexRunConfig or its MutexTargets during a run takes effect at the next reconcile. A pool that is no
  longer a target keeps its labels and selectors until the end of the run and is then restored and unpaused, so its
  remaining nodes upgrade without their Jobs. A node of it that the run already released still gets its cleanup Jobs
  first. The Jobs of a MutexRule removed from `spec.mutexRules` no longer run,
  and its label goes when the node is released.
* A failure is retried with a backoff of up to about 17 minutes, and a failed Job is started again on each retry.
* Deleting a MutexRunConfig takes effect only after the node in progress is finished, or, while another
  MutexRunConfig works through its nodes, after that whole run. It does not run the pending cleanup Jobs of a node
  that was already released.
* Changes to ClusterVersion, nodes and pools are noticed at the next reconcile: at most 10 minutes later, unless
  another MutexRunConfig is working through its nodes.
* The canary's own nodes can still pass through the `worker` pool once when an API outage begins right after the
  operator records the time on the canary and lasts longer than 5 minutes, and when the finalizer runs while MCO's view
  of the pools lags (see [A canary MachineConfigPool](#a-canary-machineconfigpool) and [Recovery](#recovery)).
* `spec.jobNamespace` can be any namespace, and the Jobs can use any ServiceAccount in it. See the permissions section.
* MutexRule names must not contain `.`.
* `spec.skipTLSVerify` is deprecated and has no effect.

## More information

Source, issues and development notes:
[github.com/shpwrck/openshift-node-upgrade-mutex-operator](https://github.com/shpwrck/openshift-node-upgrade-mutex-operator).

Licensed under the [Apache License 2.0](https://www.apache.org/licenses/LICENSE-2.0) (`LICENSE` in the repository).
