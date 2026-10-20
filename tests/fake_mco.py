"""A stand-in for OpenShift's Machine Config Operator, for tests.

It does just enough for the mutex operator to drive a rollout:

* every pool gets a rendered MachineConfig for the version the cluster has
  rendered, annotated with that version like the real MCO does;
* every node is assigned to a pool with the MCO's rules (master wins, one
  custom pool wins over worker, two custom pools is an error);
* nodes of unpaused pools move to their pool's rendered config in two steps
  (Working, then Done), the way the machine-config daemon reports progress.

``step`` works on plain dicts, so unit tests can call it directly. Run the
module to drive a real API server instead::

    python tests/fake_mco.py --kubeconfig ~/.kube/config --interval 2
"""

import argparse
import copy
import time

RELEASE_VERSION = "machineconfiguration.openshift.io/release-image-version"
CURRENT_CONFIG = "machineconfiguration.openshift.io/currentConfig"
DESIRED_CONFIG = "machineconfiguration.openshift.io/desiredConfig"
STATE = "machineconfiguration.openshift.io/state"


def _labels(obj):
    return obj.get("metadata", {}).get("labels") or {}


def _annotations(obj):
    return obj.get("metadata", {}).get("annotations") or {}


def matches(selector, labels):
    selector = selector or {}
    match_labels = selector.get("matchLabels") or {}
    expressions = selector.get("matchExpressions") or []
    if not match_labels and not expressions:
        return False
    if any(labels.get(key) != value for key, value in match_labels.items()):
        return False
    for expression in expressions:
        key, operator, values = expression["key"], expression["operator"], expression.get("values") or []
        if operator == "In" and labels.get(key) not in values:
            return False
        if operator == "NotIn" and key in labels and labels[key] in values:
            return False
        if operator == "Exists" and key not in labels:
            return False
        if operator == "DoesNotExist" and key in labels:
            return False
    return True


def pool_for_node(node, pools):
    """The pool the MCO assigns a node to, or None."""
    found = [pool for pool in pools if matches(pool["spec"].get("nodeSelector"), _labels(node))]
    names = [pool["metadata"]["name"] for pool in found]
    if "master" in names:
        return "master"
    custom = [name for name in names if name != "worker"]
    if len(custom) > 1:
        return None
    if custom:
        return custom[0]
    return "worker" if "worker" in names else None


def rendered_name(pool_name, version):
    return "rendered-%s-%s" % (pool_name, version)


def step(rendered_version, pools, nodes):
    """One pass of the fake MCO.

    Returns (machine_configs, pool_patches, node_patches): the rendered
    MachineConfigs that must exist, and merge patches keyed by object name.
    """
    machine_configs = []
    pool_patches = {}
    node_patches = {}
    pools_by_name = {pool["metadata"]["name"]: pool for pool in pools}
    for pool in pools:
        name = rendered_name(pool["metadata"]["name"], rendered_version)
        machine_configs.append({
            "apiVersion": "machineconfiguration.openshift.io/v1",
            "kind": "MachineConfig",
            "metadata": {"name": name, "annotations": {RELEASE_VERSION: rendered_version}},
            "spec": {},
        })
        if (pool["spec"].get("configuration") or {}).get("name") != name:
            pool_patches[pool["metadata"]["name"]] = {"spec": {"configuration": {"name": name}}}

    for node in nodes:
        pool_name = pool_for_node(node, pools)
        if not pool_name:
            continue
        pool = pools_by_name[pool_name]
        annotations = _annotations(node)
        current = annotations.get(CURRENT_CONFIG)
        desired = annotations.get(DESIRED_CONFIG)
        state = annotations.get(STATE)
        if state == "Working":
            node_patches[node["metadata"]["name"]] = {"metadata": {"annotations": {
                CURRENT_CONFIG: desired, STATE: "Done"}}}
            continue
        if pool["spec"].get("paused"):
            continue
        target = rendered_name(pool_name, rendered_version)
        if current != target or desired != target:
            node_patches[node["metadata"]["name"]] = {"metadata": {"annotations": {
                DESIRED_CONFIG: target, STATE: "Working"}}}
    return machine_configs, pool_patches, node_patches


def apply_merge_patch(target, patch):
    """RFC 7386, for tests that keep objects in memory."""
    if not isinstance(patch, dict):
        return copy.deepcopy(patch)
    result = copy.deepcopy(target) if isinstance(target, dict) else {}
    for key, value in patch.items():
        if value is None:
            result.pop(key, None)
        else:
            result[key] = apply_merge_patch(result.get(key), value)
    return result


def rendered_version_of(cluster_version):
    """The version the fake MCO renders: the last completed cluster update."""
    for entry in (cluster_version.get("status") or {}).get("history") or []:
        if entry.get("state") == "Completed":
            return entry["version"]
    return None


def main():
    from kubernetes import client, config, dynamic

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--kubeconfig")
    parser.add_argument("--interval", type=float, default=2.0)
    args = parser.parse_args()

    api = dynamic.DynamicClient(config.new_client_from_config(config_file=args.kubeconfig))
    pools_api = api.resources.get(api_version="machineconfiguration.openshift.io/v1", kind="MachineConfigPool")
    configs_api = api.resources.get(api_version="machineconfiguration.openshift.io/v1", kind="MachineConfig")
    versions_api = api.resources.get(api_version="config.openshift.io/v1", kind="ClusterVersion")
    nodes_api = api.resources.get(api_version="v1", kind="Node")
    merge = {"content_type": "application/merge-patch+json"}

    while True:
        cluster_version = versions_api.get(name="version").to_dict()
        version = rendered_version_of(cluster_version)
        if version:
            pools = [pool.to_dict() for pool in pools_api.get().items]
            nodes = [node.to_dict() for node in nodes_api.get().items]
            machine_configs, pool_patches, node_patches = step(version, pools, nodes)
            existing = {mc.metadata.name for mc in configs_api.get().items}
            for machine_config in machine_configs:
                if machine_config["metadata"]["name"] not in existing:
                    configs_api.create(body=machine_config)
            for name, patch in pool_patches.items():
                pools_api.patch(name=name, body=patch, **merge)
            for name, patch in node_patches.items():
                nodes_api.patch(name=name, body=patch, **merge)
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
