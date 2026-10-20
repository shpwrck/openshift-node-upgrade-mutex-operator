"""End-to-end test: a full rollout through a running operator.

The cluster needs no OpenShift. The test installs stand-ins for the OpenShift
APIs the operator reads (manifests/openshift-apis.yaml), creates fake target
nodes, and runs tests/fake_mco.py in the background to play the Machine Config
Operator. The operator itself must already run against the cluster, either
deployed (``make deploy``) or locally (``make run``).

Environment:

* ``KUBECONFIG``: the cluster (default: ~/.kube/config).
* ``E2E_JOB_NODE_SELECTOR``: JSON nodeSelector for the rule Jobs, so they run
  on a real node, for example ``{"kubernetes.io/hostname": "kind-control-plane"}``.
* ``E2E_JOB_IMAGE``: image for the rule Jobs (default: busybox).
* ``E2E_RESTART_COMMAND``: when set, this shell command runs halfway through
  the rollout and must restart the operator, to show that a new operator
  process carries on (for example ``kubectl delete pod -n <namespace> -l
  control-plane=controller-manager``).
"""

import json
import os
import subprocess
import sys
import time

import pytest
import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "roles", "mutex_common", "filter_plugins"))

import nodeupgrade as nu  # noqa: E402

kubernetes = pytest.importorskip("kubernetes")
from kubernetes import config, dynamic  # noqa: E402
from kubernetes.dynamic.exceptions import NotFoundError  # noqa: E402

NAMESPACE = "mutex-e2e"
JOB_NAMESPACE = "mutex-e2e-jobs"
WORKERS = ["worker-a", "worker-b", "worker-c"]
OLD, NEW, NEWER = "4.18.10", "4.19.2", "4.19.3"
FAKE_LABEL = "e2e.nodeupgrade.redhat-na-ssa.github.io/fake"
STUB_ANNOTATION = "e2e.nodeupgrade.redhat-na-ssa.github.io/stub"
MERGE = {"content_type": "application/merge-patch+json"}
JOB_IMAGE = os.environ.get("E2E_JOB_IMAGE", "docker.io/library/busybox:1.37.0")
JOB_NODE_SELECTOR = json.loads(os.environ.get("E2E_JOB_NODE_SELECTOR") or "{}")
TIMEOUT = int(os.environ.get("E2E_TIMEOUT", "600"))


def wait_for(check, timeout=120, interval=1.0, what="condition"):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        try:
            last = check()
        except NotFoundError:
            last = None
        if last:
            return last
        time.sleep(interval)
    raise AssertionError("timed out after %ss waiting for %s" % (timeout, what))


def condition(obj, condition_type):
    for item in (obj.get("status") or {}).get("conditions") or []:
        if item["type"] == condition_type:
            return item
    return {}


def job_spec(command, backoff_limit=1):
    pod = {"restartPolicy": "Never",
           "containers": [{"name": "main", "image": JOB_IMAGE, "command": ["sh", "-c", command]}]}
    if JOB_NODE_SELECTOR:
        pod["nodeSelector"] = JOB_NODE_SELECTOR
        pod["tolerations"] = [{"operator": "Exists"}]
    return {"backoffLimit": backoff_limit, "template": {"spec": pod}}


class Cluster(object):
    def __init__(self):
        self.api = dynamic.DynamicClient(config.new_client_from_config())

    def resource(self, api_version, kind):
        return self.api.resources.get(api_version=api_version, kind=kind)

    @property
    def nodes(self):
        return self.resource("v1", "Node")

    @property
    def pools(self):
        return self.resource("machineconfiguration.openshift.io/v1", "MachineConfigPool")

    @property
    def machine_configs(self):
        return self.resource("machineconfiguration.openshift.io/v1", "MachineConfig")

    @property
    def cluster_versions(self):
        return self.resource("config.openshift.io/v1", "ClusterVersion")

    @property
    def jobs(self):
        return self.resource("batch/v1", "Job")

    def mutex(self, kind):
        return self.resource(nu.API_VERSION, kind)

    def get(self, resource, name, namespace=None):
        return resource.get(name=name, namespace=namespace).to_dict()

    def apply(self, resource, body):
        meta = body["metadata"]
        try:
            resource.get(name=meta["name"], namespace=meta.get("namespace"))
        except NotFoundError:
            return resource.create(body=body, namespace=meta.get("namespace"))
        return resource.patch(body=body, name=meta["name"], namespace=meta.get("namespace"), **MERGE)

    def delete(self, resource, name, namespace=None):
        try:
            resource.delete(name=name, namespace=namespace)
        except NotFoundError:
            pass

    def set_cluster_version(self, desired, completed):
        history = [{"state": "Completed" if completed == desired else "Partial", "version": desired}]
        if completed != desired:
            history.append({"state": "Completed", "version": completed})
        self.cluster_versions.status.patch(name="version", body={"status": {
            "desired": {"version": desired}, "history": history}}, **MERGE)

    def node_version(self, name):
        node = self.get(self.nodes, name)
        rendered = node["metadata"]["annotations"].get(nu.MCO_CURRENT_CONFIG)
        if not rendered:
            return None
        mc = self.get(self.machine_configs, rendered)
        return mc["metadata"]["annotations"][nu.MCO_RELEASE_VERSION]

    def run_config(self):
        return self.get(self.mutex("MutexRunConfig"), "rollout", NAMESPACE)


@pytest.fixture(scope="module")
def cluster():
    cluster = Cluster()
    crds = cluster.resource("apiextensions.k8s.io/v1", "CustomResourceDefinition")
    with open(os.path.join(HERE, "manifests", "openshift-apis.yaml")) as handle:
        stubs = [crd for crd in yaml.safe_load_all(handle) if crd]
    for crd in stubs:
        try:
            existing = cluster.get(crds, crd["metadata"]["name"])
        except NotFoundError:
            continue
        if STUB_ANNOTATION not in (existing["metadata"].get("annotations") or {}):
            pytest.exit("%s exists and is not a test stub: refusing to run against OpenShift"
                        % crd["metadata"]["name"], returncode=2)
    for crd in stubs:
        cluster.apply(crds, crd)
    for crd in ("clusterversions.config.openshift.io", "machineconfigpools.machineconfiguration.openshift.io",
                "machineconfigs.machineconfiguration.openshift.io"):
        wait_for(lambda: condition(cluster.get(crds, crd), "Established").get("status") == "True",
                 what="CRD %s" % crd)
    cluster.api.resources.invalidate_cache()

    namespaces = cluster.resource("v1", "Namespace")
    for name in (NAMESPACE, JOB_NAMESPACE):
        cluster.apply(namespaces, {"apiVersion": "v1", "kind": "Namespace", "metadata": {"name": name}})
    for name in WORKERS:
        cluster.apply(cluster.nodes, {
            "apiVersion": "v1", "kind": "Node",
            "metadata": {"name": name, "labels": {"node-role.kubernetes.io/worker": "", FAKE_LABEL: "true"}},
            # Nothing should be scheduled on a node that has no kubelet.
            "spec": {"taints": [{"key": FAKE_LABEL, "value": "true", "effect": "NoSchedule"}]},
        })
    for name, selector in (("master", {"matchLabels": {"node-role.kubernetes.io/master": ""}}),
                           ("worker", {"matchLabels": {"node-role.kubernetes.io/worker": ""}}),
                           ("canary", {"matchLabels": {"node-role.kubernetes.io/canary": ""}})):
        cluster.apply(cluster.pools, {
            "apiVersion": "machineconfiguration.openshift.io/v1", "kind": "MachineConfigPool",
            "metadata": {"name": name}, "spec": {"nodeSelector": selector, "paused": False}})
    cluster.apply(cluster.cluster_versions, {"apiVersion": "config.openshift.io/v1", "kind": "ClusterVersion",
                                             "metadata": {"name": "version"}, "spec": {}})
    cluster.set_cluster_version(OLD, OLD)

    mco = subprocess.Popen([sys.executable, os.path.join(ROOT, "tests", "fake_mco.py"), "--interval", "1"])
    try:
        for name in WORKERS:
            wait_for(lambda: cluster.node_version(name) == OLD, what="fake MCO to settle %s" % name)
        yield cluster
    finally:
        mco.terminate()
        mco.wait()
        for kind in ("MutexRunConfig", "MutexTarget", "MutexRule"):
            for obj in cluster.mutex(kind).get(namespace=NAMESPACE).items:
                cluster.delete(cluster.mutex(kind), obj.metadata.name, NAMESPACE)
        wait_for(lambda: not cluster.mutex("MutexRunConfig").get(namespace=NAMESPACE).items,
                 what="MutexRunConfigs to go away")
        for name in WORKERS:
            cluster.delete(cluster.nodes, name)
        for name in ("master", "worker", "canary"):
            cluster.delete(cluster.pools, name)
        for name in (NAMESPACE, JOB_NAMESPACE):
            cluster.delete(namespaces, name)


def rule(name, pre, post=None, backoff_limit=1):
    spec = {"jobName": name, "jobNamespace": JOB_NAMESPACE, "jobSpec": job_spec(pre, backoff_limit)}
    if post:
        spec["cleanUpJobSpec"] = job_spec(post, backoff_limit)
    return {"apiVersion": nu.API_VERSION, "kind": "MutexRule",
            "metadata": {"name": name, "namespace": NAMESPACE}, "spec": spec}


def wait_valid(cluster, kind, name, status="True"):
    def check():
        obj = cluster.get(cluster.mutex(kind), name, NAMESPACE)
        valid = condition(obj, "Valid")
        current = obj.get("status", {}).get("observedGeneration") == obj["metadata"]["generation"]
        return obj if current and valid.get("status") == status else None
    return wait_for(check, what="%s %s Valid=%s" % (kind, name, status))


def test_rule_validation_is_a_dry_run(cluster):
    bad = rule("bad", "true")
    del bad["spec"]["jobSpec"]["template"]["spec"]["containers"][0]["image"]
    cluster.apply(cluster.mutex("MutexRule"), bad)
    rejected = wait_valid(cluster, "MutexRule", "bad", "False")
    assert "image" in condition(rejected, "Valid")["message"]

    cluster.apply(cluster.mutex("MutexRule"), rule(
        "drain", 'echo "pre $NODE_NAME $TARGET_VERSION"', 'echo "post $NODE_NAME $TARGET_VERSION"'))
    wait_valid(cluster, "MutexRule", "drain")
    assert not cluster.jobs.get(namespace=JOB_NAMESPACE).items
    cluster.delete(cluster.mutex("MutexRule"), "bad", NAMESPACE)


def test_target_lists_pool_nodes(cluster):
    cluster.apply(cluster.mutex("MutexTarget"), {
        "apiVersion": nu.API_VERSION, "kind": "MutexTarget", "metadata": {"name": "workers", "namespace": NAMESPACE},
        "spec": {"machineConfigPools": ["worker"]}})
    target = wait_valid(cluster, "MutexTarget", "workers")
    assert target["status"]["nodes"] == WORKERS


def test_run_config_is_idle_without_an_update(cluster):
    cluster.apply(cluster.mutex("MutexRunConfig"), {
        "apiVersion": nu.API_VERSION, "kind": "MutexRunConfig", "metadata": {"name": "rollout", "namespace": NAMESPACE},
        "spec": {"canary": {"name": "canary"}, "mutexRules": [{"name": "drain"}],
                 "mutexTargets": [{"name": "workers"}]}})
    run_config = wait_for(lambda: condition(cluster.run_config(), "Progressing").get("reason") == "Idle"
                          and cluster.run_config(), what="MutexRunConfig to be Idle")
    assert condition(run_config, "ConfigValid")["status"] == "True"
    assert run_config["metadata"]["finalizers"] == [nu.GROUP + "/finalizer"]
    assert [n["phase"] for n in run_config["status"]["nodes"]] == ["UpToDate"] * 3


def test_rollout_updates_one_node_at_a_time(cluster):
    cluster.set_cluster_version(NEW, OLD)
    wait_for(lambda: cluster.get(cluster.pools, "worker")["spec"].get("paused"), what="worker pool to pause")
    canary = cluster.get(cluster.pools, "canary")
    assert canary["spec"]["nodeSelector"] == {"matchLabels": {nu.RELEASE_LABEL: "true"}}

    # The control plane finishes; the fake MCO renders the new version.
    cluster.set_cluster_version(NEW, NEW)
    order = []
    restarted = False
    deadline = time.time() + TIMEOUT
    while True:
        assert time.time() < deadline, "rollout did not finish; last status: %s" % cluster.run_config().get("status")
        status = cluster.run_config().get("status") or {}
        active = [n["name"] for n in status.get("nodes", []) if n["phase"] in nu.ACTIVE_PHASES]
        assert len(active) <= 1, status
        released = [name for name in WORKERS if nu.RELEASE_LABEL in cluster.get(cluster.nodes, name)["metadata"].get(
            "labels", {}) and cluster.get(cluster.nodes, name)["metadata"]["annotations"].get(nu.PHASE_ANNOTATION)
            != nu.COMPLETE]
        assert len(released) <= 1, released
        if active and active[0] not in order:
            order.append(active[0])
        if active == ["worker-b"] and not restarted and os.environ.get("E2E_RESTART_COMMAND"):
            subprocess.check_call(os.environ["E2E_RESTART_COMMAND"], shell=True)
            restarted = True
        if condition(cluster.run_config(), "Progressing").get("reason") == "RolloutComplete":
            break
        time.sleep(1)

    assert order == WORKERS
    for name in WORKERS:
        assert cluster.node_version(name) == NEW
        assert nu.RELEASE_LABEL not in cluster.get(cluster.nodes, name)["metadata"].get("labels", {})
    worker = cluster.get(cluster.pools, "worker")
    assert worker["spec"]["paused"] is False
    assert worker["spec"]["nodeSelector"] == {"matchLabels": {"node-role.kubernetes.io/worker": ""}}
    canary = cluster.get(cluster.pools, "canary")
    assert canary["spec"]["nodeSelector"] == {"matchLabels": {"node-role.kubernetes.io/canary": ""}}

    jobs = [job.to_dict() for job in cluster.jobs.get(namespace=JOB_NAMESPACE).items]
    seen = sorted((job["metadata"]["annotations"][nu.NODE_ANNOTATION], job["metadata"]["labels"][nu.STAGE_LABEL])
                  for job in jobs)
    assert seen == sorted((name, stage) for name in WORKERS for stage in ("pre-update", "post-update"))
    for job in jobs:
        assert condition(job, "Complete").get("status") == "True"
        node_name = job["metadata"]["annotations"][nu.NODE_ANNOTATION]
        env = {e["name"]: e["value"] for e in job["spec"]["template"]["spec"]["containers"][0]["env"]}
        assert env["NODE_NAME"] == node_name and env["TARGET_VERSION"] == NEW
        terms = job["spec"]["template"]["spec"]["affinity"]["nodeAffinity"][
            "requiredDuringSchedulingIgnoredDuringExecution"]["nodeSelectorTerms"]
        assert terms[0]["matchFields"] == [{"key": "metadata.name", "operator": "NotIn", "values": [node_name]}]


def test_failed_job_holds_the_rollout_and_delete_restores(cluster):
    cluster.apply(cluster.mutex("MutexRule"), rule("fails", "echo failing; exit 1", backoff_limit=0))
    wait_valid(cluster, "MutexRule", "fails")
    cluster.mutex("MutexRunConfig").patch(name="rollout", namespace=NAMESPACE, body={
        "spec": {"mutexRules": [{"name": "fails"}]}}, **MERGE)
    cluster.set_cluster_version(NEWER, NEW)
    wait_for(lambda: cluster.get(cluster.pools, "worker")["spec"].get("paused"), what="worker pool to pause")
    cluster.set_cluster_version(NEWER, NEWER)

    degraded = wait_for(lambda: condition(cluster.run_config(), "Degraded").get("reason") == "JobFailed"
                        and condition(cluster.run_config(), "Degraded"), timeout=TIMEOUT, what="JobFailed")
    assert "delete the Job" in degraded["message"]
    node = cluster.get(cluster.nodes, "worker-a")
    assert node["metadata"]["annotations"][nu.PHASE_ANNOTATION] == nu.PRE_UPDATE
    assert nu.RELEASE_LABEL not in node["metadata"].get("labels", {})
    assert cluster.node_version("worker-a") == NEW

    # Deleting the MutexRunConfig hands the pools back to the MCO.
    cluster.delete(cluster.mutex("MutexRunConfig"), "rollout", NAMESPACE)
    wait_for(lambda: not cluster.mutex("MutexRunConfig").get(namespace=NAMESPACE).items,
             what="the finalizer to finish")
    worker = cluster.get(cluster.pools, "worker")
    assert worker["spec"]["paused"] is False
    assert worker["spec"]["nodeSelector"] == {"matchLabels": {"node-role.kubernetes.io/worker": ""}}
    assert nu.PAUSED_BY_ANNOTATION not in (worker["metadata"].get("annotations") or {})
    canary = cluster.get(cluster.pools, "canary")
    assert canary["spec"]["nodeSelector"] == {"matchLabels": {"node-role.kubernetes.io/canary": ""}}
    for name in WORKERS:
        node = cluster.get(cluster.nodes, name)
        assert nu.RELEASE_LABEL not in node["metadata"].get("labels", {})
        assert not [key for key in node["metadata"]["annotations"] if key.startswith(nu.GROUP)]
