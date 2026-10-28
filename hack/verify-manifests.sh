#!/usr/bin/env bash
# Guard against regressions that shipped before: the manager Deployment
# carrying the deleted gcr.io/kubebuilder/kube-rbac-proxy sidecar, an args
# patch that dropped --max-concurrent-reconciles=1, and a Service whose
# prefixed name was longer than the 63 characters Kubernetes allows. Checks the
# default, manifests and testing overlays and, when given, the CSV of a
# generated bundle.
#
# Usage: hack/verify-manifests.sh [BUNDLE_DIR]
#
# Requires kustomize and yq (set KUSTOMIZE and YQ to their paths; default:
# kustomize and yq on PATH).
set -euo pipefail

kustomize=${KUSTOMIZE:-kustomize}
yq=${YQ:-yq}
bundle_dir=${1:-}
status=0
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

check() {
  local name=$1 file=$2 arg
  if grep -q 'kube-rbac-proxy' "$file"; then
    echo "error: $name still references kube-rbac-proxy" >&2
    status=1
  fi
  for arg in --max-concurrent-reconciles=1 --metrics-secure --metrics-require-rbac --leader-elect; do
    if ! grep -q -e "- $arg\$" "$file"; then
      echo "error: $name: manager args are missing $arg" >&2
      status=1
    fi
  done
  # Services (and the DNS names derived from them) are DNS-1035 labels.
  local svc
  for svc in $("$yq" ea 'select(.kind == "Service") | .metadata.name' "$file"); do
    if [ "${#svc}" -gt 63 ]; then
      echo "error: $name: Service name $svc is longer than 63 characters" >&2
      status=1
    fi
  done
}

# config/testing (the molecule overlay) loads ../default/manager_metrics_patch.yaml,
# which needs LoadRestrictionsNone.
for overlay in default manifests testing; do
  "$kustomize" build --load-restrictor LoadRestrictionsNone "config/$overlay" > "$tmp/$overlay.yaml"
  check "config/$overlay" "$tmp/$overlay.yaml"
done

if [ -n "$bundle_dir" ]; then
  if [ -d "$bundle_dir/manifests" ]; then
    cat "$bundle_dir"/manifests/*.clusterserviceversion.yaml > "$tmp/csv.yaml"
    check "$bundle_dir CSV" "$tmp/csv.yaml"
  else
    echo "note: $bundle_dir/manifests not found, skipping the bundle check (run 'make bundle')"
  fi
fi

if [ "$status" = 0 ]; then
  echo "manifests OK"
fi
exit "$status"
