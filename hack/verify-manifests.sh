#!/usr/bin/env bash
# Guard against two regressions that shipped before: the manager Deployment
# carrying the deleted gcr.io/kubebuilder/kube-rbac-proxy sidecar, and an
# args patch that dropped --max-concurrent-reconciles=1. Checks the default
# and manifests overlays and, when given, the CSV of a generated bundle.
#
# Usage: hack/verify-manifests.sh [BUNDLE_DIR]
#
# Requires kustomize (set KUSTOMIZE to its path; default: kustomize on PATH).
set -euo pipefail

kustomize=${KUSTOMIZE:-kustomize}
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
}

for overlay in default manifests; do
  "$kustomize" build "config/$overlay" > "$tmp/$overlay.yaml"
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
