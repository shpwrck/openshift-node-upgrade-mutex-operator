#!/usr/bin/env bash
# Check that a rendered catalog still matches the basic template it is
# rendered from (same package, bundle images and channel entries). Nothing is
# pulled, so it catches a template edit that was not followed by
# `make catalog-render` (or a hand edit of the rendered file).
#
# Usage: hack/verify-catalog.sh TEMPLATE CATALOG_FILE
#
# Requires mikefarah yq v4 (set YQ to its path; default: yq on PATH).
set -euo pipefail

template=${1:?usage: hack/verify-catalog.sh TEMPLATE CATALOG_FILE}
catalog=${2:?usage: hack/verify-catalog.sh TEMPLATE CATALOG_FILE}
yq=${YQ:-yq}

# A template without a bundle (a fresh catalog) cannot be rendered: opm refuses
# a channel without a bundle.
if [ "$("$yq" '[.entries[] | select(.schema == "olm.bundle")] | length' "$template")" = 0 ]; then
  fix="make catalog-reset"
else
  fix="make catalog-render"
fi

status=0
compare() {
  local what=$1 from_template=$2 from_catalog=$3
  if [ "$from_template" != "$from_catalog" ]; then
    echo "error: $what in $catalog differ from $template; run '$fix'" >&2
    diff <(printf '%s\n' "$from_template") <(printf '%s\n' "$from_catalog") >&2 || true
    status=1
  fi
}

compare "packages" \
  "$("$yq" -o json -I0 '[.entries[] | select(.schema == "olm.package")] | sort_keys(..)' "$template")" \
  "$("$yq" ea -o json -I0 '[select(.schema == "olm.package")] | sort_keys(..)' "$catalog")"
compare "bundle images" \
  "$("$yq" '[.entries[] | select(.schema == "olm.bundle") | .image] | sort | .[]' "$template")" \
  "$("$yq" ea '[select(.schema == "olm.bundle") | .image] | sort | .[]' "$catalog")"
compare "channels" \
  "$("$yq" -o json -I0 '[.entries[] | select(.schema == "olm.channel") | .entries |= sort_by(.name)] | sort_by(.name) | sort_keys(..)' "$template")" \
  "$("$yq" ea -o json -I0 '[select(.schema == "olm.channel") | .entries |= sort_by(.name)] | sort_by(.name) | sort_keys(..)' "$catalog")"

if [ "$status" = 0 ]; then
  echo "$catalog matches $template"
fi
exit "$status"
