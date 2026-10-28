# Test Scenarios

What is tested automatically, where, and what still needs a real OpenShift
cluster. The automated tests are the molecule scenarios in `molecule/`
(see `molecule/README.md`); the `kind` scenario also runs in CI
(`.github/workflows/e2e.yaml`).

## Automated

| Behaviour | `kind` (fake OpenShift APIs) | `default` (any cluster) |
| --- | --- | --- |
| Operator deploys from `config/testing` and becomes available | yes | yes |
| Manager sets `POD_NAMESPACE` from the downward API | yes | yes |
| MutexRule `ValidConfig=True` after a server-side dry run; no Job is created | yes | yes |
| MutexRule with an invalid `jobSpec` reports `ValidConfig=False InvalidConfig` with the API server's error | yes | yes |
| MutexTarget `status.nodes` lists the nodes of its pools (exactly the workers on kind) | yes | yes |
| MutexTarget with a missing pool reports `ValidConfig=False` and no nodes | yes | yes |
| MutexRunConfig with no upgrade pending: validated, `UpgradeAvailable=False`, nothing paused, labelled or re-pointed, finalizer added | yes | when a `canary` pool exists and the cluster is not upgrading |
| MutexRunConfig that references a missing MutexRule: `ConfigValidated=False`, nothing changed | yes | same as above |
| CRs outside the operator namespace get `Reconciled=False NamespaceNotAllowed` | yes | when the operator watches all namespaces |
| Simulated upgrade: target pool paused, nodes labelled, canary re-pointed, one node at a time; each Job gets `NODE_NAME`/`MUTEX_RULE`, runs off the node being upgraded, `$(NODE_NAME)` expands in its command; cleanup Jobs run after the node reports the new version; pools, labels and selectors restored; final conditions | yes | no |
| Finalizer after a finished run changes nothing | yes | no |
| A failed Job stops the run with pools left paused (`Degraded=True PoolsLeftPaused`); deleting the MutexRunConfig then unpauses, unlabels and restores | yes | no |

In the `kind` scenario nothing plays the MCO except the test: when the
operator releases a node (removes its mutex labels, so it joins the canary
pool), the test sets the node's `machineconfiguration.openshift.io/release-image-version`
label to the new version, which is what MCO and NFD do on OpenShift.

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
