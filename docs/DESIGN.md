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

1. A MutexRunConfig outside the operator namespace (`POD_NAMESPACE`) gets `Reconciled=False` (`NamespaceNotAllowed`),
   and the play ends (`main.yml:37-64`). A finalizer run (`state` `absent`) ends there too, without the report and
   without any cleanup (`main.yml:55-64`). Without `POD_NAMESPACE`, as with `make run`, every namespace is allowed.
2. `main.yml` decides the mode. The reconcile is a finalizer run when `state` is `absent` or the MutexRunConfig has a
   `deletionTimestamp` (`main.yml:66-70`).
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
| namespace check | always (`main.yml:37-64`) | `POD_NAMESPACE` (`main.yml:39`) | status | `Reconciled=False` `NamespaceNotAllowed` (`main.yml:41-58`) | ends the play |
| `00-resolve-references.yml` | always (`main.yml:90-91`) | the spec only | nothing | none | none; builds the label keys and release expressions (`00:14-49`) |
| finalizer | being deleted (`main.yml:93-125`) | MutexTargets (`main.yml:96-105`) | through `08` | none | ends the play |
| `01-validate.yml` | not finalizing (`main.yml:127-128`) | MutexRules (`01:72`), MutexTargets (`01:111`), the canary and target pools (`01:154`, `01:185`), Nodes (`01:269-411`), all pools (`01:414`), APIServices (`01:566`) | status only | `ConfigValidated` `FetchSucceeded` or `ValidationFailed` (`01:515-556`); `ClusterStateValidated` `APIServicesUp` or `APIServicesDown`, and `ConfigValidated=False` `ClusterStateInvalid` (`01:596-638`) | `ConfigValidated` (`01:531-539`, `01:614-617`), `ClusterStateValidated` (`01:609-617`) |
| `02-check-for-upgrade.yml` | `ConfigValidated` (`main.yml:130-133`) | ClusterVersion `version` (`02:28-33`), Nodes (`02:51-55`) | status only | `NodeVersionsKnown` `VersionLabelMissing` or `VersionsKnown`, `UpgradeAvailable`, `UpgradeReady`, `UpgradeChecked` `CheckSucceeded` or `CheckFailed` (`02:114-224`) | `UpgradabilityChecked`, `UpgradeAvailable`, `UpgradeReady` (`02:149-152`, `02:201-210`) |
| `03-pause-machine-config-pools.yml` | also `UpgradabilityChecked` and `UpgradeAvailable` (`main.yml:137-142`) | the target pools read by `01` | `spec.paused: true` and `paused-by` (`03:9-25`) | `TargetPoolsPaused=False` `NotPaused`, only on failure (`03:37-50`) | `TargetPoolsPaused` (`03:27-34`) |
| `04-apply-mutex-rules-as-labels.yml` | also `TargetPoolsPaused` (`main.yml:144-150`) | the Nodes read by `02`, the canary read by `01` | node mutex labels, `labelled-by`, the release label; canary `release-labelled-at`, `modified-by`, `original-match-expressions` and the hold selector (`04:135-207`) | `MutexRulesApplied` `ApplySucceeded` or `ApplyFailed` (`04:209-248`) | `MutexRulesApplied` (`04:226-233`) |
| `05-modify-machineconfigpool.yml` | also `MutexRulesApplied` (`main.yml:152-159`) | the canary and target pools read by `01` | pool `matchExpressions`, `original-match-expressions`, `modified-by`; removes `release-labelled-at` (`05:115-178`) | `MCPUpdated` `CanaryMembersLabelled`, `UpdateSucceeded` or `UpdateFailed` (`05:86-113`, `05:179-216`) | `MCPUpdated` (`05:194-202`) |
| `06-execute-jobs.yml` | `JobRun`, set when `UpgradeReady` and `MCPUpdated` also hold (`main.yml:161-187`) | the MutexRunConfig again (`06:41-48`), Nodes (`06:74-145`, `06:283-292`) | node patches: leftover labels, release, release mark cleared (`06:196-208`, `06:263-278`, `06:318-328`); Jobs through `07` | `JobRun` `JobRunSucceeded` or `JobRunFailed`; `NodeUpgrade` `NodeAlreadyUpgraded`, `NodeUpgradeSucceeded` or `NodeUpgradeFailed` (`06:210-224`, `06:238-252`, `06:329-396`) | `JobRun=false` on a failure or a delete (`06:50-60`, `06:361-364`) |
| `07-run-job.yml` | for each rule and phase, from `06` (`06:229-236`, `06:306-313`) | Jobs with the `job-key` label (`07:83-99`, `07:127-137`) | creates a Job (`07:101-120`) | none (`06` reports) | none; fails the task (`07:139-148`) |
| `08-restore.yml` | `ConfigValidated`, `UpgradabilityChecked` and (`JobRun` or not `UpgradeAvailable`) (`main.yml:195-205`); the finalizer (`main.yml:111-121`) | all pools and Nodes (`08:71-83`) | pool selectors and annotations, `restored-at`, node labels and annotations, unpause (`08:163-293`) | from `main.yml`: `MCPUpdated=False` `SelectorsRestored`, `UpgradeAvailable` and `UpgradeReady` `False` `UpgradeFinished` (`main.yml:207-239`) | none; a failure sets `mutexrunconfig_failure` (`main.yml:241-244`) |
| `09-report.yml` | every reconcile that was not stopped by the namespace check or the finalizer (`main.yml:246-247`) | all pools (`09:17-21`) | status only | `TargetPoolsPaused` `Paused` or `NotPaused`; `Degraded` `PoolsLeftPaused`, `RunInProgress` or `NoPoolsPaused` (`09:50-111`) | none |

The gate fact `UpgradabilityChecked` reports as the condition `UpgradeChecked` (`main.yml:76`, `02:195`). Every other
gate fact has the name of its condition. `TargetPoolsPaused=True` is written only by `09`, at the end of the
reconcile, so it lags while `06` runs.

## Invariants

These are the promises the code keeps. A change that breaks one of them needs a design decision, not only a review.

1. **Only the operator namespace.** Each role acts only on CRs in `POD_NAMESPACE` (`main.yml:37-64`,
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
   for first (`06:110-136`). Before a node is taken down, the reconcile fails, reported as `NodeUpgradeFailed`, if MCO
   has started on another target node (`06:139-166`, `06:382-396`).
7. **A released node finishes first.** Nodes with this MutexRunConfig's `released-by` go first in the loop
   (`main.yml:179-182`) and resume at the wait, so their cleanup Jobs run before another node starts (`06:20-26`).
8. **The node wait needs more than the version label.** A node counts as upgraded only when its version label is the
   desired version, MCO reports `Done` with `currentConfig` equal to `desiredConfig`, that config is a rendered config
   of the canary, and the node is `Ready` (`vars/main.yml:149-192`).
9. **Jobs are never deleted.** No task in `roles/` deletes a Job (`git grep -n 'state: absent' roles/` finds none). A
   Failed Job is kept, and the next attempt creates a new one (`07:92-120`).
10. **Two MutexRunConfigs never share a pool.** `01` refuses a canary or target pool whose `paused-by` or `modified-by`
    names another MutexRunConfig (`01:199-224`).
11. **Status is merged, never replaced.** `manageStatus: false` (`watches.yaml:10`, `watches.yaml:18`,
    `watches.yaml:33`) leaves the status to the roles, which write conditions by type with
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
| finalizer `nodeupgrade.redhat-na-ssa.github.io/finalizer` | MutexRunConfig | | ansible-operator (`watches.yaml:35-38`) | ansible-operator, after the finalizer run | ansible-operator |
| `status.nodes` | MutexTarget | sorted node names | `roles/mutextarget/tasks/02-gather-nodes.yml:98-112` | replaced on each reconcile | `01:110-151` |

The job-key leaves out the JobSpec (`07:31-33`). A Complete Job is therefore re-used after the MutexRule is edited.

## State machines

The roles keep no state of their own between reconciles. Every reconcile starts at the top of `main.yml`, reads the
cluster again and works out from the labels, annotations, pool selectors and `spec.paused` where the run stands (the
table above lists them). So each state below is a state of the cluster. A reconcile cut short by an operator crash, a
restart or an API outage leaves the cluster in one of these states, or between two of them: each patch changes one
object as a whole, so "between" means that some objects are patched and others are not yet. The next reconcile
patches only what still differs.

In this section `v` is the value of the release label, the SHA-1 of the MutexRunConfig's `<namespace>/<name>`
(`vars/main.yml:30-31`). The release label is `mutexrule.nodeupgrade.redhat-na-ssa.github.io/release`, a mutex label
is `mutexrule.nodeupgrade.redhat-na-ssa.github.io/<rule>.<namespace>`, and the annotations named without a prefix have
the prefix `nodeupgrade.redhat-na-ssa.github.io/` (`vars/main.yml:54-58`, `vars/main.yml:83-84`). "300 s" is
`mutexrunconfig_label_settle_seconds` (`defaults/main.yml:29`, see [The settle time](#the-settle-time)).

Three rules hold in every state:

- A failed task fails the reconcile, also when a rescue handles it and reports it in a condition. ansible-operator
  v1.42.3, the base image (`Dockerfile:3`), leaves out a failed task only when it has `ignore_errors` or
  `event.Rescued()` is true ([`internal/ansible/controller/reconcile.go`][reconcile-go]). `Rescued()` reads a
  `rescued` key of the event data ([`internal/ansible/runner/eventapi/types.go`][eventapi-go]), and ansible-runner
  2.4.3, the version in the base image, writes that key only into the `playbook_on_stats` event, not into
  `runner_on_failed` ([`awx_display.py`][awx-display]). So ansible-operator returns an error for such a reconcile,
  controller-runtime retries it with its backoff ([Retries](USAGE.md#retries)), and the finalizer is removed only
  after a finalizer run without a failed task.
- Not every task has a rescue. The read of the MutexRunConfig before each node (`06:41-48`), the pool list of `09`
  (`09:17-21`) and the status write inside each rescue (for example `01:541-552`, `06:366-396`) end the play when the
  API does not answer. Then nothing more is patched, `09` does not run, `TargetPoolsPaused` and `Degraded` keep the
  values of an earlier reconcile, and the retry follows the backoff.
- One MutexRunConfig reconcile runs at a time (`config/manager/manager.yaml:74`), so the states of two
  MutexRunConfigs never change at the same moment. A reconcile of one MutexRunConfig, also its finalizer run, waits
  while another one's reconcile runs, which can take hours of node waits.

[reconcile-go]: https://github.com/operator-framework/ansible-operator-plugins/blob/v1.42.3/internal/ansible/controller/reconcile.go
[eventapi-go]: https://github.com/operator-framework/ansible-operator-plugins/blob/v1.42.3/internal/ansible/runner/eventapi/types.go
[awx-display]: https://github.com/ansible/ansible-runner/blob/2.4.3/src/ansible_runner/display_callback/callback/awx_display.py

### The run

This is the run as the `mutexrunconfig` role drives it. The same run from a user's point of view, with the `oc get`
columns of each state, is in [Watching a run](USAGE.md#watching-a-run) (`diagrams/run-states.svg`).

![The phases of a MutexRunConfig run as the mutexrunconfig role drives them, from the first reconcile through the run and the restore back to the states between runs, or to the finalizer, with the task file and the trigger on each transition, including where a failure keeps the pools paused and where nothing is protected.](diagrams/state-run.svg)

In words:

1. A MutexRunConfig outside `POD_NAMESPACE` is Ignored on every reconcile. A delete of it removes the finalizer
   without any cleanup, because the finalizer run ends at the same namespace check (`main.yml:55-64`).
2. In the namespace, No run and Restored, sweep pending are the states between runs: `01` and `02` pass, `02` finds
   no target node behind and none with this MutexRunConfig's `released-by`, and `main.yml` runs `08` on every
   reconcile (`main.yml:195-205`). From either of them a failure in `01` or `02`, or one in `03` before it paused a
   pool, leads to Not protecting. A retry once the cause is fixed leads back.
3. When `02` finds a target node behind, `main.yml` runs `03` and `04` (Holding) and then `05`. `05` defers the
   re-point when `04` stamped the canary (Settling) and re-points at once otherwise (Re-pointed, armed). From
   Settling, `05` re-points at the first reconcile 300 s or more after the last stamp. Another release label change
   before that stamps again, and the 300 s start over.
4. When `02` reads `status.history[0]` `Completed` for the desired version, `main.yml` sets `JobRun`, and `06`
   processes the target nodes one at a time.
5. A failure in any step of the run, while a pool is paused or changed by this MutexRunConfig, leads to Failed,
   holding. A retry re-enters the run where the labels and annotations show that it stopped.
6. After the last node `08` restores the pools (Restoring). So does any reconcile of the run, a retry included, at
   which `02` finds no node behind and none released, for example after a MutexTarget edit (`main.yml:195-199`). A
   failure there while a pool is still paused or changed leads to Failed, holding, and the retry runs `08` again. If
   a node still carries the release label (one of the canary's own), the run is Restored, sweep pending until a
   reconcile 300 s or more after `restored-at` removes it. Otherwise it is back in No run. A new upgrade before the
   sweep starts a run from Restored, sweep pending as it would from No run.
7. A delete leads to Finalizing from any state in the operator namespace. A reconcile in progress first finishes its
   current node. The finalizer goes once a finalizer run has no failed task; until then the finalizer run is
   repeated.

| State | What you see on the cluster | Entered by | Left by | After a crash or an API cut |
| --- | --- | --- | --- | --- |
| Ignored | `Reconciled=False` `NamespaceNotAllowed` (`main.yml:41-58`), nothing else | the namespace check and `end_play` (`main.yml:37-64`), on every reconcile | nothing while the CR exists: it has to be created in the operator namespace. A delete: the finalizer run ends at `main.yml:60-64` as well, without the report (`main.yml:58`) and without any cleanup, and since no task failed, ansible-operator removes the finalizer ([reconcile.go][reconcile-go]) | nothing to resume: no task writes to the cluster before the check |
| No run | `ConfigValidated=True` `FetchSucceeded` (`01:515-529`), `UpgradeAvailable=False` `UpgradeUnavailable` (`02:166-176`), `Degraded=False` `NoPoolsPaused` (`09:56-60`); no pool or node carries a mark of this MutexRunConfig | the first reconcile; Restoring or the sweep; a retry from Not protecting | `02` counts a target node behind or one with this MutexRunConfig's `released-by` (`02:139-152`), and `main.yml:137-150` runs `03` and `04`; a failure of `01`, `02` or `03`: Not protecting | `main.yml:195-205` runs `08` on every reconcile here (`UpgradeAvailable` is false), and `08` finds what a cut restore left by its annotations (`08:94-143`), so it cleans up |
| Not protecting (fail-open) | `ConfigValidated=False` `ValidationFailed` (`01:541-552`), or `ClusterStateValidated=False` `APIServicesDown` with `ConfigValidated=False` `ClusterStateInvalid` (`01:620-638`), or `UpgradeChecked=False` `CheckFailed` (`02:213-224`), with `NodeVersionsKnown=False` `VersionLabelMissing` when a version label is missing (`02:114-137`); `Degraded=False` `NoPoolsPaused` with "Last error" (`09:91-93`). After a failure of `03`, `TargetPoolsPaused=False` `NotPaused` says "No MachineConfigPool is paused by this MutexRunConfig.", because `09` writes it again from the pools in the same reconcile (`09:62-79`): the error of `03` is only in the message of `Degraded` | between runs, a rescue in `01` (`01:535-539`, `01:613-618`) or `02` (`02:205-211`) while no pool is paused or changed by this MutexRunConfig; a rescue in `03` before it paused any pool (`03:9-25`, `03:31-50`), such as a failure on the first pool of a new run. From Restored, sweep pending the canary's own nodes keep the release label until `08` runs again | a retry once the cause is fixed: back between runs, or into the run when a node is behind | The steps after the one that failed, and `08`, are skipped (`main.yml:137-205`), so only the status is written. MCO upgrades the unpaused pools WITHOUT Jobs meanwhile. An API cut leads here only when the API server answers the rescue's status write, for example while an APIService is not Available: the check reads 4 times (1 + 3 retries), 10 s apart (`01:565-594`, `defaults/main.yml:19-20`). When the API server does not answer, the rescue's own status write fails too, and nothing is written (the second rule above) |
| Holding | target pools `spec.paused: true` and `paused-by: <namespace>/<name>` (`03:9-25`); each node behind has its mutex labels (empty values) and `labelled-by` and no release label (`04:135-145`, `04:170-172`); the holders, nodes with this run's `released-by` and the canary's own nodes, have `release: v` (`04:174-183`); `MutexRulesApplied=True` `ApplySucceeded` (`04:209-224`) | `03` and `04`, which `main.yml:137-150` runs once `02` set `UpgradeAvailable` (`02:149-152`), from No run or from Restored, sweep pending | `05` in the same reconcile (`main.yml:152-159`), to Settling or Re-pointed; a reconcile does not end here, because a failure of `04` or `05` is Failed, holding | `03` skips a pool that is paused already (`03:25`), `04` skips a node that has its labels and `labelled-by` (`04:51-64`), and `01` accepts pools whose `paused-by` or `modified-by` name this MutexRunConfig (`01:199-224`). The release label changes that canary membership depends on come only after the canary is stamped, so a cut before the stamp leaves no change a selector depends on (`04:28-37`) |
| Settling | canary `matchExpressions`: its original ones plus `<mutex label> DoesNotExist` per rule (`00:32`, `04:165-167`), annotations `original-match-expressions`, `modified-by` and `release-labelled-at: <YYYY-MM-DDTHH:MM:SSZ>` (`04:152-168`, `04:196-207`); target pools paused, on their own selectors; `MCPUpdated=False` `CanaryMembersLabelled` (`05:86-103`); `Degraded=False` `RunInProgress` (`09:56-60`) | `04` stamps the canary when a canary node gets `release: v` or a node loses it while the canary is not re-pointed (`04:99-133`), and `05` defers (`05:69-76`) | `05` at the first reconcile at which the stamp is 300 s or more old and that did not write it (`05:71-76`), normally the next one, 10 minutes later (`watches.yaml:32`). Before that, another release label change, such as a node that joins or leaves the canary's own nodes (`04:72-106`), stamps again (`04:126-133`, `04:148-168`, `04:196-207`), and the 300 s count from the new stamp. A reconcile at which `02` finds no node behind and none released: Restoring (`main.yml:195-199`) | The stamp is in the cluster, so a restart waits for the same time; a value that is not a time or is later than now is written again (`04:126-133`). The hold selector selects the canary's own nodes and none of the held nodes in any MCO view, whatever their release label (`04:21-25`): that is what protects against MCO's stale view after an API cut |
| Re-pointed, armed | canary `matchExpressions`: the kept expressions (`01:351-376`) plus `release In (v)`, without `release-labelled-at` (`05:144-169`); target pools: their own expressions plus `release NotIn (v)`, annotations `original-match-expressions` and `modified-by`, still paused (`05:118-142`, `05:170-177`); `MCPUpdated=True` `UpdateSucceeded` (`05:179-192`); `UpgradeReady=False` `UpgradeNotReady` while the control plane upgrades (`02:177-186`) | `05:115-196`, the canary first (`05:14-19`) | `02` reads `status.history[0]` `Completed` for the desired version (`02:145-152`), and `main.yml:161-170` sets `JobRun`; a reconcile at which `02` finds no node behind and none released: Restoring (`main.yml:195-199`) | `05` runs on every reconcile and patches only a pool whose selector or annotations differ (`05:138-142`, `05:161-168`); that also writes the `worker` selector again after MCO reset it (see [The pools](#the-pools)). A cut between the canary and the target pools leaves a released node matching both, which MCO refuses for a custom pool and resolves for the canary over `worker` (`05:14-19`) |
| Processing node i of n | the node's labels as in [A target node](#a-target-node); `JobRun` and `NodeUpgrade` with "Node is i of n" after each node (`06:238-252`, `06:345-358`); `TargetPoolsPaused` and `Degraded` only at the end of the reconcile (`09:62-111`) | `main.yml:177-187`: the `06` loop takes the nodes with this run's `released-by` first, then the nodes MCO is updating, then the rest (`main.yml:179-182`) | the next node in the same reconcile; after the last one, with `JobRun` still true, `08` (`main.yml:195-205`); a delete seen before the next node ends the loop (`06:41-60`); a failure: Failed, holding | A restart enters from the top: `02` lists the released node (`02:77-80`), `06` takes it first and resumes at the wait (`06:95-96`, `06:231`), and `07` re-uses a Job with the same `job-key` that has not failed (`07:83-99`). A retry at which no node is behind any more and none is released goes to Restoring (`main.yml:195-199`). An API cut during the node wait only delays it: a failed read counts as not upgraded (`vars/main.yml:185-186`) and the poll goes on (`06:283-292`). A failed read of a Job ends its wait as `Missing` and fails the node (`07:127-148`); the retry waits for the same Job. An API error on the read of the MutexRunConfig before a node (`06:41-48`) ends the reconcile there, between two nodes, without a condition (the second rule above) |
| Failed, holding (fail-closed) | `Degraded=True` `PoolsLeftPaused` with the error (`09:56-60`, `09:99-109`), and the failed step's condition: `MutexRulesApplied=False` `ApplyFailed` (`04:230-248`), `MCPUpdated=False` `UpdateFailed` (`05:198-216`), `JobRun=False` `JobRunFailed` or `NodeUpgrade=False` `NodeUpgradeFailed` (`06:360-396`), or a failure of `01` or `02` while pools are held. A failure of `03` shows only in the message of `Degraded`: `09` writes `TargetPoolsPaused` again from the pools in the same reconcile (`09:62-79`). The pools stay paused and changed | a rescue sets its gate to false and `mutexrunconfig_failure` (`main.yml:21-24`) while a pool is paused with this MutexRunConfig's `paused-by` or carries its `modified-by` (`09:29-60`); the later steps are skipped (`main.yml:137-187`), and so is `08`, because `JobRun` is false while `UpgradeAvailable` is true, or `ConfigValidated` or `UpgradabilityChecked` is false (`main.yml:195-199`) | a retry once the cause is fixed, into the run where it stopped; a retry at which `02` finds no node behind and none released, as after a failure of `08`: Restoring (`main.yml:195-199`) | The retry is a reconcile like any other and finds the state in the cluster. Nothing is unpaused meanwhile ([Invariants](#invariants) 3). A delete runs the finalizer at the next reconcile, once no other MutexRunConfig's reconcile is running (`config/manager/manager.yaml:74`); no node is in progress then ([Abort a run](USAGE.md#abort-a-run)) |
| Restoring | target pools on their saved `matchExpressions`, without `original-match-expressions` and `modified-by` (`08:163-190`), then the canary, last (`08:98-103`, `08:188`), with `restored-at: <time> <namespace>/<name>` when a node carries `release: v` (`08:149-161`, `08:176-177`); nodes without mutex labels, `labelled-by` and `released-by` but with their release label (`08:196-243`); pools with this `paused-by` unpaused (`08:280-293`); `MCPUpdated=False` `SelectorsRestored` when the pass restored a selector (`main.yml:207-220`); `UpgradeAvailable=False` and `UpgradeReady=False` `UpgradeFinished` only when `JobRun` is true, after the last node (`main.yml:222-239`), and otherwise the `UpgradeAvailable=False` `UpgradeUnavailable` of `02` (`02:166-176`) | `main.yml:195-205` after the last node, while `JobRun` is true; or any reconcile at which `02` finds no target node behind and none with this run's `released-by`, so that `UpgradeAvailable` is false and `03` to `06` are skipped (`main.yml:137-199`), for example after a MutexTarget edit or once the version labels caught up | the same reconcile: the sweep when the canary got `restored-at`, else No run. A failed task while a pool is still paused or changed: Failed, holding (`main.yml:241-244`). A failed task after the last unpause, such as a status write (`main.yml:207-239`), shows `Degraded=False` `NoPoolsPaused` with "Last error" (`09:56-60`, `09:91-93`); no node is behind then, so nothing is left unprotected, and the next reconcile is between runs | Each pool and each node is one patch, and `restored-at` is in the canary's restore patch. After a cut no node is behind, so `UpgradeAvailable` is false and `main.yml:195-199` runs `08` again, which finds the rest by their annotations (`08:94-143`). The canary's own nodes keep the release label in this pass, so an MCO view that still has the run-time canary keeps them in it (`08:53-55`) |
| Restored, sweep pending | the canary on its own selector with `restored-at`; the canary's own nodes keep `release: v`, which no pool selects on any more (`08:53-55`) | `08` restored the canary while a node carried `release: v` (`08:155-161`) | `08` at a reconcile at which `restored-at` is 300 s or more old and no selector was restored in that pass (`08:111-115`, `08:149-154`): it removes the label (`08:217-219`, `08:231-243`) and then `restored-at` (`08:266-278`); normally the reconcile 10 minutes after the run (`main.yml:189-194`). A new upgrade before that: `02` sets `UpgradeAvailable` (`02:139-152`), so `08` does not run (`main.yml:195-199`) and the run starts at Holding. The canary's own nodes already carry `release: v`, so `04` stamps only when another release label changes (`04:74-81`, `04:126-133`), `05` re-points without removing `restored-at` (`05:153-157`), and the old `restored-at` stays until the next restore writes it again (`08:176-177`). A failure of `01`, `02` or `03`: Not protecting, and the labels stay. A delete: Finalizing, which removes the labels at once (`08:151-154`) and then `restored-at` (`08:266-278`) | `restored-at` is in the cluster; a value without a time, not a time, or later than now is written again (`08:106-110`, `08:249-264`). An earlier reconcile, such as one a Job event triggers, keeps the label (`08:48-52`) |
| Finalizing | `metadata.deletionTimestamp` and the finalizer `nodeupgrade.redhat-na-ssa.github.io/finalizer` (`watches.yaml:35-38`). `09` does not run in the finalizer, so `Degraded` keeps the value of the reconcile before it: when `06` saw the delete, `Degraded=True` `PoolsLeftPaused` with "The MutexRunConfig is being deleted, so ... Still held: ..." (`06:50-60`, `09:56-60`, `09:97-98`) | a delete: `main.yml:66-70` sets `mutexrunconfig_finalizing`. A reconcile in progress finishes its current node and skips the rest (`06:37-60`). When the delete came during a reconcile, ansible-operator asks for a requeue 5 s later if that reconcile had no failed task, and otherwise returns an error, so the backoff applies ([reconcile.go][reconcile-go]) | `main.yml:90-125`: `00`, the MutexTargets still present, and `08` in a single pass, which restores the selectors, removes every mark of this MutexRunConfig and its release label at once (`08:151-154`), writes no `restored-at` (`08:161`, `08:264`) and unpauses; then ansible-operator removes the finalizer | The finalizer stays until a finalizer run has no failed task, so a cut or a failed task leads to another finalizer run (`main.yml:68-70`), which finds the rest by the annotations. The single pass can let an MCO view that lags the canary's restore move one of the canary's own nodes through `worker` once (`08:56-60`) |

Notes:

- Holding is a step inside one reconcile: `03`, `04` and `05` run back to back, and a failure in `04` or `05` is
  Failed, holding, because `03` has paused the pools.
- Whether a failure is fail-open or fail-closed is decided by `09` from the pools, not by the step that failed
  (`09:56-60`): `PoolsLeftPaused` needs a pool that is paused with this MutexRunConfig's `paused-by` or carries its
  `modified-by`. A validation failure while the pools are held keeps them paused: `Degraded=True` `PoolsLeftPaused`.
  A failure of `03` before it paused a pool, and one after `08` unpaused the last pool, give `NoPoolsPaused`.
- The states between runs include a cleanup pass of `08` on every reconcile (`main.yml:189-205`). That pass is also
  what ends a run cut short during Restoring, and what restores a run in which no node is behind any more.

### A target node

![The states of a target node during a run, from behind to held, through its pre-upgrade Jobs, released into the canary, upgraded there, through its cleanup Jobs and back into its paused pool, plus the side paths for a node MCO was already updating, a failed Job, a timed-out wait and the finalizer, and the states of a node the canary had before the run.](diagrams/state-node.svg)

In words:

1. A target node is Not behind while its version label is at or above the desired version. When
   `status.desired.version` passes it, it is Behind.
2. From Behind, `03` pauses its pool and `04` holds it: a mutex label per rule and `labelled-by`. If MCO had started to
   update it before the pause, `06` first waits for that update (MCO already updating it). If the node's version
   label already showed the desired version when `06` read it, before the wait, the node gets no Jobs. A node that
   was updating to a canary config has no mutex label, so it gets no pre-upgrade Jobs either: `06` releases it right
   after the wait and runs only its cleanup Jobs. Otherwise its Jobs run after that update.
3. A held node waits for its turn in the `06` loop, then its pre-upgrade Jobs run one at a time, and all its mutex
   labels stay until the release. A Job that fails or runs past `timeoutSeconds` stops the run, and the node stays
   held. So does an update MCO started on another target node before the Jobs (`NodeUpgradeFailed`).
4. One patch releases it: the release label and `released-by` replace the mutex labels and `labelled-by`. MCO moves it
   into the canary and updates it. The `06` wait ends when it is Done on a canary config, then its cleanup Jobs run,
   or none when no rule has a `cleanUpJobSpec`. A wait that runs out after about 2 hours, or a failed cleanup Job,
   stops the run; the node stays released, and the retry resumes at the wait.
5. One patch removes the release label and `released-by`, so the node is back in its paused pool. When `08` unpauses
   the pools at the end, MCO gives it its own pool's config.
6. After a delete the finalizer removes the marks from every node still held, and from a released node when the run
   was stopped. MCO then upgrades it without its Jobs.
7. A node of the canary's own gets the release label at the start of the run, or during the run when it joins the
   canary, and loses it when it no longer matches the canary. It keeps the label after the canary's restore and
   loses it 300 s or more after `restored-at`, or at once in the finalizer. A new run before that keeps it labelled.

| State | What you see on the cluster | Entered by | Left by | After a crash or an API cut |
| --- | --- | --- | --- | --- |
| Not behind | `machineconfiguration.openshift.io/release-image-version` at or above `status.desired.version` (`02:139-144`); no mark of this MutexRunConfig | the start; a node whose turn is over | `02` reads its label below the desired version: normally within one reconcile period after `oc adm upgrade` (`watches.yaml:32`), later while another MutexRunConfig's reconcile runs (`config/manager/manager.yaml:74`) or a failed reconcile waits for its backoff ([Retries](USAGE.md#retries)) | nothing to resume. In the `06` loop it is skipped with `NodeUpgrade=True` `NodeAlreadyUpgraded`, and a leftover mutex label or `labelled-by` of this run is removed (`06:189-224`) |
| Behind | the version label below `status.desired.version` (`02:139-147`); `UpgradeAvailable=True` (`02:149-152`) | ClusterVersion `status.desired.version` changes (`02:40-43`) | `04` labels it once `03` paused the pools, in the same reconcile (`main.yml:137-150`) | nothing is written for it before `04` |
| MCO already updating it | `machineconfiguration.openshift.io/desiredConfig` differs from `currentConfig`, and no `released-by` of this run (`02:81-83`, `06:120-123`). A node updating to a canary config is not labelled (`02:73-76`, `04:46-48`); one updating in its own pool is held like any node behind | MCO started the update before `03` paused the pool | `06` takes it after the released nodes (`main.yml:179-182`) and waits for MCO: `Done`, `currentConfig` equal to `desiredConfig`, `Ready` (`06:110-133`, `vars/main.yml:184-192`), for at most 121 reads 60 s apart, about 2 hours. Then it goes on with the node as it read it before the wait (`06:106-109`): if the version label already showed the desired version, the node is skipped as Not behind, WITHOUT Jobs (`06:189-224`); otherwise its Jobs run, after MCO's update. A node that was updating to a canary config has no mutex label, so no pre-upgrade Job runs and the release patch comes right after the wait (`06:94`, `06:229-236`, `06:263-278`); only its cleanup Jobs run. A wait that runs out fails the run with `NodeUpgrade=False` `NodeUpgradeFailed` (`06:125-133`, `06:382-396`), and the node stays in flight | A restart finds it in flight again (`02:81-83`). Before it takes down a node, `06` fails the reconcile when MCO has started on another target node since `02` read them (`06:139-166`). The node step is still `wait` then (`06:102-104`, `06:168-170`), so the rescue reports `NodeUpgrade=False` `NodeUpgradeFailed` (`06:382-396`), and `09` reports `Degraded=True` `PoolsLeftPaused`: Failed, holding. The next reconcile waits for that node first |
| Held, waiting for its turn | labels `mutexrule.nodeupgrade.redhat-na-ssa.github.io/<rule>.<namespace>: ""` per rule and annotation `labelled-by: <namespace>/<name>`, no release label (`04:135-145`, `04:170-172`); in its paused target pool, which selects it before and after the re-point, because `release NotIn (v)` matches a node without the label | `04` (`main.yml:144-150`); a failed pre-upgrade Job (`06:360-380`) | its turn in the `06` loop (`main.yml:177-187`). When MCO has started on another target node by then, `06` fails the reconcile before the Jobs (`06:139-166`), reported as `NodeUpgrade=False` `NodeUpgradeFailed` (`06:382-396`), and the node stays held; the finalizer | the marks are in the cluster, and `04` does not patch a node that has them (`04:51-64`) |
| Pre-upgrade Jobs | the node as held; Jobs named `<jobName>-<suffix>` in `jobNamespace` with the label `job-key` and the annotations `mutexrunconfig`, `mutexrule`, `node`, `phase: pre` and `desired-version` (`07:101-120`), one at a time, for each rule in `spec.mutexRules` order whose mutex label the node carries (`06:94`, `06:229-236`). No task removes a mutex label when its Job completes: all of them stay until the release patch (`06:263-278`) | `06:226-236`, after the wait for MCO and the check that no other target node is updating (`06:110-166`) | every Job `Complete`: the release patch (`06:263-278`). A `Failed` Job, one still running after `timeoutSeconds`, or one that cannot be read fails the node (`07:139-148`): `JobRun=False` `JobRunFailed` (`06:366-380`), and the node stays held | A Job keeps running when the reconcile is cut. The retry goes through the same rules in the same order and finds each Job by its `job-key`: it waits for a running one and re-uses a `Complete` one, also for the rules already done; a `Failed` one is skipped and a new Job created (`07:83-120`) |
| Released | labels: no mutex label, `release: v`; annotations: no `labelled-by`, `released-by: <namespace>/<name>\|<desired version>` (`06:263-278`, `vars/main.yml:85`). It matches the run-time canary and no longer its target pool (`05:3-13`). Right after the patch it still looks `Done` on its old config (`vars/main.yml:156-157`) | `06:263-278`, one patch (`06:254-262`); for a node that was updating to a canary config, right after the wait for MCO, without pre-upgrade Jobs (`06:229-236`) | MCO sees it in the canary and changes its `desiredConfig` | `released-by` is the memory: `02` lists the node (`02:77-80`, `02:96-106`) and keeps `UpgradeAvailable` true (`02:149-152`), `04` neither labels it (`04:46-48`) nor takes its release label (`04:49`, `04:72-81`), and `06` takes it first (`main.yml:179-182`) and resumes at the wait, with no pre-upgrade Jobs (`06:231`) and no second release patch unless a mutex label or this run's `labelled-by` is left or the release label is not `v` (`06:273-277`) |
| Updating in the canary | `desiredConfig: rendered-<canary>-<hash>`, `currentConfig` the old config, `machineconfiguration.openshift.io/state` not `Done`; MCO cordons, drains, updates and reboots it | MCO | the wait passes (`06:283-292`, `vars/main.yml:175-192`). After 121 reads, 60 s apart (1 + 120 retries, about 2 hours, `defaults/main.yml:11-12`): `NodeUpgrade=False` `NodeUpgradeFailed` (`06:294-300`, `06:382-396`), and the node stays released, in the unpaused canary | as for Released. The wait counts a failed read as not upgraded (`vars/main.yml:185-186`), so an API cut shorter than the rest of the 2 hours only delays it |
| Done on the canary's config | the version label is the desired version, `state` is `Done`, `currentConfig` equals `desiredConfig` and matches `^rendered-<canary>-[^-]+$`, and `Ready` is `True` (`vars/main.yml:163`, `vars/main.yml:175-192`) | MCO finished | `06` starts the cleanup Jobs (`06:306-313`), or clears the release mark at once when no rule has a `cleanUpJobSpec` (`06:308`, `06:318-328`) | as for Released; the wait passes at once |
| Cleanup Jobs | Jobs named `cleanup-<jobName>-<suffix>` with `phase: cleanup` (`07:28-29`, `07:101-120`), for each rule with a `cleanUpJobSpec` (`01:100-105`, `06:308`); the node still released, in the unpaused canary | `06:306-313` | every Job `Complete`: `06:318-328`. A failure: `JobRun=False` `JobRunFailed`, and the node stays released | the retry resumes at the wait, which passes at once, and re-uses the `Complete` cleanup Jobs (`07:83-99`) |
| Back in its paused pool | no release label and no `released-by` (`06:318-328`); `NodeUpgrade=True` `NodeUpgradeSucceeded` "Node is i of n" (`06:345-358`); `currentConfig` stays `rendered-<canary>-*` while its pool is paused (`06:315-317`) | `06:318-328`, one patch | `08` restores and unpauses its pool (`08:163-190`, `08:280-293`) | no mark is left, so a later reconcile counts the node as upgraded (`06:189-224`) |
| On its own pool's config | MCO changes `desiredConfig` to `rendered-<pool>-*`. When both pools render the same MachineConfigs, MCD logs `SkipReboot` ([MCO behaviour seen in the live runs](../tests/Scenarios.md#mco-behaviour-seen-in-the-live-runs)); otherwise the node is updated again, without Jobs (HANDOFF [Known gaps](HANDOFF.md#known-gaps) G8) | MCO, after `08:280-293` | not left | nothing of this run is on the node |
| Unmarked by the finalizer | no mutex label, `labelled-by`, release label or `released-by` of this MutexRunConfig (`08:151-154`, `08:196-243`); its pool restored and unpaused (`08:163-190`, `08:280-293`) | the finalizer (`main.yml:93-125`), for a node still held, or released while the run was stopped | MCO upgrades it WITHOUT its pre-upgrade Jobs, or, when it was released, WITHOUT its cleanup Jobs ([Abort a run](USAGE.md#abort-a-run)) | A node released in the middle of its update moves to its paused pool once the selectors are restored, and its MCO daemon finishes the update there (`08:66-70`) |

A node of the canary's own, one the canary selects before the run that is not a target node:

| State | What you see on the cluster | Entered by | Left by | After a crash or an API cut |
| --- | --- | --- | --- | --- |
| Canary member | it matches the canary's `matchLabels` and original `matchExpressions`, and carries neither this run's `labelled-by` nor one of its mutex labels (`01:265-326`) | the start; the sweep | `04` gives it `release: v` (`04:174-183`) | `01` refuses the run while such a node carries another MutexRunConfig's release value (`01:280-303`) |
| Labelled for the run | `release: v`. While the canary is not re-pointed, `04` stamps the canary before the label (`04:152-168`) and again after it (`04:196-207`); a node that joins the canary's own nodes once the canary is re-pointed gets the label without a stamp (`04:126-133`, `05:45-46`) | `04`, at the start of a run, or during the run when the node joins the canary's own nodes (`04:72-81`, `04:174-183`); a new run before the sweep, from Kept after the restore | `08` restores the canary and keeps the label (`08:149-154`); `04` removes it when the node no longer matches the canary's own selector (`04:82-89`, `04:185-194`), with a stamp only while the canary is not re-pointed (`04:126-133`); the finalizer removes it at once (`08:151-154`) | The hold selector, the re-pointed canary and the restored canary all select it (`04:21-25`, `05:3-6`). A cut between the two stamps leaves the first one to wait for (`04:34-37`) |
| Kept after the restore | `release: v`; the canary on its own selector with `restored-at` (`08:176-177`) | the restore pass of `08` | `08`, 300 s or more after `restored-at` (`08:111-115`, `08:217-219`); the finalizer, at once (`08:151-154`, `08:217-219`); a new run before that, in which `04` finds the label in place: Labelled for the run (`04:72-81`) | as in the run's Restored, sweep pending |

### The pools

![The states of a target MachineConfigPool and of the canary pool during a run: the target pool is paused by the run or by someone else, re-pointed with release NotIn and restored, and unpaused only when the run paused it; the canary gets the hold selector and the release-labelled-at stamp when needed, is re-pointed with its kept expressions and release In, is restored with restored-at and is swept, unless a new run starts before the sweep.](diagrams/state-pools.svg)

In words:

1. `03` pauses a target pool and writes `paused-by`. `05` re-points it: its own expressions plus `release NotIn (v)`,
   with the original list saved. `08` restores and unpauses it. A pool that is paused but not yet re-pointed is only
   unpaused. A target pool that someone else paused is re-pointed and restored like the others but stays paused. MCO
   resets the selector of `worker`, and `05` writes it again.
2. The canary keeps its own selector, or gets the hold selector and the `release-labelled-at` stamp when the run
   changes a release label that canary membership depends on, and a stamp again on each further change. `05`
   re-points it to its kept expressions plus `release In (v)`, at once or 300 s or more after the last stamp. `08`
   restores it last, with `restored-at` while a node carries the release label, and a later `08` removes
   `restored-at`. A new run before that re-points the canary again and keeps the old `restored-at` until its own
   restore. The finalizer does all of it in one pass.

| Pool | State | What you see on the cluster | Entered by | Left by | After a crash or an API cut |
| --- | --- | --- | --- | --- | --- |
| target | Own selector, unpaused | its own `nodeSelector`, `spec.paused: false`, no `paused-by`, `modified-by` or `original-match-expressions` | the start; `08` | `03:9-25`, once a target node is behind (`main.yml:137-142`) | nothing to resume |
| target | Paused by someone else | `spec.paused: true` without `paused-by` | an administrator | `05` re-points it like any target pool (`05:170-177`), and `08` restores its selector (`08:124-128`), but neither `03` nor `08` unpauses it (`03:4-6`, `03:25`, `08:96-97`, `08:122-123`): it goes through Re-pointed and ends Restored, still paused | `09` reports it as paused by someone else (`09:34-38`) |
| target | Paused | `spec.paused: true`, `paused-by: <namespace>/<name>`, its own selector (`03:9-25`); `TargetPoolsPaused=True` `Paused`, written by `09` (`09:62-79`) | `03:9-25` | the re-point, `05:170-177` (`05:118-142` with an earlier build's canary selector); `08:280-293` alone when no node is behind any more or in the finalizer | Each pool is one merge patch. `03` pauses the pools a cut left unpaused and skips the others (`03:25`), and `01` accepts this `paused-by` (`01:199-224`) |
| target | Re-pointed | `matchExpressions`: its original ones plus `release NotIn (v)` (`00:23`, `05:132`); `original-match-expressions` (JSON) and `modified-by` (`05:126-129`); still paused. MCO resets the `nodeSelector` of `worker` to its own manifest within seconds ([What the operator assumes about MCO](#what-the-operator-assumes-about-mco)); whether it keeps the two annotations is not recorded (unknown) | `05`, from Paused or from Paused by someone else | `08:163-190`: the saved list back, both annotations removed; then `08:280-293` when this run paused it | `05` patches a pool again only when its selector or annotations differ (`05:138-142`), on every reconcile it runs, so it also undoes MCO's reset of `worker`. `01` reads the saved list, not the live one (`01:229-242`), and so does the MutexTarget role, so `status.nodes` stays the same (`roles/mutextarget/tasks/02-gather-nodes.yml:50-57`) |
| target | Restored and unpaused | its saved `matchExpressions`, or none when the saved list is empty (`08:179`); no annotation of this run; `spec.paused: false` | `08:163-190`, `08:280-293` | not left | A cut between the restore and the unpause leaves the pool paused with `paused-by`; the next pass of `08` unpauses it (`08:94-97`, `08:280-293`) |
| target | Restored, still paused | its saved `matchExpressions`; no annotation of this run; `spec.paused: true`; `TargetPoolsPaused=True` names it as paused by someone else while it is a target pool (`09:34-38`, `09:62-79`) | `08:163-190` for a pool that someone else paused | its administrator unpauses it | nothing to resume |
| canary | Own selector | its `matchLabels` and own `matchExpressions`, never paused (`01:165-182`); it may select nodes of its own | the start | `04:152-168` (the hold), or `05:144-169` at once when nothing was stamped (`05:69-76`) | nothing to resume |
| canary | Holding, stamped | `matchExpressions`: its original ones plus `<mutex label> DoesNotExist` per rule (`00:32`, `04:165-167`); `original-match-expressions`, `modified-by` and `release-labelled-at` (`04:152-168`, stamped again at `04:196-207`); `MCPUpdated=False` `CanaryMembersLabelled` (`05:86-103`) | `04:152-168`, from Own selector or, in a new run before the sweep, from Restored, restored-at | `05:144-169`, at the first reconcile 300 s or more after the last stamp (`05:69-76`). Another release label change before that stamps it again, and the 300 s start over (`04:126-133`, `04:196-207`). `08` restores it as from Re-pointed when no node is behind any more; the finalizer (`08:163-190`) | as in the run's Settling |
| canary | Re-pointed | `matchExpressions`: the kept expressions (`01:351-376`) plus `release In (v)` (`00:22`, `05:160`); `original-match-expressions`, which also takes expressions added to the live canary during the run (`01:244-255`), and `modified-by`; no `release-labelled-at` (`05:153-157`). It selects the released node and its own nodes | `05:144-169`, before the target pools (`05:14-19`), also from Restored, restored-at in a new run before the sweep | `08:163-190`, after every other pool (`08:98-103`, `08:129-132`): after the last node, when no node is behind any more, or in the finalizer | `04` sees it re-pointed and stamps nothing (`04:112-116`, `04:126-133`), and `05` patches it again only when it differs (`05:161-168`) |
| canary | Restored, restored-at | its own `matchExpressions`, the saved ones plus those added during the run (`08:181-187`); `restored-at: <time> <namespace>/<name>` (`08:176-177`); its own nodes keep `release: v` | the restore in `08`, when a node carries `release: v` (`08:155-161`) | `08:266-278`, once `restored-at` is 300 s or more old (`08:111-115`) and the labels are removed; the finalizer. A new run before that: `05` re-points it at once, or `04` holds and stamps it first when a release label changes (`04:126-133`), and `restored-at` stays until the next restore writes it again (`05:153-157`, `08:176-177`) | as in the run's Restored, sweep pending |
| canary | Swept | its own selector; no annotation of this run; no node with `release: v` | `08:217-219` and `08:266-278`; a restore while no node carried `release: v`; the finalizer | not left | nothing to resume |

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

The reconcile period is 10 minutes (`watches.yaml:32`), longer than the settle time. So normally the next reconcile
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

MCO decides which pool a node belongs to and when a node updates. The operator writes only the `matchExpressions` and
`spec.paused` of pools, its own labels and annotations on nodes and pools
([State kept in the cluster](#state-kept-in-the-cluster)), the Jobs of the MutexRules (`07:101-120`) and the status of
its own CRs. It does not edit a MachineConfig or MCO's annotations on a node, and it does not cordon or drain a node.
These are the MCO behaviours the code relies on.

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
| `05:58-79`, `05:118-142`, `05:170-178`; `04:108-124` | A canary that holds with the exclusion selector of the earlier design: `<mutex label> DoesNotExist` next to expressions that differ from its originals. The target pools are then re-pointed before the canary. | 0.2.x wrote such a canary selector, with the old prefix, in its `05-modify-machineconfigpool.yml`. So did the development builds before the release-label build (the build that selects the canary by a release label instead of excluding the mutex labels), also with the old prefix. | No build with the current prefix writes it. Removable now, unless kept as a guard. |
| `04:66-71`, `06:254-262` | A node with this run's `released-by` but without the release label. | Development builds from the build that added `released-by` up to the last build before the release-label build, with the old prefix. | Same. |
| `08:124-128` | A pool with `original-match-expressions` but without `modified-by`: restored when it is in the restore list or paused by this MutexRunConfig. | Development builds from the build that added `original-match-expressions` up to the last build before the one that added `modified-by` (together with `labelled-by` and `released-by`), with the old group. 0.2.x wrote neither annotation. | Same. |
| `08:196-210` (`unmarked`) | Mutex labels on a node without `labelled-by`: removed when the node is a target node, or from any node when no MutexTarget is left. | 0.2.x labelled nodes without any annotation, with the old prefix, in its `04-apply-mutex-rules-as-labels.yml`. Development builds before the one that added `labelled-by` did the same. | Same. |
| `08:133-141` | A `restored-at` that is only the owner, without a time, or empty on the canary: treated as just written. | unknown. No build writes that form: `restored-at` has carried a time since the settle-time build added it, together with `release-labelled-at`. It may only be a guard against a hand edit. | unknown |
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
