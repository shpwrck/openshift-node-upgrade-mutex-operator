# Sample manifests

These files set up the operator for one target pool, `worker`, as the [Quick start](../docs/USAGE.md#quick-start) does.
They use its names: the operator namespace `node-upgrade-mutex-operator`, the canary pool `canary`, the MutexRule
`label-node`, and the MutexTarget and MutexRunConfig `workers`. If you install the operator into another namespace,
change it in every file. Each file explains itself in its comments.

**Never apply the whole directory (`oc apply -f sample-manifests/`).** `machineconfig.yaml` reboots every worker,
`nodefeaturediscovery.yaml` replaces the worker configuration of an existing NFD instance, `job-wait-for-app.yaml`
must be edited first, and `canary-mcp-custom-pool.yaml` is only for custom pools. Apply one file at a time, in the
order below, and check each step before the next.

## Apply order

1. Install the Node Feature Discovery operator from OperatorHub into the namespace `openshift-nfd`. Then:

   ```sh
   oc apply -f sample-manifests/nodefeaturediscovery.yaml
   oc get pods -n openshift-nfd -o wide
   ```

   Expected: an `nfd-worker` pod runs on every target node. If the cluster already has a NodeFeatureDiscovery, skip
   the file and check that instance as its comments say.

2. **This step reboots every worker, and every node of a pool that inherits the worker MachineConfigs, as many at a
   time as each pool's `maxUnavailable` allows.** Apply it in a maintenance window:

   ```sh
   oc apply -f sample-manifests/machineconfig.yaml
   oc get mcp -w
   ```

   Wait until `UPDATED` is `True` for every pool. Expected: every target node shows the cluster's version in the label
   that the operator reads:

   ```sh
   oc get clusterversion version -o jsonpath='{.status.desired.version}{"\n"}'
   oc get nodes -L machineconfiguration.openshift.io/release-image-version
   ```

3. Create the canary pool. For the target pool `worker`:

   ```sh
   oc apply -f sample-manifests/canary-mcp.yaml
   oc get mcp canary
   ```

   Expected: `MACHINECOUNT` is `0`. For a custom target pool, edit and apply `canary-mcp-custom-pool.yaml` instead.

4. Add the project's catalog:

   ```sh
   oc apply -f sample-manifests/catalogsource.yaml
   oc get catalogsource node-upgrade-mutex-operator-catalog -n openshift-marketplace -o jsonpath='{.status.connectionState.lastObservedState}{"\n"}'
   ```

   Expected: `READY`. The file uses the tag `:v0.3.0-rc2`, which exists only once that version is released; see the
   file's comments for the tags and for using a catalog of your own.

5. Install the operator, then approve its first InstallPlan (the Subscription uses Manual approval):

   ```sh
   oc apply -f sample-manifests/operator-install.yaml
   oc get installplan -n node-upgrade-mutex-operator
   oc patch installplan <name> -n node-upgrade-mutex-operator --type merge -p '{"spec":{"approved":true}}'
   oc get csv -n node-upgrade-mutex-operator
   oc get pods -n node-upgrade-mutex-operator -o wide
   ```

   Expected: the CSV's `PHASE` is `Succeeded`, and the operator pod runs on a control-plane node.

6. Create the MutexRule `label-node`, with its ServiceAccount and RBAC:

   ```sh
   oc apply -f sample-manifests/job-example.yaml
   oc get mutexrule label-node -n node-upgrade-mutex-operator
   ```

   Expected: `VALIDCONFIG` is `True`. To also wait for an application around each node, edit and apply
   `job-wait-for-app.yaml`, and add `wait-for-app` to the MutexRunConfig's `spec.mutexRules`.

7. Create the MutexTarget and the MutexRunConfig:

   ```sh
   oc apply -f sample-manifests/mutex-target-and-runconfig.yaml
   oc get numo -n node-upgrade-mutex-operator
   ```

   Expected: the MutexTarget lists the nodes of pool `worker`, and the MutexRunConfig shows `VALIDATED` `True`,
   `UPGRADE` `False`, `PAUSED` `False` and `DEGRADED` `False`. From now on, an OpenShift upgrade runs through the
   operator. [Before your first upgrade](../docs/USAGE.md#before-your-first-upgrade) says what to check first.

## The files

| File | Creates | Purpose | Applied on a cluster |
| --- | --- | --- | --- |
| [nodefeaturediscovery.yaml](nodefeaturediscovery.yaml) | NodeFeatureDiscovery `nfd-instance` in `openshift-nfd` | Runs `nfd-worker`, which turns the file that the MachineConfig writes into the node label `machineconfiguration.openshift.io/release-image-version`. Reboots nothing. | An earlier revision, on OpenShift 4.21 (see [the test matrix](../tests/Scenarios.md)); this revision: unknown |
| [machineconfig.yaml](machineconfig.yaml) | MachineConfig `00-release-image-version` for role `worker` | Publishes each node's release version for NFD. **Reboots every worker.** | An earlier revision, on OpenShift 4.21; this revision: unknown |
| [canary-mcp.yaml](canary-mcp.yaml) | MachineConfigPool `canary` | The canary for the target pool `worker`. Keep it empty. | Not applied on a cluster in this form; the same pool spec was the sample canary of the live runs |
| [canary-mcp-custom-pool.yaml](canary-mcp-custom-pool.yaml) | MachineConfigPool `canary-app` | The canary for a custom target pool, here `app`. Edit it first. | Not applied on a cluster |
| [catalogsource.yaml](catalogsource.yaml) | CatalogSource `node-upgrade-mutex-operator-catalog` in `openshift-marketplace` | Offers the project's catalog image, `ghcr.io/redhat-na-ssa/openshift-node-upgrade-mutex-operator-catalog`, to OLM. | Not applied on a cluster |
| [operator-install.yaml](operator-install.yaml) | Namespace and OperatorGroup `node-upgrade-mutex-operator`, Subscription `openshift-node-upgrade-mutex-operator` | Installs the operator into its own namespace (install mode `OwnNamespace`), channel `alpha`, Manual approval. | Not applied on a cluster |
| [job-example.yaml](job-example.yaml) | ServiceAccount, ClusterRole and ClusterRoleBinding `mutex-node-labeler`; MutexRule `label-node` | The Quick start rule: its Job labels the node before its upgrade, its cleanup Job removes the label after. | Not applied on a cluster in this form; earlier revisions: unknown |
| [job-wait-for-app.yaml](job-wait-for-app.yaml) | ServiceAccount, Role and RoleBinding `mutex-wait-for-app` in `my-app`; MutexRule `wait-for-app` | Waits until a Deployment is fully available, before each node is drained and after it is back. Edit it first. | Not applied on a cluster |
| [mutex-target-and-runconfig.yaml](mutex-target-and-runconfig.yaml) | MutexTarget and MutexRunConfig `workers` | Upgrades the nodes of pool `worker` one at a time through `canary`, each after the Job of `label-node`. | Not applied on a cluster |

The two Job samples are explained in [Writing MutexRule Jobs](../docs/JOBS.md). The custom resources in
`config/samples/` are different: they feed the kind end-to-end test and the console's examples, and they use names
such as `mutexrule-sample`.

## Removing them

Remove them in the reverse order, as [Uninstall](../docs/USAGE.md#uninstall) describes. Delete the MutexRunConfig
first, while the operator still runs, so its finalizer can put back what it changed. Deleting `machineconfig.yaml`
reboots every worker again.
