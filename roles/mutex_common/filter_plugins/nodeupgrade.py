"""Decision logic for the OpenShift Node Upgrade Mutex Operator.

The roles gather cluster state with kubernetes.core.k8s_info, hand it to the
filters below, and apply the patches and Jobs the filters return. The filters
never talk to the cluster, so every decision can be unit tested
(tests/unit/test_nodeupgrade.py).

Rollout progress is stored on the cluster, never in the operator:

* Target pools are paused and get a ``<group>/release DoesNotExist`` term in
  their node selector. The canary pool's selector is replaced with
  ``<group>/release: "true"`` (the original is kept in an annotation).
* A node moves into the canary pool, and so gets updated, when the operator
  labels it ``<group>/release=true``.
* Each node carries ``<group>/phase`` and ``<group>/target-version``
  annotations, plus the rules whose Jobs already succeeded.

A restarted operator reads all of that back and carries on.
"""

import ast
import copy
import json
from datetime import datetime, timezone

GROUP = "nodeupgrade.redhat-na-ssa.github.io"
API_VERSION = GROUP + "/v1alpha1"

RELEASE_LABEL = GROUP + "/release"
PHASE_ANNOTATION = GROUP + "/phase"
TARGET_VERSION_ANNOTATION = GROUP + "/target-version"
RUN_CONFIG_ANNOTATION = GROUP + "/run-config"
PRE_COMPLETE_ANNOTATION = GROUP + "/pre-update-complete"
POST_COMPLETE_ANNOTATION = GROUP + "/post-update-complete"
PAUSED_BY_ANNOTATION = GROUP + "/paused-by"
ORIGINAL_SELECTOR_ANNOTATION = GROUP + "/original-node-selector"
RUN_CONFIG_UID_LABEL = GROUP + "/run-config-uid"
STAGE_LABEL = GROUP + "/stage"
NODE_ANNOTATION = GROUP + "/node"
RULE_ANNOTATION = GROUP + "/rule"

MCO_CURRENT_CONFIG = "machineconfiguration.openshift.io/currentConfig"
MCO_DESIRED_CONFIG = "machineconfiguration.openshift.io/desiredConfig"
MCO_STATE = "machineconfiguration.openshift.io/state"
MCO_RELEASE_VERSION = "machineconfiguration.openshift.io/release-image-version"

PRE_UPDATE_STAGE = "pre-update"
POST_UPDATE_STAGE = "post-update"

# Node phases. Pending and UpToDate are derived; the others are stored on the node.
PENDING = "Pending"
PRE_UPDATE = "PreUpdate"
UPDATING = "Updating"
POST_UPDATE = "PostUpdate"
COMPLETE = "Complete"
UP_TO_DATE = "UpToDate"
ACTIVE_PHASES = (PRE_UPDATE, UPDATING, POST_UPDATE)

# Seconds between reconciles while the operator waits on something.
REQUEUE_JOBS = 10
REQUEUE_NODE = 15
REQUEUE_STEP = 5
REQUEUE_WAIT = 30
REQUEUE_BLOCKED = 60

INJECTED_ENV = ("NODE_NAME", "MUTEX_RULE", "MUTEX_STAGE", "TARGET_VERSION")


# ---------------------------------------------------------------------------
# Small helpers


def _meta(obj):
    return (obj or {}).get("metadata") or {}


def _name(obj):
    return _meta(obj).get("name")


def _labels(obj):
    return _meta(obj).get("labels") or {}


def _annotations(obj):
    return _meta(obj).get("annotations") or {}


def _spec(obj):
    return (obj or {}).get("spec") or {}


def _status(obj):
    return (obj or {}).get("status") or {}


def _ref(namespace, name):
    return "%s/%s" % (namespace, name)


def _condition(obj, condition_type):
    for condition in _status(obj).get("conditions") or []:
        if condition.get("type") == condition_type:
            return condition
    return None


def _condition_true(obj, condition_type):
    condition = _condition(obj, condition_type)
    return bool(condition) and condition.get("status") == "True"


def _timestamp(now=None):
    if now:
        return now
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _split_list(value):
    return [item for item in (value or "").split(",") if item]


def make_condition(obj, condition_type, status, reason, message, now=None):
    """A status condition for obj. lastTransitionTime only moves when the
    status does."""
    status = "True" if status else "False"
    previous = _condition(obj, condition_type) or {}
    if previous.get("status") == status and previous.get("lastTransitionTime"):
        transitioned = previous["lastTransitionTime"]
    else:
        transitioned = _timestamp(now)
    return {
        "type": condition_type,
        "status": status,
        "reason": reason,
        "message": message,
        "lastTransitionTime": transitioned,
    }


def api_error_message(message):
    """Pull the API server's message out of a kubernetes.core error, which
    embeds the response body as a bytes literal."""
    message = str(message or "")
    for quote in ("b'", 'b"'):
        start = message.find(quote)
        if start < 0:
            continue
        try:
            body = json.loads(ast.literal_eval(message[start:]).decode("utf-8"))
        except (ValueError, SyntaxError, UnicodeDecodeError):
            continue
        if isinstance(body, dict) and body.get("message"):
            return body["message"]
    return message


def merge_patch(old, new):
    """Return the JSON merge patch (RFC 7386) that turns ``old`` into ``new``."""
    if not isinstance(old, dict) or not isinstance(new, dict):
        return copy.deepcopy(new)
    patch = {}
    for key in old:
        if key not in new:
            patch[key] = None
    for key, value in new.items():
        if key not in old:
            patch[key] = copy.deepcopy(value)
        elif old[key] != value:
            patch[key] = merge_patch(old[key], value)
    return patch


# ---------------------------------------------------------------------------
# Label selectors and pool membership (mirrors the MCO's own rules)


def selector_matches(selector, labels):
    """Match like metav1.LabelSelectorAsSelector, except that an empty selector
    matches nothing, which is how the MCO treats pools."""
    selector = selector or {}
    match_labels = selector.get("matchLabels") or {}
    match_expressions = selector.get("matchExpressions") or []
    if not match_labels and not match_expressions:
        return False
    for key, value in match_labels.items():
        if key not in labels or labels[key] != value:
            return False
    for expression in match_expressions:
        key = expression.get("key")
        operator = expression.get("operator")
        values = expression.get("values") or []
        if operator == "In":
            if key not in labels or labels[key] not in values:
                return False
        elif operator == "NotIn":
            if key in labels and labels[key] in values:
                return False
        elif operator == "Exists":
            if key not in labels:
                return False
        elif operator == "DoesNotExist":
            if key in labels:
                return False
        else:
            return False
    return True


def _strip_release_terms(selector):
    selector = copy.deepcopy(selector or {})
    if selector.get("matchLabels"):
        selector["matchLabels"] = {
            key: value for key, value in selector["matchLabels"].items() if key != RELEASE_LABEL
        }
        if not selector["matchLabels"]:
            del selector["matchLabels"]
    if selector.get("matchExpressions"):
        selector["matchExpressions"] = [
            expression for expression in selector["matchExpressions"] if expression.get("key") != RELEASE_LABEL
        ]
        if not selector["matchExpressions"]:
            del selector["matchExpressions"]
    return selector


def _original_selector(pool):
    """The pool's node selector without anything this operator added."""
    saved = _annotations(pool).get(ORIGINAL_SELECTOR_ANNOTATION)
    if saved:
        try:
            return json.loads(saved)
        except ValueError:
            pass
    return _strip_release_terms(_spec(pool).get("nodeSelector"))


def home_pool(node, pools):
    """Return (pool name, problem) for the pool a node belongs to when no
    rollout is running. Follows the MCO: Windows nodes are unmanaged, master
    wins over everything, one custom pool wins over worker, and a node in two
    custom pools is an error."""
    labels = _labels(node)
    if labels.get("kubernetes.io/os") == "windows":
        return None, None
    master = worker = None
    custom = []
    for pool in pools:
        if not selector_matches(_original_selector(pool), labels):
            continue
        if _name(pool) == "master":
            master = pool
        elif _name(pool) == "worker":
            worker = pool
        else:
            custom.append(pool)
    if len(custom) > 1:
        names = ", ".join(sorted(_name(pool) for pool in custom))
        return None, "node %s matches more than one custom pool (%s)" % (_name(node), names)
    if master:
        return "master", None
    if custom:
        return _name(custom[0]), None
    if worker:
        return "worker", None
    return None, None


def pool_members(pools, nodes, pool_names):
    """Nodes whose home pool is in pool_names, in pool order then by name."""
    homes = {}
    problems = []
    for node in nodes or []:
        pool_name, problem = home_pool(node, pools or [])
        if problem:
            problems.append(problem)
        elif pool_name:
            homes.setdefault(pool_name, []).append(_name(node))
    members = []
    for pool_name in pool_names:
        for node_name in sorted(homes.get(pool_name, [])):
            if node_name not in members:
                members.append(node_name)
    return members, problems


def target_summary(pools, nodes, pool_names):
    """Status for a MutexTarget: its nodes and anything wrong with its pools."""
    existing = {_name(pool) for pool in pools or []}
    problems = []
    for pool_name in pool_names or []:
        if pool_name == "master":
            problems.append("the master pool cannot be a target")
        elif pool_name not in existing:
            problems.append("MachineConfigPool %s not found" % pool_name)
    members, membership_problems = pool_members(pools, nodes, pool_names or [])
    return {"nodes": members, "problems": problems + membership_problems}


# ---------------------------------------------------------------------------
# Node versions


def release_versions(machine_configs):
    """Map rendered MachineConfig name to the OpenShift version it belongs to."""
    versions = {}
    for machine_config in machine_configs or []:
        version = _annotations(machine_config).get(MCO_RELEASE_VERSION)
        if version:
            versions[_name(machine_config)] = version
    return versions


def rendered_config_names(nodes, pools):
    """Rendered MachineConfigs the planner needs: what nodes run and what pools want."""
    names = set()
    for node in nodes or []:
        for key in (MCO_CURRENT_CONFIG, MCO_DESIRED_CONFIG):
            if _annotations(node).get(key):
                names.add(_annotations(node)[key])
    for pool in pools or []:
        configured = (_spec(pool).get("configuration") or {}).get("name")
        if configured:
            names.add(configured)
    return sorted(names)


def _node_state(node, versions, target_version):
    annotations = _annotations(node)
    current = annotations.get(MCO_CURRENT_CONFIG)
    settled = bool(current) and current == annotations.get(MCO_DESIRED_CONFIG) and annotations.get(MCO_STATE) == "Done"
    version = versions.get(current)
    stored_phase = None
    if target_version and annotations.get(TARGET_VERSION_ANNOTATION) == target_version:
        stored_phase = annotations.get(PHASE_ANNOTATION)
    return {
        "name": _name(node),
        "version": version,
        "settled": settled,
        "mcd_state": annotations.get(MCO_STATE),
        "updated": settled and version == target_version,
        "phase": stored_phase,
        "run_config": annotations.get(RUN_CONFIG_ANNOTATION),
        "released": _labels(node).get(RELEASE_LABEL) == "true",
        "pre_complete": _split_list(annotations.get(PRE_COMPLETE_ANNOTATION)),
        "post_complete": _split_list(annotations.get(POST_COMPLETE_ANNOTATION)),
    }


# ---------------------------------------------------------------------------
# Jobs


def job_spec_for_node(job_spec, node_name, rule_name, stage, target_version):
    """Copy a rule's Job spec and point it at one node.

    Every container and init container gets NODE_NAME, MUTEX_RULE, MUTEX_STAGE
    and TARGET_VERSION (replacing any variables of the same name). Every node
    selector term gets a ``metadata.name NotIn [node]`` field, so the Job never
    runs on the node it is preparing; the rest of the affinity is kept."""
    spec = copy.deepcopy(job_spec or {})
    template = spec.get("template") or {}
    spec["template"] = template
    pod = template.get("spec") or {}
    template["spec"] = pod

    injected = [
        {"name": "NODE_NAME", "value": node_name},
        {"name": "MUTEX_RULE", "value": rule_name},
        {"name": "MUTEX_STAGE", "value": stage},
        {"name": "TARGET_VERSION", "value": target_version},
    ]
    for key in ("initContainers", "containers"):
        for container in pod.get(key) or []:
            kept = [env for env in container.get("env") or [] if env.get("name") not in INJECTED_ENV]
            container["env"] = kept + copy.deepcopy(injected)

    exclusion = {"key": "metadata.name", "operator": "NotIn", "values": [node_name]}
    affinity = pod.get("affinity") or {}
    pod["affinity"] = affinity
    node_affinity = affinity.get("nodeAffinity") or {}
    affinity["nodeAffinity"] = node_affinity
    required = node_affinity.get("requiredDuringSchedulingIgnoredDuringExecution") or {}
    node_affinity["requiredDuringSchedulingIgnoredDuringExecution"] = required
    terms = required.get("nodeSelectorTerms") or [{}]
    for term in terms:
        term["matchFields"] = (term.get("matchFields") or []) + [copy.deepcopy(exclusion)]
    required["nodeSelectorTerms"] = terms
    return spec


def build_job(rule, stage, node_name, target_version, run_config):
    """The Job a rule runs for one node at one stage."""
    rule_spec = _spec(rule)
    rule_meta = _meta(rule)
    run_config_meta = _meta(run_config)
    if stage == PRE_UPDATE_STAGE:
        job_spec, prefix = rule_spec.get("jobSpec"), rule_spec.get("jobName")
    else:
        job_spec, prefix = rule_spec.get("cleanUpJobSpec"), "cleanup-" + rule_spec.get("jobName", "")
    return {
        "apiVersion": "batch/v1",
        "kind": "Job",
        "metadata": {
            "generateName": prefix + "-",
            "namespace": rule_spec.get("jobNamespace"),
            "labels": {
                RUN_CONFIG_UID_LABEL: run_config_meta.get("uid", ""),
                STAGE_LABEL: stage,
            },
            "annotations": {
                NODE_ANNOTATION: node_name,
                RULE_ANNOTATION: _ref(rule_meta.get("namespace"), rule_meta.get("name")),
                TARGET_VERSION_ANNOTATION: target_version,
                RUN_CONFIG_ANNOTATION: _ref(run_config_meta.get("namespace"), run_config_meta.get("name")),
            },
        },
        "spec": job_spec_for_node(job_spec, node_name, rule_meta.get("name"), stage, target_version),
    }


def validation_job(rule, stage):
    """A Job for a server-side dry run that checks a MutexRule's template."""
    placeholder_run_config = {"metadata": {"uid": "validation", "namespace": "validation", "name": "validation"}}
    return build_job(rule, stage, "validation-node", "0.0.0", placeholder_run_config)


def dry_run_errors(results):
    """Turn the registered results of the dry-run loop into "stage: message"
    strings, one per rejected Job template."""
    errors = []
    for result in results or []:
        if result.get("failed"):
            errors.append("%s Job: %s" % (result.get("item"), api_error_message(result.get("msg"))))
    return errors


# Statuses are built here rather than in YAML: Ansible would turn integers
# taken from the (unsafe-marked) resource into strings.


def rule_status(rule, dry_run_results, now=None):
    """Status for a MutexRule from the results of its dry-run loop."""
    errors = dry_run_errors(dry_run_results)
    if errors:
        valid = make_condition(rule, "Valid", False, "JobTemplateRejected", "; ".join(errors), now)
    else:
        valid = make_condition(rule, "Valid", True, "JobTemplatesAccepted",
                               "The API server accepts the Job templates", now)
    return {"observedGeneration": _meta(rule).get("generation"), "conditions": [valid]}


def target_status(target, pools, nodes, pools_api_found=True, now=None):
    """Status for a MutexTarget: its nodes and whether its pools are usable."""
    summary = target_summary(pools, nodes, _spec(target).get("machineConfigPools"))
    problems = summary["problems"]
    if not pools_api_found:
        problems = ["the MachineConfigPool API is not available; this operator needs OpenShift"]
    if problems:
        valid = make_condition(target, "Valid", False, "InvalidPools", "; ".join(problems), now)
    else:
        valid = make_condition(target, "Valid", True, "PoolsFound",
                               "Targets %d node(s)" % len(summary["nodes"]), now)
    return {"observedGeneration": _meta(target).get("generation"), "nodes": summary["nodes"],
            "conditions": [valid]}


def _job_result(job):
    for condition in _status(job).get("conditions") or []:
        if condition.get("status") != "True":
            continue
        if condition.get("type") == "Complete":
            return "Complete"
        if condition.get("type") == "Failed":
            return "Failed"
    return None


def _find_job(jobs, node_name, rule_ref, stage, target_version):
    found = [
        job
        for job in jobs
        if _labels(job).get(STAGE_LABEL) == stage
        and _annotations(job).get(NODE_ANNOTATION) == node_name
        and _annotations(job).get(RULE_ANNOTATION) == rule_ref
        and _annotations(job).get(TARGET_VERSION_ANNOTATION) == target_version
        and not _meta(job).get("deletionTimestamp")
    ]
    if not found:
        return None
    return max(found, key=lambda job: _meta(job).get("creationTimestamp") or "")


# ---------------------------------------------------------------------------
# The rollout planner


class _Plan(object):
    def __init__(self, run_config, now):
        self.run_config = run_config
        self.now = _timestamp(now)
        self.pool_patches = {}
        self.node_patches = {}
        self.jobs = []
        self.requeue_after = None
        self.conditions = {}
        self.current_node = None

    def patch_pool(self, name, patch):
        if patch:
            _deep_merge(self.pool_patches.setdefault(name, {}), patch)

    def patch_node(self, name, patch):
        if patch:
            _deep_merge(self.node_patches.setdefault(name, {}), patch)

    def requeue(self, seconds):
        if self.requeue_after is None or seconds < self.requeue_after:
            self.requeue_after = seconds

    def set_condition(self, condition_type, status, reason, message):
        self.conditions[condition_type] = make_condition(
            self.run_config, condition_type, status, reason, message, self.now)

    def progressing(self, status, reason, message):
        self.set_condition("Progressing", status, reason, message)

    def degraded(self, reason, message):
        self.set_condition("Degraded", True, reason, message)


def _deep_merge(target, source):
    for key, value in source.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _deep_merge(target[key], value)
        else:
            target[key] = copy.deepcopy(value)
    return target


def _find(objects, namespace, name):
    for obj in objects or []:
        if _meta(obj).get("name") == name and _meta(obj).get("namespace") == namespace:
            return obj
    return None


def _check_dependency(obj, kind, ref):
    if obj is None:
        return "%s %s not found" % (kind, ref)
    observed = _status(obj).get("observedGeneration")
    if observed is None or observed != _meta(obj).get("generation"):
        return "%s %s has not been validated yet" % (kind, ref)
    if not _condition_true(obj, "Valid"):
        condition = _condition(obj, "Valid") or {}
        return "%s %s is not valid: %s" % (kind, ref, condition.get("message", "no reason given"))
    return None


def _unavailable_api_services(api_services):
    unavailable = []
    for service in api_services or []:
        if not _condition_true(service, "Available"):
            unavailable.append(_name(service))
    return sorted(unavailable)


def _pool_degraded(pool):
    return _condition_true(pool, "Degraded") or _condition_true(pool, "NodeDegraded")


def _has_release_terms(selector):
    selector = selector or {}
    if RELEASE_LABEL in (selector.get("matchLabels") or {}):
        return True
    return any(expression.get("key") == RELEASE_LABEL for expression in selector.get("matchExpressions") or [])


def _holds_released_nodes_out(selector):
    return any(
        expression.get("key") == RELEASE_LABEL and expression.get("operator") == "DoesNotExist"
        for expression in (selector or {}).get("matchExpressions") or []
    )


def _rollout_pool_patches(plan, pools_by_name, target_pools, canary_name, run_config_ref):
    """Pause the target pools and point the canary pool at released nodes."""
    for pool_name in target_pools:
        pool = pools_by_name[pool_name]
        patch = {}
        if not _spec(pool).get("paused"):
            patch["spec"] = {"paused": True}
            patch["metadata"] = {"annotations": {PAUSED_BY_ANNOTATION: run_config_ref}}
        current = _spec(pool).get("nodeSelector") or {}
        if not _holds_released_nodes_out(current):
            desired = _strip_release_terms(current)
            desired["matchExpressions"] = (desired.get("matchExpressions") or []) + [
                {"key": RELEASE_LABEL, "operator": "DoesNotExist"}
            ]
            patch.setdefault("spec", {})["nodeSelector"] = merge_patch(current, desired)
        plan.patch_pool(pool_name, patch)

    canary = pools_by_name[canary_name]
    current = _spec(canary).get("nodeSelector") or {}
    desired = {"matchLabels": {RELEASE_LABEL: "true"}}
    patch = {}
    if ORIGINAL_SELECTOR_ANNOTATION not in _annotations(canary):
        patch["metadata"] = {"annotations": {ORIGINAL_SELECTOR_ANNOTATION: json.dumps(current, sort_keys=True)}}
    selector_patch = merge_patch(current, desired)
    if selector_patch:
        patch["spec"] = {"nodeSelector": selector_patch}
    plan.patch_pool(canary_name, patch)


def _restore_patches(plan, pools, nodes, run_config_ref):
    """Undo everything a rollout changed on pools and nodes."""
    for pool in pools:
        annotations = _annotations(pool)
        current = _spec(pool).get("nodeSelector") or {}
        patch = {}
        if ORIGINAL_SELECTOR_ANNOTATION in annotations:
            desired = _original_selector(pool)
            patch["metadata"] = {"annotations": {ORIGINAL_SELECTOR_ANNOTATION: None}}
        else:
            desired = _strip_release_terms(current)
        selector_patch = merge_patch(current, desired)
        if selector_patch:
            patch["spec"] = {"nodeSelector": selector_patch}
        if annotations.get(PAUSED_BY_ANNOTATION) == run_config_ref:
            patch.setdefault("spec", {})["paused"] = False
            patch.setdefault("metadata", {}).setdefault("annotations", {})[PAUSED_BY_ANNOTATION] = None
        plan.patch_pool(_name(pool), patch)
    for node in nodes:
        if RELEASE_LABEL in _labels(node):
            plan.patch_node(_name(node), {"metadata": {"labels": {RELEASE_LABEL: None}}})


def _forget_patches(plan, nodes, run_config_ref):
    """Remove the progress annotations this MutexRunConfig left on nodes."""
    keys = (PHASE_ANNOTATION, TARGET_VERSION_ANNOTATION, RUN_CONFIG_ANNOTATION,
            PRE_COMPLETE_ANNOTATION, POST_COMPLETE_ANNOTATION)
    for node in nodes:
        annotations = _annotations(node)
        if annotations.get(RUN_CONFIG_ANNOTATION) != run_config_ref:
            continue
        patch = {key: None for key in keys if key in annotations}
        if patch:
            plan.patch_node(_name(node), {"metadata": {"annotations": patch}})


def _is_managed(pools, nodes, run_config_ref):
    """Whether pools or nodes still carry changes from a rollout."""
    for pool in pools:
        annotations = _annotations(pool)
        if annotations.get(PAUSED_BY_ANNOTATION) == run_config_ref or ORIGINAL_SELECTOR_ANNOTATION in annotations:
            return True
        if _has_release_terms(_spec(pool).get("nodeSelector")):
            return True
    return any(RELEASE_LABEL in _labels(node) for node in nodes)


def _blocking_run_config(run_config, run_configs):
    """The MutexRunConfig that goes first if more than one exists: the oldest,
    then the lowest namespace/name. Returns None when run_config goes first."""
    def order(obj):
        meta = _meta(obj)
        return (meta.get("creationTimestamp") or "", meta.get("namespace") or "", meta.get("name") or "")

    me = order(run_config)
    others = [obj for obj in run_configs or [] if _meta(obj).get("uid") != _meta(run_config).get("uid")]
    earlier = [obj for obj in others if order(obj) < me]
    if not earlier:
        return None
    first = min(earlier, key=order)
    return _ref(_meta(first).get("namespace"), _meta(first).get("name"))


def _advance_jobs(plan, state, rules, stage, jobs, target_version, run_config):
    """Run each rule's Job for one node, one after another.

    Returns "done", "waiting" or "failed"."""
    if stage == PRE_UPDATE_STAGE:
        spec_key, done_key, annotation = "jobSpec", "pre_complete", PRE_COMPLETE_ANNOTATION
    else:
        spec_key, done_key, annotation = "cleanUpJobSpec", "post_complete", POST_COMPLETE_ANNOTATION
    done = list(state[done_key])
    result = "done"
    for rule in rules:
        if not _spec(rule).get(spec_key):
            continue
        rule_ref = _ref(_meta(rule).get("namespace"), _meta(rule).get("name"))
        if rule_ref in done:
            continue
        job = _find_job(jobs, state["name"], rule_ref, stage, target_version)
        if job is None:
            plan.jobs.append(build_job(rule, stage, state["name"], target_version, run_config))
            plan.progressing(True, "Running%sJobs" % stage.title().replace("-", ""),
                             "Running the %s Job of MutexRule %s for node %s" % (stage, rule_ref, state["name"]))
            plan.requeue(REQUEUE_JOBS)
            result = "waiting"
            break
        job_result = _job_result(job)
        if job_result == "Complete":
            done.append(rule_ref)
            continue
        job_ref = _ref(_meta(job).get("namespace"), _meta(job).get("name"))
        if job_result == "Failed":
            plan.progressing(True, "Blocked", "Waiting on failed Job %s for node %s" % (job_ref, state["name"]))
            plan.degraded("JobFailed", "Job %s (%s, MutexRule %s, node %s) failed. Fix the cause and delete the "
                          "Job to retry it." % (job_ref, stage, rule_ref, state["name"]))
            plan.requeue(REQUEUE_BLOCKED)
            result = "failed"
            break
        plan.progressing(True, "Running%sJobs" % stage.title().replace("-", ""),
                         "Waiting for Job %s (%s, MutexRule %s) for node %s" % (job_ref, stage, rule_ref, state["name"]))
        plan.requeue(REQUEUE_JOBS)
        result = "waiting"
        break
    if done != state[done_key]:
        plan.patch_node(state["name"], {"metadata": {"annotations": {annotation: ",".join(done)}}})
        state[done_key] = done
    return result


def plan_rollout(run_config, cluster_version=None, rules=None, targets=None, pools=None, nodes=None,
                 machine_configs=None, jobs=None, api_services=None, run_configs=None, deleting=False, now=None):
    """Decide the next step for a MutexRunConfig.

    Returns a dict with ``pool_patches`` and ``node_patches`` (lists of
    ``{name, patch}`` JSON merge patches), ``jobs`` (Job definitions to
    create), ``status`` and ``conditions`` for the MutexRunConfig, and
    ``requeue_after`` (for example "15s", or None to wait for the reconcile
    period).
    """
    pools = pools or []
    nodes = nodes or []
    jobs = jobs or []
    rules = rules or []
    targets = targets or []
    meta = _meta(run_config)
    spec = _spec(run_config)
    namespace = meta.get("namespace")
    run_config_ref = _ref(namespace, meta.get("name"))
    deleting = bool(deleting or meta.get("deletionTimestamp"))
    plan = _Plan(run_config, now)
    pools_by_name = {_name(pool): pool for pool in pools}
    versions = release_versions(machine_configs)

    # Configuration
    problems = []
    rule_objects = []
    for ref in spec.get("mutexRules") or []:
        rule_ns = ref.get("namespace") or namespace
        rule = _find(rules, rule_ns, ref.get("name"))
        problem = _check_dependency(rule, "MutexRule", _ref(rule_ns, ref.get("name")))
        if problem:
            problems.append(problem)
        else:
            rule_objects.append(rule)
    target_pools = []
    for ref in spec.get("mutexTargets") or []:
        target_ns = ref.get("namespace") or namespace
        target = _find(targets, target_ns, ref.get("name"))
        problem = _check_dependency(target, "MutexTarget", _ref(target_ns, ref.get("name")))
        if problem:
            problems.append(problem)
            continue
        for pool_name in _spec(target).get("machineConfigPools") or []:
            if pool_name not in target_pools:
                target_pools.append(pool_name)
    canary_name = (spec.get("canary") or {}).get("name")
    for pool_name in target_pools:
        if pool_name not in pools_by_name:
            problems.append("MachineConfigPool %s not found" % pool_name)
        elif pool_name == "master":
            problems.append("the master pool cannot be a target")
    if not canary_name:
        problems.append("spec.canary.name is not set")
    elif canary_name not in pools_by_name:
        problems.append("canary MachineConfigPool %s not found" % canary_name)
    elif canary_name in target_pools:
        problems.append("canary MachineConfigPool %s is also a target" % canary_name)
    elif _spec(pools_by_name[canary_name]).get("paused"):
        problems.append("canary MachineConfigPool %s is paused" % canary_name)
    else:
        canary_members, _ = pool_members(pools, nodes, [canary_name])
        if canary_members:
            problems.append("canary MachineConfigPool %s must not select any nodes of its own (selects %s)"
                            % (canary_name, ", ".join(canary_members)))
    valid_targets = [pool_name for pool_name in target_pools if pool_name in pools_by_name]

    if problems:
        plan.set_condition("ConfigValid", False, "InvalidConfig", "; ".join(problems))
    else:
        plan.set_condition("ConfigValid", True, "Valid", "MutexRules, MutexTargets and the canary pool are valid")

    # Cluster and node state
    desired = _status(cluster_version).get("desired") or {}
    target_version = desired.get("version") or ""
    history = _status(cluster_version).get("history") or []
    control_plane_done = bool(
        target_version and history and history[0].get("state") == "Completed" and history[0].get("version") == target_version
    )
    members, membership_problems = pool_members(pools, nodes, valid_targets)
    nodes_by_name = {_name(node): node for node in nodes}
    states = [_node_state(nodes_by_name[name], versions, target_version) for name in members]
    for state in states:
        if state["phase"] in ACTIVE_PHASES + (COMPLETE,):
            pass
        elif state["updated"]:
            state["phase"] = UP_TO_DATE
        else:
            state["phase"] = PENDING
    active = [state for state in states if state["phase"] in ACTIVE_PHASES]
    pending = [state for state in states if state["phase"] == PENDING]
    managed = _is_managed(pools, nodes, run_config_ref)
    blocker = _blocking_run_config(run_config, run_configs)

    plan.set_condition("Degraded", False, "AsExpected", "")
    status = {
        "observedGeneration": meta.get("generation"),
        "targetVersion": target_version,
        "currentNode": "",
        "nodes": [],
    }

    def finish():
        status["currentNode"] = plan.current_node or ""
        status["nodes"] = [
            {"name": state["name"], "phase": state["phase"], "version": state["version"] or ""} for state in states
        ]
        return {
            "pool_patches": [{"name": name, "patch": patch} for name, patch in sorted(plan.pool_patches.items())],
            "node_patches": [{"name": name, "patch": patch} for name, patch in sorted(plan.node_patches.items())],
            "jobs": plan.jobs,
            "status": status,
            "conditions": [plan.conditions[key] for key in ("ConfigValid", "Progressing", "Degraded")
                           if key in plan.conditions],
            "requeue_after": "%ds" % plan.requeue_after if plan.requeue_after else None,
        }

    if blocker:
        # Another MutexRunConfig owns the pools. Touch nothing, not even on delete.
        plan.progressing(False, "Blocked", "MutexRunConfig %s goes first; only one rollout runs at a time" % blocker)
        plan.degraded("Conflict", "More than one MutexRunConfig exists; this one is ignored while %s exists"
                      % blocker)
        if not deleting:
            plan.requeue(REQUEUE_BLOCKED)
        return finish()

    if deleting:
        _restore_patches(plan, pools, nodes, run_config_ref)
        _forget_patches(plan, nodes, run_config_ref)
        plan.progressing(False, "Deleted", "MutexRunConfig deleted; restored pools and nodes")
        return finish()

    if problems:
        if managed or active:
            plan.progressing(True, "Blocked", "Rollout paused until the configuration is fixed")
            plan.degraded("InvalidConfig", "; ".join(problems))
        else:
            plan.progressing(False, "InvalidConfig", "Nothing will run until the configuration is fixed")
        plan.requeue(REQUEUE_BLOCKED)
        return finish()

    if membership_problems:
        plan.degraded("PoolMembership", "; ".join(membership_problems))

    if not target_version:
        plan.progressing(False, "Idle", "ClusterVersion has no desired version")
        return finish()

    if not pending and not active:
        if managed:
            _restore_patches(plan, pools, nodes, run_config_ref)
            plan.progressing(True, "Finishing", "All target nodes run %s; restoring pools" % target_version)
            plan.requeue(REQUEUE_STEP)
        elif any(state["phase"] == COMPLETE for state in states):
            completed = len([state for state in states if state["phase"] == COMPLETE])
            plan.progressing(False, "RolloutComplete", "Updated %d node(s) to %s" % (completed, target_version))
        else:
            plan.progressing(False, "Idle", "All target nodes run %s" % target_version)
        return finish()

    # A rollout is needed. Hold every target node in its paused pool first.
    before = (len(plan.pool_patches), len(plan.node_patches))
    _rollout_pool_patches(plan, pools_by_name, valid_targets, canary_name, run_config_ref)
    if (len(plan.pool_patches), len(plan.node_patches)) != before:
        plan.progressing(True, "PausingPools", "Pausing %s and preparing canary pool %s for %s"
                         % (", ".join(valid_targets), canary_name, target_version))
        plan.requeue(REQUEUE_STEP)
        return finish()

    if not control_plane_done:
        plan.progressing(True, "WaitingForControlPlane",
                         "Target pools are paused; waiting for the cluster update to %s to complete" % target_version)
        plan.requeue(REQUEUE_WAIT)
        return finish()

    if len(active) > 1:
        plan.degraded("MultipleActiveNodes", "More than one node is mid-rollout: %s"
                      % ", ".join(state["name"] for state in active))

    if active:
        state = active[0]
    else:
        unsettled = [s["name"] for s in states if not s["settled"] and s["phase"] not in ACTIVE_PHASES]
        if unsettled:
            plan.progressing(True, "WaitingForNodes", "Waiting for nodes the MCO is already updating: %s"
                             % ", ".join(unsettled))
            plan.requeue(REQUEUE_WAIT)
            return finish()
        canary = pools_by_name[canary_name]
        canary_config = (_spec(canary).get("configuration") or {}).get("name")
        if versions.get(canary_config) != target_version:
            plan.progressing(True, "WaitingForCanary",
                             "Waiting for the MCO to render %s for canary pool %s" % (target_version, canary_name))
            plan.requeue(REQUEUE_WAIT)
            return finish()
        if _pool_degraded(canary):
            plan.progressing(True, "Blocked", "Canary pool %s is degraded" % canary_name)
            plan.degraded("CanaryDegraded", "Canary pool %s is degraded" % canary_name)
            plan.requeue(REQUEUE_BLOCKED)
            return finish()
        unavailable = _unavailable_api_services(api_services)
        if unavailable:
            plan.progressing(True, "WaitingForCluster", "Waiting for APIServices to become available: %s"
                             % ", ".join(unavailable))
            plan.requeue(REQUEUE_WAIT)
            return finish()
        state = pending[0]
        state["phase"] = PRE_UPDATE
        state["pre_complete"] = []
        state["post_complete"] = []
        plan.patch_node(state["name"], {"metadata": {"annotations": {
            PHASE_ANNOTATION: PRE_UPDATE,
            TARGET_VERSION_ANNOTATION: target_version,
            RUN_CONFIG_ANNOTATION: run_config_ref,
            PRE_COMPLETE_ANNOTATION: "",
            POST_COMPLETE_ANNOTATION: "",
        }}})

    plan.current_node = state["name"]

    if state["phase"] == PRE_UPDATE:
        result = _advance_jobs(plan, state, rule_objects, PRE_UPDATE_STAGE, jobs, target_version, run_config)
        if result != "done":
            return finish()
        state["phase"] = UPDATING
        plan.patch_node(state["name"], {"metadata": {
            "labels": {RELEASE_LABEL: "true"},
            "annotations": {PHASE_ANNOTATION: UPDATING},
        }})
        plan.progressing(True, "UpdatingNode", "Released node %s into canary pool %s" % (state["name"], canary_name))
        plan.requeue(REQUEUE_NODE)
        return finish()

    if state["phase"] == UPDATING:
        if not state["released"]:
            plan.patch_node(state["name"], {"metadata": {"labels": {RELEASE_LABEL: "true"}}})
        if not state["updated"]:
            if state["mcd_state"] == "Degraded":
                plan.degraded("NodeDegraded", "The machine-config daemon on %s reports Degraded" % state["name"])
            plan.progressing(True, "UpdatingNode", "Waiting for node %s to reach %s (now %s, MCD state %s)" % (
                state["name"], target_version, state["version"] or "unknown", state["mcd_state"] or "unknown"))
            plan.requeue(REQUEUE_NODE)
            return finish()
        state["phase"] = POST_UPDATE
        plan.patch_node(state["name"], {"metadata": {"annotations": {PHASE_ANNOTATION: POST_UPDATE}}})

    if state["phase"] == POST_UPDATE:
        result = _advance_jobs(plan, state, rule_objects, POST_UPDATE_STAGE, jobs, target_version, run_config)
        if result != "done":
            return finish()
        state["phase"] = COMPLETE
        plan.patch_node(state["name"], {"metadata": {"annotations": {PHASE_ANNOTATION: COMPLETE}}})
        plan.progressing(True, "NodeComplete", "Node %s runs %s" % (state["name"], target_version))
        plan.requeue(REQUEUE_STEP)
    return finish()


class FilterModule(object):
    def filters(self):
        return {
            "nodeupgrade_plan": plan_rollout,
            "nodeupgrade_rule_status": rule_status,
            "nodeupgrade_target_status": target_status,
            "nodeupgrade_rendered_config_names": rendered_config_names,
            "nodeupgrade_validation_job": validation_job,
            "nodeupgrade_condition": make_condition,
            "nodeupgrade_const": lambda name: globals()[name],
        }
