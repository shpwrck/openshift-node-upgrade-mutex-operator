#!/usr/bin/env bash
# Add a released bundle to the basic catalog template as the new head of a
# channel. With --check, only verify that VERSION has not been released yet.
#
# Usage: hack/catalog-add.sh [--check] TEMPLATE PACKAGE CHANNEL VERSION BUNDLE_REF [SKIP_RANGE]
#
# Requires mikefarah yq v4 (set YQ to its path; default: yq on PATH).
set -euo pipefail

usage() {
  sed -n '2,7p' "$0" | sed 's/^# \{0,1\}//' >&2
  exit 2
}

check_only=false
if [ "${1:-}" = "--check" ]; then
  check_only=true
  shift
fi
[ "$#" -ge 5 ] || usage

template=$1
package=$2
channel=$3
version=$4
bundle_ref=$5
skip_range=${6:-}
yq=${YQ:-yq}

[ -f "$template" ] || { echo "error: $template not found" >&2; exit 1; }

export NAME="${package}.v${version}"
export PACKAGE="$package" CHANNEL="$channel" BUNDLE_REF="$bundle_ref" SKIP_RANGE="$skip_range"

released=$("$yq" '[.entries[] | select(.schema == "olm.channel") | .entries[] | select(.name == strenv(NAME))] | length' "$template")
if [ "$released" != 0 ]; then
  echo "error: $NAME is already in $template; bump the version (make increment) instead of re-releasing it" >&2
  exit 1
fi
listed=$("$yq" '[.entries[] | select(.schema == "olm.bundle" and .image == strenv(BUNDLE_REF))] | length' "$template")
if [ "$listed" != 0 ]; then
  echo "error: $BUNDLE_REF is already listed in $template" >&2
  exit 1
fi
if $check_only; then
  echo "$NAME is not in $template yet"
  exit 0
fi

channels=$("$yq" '[.entries[] | select(.schema == "olm.channel" and .name == strenv(CHANNEL))] | length' "$template")
case $channels in
  0)
    head=""
    "$yq" -c -i '.entries += [{"entries": [], "name": strenv(CHANNEL), "package": strenv(PACKAGE), "schema": "olm.channel"}]' "$template"
    ;;
  1)
    # The head is the one entry that no other entry replaces or skips.
    # shellcheck disable=SC2016 # $e is a yq variable, not a shell one
    heads=$("$yq" '[.entries[] | select(.schema == "olm.channel" and .name == strenv(CHANNEL)) | .entries[]] as $e
      | ($e | map(.name)) - ($e | map(.replaces // "")) - ($e | map(.skips // []) | flatten) | .[]' "$template")
    count=$(printf '%s\n' "$heads" | grep -c . || true)
    if [ "$count" != 1 ]; then
      echo "error: channel $CHANNEL in $template has $count heads (${heads//$'\n'/ }); fix the template by hand" >&2
      exit 1
    fi
    head=$heads
    ;;
  *)
    echo "error: channel $CHANNEL is defined $channels times in $template" >&2
    exit 1
    ;;
esac
export REPLACES="$head"

select_entry='.entries[] | select(.schema == "olm.channel" and .name == strenv(CHANNEL)) | .entries[] | select(.name == strenv(NAME))'
"$yq" -c -i '(.entries[] | select(.schema == "olm.channel" and .name == strenv(CHANNEL)) | .entries) += [{"name": strenv(NAME)}]' "$template"
if [ -n "$REPLACES" ]; then
  "$yq" -c -i "($select_entry).replaces = strenv(REPLACES)" "$template"
fi
if [ -n "$SKIP_RANGE" ]; then
  "$yq" -c -i "($select_entry).skipRange = strenv(SKIP_RANGE)" "$template"
fi
"$yq" -c -i '.entries += [{"image": strenv(BUNDLE_REF), "schema": "olm.bundle"}]' "$template"

echo "added $NAME to channel $CHANNEL in $template${REPLACES:+ (replaces $REPLACES)}${SKIP_RANGE:+ (skipRange $SKIP_RANGE)}"
