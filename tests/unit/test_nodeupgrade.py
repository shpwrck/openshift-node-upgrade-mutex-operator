import copy
import json

import pytest

import fake_mco
import nodeupgrade as nu

OLD = "4.18.10"
NEW = "4.19.2"
NOW = "2026-10-20T12:00:00Z"
WORKER = {"matchLabels": {"node-role.kubernetes.io/worker": ""}}
INFRA = {"matchLabels": {"node-role.kubernetes.io/infra": ""}}
CANARY = {"matchLabels": {"node-role.kubernetes.io/canary": ""}}


def node(name, roles=("worker",), config=None, labels=None, annotations=None):
    node_labels = {"node-role.kubernetes.io/%s" % role: "" for role in roles}
    node_labels.update(labels or {})
    node_annotations = {}
    if config:
        node_annotations = {nu.MCO_CURRENT_CONFIG: config, nu.MCO_DESIRED_CONFIG: config, nu.MCO_STATE: "Done"}
    node_annotations.update(annotations or {})
    return {"metadata": {"name": name, "labels": node_labels, "annotations": node_annotations}}


def pool(name, selector, paused=False, config=None, annotations=None):
    return {
        "metadata": {"name": name, "annotations": dict(annotations or {})},
        "spec": {"nodeSelector": copy.deepcopy(selector), "paused": paused,
                 "configuration": {"name": config} if config else {}},
    }


def machine_config(name, version):
    return {"metadata": {"name": name, "annotations": {nu.MCO_RELEASE_VERSION: version}}}


def cluster_version(desired, completed=None):
    history = [{"state": "Completed" if completed == desired else "Partial", "version": desired}]
    if completed and completed != desired:
        history.append({"state": "Completed", "version": completed})
    return {"spec": {}, "status": {"desired": {"version": desired}, "history": history}}


def validated(obj, valid=True, message=""):
    obj["metadata"].setdefault("generation", 1)
    obj["status"] = {
        "observedGeneration": obj["metadata"]["generation"],
        "conditions": [{"type": "Valid", "status": "True" if valid else "False", "message": message}],
    }
    return obj


def rule(name, cleanup=True, namespace="mutex"):
    job_spec = {"template": {"spec": {"restartPolicy": "Never", "containers": [{"name": "c", "image": "busybox"}]}}}
    spec = {"jobName": name, "jobNamespace": "jobs", "jobSpec": job_spec, "type": "kubernetes"}
    if cleanup:
        spec["cleanUpJobSpec"] = copy.deepcopy(job_spec)
    return validated({"metadata": {"name": name, "namespace": namespace}, "spec": spec})


def target(name, pools, namespace="mutex"):
    return validated({"metadata": {"name": name, "namespace": namespace}, "spec": {"machineConfigPools": pools}})


def run_config(name="rollout", namespace="mutex", rules=("drain-app",), targets=("workers",), canary="canary",
               created="2026-10-01T00:00:00Z", uid="uid-1"):
    return {
        "metadata": {"name": name, "namespace": namespace, "uid": uid, "generation": 1,
                     "creationTimestamp": created},
        "spec": {
            "canary": {"name": canary},
            "mutexRules": [{"name": r, "namespace": namespace} for r in rules],
            "mutexTargets": [{"name": t, "namespace": namespace} for t in targets],
        },
    }


class Cluster(object):
    """An in-memory cluster: the planner's patches and Jobs are applied to it,
    and the fake MCO moves nodes between rendered configs."""

    def __init__(self, workers=("worker-a", "worker-b"), infra=(), target_pools=("worker",)):
        self.rendered = OLD
        self.cv = cluster_version(OLD, OLD)
        self.pools = [
            pool("master", {"matchLabels": {"node-role.kubernetes.io/master": ""}}),
            pool("worker", WORKER),
            pool("canary", CANARY),
        ]
        if infra:
            self.pools.append(pool("infra", INFRA))
        self.nodes = [node("master-0", roles=("master",))]
        self.nodes += [node(name) for name in workers]
        self.nodes += [node(name, roles=("worker", "infra")) for name in infra]
        self.rules = [rule("drain-app")]
        self.targets = [target("workers", list(target_pools))]
        self.run_config = run_config()
        self.run_configs = [self.run_config]
        self.jobs = []
        self.machine_configs = {}
        self.history = []
        self.job_counter = 0
        self.mco()
        self.mco()

    # The fake MCO
    def mco(self):
        configs, pool_patches, node_patches = fake_mco.step(self.rendered, self.pools, self.nodes)
        for config in configs:
            self.machine_configs[config["metadata"]["name"]] = config
        self._patch(self.pools, pool_patches)
        self._patch(self.nodes, node_patches)

    def _patch(self, objects, patches):
        for index, obj in enumerate(objects):
            patch = patches.get(obj["metadata"]["name"])
            if patch:
                objects[index] = fake_mco.apply_merge_patch(obj, patch)

    def node(self, name):
        return next(n for n in self.nodes if n["metadata"]["name"] == name)

    def pool(self, name):
        return next(p for p in self.pools if p["metadata"]["name"] == name)

    def version(self, name):
        config = self.node(name)["metadata"]["annotations"].get(nu.MCO_CURRENT_CONFIG)
        return self.machine_configs[config]["metadata"]["annotations"][nu.MCO_RELEASE_VERSION]

    def start_update(self):
        self.cv = cluster_version(NEW, OLD)

    def finish_control_plane(self):
        self.cv = cluster_version(NEW, NEW)
        self.rendered = NEW

    def plan(self, **kwargs):
        args = dict(cluster_version=self.cv, rules=self.rules, targets=self.targets, pools=self.pools,
                    nodes=self.nodes, machine_configs=list(self.machine_configs.values()), jobs=self.jobs,
                    api_services=[], run_configs=self.run_configs, now=NOW)
        args.update(kwargs)
        return nu.plan_rollout(self.run_config, **args)

    def apply(self, plan):
        self._patch(self.nodes, {item["name"]: item["patch"] for item in plan["node_patches"]})
        self._patch(self.pools, {item["name"]: item["patch"] for item in plan["pool_patches"]})
        for job in plan["jobs"]:
            job = copy.deepcopy(job)
            self.job_counter += 1
            job["metadata"]["name"] = job["metadata"]["generateName"] + str(self.job_counter)
            job["metadata"]["creationTimestamp"] = "2026-10-20T12:%02d:00Z" % self.job_counter
            job["status"] = {}
            self.jobs.append(job)
        self.run_config = fake_mco.apply_merge_patch(self.run_config, {"status": dict(
            plan["status"], conditions=plan["conditions"])})
        self.run_configs = [self.run_config]

    def finish_jobs(self, result="Complete"):
        for job in self.jobs:
            if not job["status"]:
                job["status"] = {"conditions": [{"type": result, "status": "True"}]}

    def step(self, finish_jobs=True):
        plan = self.plan()
        self.apply(plan)
        self.history.append(plan)
        if finish_jobs:
            self.finish_jobs()
        self.mco()
        return plan


def condition(plan, condition_type):
    return next(c for c in plan["conditions"] if c["type"] == condition_type)


def reason(plan):
    return condition(plan, "Progressing")["reason"]


# ---------------------------------------------------------------------------
# Helpers


def test_merge_patch_round_trip():
    old = {"a": 1, "b": {"c": 2, "d": 3}, "e": [1]}
    new = {"a": 1, "b": {"c": 5}, "f": True}
    patch = nu.merge_patch(old, new)
    assert patch == {"b": {"c": 5, "d": None}, "e": None, "f": True}
    assert fake_mco.apply_merge_patch(old, patch) == new


def test_empty_selector_matches_nothing():
    assert not nu.selector_matches({}, {"a": "b"})
    assert nu.selector_matches({"matchExpressions": [{"key": "a", "operator": "Exists"}]}, {"a": ""})
    assert not nu.selector_matches({"matchExpressions": [{"key": "a", "operator": "DoesNotExist"}]}, {"a": ""})
    assert nu.selector_matches({"matchExpressions": [{"key": "a", "operator": "NotIn", "values": ["x"]}]}, {})


def test_home_pool_follows_mco_rules():
    pools = [pool("master", {"matchLabels": {"node-role.kubernetes.io/master": ""}}), pool("worker", WORKER),
             pool("infra", INFRA), pool("gpu", {"matchLabels": {"gpu": "true"}})]
    assert nu.home_pool(node("m", roles=("master", "worker")), pools) == ("master", None)
    assert nu.home_pool(node("i", roles=("worker", "infra")), pools) == ("infra", None)
    assert nu.home_pool(node("w"), pools) == ("worker", None)
    windows = node("win", labels={"kubernetes.io/os": "windows"})
    assert nu.home_pool(windows, pools) == (None, None)
    name, problem = nu.home_pool(node("both", roles=("worker", "infra"), labels={"gpu": "true"}), pools)
    assert name is None and "gpu, infra" in problem


def test_home_pool_ignores_rollout_changes():
    canary = pool("canary", {"matchLabels": {nu.RELEASE_LABEL: "true"}},
                  annotations={nu.ORIGINAL_SELECTOR_ANNOTATION: json.dumps(CANARY)})
    worker = pool("worker", {"matchLabels": WORKER["matchLabels"],
                             "matchExpressions": [{"key": nu.RELEASE_LABEL, "operator": "DoesNotExist"}]})
    released = node("w", labels={nu.RELEASE_LABEL: "true"})
    assert nu.home_pool(released, [worker, canary]) == ("worker", None)


def test_target_summary():
    pools = [pool("master", {"matchLabels": {"node-role.kubernetes.io/master": ""}}), pool("worker", WORKER)]
    nodes = [node("b"), node("a"), node("m", roles=("master",))]
    assert nu.target_summary(pools, nodes, ["worker"]) == {"nodes": ["a", "b"], "problems": []}
    summary = nu.target_summary(pools, nodes, ["worker", "master", "gone"])
    assert summary["problems"] == ["the master pool cannot be a target", "MachineConfigPool gone not found"]


def test_job_spec_for_node_keeps_the_template():
    job_spec = {"template": {"spec": {
        "initContainers": [{"name": "init", "env": [{"name": "NODE_NAME", "value": "stale"}]}],
        "containers": [{"name": "a", "env": [{"name": "KEEP", "value": "1"}]}, {"name": "b"}],
        "affinity": {
            "podAntiAffinity": {"x": 1},
            "nodeAffinity": {"requiredDuringSchedulingIgnoredDuringExecution": {"nodeSelectorTerms": [
                {"matchExpressions": [{"key": "zone", "operator": "In", "values": ["a"]}]},
                {"matchExpressions": [{"key": "zone", "operator": "In", "values": ["b"]}]},
            ]}},
        },
    }}}
    original = copy.deepcopy(job_spec)
    spec = nu.job_spec_for_node(job_spec, "worker-a", "rule", "pre-update", NEW)
    assert job_spec == original
    pod = spec["template"]["spec"]
    for container in pod["initContainers"] + pod["containers"]:
        env = {item["name"]: item["value"] for item in container["env"]}
        assert env["NODE_NAME"] == "worker-a" and env["TARGET_VERSION"] == NEW
        assert env["MUTEX_STAGE"] == "pre-update" and env["MUTEX_RULE"] == "rule"
    assert {"name": "KEEP", "value": "1"} in pod["containers"][0]["env"]
    assert pod["affinity"]["podAntiAffinity"] == {"x": 1}
    terms = pod["affinity"]["nodeAffinity"]["requiredDuringSchedulingIgnoredDuringExecution"]["nodeSelectorTerms"]
    assert len(terms) == 2
    for term in terms:
        assert term["matchExpressions"][0]["key"] == "zone"
        assert term["matchFields"] == [{"key": "metadata.name", "operator": "NotIn", "values": ["worker-a"]}]


def test_job_spec_for_node_without_affinity():
    spec = nu.job_spec_for_node({"template": {"spec": {"containers": [{"name": "a"}]}}}, "n", "r", "post-update", NEW)
    terms = spec["template"]["spec"]["affinity"]["nodeAffinity"][
        "requiredDuringSchedulingIgnoredDuringExecution"]["nodeSelectorTerms"]
    assert terms == [{"matchFields": [{"key": "metadata.name", "operator": "NotIn", "values": ["n"]}]}]


def test_build_job_names_and_labels():
    job = nu.build_job(rule("drain-app"), "post-update", "worker-a", NEW, run_config())
    assert job["metadata"]["generateName"] == "cleanup-drain-app-"
    assert job["metadata"]["namespace"] == "jobs"
    assert job["metadata"]["labels"] == {nu.RUN_CONFIG_UID_LABEL: "uid-1", nu.STAGE_LABEL: "post-update"}
    assert job["metadata"]["annotations"][nu.RULE_ANNOTATION] == "mutex/drain-app"
    assert job["metadata"]["annotations"][nu.NODE_ANNOTATION] == "worker-a"


def test_api_error_message():
    body = b'{"kind":"Status","message":"Job.batch \\"x\\" is invalid: spec.template.spec.containers: Required value"}'
    message = "Failed to create object: %r" % body
    assert nu.api_error_message(message) == 'Job.batch "x" is invalid: spec.template.spec.containers: Required value'
    assert nu.api_error_message("plain failure") == "plain failure"


def test_rule_status():
    accepted = nu.rule_status(rule("drain-app"), [{"item": "pre-update", "failed": False}], NOW)
    assert accepted["observedGeneration"] == 1
    assert accepted["conditions"][0]["status"] == "True"
    results = [{"item": "pre-update", "failed": False},
               {"item": "post-update", "failed": True, "msg": "Failed to create object: b'{\"message\":\"nope\"}'"}]
    rejected = nu.rule_status(rule("drain-app"), results, NOW)["conditions"][0]
    assert rejected["status"] == "False" and rejected["message"] == "post-update Job: nope"


def test_target_status():
    pools = [pool("worker", WORKER)]
    status = nu.target_status(target("workers", ["worker"]), pools, [node("b"), node("a")], True, NOW)
    assert status["nodes"] == ["a", "b"]
    assert status["conditions"][0]["message"] == "Targets 2 node(s)"
    status = nu.target_status(target("workers", ["worker"]), [], [], False, NOW)
    assert status["conditions"][0]["status"] == "False"
    assert "needs OpenShift" in status["conditions"][0]["message"]


def test_make_condition_keeps_transition_time():
    obj = {"status": {"conditions": [{"type": "Valid", "status": "True", "lastTransitionTime": "then"}]}}
    assert nu.make_condition(obj, "Valid", True, "Ok", "changed message", NOW)["lastTransitionTime"] == "then"
    assert nu.make_condition(obj, "Valid", False, "Bad", "", NOW)["lastTransitionTime"] == NOW


def test_rendered_config_names():
    nodes = [node("a", config="rendered-worker-1", annotations={nu.MCO_DESIRED_CONFIG: "rendered-worker-2"})]
    pools = [pool("worker", WORKER, config="rendered-worker-3")]
    assert nu.rendered_config_names(nodes, pools) == ["rendered-worker-1", "rendered-worker-2", "rendered-worker-3"]


# ---------------------------------------------------------------------------
# The planner, step by step


def test_idle_when_everything_is_current():
    cluster = Cluster()
    plan = cluster.plan()
    assert reason(plan) == "Idle"
    assert condition(plan, "ConfigValid")["status"] == "True"
    assert not plan["pool_patches"] and not plan["node_patches"] and not plan["jobs"]
    assert plan["requeue_after"] is None
    assert [n["phase"] for n in plan["status"]["nodes"]] == ["UpToDate", "UpToDate"]


def test_update_pauses_pools_before_the_mco_renders():
    cluster = Cluster()
    cluster.start_update()
    plan = cluster.plan()
    assert reason(plan) == "PausingPools"
    patches = {item["name"]: item["patch"] for item in plan["pool_patches"]}
    assert patches["worker"]["spec"]["paused"] is True
    assert patches["worker"]["metadata"]["annotations"][nu.PAUSED_BY_ANNOTATION] == "mutex/rollout"
    assert {"key": nu.RELEASE_LABEL, "operator": "DoesNotExist"} in \
        patches["worker"]["spec"]["nodeSelector"]["matchExpressions"]
    assert patches["canary"]["spec"]["nodeSelector"] == {
        "matchLabels": {"node-role.kubernetes.io/canary": None, nu.RELEASE_LABEL: "true"}}
    assert json.loads(patches["canary"]["metadata"]["annotations"][nu.ORIGINAL_SELECTOR_ANNOTATION]) == CANARY
    assert "master" not in patches
    cluster.apply(plan)
    plan = cluster.plan()
    assert reason(plan) == "WaitingForControlPlane"
    assert not plan["pool_patches"]


def test_waits_for_the_canary_to_render():
    cluster = Cluster()
    cluster.start_update()
    cluster.step()
    cluster.cv = cluster_version(NEW, NEW)
    assert reason(cluster.plan()) == "WaitingForCanary"


def test_full_rollout_one_node_at_a_time():
    cluster = Cluster(workers=("worker-b", "worker-a", "worker-c"))
    cluster.start_update()
    for _ in range(3):
        cluster.step()
    cluster.finish_control_plane()
    order = []
    for _ in range(200):
        plan = cluster.step()
        busy = [n["name"] for n in plan["status"]["nodes"] if n["phase"] in nu.ACTIVE_PHASES]
        assert len(busy) <= 1
        released = [n["metadata"]["name"] for n in cluster.nodes
                    if nu.RELEASE_LABEL in n["metadata"]["labels"]
                    and n["metadata"]["annotations"].get(nu.PHASE_ANNOTATION) != nu.COMPLETE]
        assert len(released) <= 1
        if busy and (not order or order[-1] != busy[0]):
            order.append(busy[0])
        if reason(plan) in ("RolloutComplete",):
            break
    else:
        pytest.fail("rollout did not finish: %s" % [reason(p) for p in cluster.history[-5:]])

    assert order == ["worker-a", "worker-b", "worker-c"]
    for name in order:
        assert cluster.version(name) == NEW
        assert nu.RELEASE_LABEL not in cluster.node(name)["metadata"]["labels"]
    assert cluster.pool("canary")["spec"]["nodeSelector"] == CANARY
    assert cluster.pool("worker")["spec"]["nodeSelector"] == WORKER
    assert cluster.pool("worker")["spec"]["paused"] is False
    for item in cluster.pools:
        assert not set(item["metadata"]["annotations"]) & {nu.PAUSED_BY_ANNOTATION, nu.ORIGINAL_SELECTOR_ANNOTATION}
    # Each node ran the pre-update Job, then the post-update Job.
    stages = [(j["metadata"]["annotations"][nu.NODE_ANNOTATION], j["metadata"]["labels"][nu.STAGE_LABEL])
              for j in cluster.jobs]
    assert stages == [(name, stage) for name in order for stage in ("pre-update", "post-update")]
    final = cluster.plan()
    assert reason(final) == "RolloutComplete"
    assert [n["phase"] for n in final["status"]["nodes"]] == ["Complete"] * 3
    assert not final["pool_patches"] and not final["node_patches"]


def test_nodes_are_not_updated_before_release():
    cluster = Cluster()
    cluster.start_update()
    cluster.step()
    cluster.finish_control_plane()
    for _ in range(5):
        cluster.mco()
    assert cluster.version("worker-a") == OLD and cluster.version("worker-b") == OLD
    assert cluster.version("master-0") == NEW


def _drive_until(cluster, wanted, limit=50, finish_jobs=True):
    for _ in range(limit):
        plan = cluster.step(finish_jobs=finish_jobs)
        if reason(plan) == wanted:
            return plan
    pytest.fail("never reached %s: %s" % (wanted, [reason(p) for p in cluster.history[-5:]]))


def _ready_cluster(**kwargs):
    cluster = Cluster(**kwargs)
    cluster.start_update()
    cluster.step()
    cluster.finish_control_plane()
    cluster.mco()
    return cluster


def test_failed_job_blocks_until_deleted():
    cluster = _ready_cluster()
    plan = cluster.step(finish_jobs=False)
    assert reason(plan) == "RunningPreUpdateJobs"
    assert plan["requeue_after"] == "10s"
    cluster.finish_jobs("Failed")
    plan = cluster.step()
    assert reason(plan) == "Blocked"
    degraded = condition(plan, "Degraded")
    assert degraded["status"] == "True" and degraded["reason"] == "JobFailed"
    assert "delete the Job" in degraded["message"]
    assert not plan["jobs"]
    assert nu.RELEASE_LABEL not in cluster.node("worker-a")["metadata"]["labels"]
    cluster.jobs = []
    plan = cluster.step(finish_jobs=False)
    assert len(plan["jobs"]) == 1
    assert condition(plan, "Degraded")["status"] == "False"


def test_rules_run_in_order_and_are_remembered():
    cluster = _ready_cluster()
    cluster.rules.append(rule("second", cleanup=False))
    cluster.run_config["spec"]["mutexRules"].append({"name": "second", "namespace": "mutex"})
    first = cluster.step()
    assert first["jobs"][0]["metadata"]["generateName"] == "drain-app-"
    second = cluster.step()
    assert second["jobs"][0]["metadata"]["generateName"] == "second-"
    annotations = cluster.node("worker-a")["metadata"]["annotations"]
    assert annotations[nu.PRE_COMPLETE_ANNOTATION] == "mutex/drain-app"
    # A Job that has gone away (for example after its TTL) is not run again.
    cluster.jobs = [job for job in cluster.jobs if job["metadata"]["generateName"] == "second-"]
    third = cluster.step()
    assert not third["jobs"]
    assert reason(third) == "UpdatingNode"
    assert cluster.node("worker-a")["metadata"]["labels"][nu.RELEASE_LABEL] == "true"


def test_degraded_node_is_reported():
    cluster = _ready_cluster()
    _drive_until(cluster, "UpdatingNode")
    node_obj = cluster.node("worker-a")
    node_obj["metadata"]["annotations"][nu.MCO_STATE] = "Degraded"
    plan = cluster.plan()
    assert condition(plan, "Degraded")["reason"] == "NodeDegraded"
    assert plan["requeue_after"] == "15s"


def test_resumes_from_state_on_the_cluster():
    cluster = _ready_cluster()
    _drive_until(cluster, "UpdatingNode")
    # A new operator process has nothing but the cluster to go on.
    cluster.run_config.pop("status")
    plan = cluster.plan()
    assert plan["status"]["currentNode"] == "worker-a"
    assert not plan["jobs"]
    assert {n["name"]: n["phase"] for n in plan["status"]["nodes"]}["worker-a"] in ("Updating", "PostUpdate")


def test_waits_for_nodes_the_mco_is_already_updating():
    cluster = _ready_cluster()
    cluster.node("worker-b")["metadata"]["annotations"][nu.MCO_STATE] = "Working"
    plan = cluster.plan()
    assert reason(plan) == "WaitingForNodes"
    assert not plan["node_patches"]


def test_waits_for_unavailable_api_services():
    cluster = _ready_cluster()
    service = {"metadata": {"name": "v1.metrics.k8s.io"},
               "status": {"conditions": [{"type": "Available", "status": "False"}]}}
    plan = cluster.plan(api_services=[service])
    assert reason(plan) == "WaitingForCluster"
    assert "v1.metrics.k8s.io" in condition(plan, "Progressing")["message"]


def test_degraded_canary_blocks():
    cluster = _ready_cluster()
    cluster.pool("canary")["status"] = {"conditions": [{"type": "Degraded", "status": "True"}]}
    plan = cluster.plan()
    assert condition(plan, "Degraded")["reason"] == "CanaryDegraded"
    assert not plan["node_patches"]


def test_deleting_mid_rollout_restores_everything():
    cluster = _ready_cluster()
    _drive_until(cluster, "UpdatingNode")
    plan = cluster.plan(deleting=True)
    assert reason(plan) == "Deleted"
    assert plan["requeue_after"] is None
    cluster.apply(plan)
    worker = cluster.node("worker-a")
    assert nu.RELEASE_LABEL not in worker["metadata"]["labels"]
    assert not [key for key in worker["metadata"]["annotations"] if key.startswith(nu.GROUP)]
    assert cluster.pool("canary")["spec"]["nodeSelector"] == CANARY
    assert cluster.pool("worker")["spec"] == dict(cluster.pool("worker")["spec"], paused=False, nodeSelector=WORKER)


def test_pools_paused_by_someone_else_stay_paused():
    cluster = Cluster()
    cluster.pool("worker")["spec"]["paused"] = True
    cluster.start_update()
    plan = cluster.plan()
    patch = {item["name"]: item["patch"] for item in plan["pool_patches"]}["worker"]
    assert "paused" not in patch["spec"] and "metadata" not in patch
    cluster.apply(plan)
    plan = cluster.plan(deleting=True)
    patch = {item["name"]: item["patch"] for item in plan["pool_patches"]}["worker"]
    assert "paused" not in patch["spec"]


def test_older_run_config_goes_first():
    cluster = _ready_cluster()
    older = run_config(name="older", created="2026-09-01T00:00:00Z", uid="uid-0")
    plan = cluster.plan(run_configs=[older, cluster.run_config])
    assert reason(plan) == "Blocked"
    assert condition(plan, "Degraded")["reason"] == "Conflict"
    assert not plan["pool_patches"] and not plan["node_patches"] and not plan["jobs"]
    # Deleting the newer one must not undo the older one's work.
    plan = cluster.plan(run_configs=[older, cluster.run_config], deleting=True)
    assert not plan["pool_patches"] and not plan["node_patches"]


@pytest.mark.parametrize("mutate, message", [
    (lambda c: c.rules.clear(), "MutexRule mutex/drain-app not found"),
    (lambda c: c.rules[0]["metadata"].update(generation=2), "has not been validated yet"),
    (lambda c: validated(c.rules[0], valid=False, message="bad image"), "is not valid: bad image"),
    (lambda c: c.targets[0]["spec"].update(machineConfigPools=["master"]), "the master pool cannot be a target"),
    (lambda c: c.targets[0]["spec"].update(machineConfigPools=["worker", "canary"]), "is also a target"),
    (lambda c: c.pool("canary")["spec"].update(paused=True), "canary MachineConfigPool canary is paused"),
    (lambda c: c.run_config["spec"]["canary"].update(name="missing"), "canary MachineConfigPool missing not found"),
    (lambda c: c.nodes.append(node("canary-0", roles=("worker", "canary"))), "must not select any nodes"),
])
def test_invalid_configuration(mutate, message):
    cluster = Cluster()
    mutate(cluster)
    cluster.start_update()
    plan = cluster.plan()
    valid = condition(plan, "ConfigValid")
    assert valid["status"] == "False" and message in valid["message"]
    assert reason(plan) == "InvalidConfig"
    assert not plan["pool_patches"] and not plan["node_patches"] and not plan["jobs"]


def test_invalid_configuration_mid_rollout_is_degraded():
    cluster = _ready_cluster()
    _drive_until(cluster, "UpdatingNode")
    cluster.rules.clear()
    plan = cluster.plan()
    assert reason(plan) == "Blocked"
    assert condition(plan, "Degraded")["reason"] == "InvalidConfig"


def test_stale_progress_from_an_earlier_update_is_ignored():
    cluster = _ready_cluster()
    cluster.node("worker-a")["metadata"]["annotations"].update({
        nu.PHASE_ANNOTATION: nu.COMPLETE, nu.TARGET_VERSION_ANNOTATION: OLD})
    plan = cluster.step()
    assert plan["status"]["currentNode"] == "worker-a"
    assert {n["name"]: n["phase"] for n in plan["status"]["nodes"]}["worker-a"] == "PreUpdate"


def test_infra_nodes_leave_their_custom_pool_for_the_canary():
    cluster = _ready_cluster(workers=("worker-a",), infra=("infra-a",), target_pools=("infra", "worker"))
    order = []
    for _ in range(100):
        plan = cluster.step()
        if plan["status"]["currentNode"] and plan["status"]["currentNode"] not in order:
            order.append(plan["status"]["currentNode"])
        if reason(plan) == "RolloutComplete":
            break
    assert order == ["infra-a", "worker-a"]
    assert cluster.version("infra-a") == NEW and cluster.version("worker-a") == NEW
    assert cluster.pool("infra")["spec"]["nodeSelector"] == INFRA


def test_transition_time_survives_reconciles():
    cluster = _ready_cluster()
    first = cluster.step(finish_jobs=False)
    cluster.run_config["status"]["conditions"][1]["lastTransitionTime"] = "earlier"
    second = cluster.plan(now="2026-10-20T13:00:00Z")
    assert condition(first, "Progressing")["status"] == condition(second, "Progressing")["status"] == "True"
    assert condition(second, "Progressing")["lastTransitionTime"] == "earlier"
