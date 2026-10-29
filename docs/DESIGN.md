# Design notes

This file is for maintainers. It explains how the `mutexrunconfig` role is built, what it keeps in the cluster, and
what it assumes about the Machine Config Operator (MCO). It is not part of `README.md` or of the operator's
description on OperatorHub. For what the operator does from a user's point of view, read [USAGE.md](USAGE.md). For
the task files one by one, read [roles/mutexrunconfig/README.md](../roles/mutexrunconfig/README.md).

File references have the form `file:line`. Short forms are in the `mutexrunconfig` role: `main.yml` is
`roles/mutexrunconfig/tasks/main.yml`, a number such as `05:118` is line 118 of
`roles/mutexrunconfig/tasks/05-modify-machineconfigpool.yml`, and `vars/` and `defaults/` are
`roles/mutexrunconfig/vars/` and `roles/mutexrunconfig/defaults/`. Other files have their full path. The line numbers
were checked against the code when this file was written. If they drift, the task names next to them are the stable
anchor.

## Reconcile pipeline

![The mutexrunconfig role's reconcile pipeline: task files in order, the gate that decides whether each runs, and the conditions each writes.](diagrams/reconcile-pipeline.svg)

In words:

1. `main.yml` decides the mode. The reconcile is a finalizer run when `state` is `absent` or the MutexRunConfig has a
   `deletionTimestamp` (`main.yml:34-39`).
2. A MutexRunConfig outside the operator namespace (`POD_NAMESPACE`) gets `Reconciled=False` (`NamespaceNotAllowed`),
   and the play ends (`main.yml:44-70`). Without `POD_NAMESPACE`, as with `make run`, every namespace is allowed.
3. `00-resolve-references.yml` always runs. It resolves the rule and target references, the mutex label keys and the
   release label expressions. It reads nothing from the API.
4. A finalizer run reads the MutexTargets that still exist, runs `08-restore.yml` and ends (`main.yml:93-125`).
   `09-report.yml` does not run then.
5. `01-validate.yml` checks the configuration and the APIServices (`ConfigValidated`, `ClusterStateValidated`).
6. `02-check-for-upgrade.yml` runs when the configuration is valid. It reads ClusterVersion and the nodes
   (`UpgradeChecked`, `NodeVersionsKnown`, `UpgradeAvailable`, `UpgradeReady`).
7. When an upgrade is available, `03` pauses the target pools, `04` labels the nodes and `05` re-points the pools.
   Each runs only when every step before it succeeded.
8. When, in addition, the control plane is done and the pools are re-pointed, `06-execute-jobs.yml` handles the
   target nodes one at a time and calls `07-run-job.yml` for each rule and phase (`JobRun`, `NodeUpgrade`).
9. `08-restore.yml` runs when every node is done, and also whenever no target node needs the upgrade
   (`MCPUpdated=False` `SelectorsRestored`, `UpgradeAvailable=False` `UpgradeFinished`).
10. `09-report.yml` runs at the end of every reconcile that got this far (`TargetPoolsPaused`, `Degraded`).

Every step sets a boolean gate fact: false at the top of its rescue, true as the last task of its block
(`main.yml:21-24`). The later steps test these facts (`main.yml:127-247`).

| Step | Runs when | Reads | Writes in the cluster | Conditions | Gate fact |
| --- | --- | --- | --- | --- | --- |
| namespace check | always (`main.yml:44-70`) | `POD_NAMESPACE` (`main.yml:36`) | status | `Reconciled=False` `NamespaceNotAllowed` (`main.yml:50-66`) | ends the play |
| `00-resolve-references.yml` | always (`main.yml:90-91`) | the spec only | nothing | none | none; builds the label keys and release expressions (`00:14-49`) |
| finalizer | being deleted (`main.yml:93-125`) | MutexTargets (`main.yml:96-105`) | through `08` | none | ends the play |
| `01-validate.yml` | not finalizing (`main.yml:127-128`) | MutexRules (`01:72`), MutexTargets (`01:111`), the canary and target pools (`01:154`, `01:185`), Nodes (`01:269-411`), all pools (`01:414`), APIServices (`01:566`) | status only | `ConfigValidated` `FetchSucceeded` or `ValidationFailed` (`01:515-556`); `ClusterStateValidated` `APIServicesUp` or `APIServicesDown`, and `ConfigValidated=False` `ClusterStateInvalid` (`01:596-638`) | `ConfigValidated` (`01:531-539`, `01:614-617`), `ClusterStateValidated` (`01:609-617`) |
| `02-check-for-upgrade.yml` | `ConfigValidated` (`main.yml:130-133`) | ClusterVersion `version` (`02:28-33`), Nodes (`02:51-55`) | status only | `NodeVersionsKnown` `VersionLabelMissing` or `VersionsKnown`, `UpgradeAvailable`, `UpgradeReady`, `UpgradeChecked` `CheckSucceeded` or `CheckFailed` (`02:114-224`) | `UpgradabilityChecked`, `UpgradeAvailable`, `UpgradeReady` (`02:149-152`, `02:201-210`) |
| `03-pause-machine-config-pools.yml` | also `UpgradabilityChecked` and `UpgradeAvailable` (`main.yml:137-142`) | the target pools read by `01` | `spec.paused: true` and `paused-by` (`03:9-25`) | `TargetPoolsPaused=False` `NotPaused`, only on failure (`03:37-50`) | `TargetPoolsPaused` (`03:27-34`) |
| `04-apply-mutex-rules-as-labels.yml` | also `TargetPoolsPaused` (`main.yml:144-150`) | the Nodes read by `02`, the canary read by `01` | node mutex labels, `labelled-by`, the release label; canary `release-labelled-at`, `modified-by`, `original-match-expressions` and the hold selector (`04:135-207`) | `MutexRulesApplied` `ApplySucceeded` or `ApplyFailed` (`04:209-248`) | `MutexRulesApplied` (`04:226-233`) |
| `05-modify-machineconfigpool.yml` | also `MutexRulesApplied` (`main.yml:152-159`) | the canary and target pools read by `01` | pool `matchExpressions`, `original-match-expressions`, `modified-by`; removes `release-labelled-at` (`05:115-178`) | `MCPUpdated` `CanaryMembersLabelled`, `UpdateSucceeded` or `UpdateFailed` (`05:86-113`, `05:179-216`) | `MCPUpdated` (`05:194-202`) |
| `06-execute-jobs.yml` | `JobRun`, set when `UpgradeReady` and `MCPUpdated` also hold (`main.yml:161-187`) | the MutexRunConfig again (`06:41-48`), Nodes (`06:74-145`, `06:283-292`) | node patches: leftover labels, release, release mark cleared (`06:196-208`, `06:263-278`, `06:318-328`); Jobs through `07` | `JobRun` `JobRunSucceeded` or `JobRunFailed`; `NodeUpgrade` `NodeAlreadyUpgraded`, `NodeUpgradeSucceeded` or `NodeUpgradeFailed` (`06:210-224`, `06:238-252`, `06:329-396`) | `JobRun=false` on a failure or a delete (`06:50-60`, `06:361-364`) |
| `07-run-job.yml` | for each rule and phase, from `06` (`06:229-236`, `06:306-316`) | Jobs with the `job-key` label (`07:83-99`, `07:127-137`) | creates a Job (`07:101-120`) | none (`06` reports) | none; fails the task (`07:139-148`) |
| `08-restore.yml` | `ConfigValidated`, `UpgradabilityChecked` and (`JobRun` or not `UpgradeAvailable`) (`main.yml:195-205`); the finalizer (`main.yml:111-121`) | all pools and Nodes (`08:71-83`) | pool selectors and annotations, `restored-at`, node labels and annotations, unpause (`08:163-293`) | from `main.yml`: `MCPUpdated=False` `SelectorsRestored`, `UpgradeAvailable` and `UpgradeReady` `False` `UpgradeFinished` (`main.yml:207-239`) | none; a failure sets `mutexrunconfig_failure` (`main.yml:241-244`) |
| `09-report.yml` | every reconcile that was not stopped by the namespace check or the finalizer (`main.yml:246-247`) | all pools (`09:17-21`) | status only | `TargetPoolsPaused` `Paused` or `NotPaused`; `Degraded` `PoolsLeftPaused`, `RunInProgress` or `NoPoolsPaused` (`09:50-111`) | none |

The gate fact `UpgradabilityChecked` reports as the condition `UpgradeChecked` (`main.yml:76`, `02:195`). Every other
gate fact has the name of its condition. `TargetPoolsPaused=True` is written only by `09`, at the end of the
reconcile, so it lags while `06` runs.

## Invariants

These are the promises the code keeps. A change that breaks one of them needs a design decision, not only a review.

1. **Only the operator namespace.** Each role acts only on CRs in `POD_NAMESPACE` (`main.yml:44-70`,
   `roles/mutexrule/tasks/main.yml:9-35`, `roles/mutextarget/tasks/main.yml:10-36`).
2. **Nothing changes before the checks pass.** `03`, `04` and `05` run only after `01` and `02` succeeded
   (`main.yml:137-159`). A failed check sets `UpgradeAvailable` to false (`02:205-210`), so nothing is paused. The
   consequence is fail-open: while nothing is paused, MCO upgrades the nodes without their Jobs. See the
   [Safety model](USAGE.md#safety-model).
3. **A failure never unpauses.** Only `08` unpauses (`08:280-293`). In a normal reconcile `08` runs only when `JobRun`
   is still true after the last node, or when no target node needs the upgrade (`main.yml:195-199`). Every rescue sets
   its gate to false, which skips the steps after it.
4. **Only its own pools are unpaused.** `08` unpauses a pool only when its `paused-by` annotation names this
   MutexRunConfig (`08:122-123`, `08:280-293`). A pool an administrator paused stays paused.
5. **Pre-upgrade Jobs come before the release.** The patch that gives a target node the release label
   (`06:263-278`) comes after its pre-upgrade Jobs (`06:229-236`), in the same block, so a Job failure goes to the
   rescue first. `04` gives the release label only to the holders: nodes this run released and the canary's own
   nodes (`04:44-48`, `04:72-100`).
6. **One target node at a time.** `06` runs in a loop, one node after the other (`main.yml:177-187`), and the manager
   runs one reconcile per kind at a time (`config/manager/manager.yaml:74`). A node MCO is already updating is waited
   for first (`06:110-136`). Before a node is taken down, the reconcile stops if MCO has started on another target node
   (`06:139-166`).
7. **A released node finishes first.** Nodes with this MutexRunConfig's `released-by` go first in the loop
   (`main.yml:179-182`) and resume at the wait, so their cleanup Jobs run before another node starts (`06:20-26`).
8. **The node wait needs more than the version label.** A node counts as upgraded only when its version label is the
   desired version, MCO reports `Done` with `currentConfig` equal to `desiredConfig`, that config is a rendered config
   of the canary, and the node is `Ready` (`vars/main.yml:149-192`).
9. **Jobs are never deleted.** No task in `roles/` deletes a Job (`git grep -n 'state: absent' roles/` finds none). A
   Failed Job is kept, and the next attempt creates a new one (`07:92-120`).
10. **Two MutexRunConfigs never share a pool.** `01` refuses a canary or target pool whose `paused-by` or `modified-by`
    names another MutexRunConfig (`01:199-224`).
11. **Status is merged, never replaced.** `manageStatus: false` (`watches.yaml:7`, `watches.yaml:14`,
    `watches.yaml:28`) leaves the status to the roles, which write conditions by type with
    `operator_sdk.util.k8s_status`.

## State kept in the cluster

The roles keep no state between reconciles except these labels and annotations and the CR status. A restart of the
operator, or a reconcile cut short, resumes from them. The names are in `vars/main.yml:13-90`.

| Key | On | Value | Written by | Removed by | Read by |
| --- | --- | --- | --- | --- | --- |
| label `mutexrule.nodeupgrade.redhat-na-ssa.github.io/<rule>.<namespace>` | target node | empty | `04:135-146` | the release patch `06:263-278`; `08:196-247` | `06:94` (which pre-upgrade Jobs are left), `04:52-64`, `08` |
| label `mutexrule.nodeupgrade.redhat-na-ssa.github.io/release` | released target node, the canary's own nodes | SHA-1 of `<namespace>/<name>` (`vars/main.yml:30-31`) | `04:174-183` (holders), `06:263-278` (release) | `06:318-328`, `04:170-194`, `08:196-247` | the run-time pool selectors (`00:22-23`, `05:115-178`) |
| `nodeupgrade.redhat-na-ssa.github.io/labelled-by` | node | `<namespace>/<name>` | `04:135-146`, with the mutex labels | `06:263-278`, `08:196-247` | `08:196-229` (whose labels to remove), `01:316-327` |
| `nodeupgrade.redhat-na-ssa.github.io/released-by` | node | `<namespace>/<name>\|<version>` (`vars/main.yml:85`) | `06:263-278` | `06:318-328`, `08:196-247` | `02:69-107` (resume), `06:95-96` |
| `nodeupgrade.redhat-na-ssa.github.io/paused-by` | pool | `<namespace>/<name>` | `03:9-25` | `08:280-293` | `08:122-123`, `09:29-48`, `01:199-224` |
| `nodeupgrade.redhat-na-ssa.github.io/modified-by` | pool | `<namespace>/<name>` | `04:152-168` (canary), `05:118-178` | `08:163-194` | `08:94-147`, `09:29-48`, `01:199-224`, `01:413-441` |
| `nodeupgrade.redhat-na-ssa.github.io/original-match-expressions` | pool | JSON copy of the `matchExpressions` before the run | `04:152-168` (canary), `05:118-178` | `08:163-194` | `01:229-266`, `08:163-194`, `roles/mutextarget/tasks/02-gather-nodes.yml:50-57` |
| `nodeupgrade.redhat-na-ssa.github.io/release-labelled-at` | canary | time, `YYYY-MM-DDTHH:MM:SSZ` | `04:148-168`, `04:196-207` | the canary re-point `05:144-169`, `08:163-194` | `05:69-84` |
| `nodeupgrade.redhat-na-ssa.github.io/restored-at` | canary | `<time> <namespace>/<name>` | `08:163-194`, `08:249-264` | `08:266-278` | `08:94-161` |
| label `nodeupgrade.redhat-na-ssa.github.io/job-key` | Job | SHA-1 of MutexRunConfig, node, rule, phase and desired version (`07:31-33`) | `07:101-120` | never | `07:83-99` (re-use) |
| `nodeupgrade.redhat-na-ssa.github.io/mutexrunconfig`, `/mutexrule`, `/node`, `/phase`, `/desired-version` | Job | names and version | `07:111-116` | never | not read by the roles; they are for people |
| finalizer `nodeupgrade.redhat-na-ssa.github.io/finalizer` | MutexRunConfig | | ansible-operator (`watches.yaml:29-32`) | ansible-operator, after the finalizer run | ansible-operator |
| `status.nodes` | MutexTarget | sorted node names | `roles/mutextarget/tasks/02-gather-nodes.yml:98-112` | replaced on each reconcile | `01:110-151` |

The job-key leaves out the JobSpec (`07:31-33`). A Complete Job is therefore re-used after the MutexRule is edited.

## The settle time

`mutexrunconfig_label_settle_seconds` is 300 seconds (`defaults/main.yml:29`). It covers one risk. MCO's controller
reads the nodes and pools from its own cache. After an API outage, such as a kube-apiserver rollout early in an
upgrade, that cache can be stale. If the canary's selector changes while MCO still sees an old release label on a node,
MCO can move the node into the wrong pool. A held node could then be upgraded without its Jobs, and one of the canary's
own nodes could move into `worker`. The first live upgrade with an earlier canary design lost a node this way: a held
node went into the canary and rebooted without its Jobs (see the live runs in
[tests/Scenarios.md](../tests/Scenarios.md)).

So a selector change that depends on a release label change waits until the label change is old:

- At the start of a run, `04` stamps the canary's `release-labelled-at` before and after the release label changes
  that canary membership depends on (`04:148-168`, `04:196-207`). `05` re-points the pools only once that time is
  300 seconds old, and never in the reconcile that wrote it (`05:69-84`). Until then `MCPUpdated` is `False`
  (`CanaryMembersLabelled`) and `06` does not run.
- At the end of a run, `08` writes `restored-at` with the canary's restore. The release label is removed from the
  canary's own nodes only in a later pass, once that time is 300 seconds old (`08:149-161`, `08:266-278`).
- The time is kept in the cluster, not in memory, so a restart or a cut reconcile still waits (`04:33-37`).

The reconcile period is 10 minutes (`watches.yaml:27`), longer than the settle time. So normally the next reconcile
re-points. A reconcile that comes earlier, such as a retry or the first one after a restart, waits again.

Why 300 seconds: in the live runs on 4.21, MCO's node and pool caches came back 70 to 115 seconds after an API outage,
and the first re-render came about 2 minutes after the API was back
([MCO behaviour seen in the live runs](../tests/Scenarios.md#mco-behaviour-seen-in-the-live-runs); the comment in
`defaults/main.yml:21-28` says the same). There is no MCO source reference for these numbers, and other versions are
unknown. See the MCO table below for how to re-check them.

The wait at the start happens only when one of the canary's own nodes gets the release label or a node loses it.
Without a stamp the pools are re-pointed at once (`05:43-45`). The wait at the end happens only when a node still
carries this run's release label when the canary is restored (`08:149-161`).

## What the operator assumes about MCO

MCO decides which pool a node belongs to and when a node updates. The operator only changes pool selectors, node
labels and `spec.paused`. These are the MCO behaviours the code relies on.

| Assumption | Evidence | What breaks if it changes | How to re-check |
| --- | --- | --- | --- |
| MCO resets the `nodeSelector` of the built-in `worker` and `master` pools to its own manifests. | `syncMachineConfigPools` applies `manifests/worker.machineconfigpool.yaml` and `master.machineconfigpool.yaml` ([sync.go, release-4.21](https://github.com/openshift/machine-config-operator/blob/release-4.21/pkg/operator/sync.go)); `EnsureMachineConfigPool` replaces a `nodeSelector` that differs ([lib/resourcemerge/machineconfig.go, release-4.21](https://github.com/openshift/machine-config-operator/blob/release-4.21/lib/resourcemerge/machineconfig.go)). How soon after a change it resets: not measured in the repository (unknown). | On a `worker` target the `release NotIn` expression does not stay (`05:115-178` writes it anyway). The released node then leaves `worker` only through the next row. | Patch the `worker` selector on a test cluster and watch it: `oc get mcp worker -o jsonpath='{.spec.nodeSelector}' -w`. |
| A node that matches `worker` and one custom pool belongs to the custom pool. | `GetPoolsForNode`, case `len(custom) == 1` without master ([pkg/helpers/helpers.go, release-4.16](https://github.com/openshift/machine-config-operator/blob/release-4.16/pkg/helpers/helpers.go) and [release-4.21](https://github.com/openshift/machine-config-operator/blob/release-4.21/pkg/helpers/helpers.go)). Live runs on 4.21 used it for every released node of a `worker` target ([tests/Scenarios.md](../tests/Scenarios.md#mco-behaviour-seen-in-the-live-runs)). | A released node of a `worker` target stays in the paused `worker` pool and never upgrades. The node wait times out after 2 hours (`NodeUpgradeFailed`). | Read `GetPoolsForNode` on the MCO release branch of the target version. |
| A node that matches two or more custom pools is refused: MCO manages it in no pool. | `GetPoolsForNode` returns the error "belongs to N custom roles", and `GetNodesForPool` skips the node (same files). | The ordering in `05` (canary first, `05:13-19`) and in `08` (canary last, `08:17-25`) relies on it. During one patch a released node of a custom target pool matches two custom pools and stays where it is. If MCO picked one of them, the node could land in an unpaused pool. Note that `roles/mutextarget/tasks/02-gather-nodes.yml:89-96` still lists such a node in `status.nodes` when one of its pools is a target. | Same function. |
| A node that matches `master` and a custom pool stays in `master`. A node that matches `master` and `worker` is in `master`. | `GetPoolsForNode`: "defaulting to master" for master plus one custom pool, and the `master != nil` case (same files, 4.16 and 4.21). Two custom pools plus master is refused (the check for two custom pools comes first). | `01:313-315` relies on it: a control-plane node that matches the canary's labels is harmless. Note the mismatch: `roles/mutextarget/tasks/02-gather-nodes.yml:89-96` gives the custom pool precedence over `master`, so a control-plane node that matches a custom target pool is listed in `status.nodes`. The comments at `roles/mutextarget/tasks/02-gather-nodes.yml:10-13` and `01:378-380` state the MCO rule; the mismatch is HANDOFF [Known gaps](HANDOFF.md#known-gaps) G20. | Same function. |
| After an API outage MCO's controller sees the nodes again 1 to 2 minutes after the API is back and renders about 2 minutes after it. | Live runs on 4.21.20 to 4.21.23: 70 to 115 seconds for the node and pool caches, about 2 minutes to the first re-render ([tests/Scenarios.md](../tests/Scenarios.md#mco-behaviour-seen-in-the-live-runs)); the comment in `defaults/main.yml:21-28`. No MCO source reference: other versions are unknown. | If MCO takes longer than 300 seconds to see a release label change, the protection of the settle time is gone (see above). | During a kube-apiserver rollout on a test cluster, compare the times of node label changes with the times MCO logs them: `oc logs -n openshift-machine-config-operator deploy/machine-config-controller -c machine-config-controller`. |
| Rendered configs are named `rendered-<pool>-<hash>`, and the hash has no `-`. | `getMachineConfigHashedName` writes `rendered-<pool>-<md5 in hex>` ([pkg/controller/render/hash.go, release-4.21](https://github.com/openshift/machine-config-operator/blob/release-4.21/pkg/controller/render/hash.go)). Live runs read real `currentConfig` names this way, such as `rendered-canary-*` ([tests/Scenarios.md](../tests/Scenarios.md#rehearsals)). | The node wait matches `^rendered-<canary>-[^-]+$` (`vars/main.yml:160-163`), and `01:451-453` reads a node's pool from its `currentConfig`. A new format would make every node wait time out, and the overlap check would misplace nodes. | `oc get mc \| grep rendered-` on the target version. |

## Compatibility paths

Some code handles cluster state that an earlier build wrote. Every such build used the old API group (HANDOFF,
[The API group](HANDOFF.md#the-api-group)) and the label prefix `mutexrule.<old group>/`. The current code
matches only `mutexrule.nodeupgrade.redhat-na-ssa.github.io/` and `nodeupgrade.redhat-na-ssa.github.io/` keys
(`vars/main.yml:14`, `vars/main.yml:54-90`). So no build that wrote this state can trigger these paths any more; only a
hand-made label or annotation with the new keys can. Moving from 0.2.x is a reinstall
([Moving from 0.2.x](USAGE.md#moving-from-02x)), not an in-place upgrade. Whether to remove these paths, or to keep them
as a guard against hand edits, is a decision for the owner.

| Code location | State handled | Which build wrote it | When it can be removed |
| --- | --- | --- | --- |
| `05:58-79`, `05:118-142`, `05:170-178`; `04:108-124` | A canary that holds with the exclusion selector of the earlier design: `<mutex label> DoesNotExist` next to expressions that differ from its originals. The target pools are then re-pointed before the canary. | 0.2.x wrote such a canary selector with the old prefix (`roles/mutexrunconfig/tasks/05-modify-machineconfigpool.yml:6` at tag `v0.2.34`). Development builds before commit `1970a68` ("select the canary by a release label") did too, also with the old prefix. | No build with the current prefix writes it. Removable now, unless kept as a guard. |
| `04:66-71`, `06:254-262` | A node with this run's `released-by` but without the release label. | Development builds from commit `ba100a2` (which added `released-by`) to before `1970a68` (which added the release label), with the old prefix. | Same. |
| `08:124-128` | A pool with `original-match-expressions` but without `modified-by`: restored when it is in the restore list or paused by this MutexRunConfig. | Development builds from commit `b70f850` (which added `original-match-expressions`) to before `ba100a2` (which added `modified-by`), with the old group. 0.2.x wrote neither annotation. | Same. |
| `08:196-210` (`unmarked`) | Mutex labels on a node without `labelled-by`: removed when the node is a target node, or from any node when no MutexTarget is left. Added in commit `bfe8347` for "nodes labelled by an older build". | 0.2.x labelled nodes without any annotation (`roles/mutexrunconfig/tasks/04-apply-mutex-rules-as-labels.yml:12` at tag `v0.2.34`), with the old prefix. Development builds before `ba100a2` did the same. | Same. |
| `08:133-141` | A `restored-at` that is only the owner, without a time, or empty on the canary: treated as just written. | unknown. No commit in the history writes that form: `restored-at` has carried a time since it was added in commit `c5acdec`. It may only be a guard against a hand edit. | unknown |
| `02:9-10`, CRD field `spec.skipTLSVerify` | Still accepted, no effect. | Builds that pulled the release image to find the version (`02:9-10`). | With the next API version: removing the field from `v1alpha1` is an API change for existing CRs. |

## Coupling between the roles

The three roles share names and logic by copy, not by an include. A change to one of these needs the same change in the
other place.

- **Annotation and label names.** `roles/mutextarget/vars/main.yml:12` (`mutextarget_annotation_original_expressions`)
  must equal `vars/main.yml:54`. `roles/mutextarget/vars/main.yml:13` (`mutextarget_label_prefix`) must equal
  `vars/main.yml:14`. If they differ, the MutexTarget role reads a pool's run-time selector instead of its saved one,
  and `status.nodes` can change in the middle of a run.
- **The selector builder.** `mutextarget_selector` (`roles/mutextarget/vars/main.yml:24-40`) is a copy of
  `mutexrunconfig_selector` (`vars/main.yml:100-116`). The supported operators are listed only in
  `roles/mutextarget/vars/main.yml:15-19`.
- **Pool assignment.** `roles/mutextarget/tasks/02-gather-nodes.yml:89-96` imitates MCO's pool choice for
  `status.nodes`. It differs from MCO for a node that matches `master` and a custom pool, and for a node that matches
  two custom pools (see the MCO table and `roles/mutextarget/README.md`).
- **The Job namespace default.** A rule without `jobNamespace` uses its own namespace, both in
  `roles/mutexrule/vars/main.yml:12` (the dry run) and in `07:30` (the real Job).
- **The helpers.** The timestamp helper (`mutexrule_now`, `mutextarget_now`, `mutexrunconfig_now`) and the rescue
  message helper (`*_failed_msg`) are copied into each role's `vars/main.yml`. The `mutexrunconfig` role also compares
  its annotation times as strings (`vars/main.yml:60-69`), so its time format must not change.
- **Status contracts.** The `mutexrunconfig` role uses only MutexRules with `ValidConfig=True` (`01:71-98`) and only
  MutexTargets with `ValidConfig=True`, `NodeListGathered=True` and a non-empty `status.nodes` (`01:110-151`).

## Residual risks

The known risks of a run, with what triggers them and what mitigates them, are in the
[Safety model](USAGE.md#safety-model) of the user guide. Code changes that would close some of them are listed in
[docs/HANDOFF.md](HANDOFF.md).
