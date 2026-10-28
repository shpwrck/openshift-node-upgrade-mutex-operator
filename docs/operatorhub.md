The OpenShift Node Upgrade Mutex Operator updates worker nodes one at a time during an OpenShift update and runs your Jobs before and after each node.

Use it when something has to happen around every node update that the Machine Config Operator cannot do for you: move a workload away first, check that a quorum is still healthy, take a backup, or tell an external system that a node is going away and coming back.

## How it works

1. When the cluster starts updating to a new version, the operator pauses the target MachineConfigPools so the Machine Config Operator (MCO) cannot update their nodes on its own.
2. After the control plane has finished updating, the operator takes the target nodes one at a time. For each node it:
   1. runs the pre-update Job of every MutexRule and waits for it to succeed;
   2. moves the node into the canary pool, where the MCO updates it;
   3. waits until the node runs the new version;
   4. runs the post-update Job of every MutexRule.
3. When every node is done, the operator returns the nodes to their pools and unpauses them.

A failed Job holds the rollout and marks the MutexRunConfig `Degraded`. Delete the Job to retry it. Deleting the MutexRunConfig stops the rollout and hands the pools back to the MCO.

## Resources

* **MutexRule**: a Job to run before each node is updated (`jobSpec`) and, optionally, one to run after it (`cleanUpJobSpec`). Every container gets `NODE_NAME`, `TARGET_VERSION`, `MUTEX_RULE` and `MUTEX_STAGE`, and the Jobs never run on the node they are about.
* **MutexTarget**: the MachineConfigPools whose nodes are updated one at a time.
* **MutexRunConfig**: ties rules, targets and a canary pool together. Its status shows the version being rolled out, the node being updated and the phase of every node.

## Before you start

* Create a canary MachineConfigPool that renders the same MachineConfigs as your target pools, selects no nodes and is not paused. An example is in the repository under `sample-manifests/canary-machineconfigpool.yaml`.
* Create the namespace your Jobs run in, and give the Jobs' service account whatever access they need. The operator creates no RBAC for them.
* Create the MutexRules, MutexTargets and one MutexRunConfig before you start the cluster update.

Version 0.3.0 moved the API group to `nodeupgrade.redhat-na-ssa.github.io`. Resources created with 0.2.x (`openshift-optional.skrzypek.io`) must be recreated.

For details, diagrams and troubleshooting, see the [project on GitHub](https://github.com/redhat-na-ssa/openshift-node-upgrade-mutex-operator).
