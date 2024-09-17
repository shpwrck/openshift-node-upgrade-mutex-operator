## To Install The Operator

1. Install NFD
2. Create an NFD Instance
3. Create `machineconfig.yaml`
4. Create `catalogsource.yaml`
5. Install OpenShift Node Upgrade Mutex Operator through OperatorHub
6. Create MutexRule, MutexTarget, and MutexRunConfig

## Work Remaining

- Update CRD OpenAPI Validation
- Update Examples
- Create Instructions
- Automate Release Process
- Update This Document

## Introduction

This operator injects required operations in the form of a Kubernetes job into the worker node upgrade process using MachineConfigPools. In short, when provided a list of operations (`MutexRules`) and a list of MachineConfigPools (`MutexTargets`) , the OpenShift Node Upgrade Mutex Operator will execute each operation for a given target, enable updates for the given target by modifying it's MachineConfigPool membership, and wait until the node has been upgraded before proceeding onto subsequent operations and targets.

## Dependencies

### Release Version Label

In order to confirm the successful upgrade of each target node, the NFD Operator is used to generate a version feature on every worker node. In order to proceed through given targets, each node must have this label
`'machineconfiguration.openshift.io/release-image-version'` with a key providing the semantic version of this node (e.g. `'4.16.4'`)

There are several ways to accomplish this, but an example MachineConfig has been provided [here](https://github.com/shpwrck/openshift-node-upgrade-mutex-operator/blob/main/machineconfig.yaml).

### Canary Machine Config Pool

In addition to node labels, a MachineConfigPool that will be used to accomodate targets subject to upgrades must be provided matching the following criteria:
* selects only worker nodes
* is not paused

Applying the example below will create a compatible canary pool:

```yaml
---
apiVersion: machineconfiguration.openshift.io/v1
kind: MachineConfigPool
metadata:
  name: canary-example
spec:
  machineConfigSelector:
    matchLabels:
      machineconfiguration.openshift.io/role: worker
  nodeSelector:
    matchLabels:
      node-role.kubernetes.io/worker: ''
  paused: false
```

## Usage / Custom Resources Definitions

#### MutexRule:

A resource storing a single rule referring to a template for a Kubernetes job to be created.
This resource **does not** modify existing resources.

```yaml
---
apiVersion: openshift-optional.skrzypek.io/v1alpha1
kind: MutexRule
metadata:
  name: k8s-example
spec:
  jobName: "Job Name" # Jobs will be run with this prefix name
  jobNamespace: "Job Namespace" # Jobs will be run in this namespace
  jobSpec: # Accepts full 'batch/v1' job spec
    selector: {}
    template:
      metadata:
        name: mutex
      spec:
        containers:
        - command:
          - /bin/sh
          - sleep
          - "30"
          image: ubi9/toolbox
          name: mutex
        restartPolicy: Never
  type: kubernetes
```

#### MutexTarget:

A resource storing a set of MachineConfigPools to pause and incrementally upgrade.
This resource **does not** modify existing resources.

```yaml
---
apiVersion: openshift-optional.skrzypek.io/v1alpha1
kind: MutexTarget
metadata:
  name: worker-example
spec:
  machineConfigPools:
    - worker # Name of existing machineconfigpool
```

#### MutexRunConfig:

A resource that references existing MutexRules and MutexTargets as well as an existing MachineConfigPool that will allow members to be upgraded. Every rule defined in the `mutexRules` list will be added as a mandatory task to every node that is a member of the each MachineConfigPool defined in the `mutexTargets` list.
This resource **does** modify existing resources.

```yaml
apiVersion: openshift-optional.skrzypek.io/v1alpha1
kind: MutexRunConfig
metadata:
  name: example
spec:
  canary:
    name: canary # Name of unpaused machineconfigpool to modify
  mutexRules: # List of existing mutexRules
    - name: k8s-example
      namespace: node-upgrade-mutex-operator
  mutexTargets: # List of existing mutexTargets
    - name: worker-example
      namespace: node-upgrade-mutex-operator
```

## Procedure

#### MutexRule

1. Upon creation/modification, the schema of each K8s rule is validated.
2. Status is updated to indicate valid or invalid configuration.

#### MutexTargets

1. Upon creation/modification, the existence of each target is validated.
2. Status is updated to indicate valid or invalid configuration.
3. The nodes assigned to each target are added to the status field `nodes`.

#### MutexRunConfigs

1. Upon creation/modification, the existence as well as validation status of each rule, target, and canary pool is confirmed.
2. If valid, the existence of an upgrade is queried. An upgrade is available if the following is true:
    * The `status.history` of the `cluster` ClusterVersion equals `Completed`
    * The `release-image-version` of any worker node is less than the `spec.desiredUpdate.version` of the `cluster` ClusterVersion.
3. If an update exists, each target MachineConfigPool has `spec.paused` set to `true`.
4. If each pool is paused, each node is updated to include a label for each rule with the following format:
    * `mutexrule.openshift-optional.skrzypek.io/{{MutexRule_Name}}.{{MutexRule_Namespace}}`
5. If labels have been applied, the provided canary pool is modified to exclude nodes with labels provided by step (4).
6. Assuming steps (2-5) have completed successfully, then the process for running jobs and updating nodes begins. The process per node is as follows:
    * Launch each K8S job sequentially
    * Remove the current node's rule labels
    * Wait until the `release-image-version` of the node matches the `spec.desiredUpdate.version` of the `cluster` ClusterVersion
7. If the update succeeds, all machine config pools are unpaused and all match expressions are removed.

## Permissions Granted

In addition to the permissions required to operate the included CRDs, the following access is granted to the operator's service account.

| Resource | Permissions |
| :---: | :---: |
| Jobs | Create & Read |
| Nodes | Read & Update |
| ClusterVersion | Read |
| MachineConfigPools | Read & Update |

## Notes

* This operator was built using the operator-sdk's ansible plugin and therefore has all of the inherited capabilities and restrictions.
* This operator has undergone minimal testing and should not be run in production environments without acknowledging the risks.
* This operator is currently alpha and subject to change based on requirements.

## Additional Information
For additional information refer to the [GitHub Repository](https://github.com/shpwrck/openshift-node-upgrade-mutex-operator)
