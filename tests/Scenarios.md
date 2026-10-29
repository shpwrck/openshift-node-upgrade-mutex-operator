# Test Scenarios

What is tested automatically, where, and what still needs a real OpenShift
cluster. The automated tests are the molecule scenarios in `molecule/`
(see `molecule/README.md`); the `kind` scenario also runs in CI
(`.github/workflows/e2e.yaml`).

## Automated

| Behaviour | `kind` (fake OpenShift APIs) | `default` (a cluster without the operator installed) |
| --- | --- | --- |
| Operator deploys from `config/testing` and becomes available | yes | yes |
| Manager sets `POD_NAMESPACE` from the downward API | yes | yes |
| MutexRule `ValidConfig=True` after a server-side dry run; no Job is created | yes | yes |
| MutexRule with an invalid `jobSpec` reports `ValidConfig=False InvalidConfig` with the API server's error | yes | yes |
| MutexTarget `status.nodes` lists the nodes of its pools (exactly the workers on kind) | yes | yes |
| MutexTarget with a missing pool reports `ValidConfig=False` and no nodes | yes | yes |
| MutexRunConfig with no upgrade pending: validated, `UpgradeAvailable=False`, nothing paused, labelled or re-pointed, finalizer added | yes | when a `canary` pool exists, the cluster is not upgrading and the target pool is not paused; the canary must pass validation (on a cluster whose infra nodes keep the worker label, the sample canary needs `node-role.kubernetes.io/infra DoesNotExist`) |
| MutexRunConfig that references a missing MutexRule: `ConfigValidated=False`, nothing changed | yes | same as above |
| CRs outside the operator namespace get `Reconciled=False NamespaceNotAllowed` | yes | when the operator watches all namespaces |
| Simulated upgrade: target pool paused, nodes labelled, target pool and canary re-pointed to the release label (`NotIn`/`In` this MutexRunConfig's value), one node at a time; the release label set in the patch that removes the mutex labels and removed with `released-by` after the cleanup Job; each Job gets `NODE_NAME`/`MUTEX_RULE`, runs off the node being upgraded, `$(NODE_NAME)` expands in its command; no cleanup Job starts while MCO still reports the node `Working`, cleanup Jobs run after the node has finished its upgrade; pools, labels, selectors and node annotations restored; final conditions | yes | no |
| Finalizer after a finished run changes nothing | yes | no |
| A failed Job stops the run with pools left paused (`Degraded=True PoolsLeftPaused`); deleting the MutexRunConfig then unpauses, unlabels and restores | yes | no |

In the `kind` scenario nothing plays the MCO except the test. Before the
tests, `molecule/default/tasks/fake_reset.yml` makes every node report
`machineconfiguration.openshift.io/state` `Done` with `currentConfig` and
`desiredConfig` set to `rendered-<master|worker>-<hash>`. When the operator
releases a node (removes its mutex labels and sets the release label, so it
joins the canary pool), the test:

1. sets the node's `desiredConfig` to the canary's rendered config and its
   `state` to `Working`;
2. sets its `machineconfiguration.openshift.io/release-image-version` label
   to the new version, as NFD can before the reboot, and for 70 seconds
   checks that no cleanup Job starts for the node;
3. sets `state` to `Done` and `currentConfig` to the `desiredConfig`, as MCO
   does after the reboot. The kind nodes report `Ready` themselves.

Only then does the operator count the node as upgraded and run its cleanup
Jobs. The check in step 2 lasts longer than the operator's 60-second node poll
(`mutexrunconfig_node_upgrade_delay`), so an operator that trusted the label
alone would start its cleanup Job inside that window. After the cleanup Job
the test waits until the release label and `released-by` are gone from the
node, which puts it back in its paused pool.

## Not automated (needs OpenShift)

1. Works in a disconnected environment. The upgrade check reads ClusterVersion
   `status.desired.version` and pulls no release image, so no egress is
   needed by the operator itself; MutexRule Job images must be mirrored.
2. Works with or without TLS. `spec.skipTLSVerify` is deprecated and has no
   effect any more (no release image is pulled).
3. Works without the default MachineConfigPools: targets that are custom
   pools, and a canary whose matchExpressions must be kept during a run.
   The `kind` scenario only has the master, worker and canary pools.
4. A real upgrade: MCO updating and rebooting the released node, NFD
   publishing the release-image-version label (`sample-manifests/`), and
   cleanup Jobs running after the reboot.
5. The scorecard (`config/scorecard`) and the OLM install from the bundle.
