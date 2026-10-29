#!/usr/bin/env bash
# Start a fresh catalog: keep only the olm.package entry of the basic catalog
# template, and write the rendered catalog with just that entry. The next
# `make release` (catalog-add) creates the channel with its first bundle.
#
# Usage: hack/catalog-reset.sh TEMPLATE CATALOG_FILE
#
# Requires mikefarah yq v4 (set YQ to its path; default: yq on PATH).
set -euo pipefail

template=${1:?usage: hack/catalog-reset.sh TEMPLATE CATALOG_FILE}
catalog=${2:?usage: hack/catalog-reset.sh TEMPLATE CATALOG_FILE}
yq=${YQ:-yq}

[ -f "$template" ] || { echo "error: $template not found" >&2; exit 1; }

packages=$("$yq" '[.entries[] | select(.schema == "olm.package")] | length' "$template")
if [ "$packages" != 1 ]; then
  echo "error: $template has $packages olm.package entries, expected 1" >&2
  exit 1
fi

"$yq" -i '.entries |= [.[] | select(.schema == "olm.package")]' "$template"
mkdir -p "$(dirname "$catalog")"
{
  echo '---'
  "$yq" '.entries[0]' "$template"
} > "$catalog"

echo "reset $template and $catalog to the package entry only"
