#!/usr/bin/env bash
# Render docs/diagrams/*.mmd to *.svg, or check that every committed SVG was
# rendered from its current .mmd source.
#
#   hack/diagrams.sh render   (needs podman or docker; run by `make diagrams`)
#   hack/diagrams.sh check    (needs only a shell; run by `make diagrams-check`)
#
# Each SVG ends with a "diagram-source-sha256" comment: the SHA-256 of the .mmd
# file, the shared mermaid.json and the mermaid-cli image digest. `check`
# recomputes it, so it fails when a source, the config or the pinned image
# changed without a re-render. It does not need byte-identical rendering, so
# SVGs rendered on arm64 and on amd64 are equally valid.
#
# Environment: MMDC_IMG (required, the pinned mermaid-cli image), CONTAINER_TOOL
# (default podman), DIAGRAMS_DIR (default docs/diagrams).
set -euo pipefail

DIR=${DIAGRAMS_DIR:-docs/diagrams}
IMG=${MMDC_IMG:?set MMDC_IMG to the pinned mermaid-cli image}
TOOL=${CONTAINER_TOOL:-podman}

sha256() {
  if command -v sha256sum >/dev/null; then sha256sum | cut -d' ' -f1; else shasum -a 256 | cut -d' ' -f1; fi
}
stamp() { { cat "$1" "$DIR/mermaid.json"; printf '%s\n' "${IMG##*@}"; } | sha256; }

# True when DIR holds at least one .mmd file.
have_sources() {
  local f
  for f in "$DIR"/*.mmd; do [[ -e $f ]] && return 0; done
  return 1
}

render() {
  if ! have_sources; then
    echo "no .mmd files in $DIR: nothing to render"
    return 0
  fi
  local abs userns=()
  abs=$(cd "$DIR" && pwd)
  [[ $(basename "$TOOL") == podman ]] && userns=(--userns=keep-id)
  # The image already starts Chromium with --no-sandbox (/puppeteer-config.json).
  # Only the diagrams directory is mounted, so :z relabels nothing else on SELinux hosts.
  # ${userns[@]+...} keeps an empty array safe under set -u in bash before 4.4.
  # shellcheck disable=SC2016 # the loop runs in the container's shell
  "$TOOL" run --rm ${userns[@]+"${userns[@]}"} --user "$(id -u):$(id -g)" \
    -v "$abs:/data:z" --entrypoint /bin/sh "$IMG" -c '
      set -e
      for f in *.mmd; do
        n=${f%.mmd}
        /home/mermaidcli/node_modules/.bin/mmdc -p /puppeteer-config.json -q \
          -c mermaid.json -b white -I "$n" -i "$f" -o "$n.svg"
      done'
  local f
  for f in "$DIR"/*.mmd; do
    # mmdc writes no final newline; the stamp goes on a line of its own.
    printf '\n<!-- diagram-source-sha256: %s -->\n' "$(stamp "$f")" >> "${f%.mmd}.svg"
    echo "rendered ${f%.mmd}.svg"
  done
}

check() {
  local rc=0 f svg
  for f in "$DIR"/*.mmd; do
    [[ -e $f ]] || continue
    svg=${f%.mmd}.svg
    if ! grep -qxF "<!-- diagram-source-sha256: $(stamp "$f") -->" "$svg" 2>/dev/null; then
      echo "$svg is missing or out of date with $f: run 'make diagrams' and commit the SVG." >&2
      rc=1
    fi
  done
  for svg in "$DIR"/*.svg; do
    if [[ -e $svg && ! -e ${svg%.svg}.mmd ]]; then
      echo "$svg has no ${svg%.svg}.mmd source: delete it or add the source." >&2
      rc=1
    fi
  done
  if [[ $rc == 0 ]]; then echo "diagrams OK"; fi
  return "$rc"
}

if [[ ! -f $DIR/mermaid.json ]]; then
  echo "$DIR/mermaid.json not found: run this from the repository root (or set DIAGRAMS_DIR)." >&2
  exit 2
fi
case ${1:-} in
  render) render ;;
  check) check ;;
  *) echo "usage: $0 render|check" >&2; exit 2 ;;
esac
