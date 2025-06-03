## To Install The Operator

1. Install NFD
2. Create an NFD Instance
3. Create `machineconfig.yaml`
4. Create `catalogsource.yaml`
5. Install OpenShift Node Upgrade Mutex Operator through OperatorHub
6. Create MutexRule, MutexTarget, and MutexRunConfig

## Work Remaining

- Automate Release Process

## Requirements for `make`

- yq binary
- operator-sdk binary
- opm binary
- registry.redhat.com credentials
- quay.io credentials

## Updating Public Operator Hubs

- Make Release Candidate
- Fork appropriate hub repository
  - [Community](https://github.com/k8s-operatorhub/community-operators)
  - [Red Hat](https://github.com/redhat-openshift-ecosystem/community-operators-prod)
- Clone the appropriate fork
- Copy the contents of `bundles` into `operators/openshift-node-upgrade-mutex-operator/`
