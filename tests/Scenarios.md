# Test scenarios

This is the operator's single test matrix: what CI and the molecule scenarios check, what ran live on OpenShift and on
which design, and what is still open. The other docs link here instead of repeating it.

## How it is tested

| Layer | What it checks | Where | When |
| --- | --- | --- | --- |
| Lint | `make lint` (yamllint, ansible-lint), `shellcheck hack/*.sh`, `make diagrams-check`, `make docs-lint` | [ci.yaml](../.github/workflows/ci.yaml), job `Lint` | every pull request and every push to `main` |
| Build and validate | `make document-check`, then `docker-build`, `image-smoke-test`, `bundle` with `bundle-validate`, `verify-manifests`, `bundle-build`, `catalog-validate`, `catalog-build` | [ci.yaml](../.github/workflows/ci.yaml), job `Build and validate` | every pull request and every push to `main` |
| Molecule `kind` | the operator image on a new kind cluster (one control-plane node, two workers) with fake MachineConfigPool and ClusterVersion APIs: the "kind" column below | [e2e.yaml](../.github/workflows/e2e.yaml), job `Molecule on kind`, 45-minute limit | pull requests that touch `roles/`, `watches.yaml`, `Dockerfile`, `requirements.yml`, `config/`, `molecule/`, `sample-manifests/` or the workflow; on demand |
| Molecule `default` | the checks that are safe on a real cluster, against whatever `KUBECONFIG` points at: the "default" column below | [molecule/](../molecule/README.md) | by hand |
| Offline harness | the real roles against a fake API server; CRD schema tests against Kubernetes 1.29 and 1.34 API servers; the operator image against a plain Kubernetes 1.29 API server with stub MachineConfigPool and ClusterVersion CRDs and the shipped RBAC | local tooling, **not in the repository** | run by hand during the refresh for the handoff; cannot be reproduced from the repository ([Known gaps](../docs/HANDOFF.md#known-gaps) G14) |
| Live runs | installs, rehearsals and three z-stream upgrades on one small OpenShift 4.21 cluster | by hand, see [Live runs](#live-runs) | 2026-10-28 and 2026-10-29 |

None of the automated layers has a Machine Config Operator (MCO). In the kind scenario the test plays its part (see
[How the kind scenario plays MCO](#how-the-kind-scenario-plays-mco)).

## Live runs

All live runs used one small OpenShift 4.21 cluster: one control-plane node that also runs workloads, and two workers.
The operator was installed through OLM from test builds made during the refresh for the handoff (below). Those builds
still had the old API group and were pushed to the old image registry. No live run used the new API group or an image
from `ghcr.io/redhat-na-ssa` (row S44).

| Run | Date | Build | Design | OpenShift | What it covered |
| --- | --- | --- | --- | --- | --- |
| Checks | 2026-10-28 | A | earlier | 4.21.20 | installs and install modes, the OLM upgrade from 0.2.68, scorecard, metrics, the custom-pool refusal, missing version labels; no upgrade |
| Rehearsals | 2026-10-28 | A; the last two with the node-wait fix of B | earlier | 4.21.20 | full runs without a real upgrade (below) |
| Upgrade 1 | 2026-10-28 | B | earlier | 4.21.20 → 4.21.21 | two target nodes |
| Upgrade 2 | 2026-10-29 | C | release-label | 4.21.21 → 4.21.22 | two target nodes; an admin MachineConfig applied and the operator pod deleted during the first node's update |
| Upgrade 3 | 2026-10-29 | D | release-label | 4.21.22 → 4.21.23 | one target node and one canary node of its own; an admin MachineConfig deleted and the operator pod deleted during the target node's update |

### The builds

Each build is the one before it plus the change in its row.

| Build | What it contained | Design |
| --- | --- | --- |
| A | The refreshed operator before the live runs, with the earlier canary design | earlier |
| B | The node-wait fix: a released node counts as upgraded only once its `currentConfig` is a rendered config of the canary, `rendered-<canary>-<hash>`, with the canary's name matched exactly (`roles/mutexrunconfig/vars/main.yml:160-163`) | earlier |
| C | The release-label build: the canary selects only the released node, by the release label. A canary with nodes of its own gets the hold selector while they get the release label, and the pools are re-pointed one reconcile later | release-label |
| D | The settle-time build: the pools are re-pointed only once `mutexrunconfig_label_settle_seconds` (300) have passed since the last release label change of the canary's own nodes (`release-labelled-at`), and those nodes lose the label only that long after the canary's `restored-at` | release-label |
| E | The rename build: D with the new API group and the license metadata, and no other change in `roles/` or `watches.yaml` | release-label |

No live run used build E; the kind E2E passed on it (row S44). Today's `roles/` and `watches.yaml` are build E plus
two changes after it:

* The documentation sweep, which changed comments, the role READMEs and the wording of two condition messages
  (`JobRunFailed` and `NodeUpgradeFailed` in `06-execute-jobs.yml`).
* The G6 fix ([Known gaps](../docs/HANDOFF.md#known-gaps)): `markUnsafe: true` on the three kinds in `watches.yaml`,
  so every string value of a CR reaches the roles marked unsafe, and the namespace check of the `mutexrunconfig` role
  moved before its first read of the CR. Its finalizer also reads only the MutexTargets in the operator namespace.
  With it, the offline harness gave the same results in all its scenarios as before. The kind E2E has not run on it
  yet; its new checks are rows S45 and S46.

### The two designs

* **Earlier design.** During a run the canary pool kept the held nodes out with one `DoesNotExist` expression per
  mutex label. In Upgrade 1 this failed once. After an API outage, MCO's controller still had a view of the nodes from
  before the mutex labels. It took a held node into the re-pointed canary, and that node rebooted into the canary's
  config without its Jobs. Later in the same run both nodes were upgraded one at a time, with their Jobs.
* **Release-label design (shipped).** The canary selects only the released node, by the release label (`In`), and the
  target pools leave it out (`NotIn`). It came in build C, and build D added the settle time for the canary's own
  nodes. Upgrades 2 and 3 ran it.

What the design column means for each row:

* From build A to today, `07-run-job.yml` (Jobs, timeouts, re-use), `03-pause-machine-config-pools.yml`,
  `09-report.yml` and the `mutexrule` and `mutextarget` roles changed only by the API group rename (build E) and, after
  it, in comments and the role READMEs. So the Job and validation rows that ran on the earlier design ran today's logic
  in those files. The G6 fix changed how every role receives CR values, not what it does with a value that holds no
  template expression. The node handling around the Jobs (`06-execute-jobs.yml`), the labels (`04`), the canary re-point
  (`05`) and the restore (`08`) changed with the redesign.
* From build D to today, `roles/` and `watches.yaml` changed only as described for build E and after it above.

### Rehearsals

A rehearsal ran a whole run without a real upgrade. The cluster stayed at 4.21.20. A privileged helper made one worker
report an older version: it rewrote the feature file of the sample version label publisher, and NFD relabelled the
node within about a minute. Once the released node was `Done` on a `rendered-canary-*` config, the helper published
the current version again. Moving a node between pools that render the same MachineConfigs does not reboot it, so
rehearsals had no real reboots unless a test MachineConfig forced one. The reconcile period was 1 minute, and the test
Jobs were harmless, with switches to fail, hang or hold.

An invariant checker sampled the cluster every 5 seconds and checked: at most one target node unavailable; the
pre-upgrade Jobs finish before the release; cleanup starts only after the node wait; the selectors are restored;
nothing is left on nodes or pools; the nodes are handled one after another. The helper and the checker are local
tooling, not in the repository.

### Upgrade notes

* **Upgrade 1.** The operator paused `worker` about 24 minutes before MCO started on any pool. ClusterVersion reached
  `Completed` while `worker` was still paused. The operator pod restarted during the API outages (a single
  control-plane node loses the leader election), and the run state survived. Both nodes then went through the canary
  one at a time, with a real OS update there, and all eight Jobs succeeded. At the end both rejoined `worker` with no
  reboot.
* **Upgrade 2.** On the first node, `ostree-finalize-staged` failed during the SELinux policy refresh. The node booted
  its old OS image and MCD reported it Degraded. The operator kept the other node held and kept waiting.
  `touch /run/machine-config-daemon-force` on the node made MCD apply the canary's current config in one reboot. This
  was a transient RHCOS failure, not an operator problem. At the restore, both nodes moved into `worker` with no
  reboot.
* **Upgrade 3.** Deleting the admin MachineConfig re-rendered the canary during the target node's update. The target
  node updated again inside the canary, and the canary's own node took the new config as well, before the restore.
  For the canary's own node, see S31.

## How to read the matrix

* **kind / default:** yes, no, or the condition under which the molecule scenario checks it. The task files are in
  `molecule/default/tasks/`.
* **Live:** the run from [Live runs](#live-runs) and what it showed. "Not run" means no live run covered it.
* **Design:** `release-label` (shipped) or `earlier`, as above. "–" means it does not apply.
* **Open:** what still needs a live OpenShift cluster. Run it on a non-production OpenShift cluster before you rely on
  it.

## The matrix

### Install, validation and the namespace boundary

| ID | Behaviour | kind / default | Live | Design | OpenShift | Open | How to reproduce |
| --- | --- | --- | --- | --- | --- | --- | --- |
| S1 | The operator deploys from `config/testing` and becomes available; the manager gets `POD_NAMESPACE` from the downward API | yes / yes | – | – | – | – | `molecule test -s kind` (`preflight.yml`) |
| S2 | OLM install in `OwnNamespace` and `AllNamespaces`: `WATCH_NAMESPACE` and `POD_NAMESPACE` are set; a CR in another namespace is ignored (`OwnNamespace`) or gets `Reconciled=False NamespaceNotAllowed` (`AllNamespaces`); OLM refuses `SingleNamespace` | no / no | Checks: as described; `SingleNamespace` failed with `UnsupportedOperatorGroup` | earlier | 4.21.20 | an install from `ghcr.io/redhat-na-ssa` (S44) | [USAGE, Install](../docs/USAGE.md#install), with one OperatorGroup per mode |
| S3 | A MutexRule passes a server-side dry run: `ValidConfig=True`, and no Job is created | yes / yes | – | – | – | – | `mutexrule_test.yml` |
| S4 | A MutexRule whose `jobSpec` the API server rejects: `ValidConfig=False InvalidConfig` with the API server's error | yes / yes | – | – | – | – | `mutexrule_test.yml` |
| S5 | A MutexTarget's `status.nodes` lists the nodes of its pools (on kind exactly the two workers) | yes / yes | – | – | – | – | `mutextarget_test.yml` |
| S6 | A MutexTarget for a pool that does not exist: `ValidConfig=False MachineConfigPoolFetchFailed`, no nodes | yes / yes | – | – | – | – | `mutextarget_test.yml` |
| S7 | A MutexRunConfig with no upgrade pending: validated, `UpgradeAvailable=False`, nothing paused, labelled or re-pointed, finalizer added | yes / only when a `canary` pool exists, the cluster is not upgrading and the target pool is not paused; the canary must pass validation (where infra nodes keep the worker label, the sample canary needs `node-role.kubernetes.io/infra DoesNotExist`) | – | – | – | – | `mutexrunconfig_test.yml` |
| S8 | A MutexRunConfig that references a missing MutexRule: `ConfigValidated=False ValidationFailed` naming the rule; nothing changed | yes / as S7 | – | – | – | – | `mutexrunconfig_test.yml` |
| S9 | A CR outside the operator namespace: `Reconciled=False NamespaceNotAllowed`, nothing else happens | yes / only when the operator watches all namespaces | see S2 | – | – | – | `namespace_test.yml` |
| S10 | A target node without a version label: `NodeVersionsKnown=False VersionLabelMissing` and nothing is paused, so an upgrade would go ahead without Jobs | no / accepted as the expected result when the nodes have no label | Checks and a rehearsal: as described, with `Degraded=False NoPoolsPaused` | earlier | 4.21.20 | – | a rehearsal with an empty label on one target node |
| S11 | A custom target pool (for example `apps`) with the sample canary: `ConfigValidated=False` names the `worker` pool nodes that the canary's `matchLabels` select (each node's pool comes from the `rendered-<pool>-<hash>` name in its `currentConfig`), and nothing is paused or patched; with the suggested expression, such as `node-role.kubernetes.io/app Exists`, it validates | no / no (kind has only the `master`, `worker` and `canary` pools) | Checks: the refusal named the real nodes and pools; the suggested expression validated | earlier | 4.21.20 | a full run (S34) | [USAGE, The canary pool](../docs/USAGE.md#the-canary-pool) |
| S12 | `spec.skipTLSVerify` has no effect | not needed: the roles never read it (`roles/mutexrunconfig/tasks/02-check-for-upgrade.yml:9`) | – | – | – | – | – |
| S45 | Template expressions in CR values are used as written (`markUnsafe`, [Known gaps](../docs/HANDOFF.md#known-gaps) G6): a MutexRunConfig whose canary name is `{{ 'canary' }}` gets `ConfigValidated=False ValidationFailed` naming that string; a MutexRule Job argument `{{ 7 * 7 }} {{ .Values.name }}` passes the dry run and reaches the Job unchanged | yes / the canary name only, as S7 | – | – | – | – | `mutexrunconfig_test.yml`, `finalizer_test.yml` |
| S46 | CRs in another namespace stay data (G6): a MutexRunConfig there with template expressions in its canary name and an annotation gets only `Reconciled=False NamespaceNotAllowed`, and its delete runs no cleanup; a MutexRunConfig in the operator namespace that references a MutexTarget in another namespace fails validation, and its finalizer does not restore that MutexTarget's pools | yes / the first part only, when the operator watches all namespaces | – | – | – | – | `namespace_test.yml` |

### A run

| ID | Behaviour | kind / default | Live | Design | OpenShift | Open | How to reproduce |
| --- | --- | --- | --- | --- | --- | --- | --- |
| S13 | Simulated upgrade: the target pool is paused and the nodes labelled; the target pool and the canary are re-pointed to the release label (`NotIn`/`In` this MutexRunConfig's value); one node at a time; the release label is set in the patch that removes the mutex labels and removed with `released-by` after the cleanup Job; each Job gets `NODE_NAME` and `MUTEX_RULE`, runs off the node being upgraded, and `$(NODE_NAME)` expands in its command; pools, labels, selectors and node annotations are restored; final conditions | yes / no | see S14 to S16 | – | – | – | `upgrade_test.yml`, `upgrade_node.yml` |
| S14 | A real upgrade with two target nodes: the pools are paused before MCO reaches them; a node gets a canary `desiredConfig` only after its pre-upgrade Jobs and its release patch, also while the kube-apiserver rolls out; MCO upgrades it in the canary; it goes back to its paused pool after its cleanup Jobs, with no reboot then or when the pools are unpaused | simulated (S13) | Upgrade 2: every point held. Upgrade 3: the same for its one target node. Upgrade 1 (earlier design): a held node rebooted without its Jobs ([The two designs](#the-two-designs)) | release-label | 4.21.21 → 4.21.23 | a minor upgrade (S39), the low end of the range (S40), the new API group (S44) | [USAGE, Quick start](../docs/USAGE.md#quick-start), then `oc adm upgrade --to=<next z-stream>` |
| S15 | A node's cleanup Jobs start only after MCO reports it `machineconfiguration.openshift.io/state: Done` with `currentConfig` equal to `desiredConfig` on a rendered config of the canary, and the node is `Ready`; also when its version label changes earlier and when the canary re-renders during the update | the early label: yes (the test sets it and checks for 70 s that no cleanup Job starts); a re-render: no | Upgrades 2 and 3: the wait held through an admin MachineConfig applied (2) or deleted (3) during a node's update, and through a node that booted its old OS image once (2). A rehearsal on the earlier design showed why the wait needs the canary's config: a node can be `Done` on its old pool's config, with its label already at the target version, before MCO moves it | release-label | 4.21.21 → 4.21.23 | – | apply or delete a MachineConfig for the `worker` role while a released node updates |
| S16 | The operator pod restarts in the middle of a run: a node released before the restart resumes at the wait and gets its cleanup Jobs before any other node starts | no / no | Upgrade 2: the pod was deleted during the first node's update; that node got its cleanup Jobs before the second node's pre-upgrade Jobs. Upgrade 3: the same restart; the node resumed at the wait | release-label | 4.21.21 → 4.21.23 | – | `oc delete pod -n node-upgrade-mutex-operator -l app.kubernetes.io/name=openshift-node-upgrade-mutex-operator` while a node waits |
| S17 | A node MCO is already updating when the pools are paused: the operator waits until MCO reports it `Done` and `Ready` before the node's first Job | no / no | Rehearsal: the wait held for about 4.5 minutes; the node's first pre-upgrade Job started 11 s after `Done` | earlier | 4.21.20 | not run on the release-label design | a rehearsal: while the MutexRunConfig is invalid, start a MachineConfig rollout, then fix the MutexRunConfig |
| S18 | A target node that is already at the new version while another target node is upgraded | no / no | Rehearsals: on the earlier design such a node moved into the re-pointed canary, and the operator reported one spurious `NodeUpgradeFailed` (seen three times). The release-label design removes the cause: a node that is not behind never gets the release label | earlier | 4.21.20 | not run on the release-label design | a rehearsal with one target node behind and one current |
| S19 | Two MutexRunConfigs: the second is reconciled only after the first has finished its nodes ([USAGE, One MutexRunConfig at a time](../docs/USAGE.md#one-mutexrunconfig-at-a-time)) | no / no | Rehearsal: one on `worker`, one on a custom pool `apps` with a canary of its own. They ran strictly one after the other; the second's pool stayed unpaused while it waited; both restored cleanly | earlier | 4.21.20 | deleting the waiting one (S26) | two MutexRunConfigs on different pools |
| S20 | A rule is removed from `spec.mutexRules` during a run: the next reconcile uses the remaining rules; a release also removes the removed rule's mutex label; no Jobs of the removed rule run | no / no | Rehearsal: as described; nothing was left over | earlier | 4.21.20 | – | edit `spec.mutexRules` while a node's Job runs |

### Failures, stopping and recovery

| ID | Behaviour | kind / default | Live | Design | OpenShift | Open | How to reproduce |
| --- | --- | --- | --- | --- | --- | --- | --- |
| S21 | A failed pre-upgrade Job stops the run: `JobRun=False JobRunFailed`, `Degraded=True PoolsLeftPaused`, the pools stay paused; a retry starts a new Job | yes, except the retry / no | Rehearsal: the Job failed three times, with a new Job each retry, and the pool stayed paused | earlier | 4.21.20 | – | `finalizer_test.yml`; live: a MutexRule whose Job exits 1 |
| S22 | A Job still running at `timeoutSeconds`: `JobRun=False` with "did not finish within Ns (timeoutSeconds)", `Degraded=True`, the pools stay paused; each retry waits for the same Job again; once it is Complete it is re-used | no / no | Rehearsal with `timeoutSeconds: 60`: four retries re-used the same Job, then the Complete Job was re-used | earlier | 4.21.20 | – | a Job that runs longer than `timeoutSeconds` |
| S23 | A failed cleanup Job: the same conditions as S21 | no / no | Rehearsal: `Degraded=True`, the pool stayed paused, the next reconcile retried | earlier | 4.21.20 | – | a `cleanUpJobSpec` whose Job exits 1 |
| S24 | A node that never finishes its upgrade (`mutexrunconfig_node_upgrade_retries` × `mutexrunconfig_node_upgrade_delay`, 120 × 60 s): `NodeUpgrade=False NodeUpgradeFailed`, `Degraded=True`, the pools stay paused, and the retry resumes at the wait | no / no | Not run. In Upgrade 2 a node was unfinished for a few minutes and recovered before the wait ran out | – | – | yes | no tested method yet. A test build with fewer retries ([defaults](../roles/mutexrunconfig/defaults/main.yml)) shortens the wait. A PodDisruptionBudget did not hold a node, because a file-only MachineConfig skips the drain |
| S25 | Aborting: deleting a MutexRunConfig in the middle of a run. The reconcile in progress first finishes the released node, including its cleanup Jobs; then the finalizer unpauses, unlabels and restores; the other nodes get no Jobs; Jobs in the operator namespace are garbage-collected | the restore after a failed run: yes / no | Rehearsal: for 2.5 minutes nothing changed; then the released node got its cleanup Jobs, the other node got none, and the finalizer restored everything | earlier | 4.21.20 | on the release-label design (the restore changed with it) | `finalizer_test.yml`; live: delete the MutexRunConfig while a released node waits |
| S26 | Deleting a MutexRunConfig that waits for another one's run: the deletion also waits until that run ends | no / no | Not run | – | – | yes | two MutexRunConfigs (S19); delete the waiting one |
| S27 | The finalizer after a finished run changes nothing | yes / no | – | – | – | – | `finalizer_test.yml` |
| S28 | The manual restore in [USAGE, The operator is gone in the middle of a run](../docs/USAGE.md#the-operator-is-gone-in-the-middle-of-a-run), as written now | no / no | Rehearsal of an earlier version of the steps, without the release-label and canary-annotation steps, after a MutexRunConfig was lost (finalizer removed, then deleted): it restored every selector, label and mark and unpaused the pool | earlier | 4.21.20 | the current steps ([Known gaps](../docs/HANDOFF.md#known-gaps) G11) | remove the finalizer and delete the MutexRunConfig in the middle of a run, then follow the steps |
| S29 | A target pool that an administrator paused before the run ([USAGE, Pausing the pools yourself](../docs/USAGE.md#pausing-the-pools-yourself)): the operator sets no `paused-by` and leaves the pool paused at the end; `TargetPoolsPaused=True` says it is paused by someone else | no / no | One rehearsal, with `worker` paused by hand before the run: no `paused-by` was set, `worker` was still paused at the end, `TargetPoolsPaused=True` said it was paused by someone else, and the invariant checker passed. Whether a node went through the canary in that rehearsal is not recorded. It was not a real upgrade (see [Rehearsals](#rehearsals)) | earlier | 4.21.20 | a real upgrade on the release-label design, with each node released through the canary. Since build A, the pause and the report (`03`, `09`) changed only in the rename; the restore (`08`) changed with the redesign | pause the pool (`spec.paused: true`) before the run |

### The canary pool

| ID | Behaviour | kind / default | Live | Design | OpenShift | Open | How to reproduce |
| --- | --- | --- | --- | --- | --- | --- | --- |
| S30 | During a run the canary keeps those of its own `matchExpressions` that every target node satisfies, plus the release label's `In`; the restore gives it back all of its original expressions | yes: the run drops the kind canary's `isCanary Exists`, and the restore brings it back / no | Upgrades 2 and 3: the canary also had an expression that kept out the control-plane node, which runs workloads too; it was kept during the run and restored each time. A rehearsal: an expression added to the canary during a run survived the restore | release-label; the rehearsal earlier | 4.21.21 → 4.21.23 | – | `upgrade_test.yml` |
| S31 | A canary with nodes of its own (the sample canary and a worker labelled `isCanary`): they stay in the canary at the start and at the end of a run. The first reconcile reports `MCPUpdated=False CanaryMembersLabelled` and gives the canary its hold selector (its own `matchExpressions` plus one `DoesNotExist` per mutex label) and the `release-labelled-at` annotation. The pools are re-pointed only at a reconcile at least `mutexrunconfig_label_settle_seconds` (300) later, also after a restart. After the run the nodes keep the release label until a reconcile at least 300 s after the canary's `restored-at`, and then the annotation goes too | no / no ([Known gaps](../docs/HANDOFF.md#known-gaps) G10) | Upgrade 3: the label, the hold selector and `release-labelled-at` came in the first reconcile, during the kube-apiserver rollout. The operator restarted before the re-point, and the reconcile after the restart waited again. The pools were re-pointed 13 minutes after the stamp. The node never left the canary, and MCO upgraded it there. Its label and `restored-at` went at a reconcile 5 minutes after the restore | release-label | 4.21.22 → 4.21.23 | S32, S33 | label one worker `isCanary=` and wait until MCO has moved it into the canary |
| S32 | Deleting the MutexRunConfig in the middle of a run while the canary has nodes of its own: they pass through `worker` at most once (the finalizer has a single pass) | no / no | Not run | – | – | yes | S31, then delete the MutexRunConfig before the restore |
| S33 | A canary node of its own with a custom target pool (for `apps`: `isCanary` and also `node-role.kubernetes.io/app=canary`) | no / no | Not run | – | – | yes | S31 with a custom target pool |
| S34 | A full run on a custom target pool with the sample canary plus the suggested expression (S11): the `worker` pool nodes stay where they are | no / no | Only a run on `apps` with a canary of its own, next to a second MutexRunConfig on `worker` (S19) | earlier | 4.21.20 | yes | [USAGE, The canary pool](../docs/USAGE.md#the-canary-pool) |

### Versions, packaging and environments

| ID | Behaviour | kind / default | Live | Design | OpenShift | Open | How to reproduce |
| --- | --- | --- | --- | --- | --- | --- | --- |
| S35 | The sample version label publisher ([machineconfig.yaml](../sample-manifests/machineconfig.yaml) with NFD and [nodefeaturediscovery.yaml](../sample-manifests/nodefeaturediscovery.yaml)) labels each worker with the new version after its upgrade reboot, before MCO marks the node `Done`, which is why the node wait checks more than the label | no / no | Checks, and Upgrades 1 to 3 | – | 4.21.20 → 4.21.23 | – | [USAGE, The release version label](../docs/USAGE.md#the-release-version-label) |
| S36 | `operator-sdk scorecard` (`config/scorecard`) against the bundle | no / no | Checks: 6 of 6 passed | earlier | 4.21.20 | – | `operator-sdk scorecard bundles/<VERSION>` |
| S37 | The HTTPS metrics endpoint with the `openshift-node-upgrade-mutex-operator-metrics-reader` ClusterRole bound to the scraper | no / no | Checks: 403 without the binding, 200 with it | earlier | 4.21.20 | – | [USAGE, Metrics](../docs/USAGE.md#metrics) |
| S38 | Moving from 0.2.x by reinstalling ([USAGE, Moving from 0.2.x](../docs/USAGE.md#moving-from-02x)): save the CRs, uninstall 0.2.x, install 0.3.0, create the CRs again under the new group | no / no | Only the earlier in-place OLM upgrade from 0.2.68, before the API group changed: a broken CR made the InstallPlan fail; deleting the Subscription and both CSVs and creating the Subscription again recovered it, and the CRs were kept | earlier | 4.21.20 | the reinstall as written now; possible only where 0.2.x still runs, because its images are gone | – |
| S39 | A minor (y-stream) OpenShift upgrade | no / no | Not run | – | – | yes | a non-production cluster, `oc adm upgrade` to the next minor version |
| S40 | A version at the low end of the declared range (OpenShift 4.16, Kubernetes 1.29) | no / no (kind uses kind's default node image) | Not run | – | – | yes | – |
| S41 | An EUS-to-EUS upgrade | no / no | Not run | – | – | yes | – |
| S42 | A disconnected cluster. Expected to work: the operator reads ClusterVersion `status.desired.version` and pulls no release image; the MutexRule Job images must be mirrored. The CSV keeps `features.operators.openshift.io/disconnected: "false"` until this is tested | no / no | Not run | – | – | yes | mirror the operator, bundle, catalog and Job images |
| S43 | The CSV description in the OpenShift console: diagrams appear as links, tables and code blocks render | no / no (`make docs-lint` checks the console rules for `docs/USAGE.md`) | Not checked | – | – | yes | [HANDOFF, Takeover checklist](../docs/HANDOFF.md#takeover-checklist), step 6 |
| S44 | A release from `ghcr.io/redhat-na-ssa`, with the new API group, on OpenShift | the kind E2E passed with the new group / no | Not run: every live run used test builds with the old API group | – | – | yes | [HANDOFF, Takeover checklist](../docs/HANDOFF.md#takeover-checklist), steps 5 to 7 |

## MCO behaviour seen in the live runs

These are observations on OpenShift 4.21.20 to 4.21.23, not guarantees. Recheck them on other versions.

* MCO resets the `nodeSelector` of the built-in `worker` pool within seconds after the operator patches it; runs still
  work. Custom pools such as `apps` keep theirs.
* A node that both `worker` and a custom pool select belongs to the custom pool (seen for the canary and for `apps`).
* Moving a node between two pools that render the same MachineConfigs does not reboot it; MCD logs `SkipReboot`.
* A paused pool never changes its nodes' `desiredConfig`. ClusterVersion still reaches `Completed` while `worker` is
  paused.
* MCD finishes an update it has started even after the node leaves the pool (an MCO-only rehearsal on 4.21.21, with
  the operator scaled to 0).
* A file-only MachineConfig logs "Drain not required" but still reboots the node. With `maxUnavailable` 2 it rebooted
  both workers at once, without evicting pods.
* After an API outage, MCO's node and pool caches came back about 70 to 115 seconds later, each on its own. The first
  re-render came about 2 minutes after the API was back. This stale view is what took a held node into the earlier
  design's canary.
* The sample label publisher reports the new version at boot, before MCO marks the node `Done` (S35).
* With a single control-plane node, the operator pod restarts at each API outage (it loses the leader election).

## How the kind scenario plays MCO

In the `kind` scenario nothing plays the MCO except the test. Before the tests, `molecule/default/tasks/fake_reset.yml`
makes every node report `machineconfiguration.openshift.io/state` `Done`, with `currentConfig` and `desiredConfig` set
to `rendered-<master|worker>-<hash>`. When the operator releases a node (it removes the node's mutex labels and sets
the release label, so the node joins the canary pool), the test (`upgrade_node.yml`):

1. sets the node's `desiredConfig` to the canary's rendered config and its `state` to `Working`;
2. sets its `machineconfiguration.openshift.io/release-image-version` label to the new version, as NFD can before the
   reboot, and for 70 seconds checks that no cleanup Job starts for the node;
3. sets `state` to `Done` and `currentConfig` to the `desiredConfig`, as MCO does after the reboot. The kind nodes
   report `Ready` themselves.

Only then does the operator count the node as upgraded and run its cleanup Jobs. The check in step 2 lasts longer than
the operator's 60-second node poll (`mutexrunconfig_node_upgrade_delay`), so an operator that trusted the label alone
would start its cleanup Job inside that window. After the cleanup Job the test waits until the release label and
`released-by` are gone from the node, which puts it back in its paused pool. More on the scenarios, their variables
and how to run them: [molecule/README.md](../molecule/README.md).
