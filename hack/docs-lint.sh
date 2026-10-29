#!/usr/bin/env bash
# hack/docs-lint.sh: check the Markdown documentation. Run by `make docs-lint`
# and by CI. Needs bash (3.2 or later), git, awk, grep, sort and tr.
#
# Every *.md file git knows about (tracked, or untracked and not ignored) is
# checked, the generated README.md included. Outside ``` fences and `code`:
#   [link]     every relative link or image target exists in the repository,
#              resolved from the file's directory; no root-relative (/x)
#              targets; no absolute REPO_URL/blob/ or REPO_URL/tree/ links
#              (write them relative: `make document` makes them absolute in
#              the CSV, pinned to a branch or tag)
#   [anchor]   every #fragment of a link to a Markdown file (the same file or
#              another) is the GitHub anchor of one of its headings
#   [image]    every image has alt text
#   [console]  docs/USAGE.md, which becomes the CSV description shown in the
#              OpenShift console: no blockquotes or GitHub alerts, no h5/h6
#              headings, no <img>, <picture>, <details>, <summary>, <br>,
#              <blockquote>, <h5> or <h6>, and every image is written on one
#              line as ![<alt text>](diagrams/<name>.svg)
#   [targets]  the table in docs/DEVELOPMENT.md whose first header cell is
#              "Target" lists exactly the Makefile targets that `make help`
#              shows, each as `name` or `make name` in the first column
# In other files:
#   [diagram]  every docs/diagrams/*.svg is referenced by some *.md file
#   [owner]    outside docs/HANDOFF.md, every github.com, raw.githubusercontent.com
#              and ghcr.io path of this repository uses REPO_URL's owner
#   [private]  *.md and *.mmd files name no RFC 1918 address and no .lan or
#              .home.arpa host
#
# Usage: REPO_URL=https://github.com/<owner>/<repository> hack/docs-lint.sh
set -euo pipefail

cd "$(dirname "$0")/.."

repo_url=${REPO_URL:?set REPO_URL to https://<host>/<owner>/<repository> (make docs-lint does)}
repo_url=${repo_url%/}
case $repo_url in
  https://*/*/*) ;;
  *) echo "REPO_URL=$repo_url is not https://<host>/<owner>/<repository>" >&2; exit 2 ;;
esac
rest=${repo_url#https://*/}
owner=${rest%%/*}
owner_lc=$(printf '%s' "$owner" | tr '[:upper:]' '[:lower:]')

tmp=$(mktemp -d "${TMPDIR:-/tmp}/docs-lint.XXXXXX")
trap 'rm -rf "$tmp"' EXIT
: > "$tmp/errors"

# The files git knows about that exist on disk: tracked ones, and untracked
# ones that are not ignored, so a new document counts before it is committed.
git ls-files -z --cached --others --exclude-standard | tr '\0' '\n' | sort -u |
  while IFS= read -r f; do
    if [ -e "$f" ]; then printf '%s\n' "$f"; fi
  done > "$tmp/files"
grep -E '\.md$' "$tmp/files" > "$tmp/md" || true

# [link] [anchor] [image] [console] [targets]
LC_ALL=C awk -v files="$tmp/files" -v mdlist="$tmp/md" -v repo="$repo_url" '
function err(f, n, msg) { printf "%s:%d: %s\n", f, n, msg }
function dirname(p) { return match(p, /\/[^\/]*$/) ? substr(p, 1, RSTART - 1) : "" }
function nocode(s) { gsub(/`[^`]*`/, "", s); return s }
# Collapse . and .. ; returns "\n" for a path above the repository root.
function norm(p,   n, parts, i, outn, out, s) {
  n = split(p, parts, "/"); outn = 0
  for (i = 1; i <= n; i++) {
    if (parts[i] == "" || parts[i] == ".") continue
    if (parts[i] == "..") { if (outn == 0) return "\n"; outn--; continue }
    out[++outn] = parts[i]
  }
  s = ""
  for (i = 1; i <= outn; i++) s = s (i > 1 ? "/" : "") out[i]
  return s
}
# The anchor GitHub gives a heading: its text without Markdown link syntax and
# HTML tags, lower-cased, without punctuation, spaces turned into hyphens.
function slug(h,   s, m, t) {
  s = h
  sub(/^[ \t]*#+[ \t]*/, "", s); sub(/[ \t]+#+[ \t]*$/, "", s); sub(/[ \t]+$/, "", s)
  while (match(s, /!?\[[^]]*\]\([^)]*\)/)) {
    m = substr(s, RSTART, RLENGTH); t = m
    sub(/^!?\[/, "", t); sub(/\]\(.*$/, "", t)
    s = substr(s, 1, RSTART - 1) t substr(s, RSTART + RLENGTH)
  }
  gsub(/<[^>]*>/, "", s)
  s = tolower(s)
  gsub(/[^a-z0-9 _-]/, "", s)
  gsub(/ /, "-", s)
  return s
}
function target(f, n, t,   q, frag, base, p) {
  sub(/^[ \t]+/, "", t)
  if (t ~ /^</) { sub(/^</, "", t); sub(/>.*$/, "", t) } else sub(/[ \t].*$/, "", t)
  if (t == "") { err(f, n, "[link] empty link target"); return }
  if (t ~ /^[A-Za-z][A-Za-z0-9+.-]*:/) {
    if (f != "README.md" && (index(t, repo "/blob/") == 1 || index(t, repo "/tree/") == 1))
      err(f, n, "[link] " t " is an absolute link to this repository: write it relative to " f)
    return
  }
  if (t ~ /^\//) { err(f, n, "[link] " t " is root-relative: write it relative to " f); return }
  frag = ""
  if ((q = index(t, "#")) > 0) { frag = substr(t, q + 1); t = substr(t, 1, q - 1) }
  sub(/\?.*$/, "", t)
  if (t == "") p = f
  else {
    base = dirname(f)
    p = norm(base == "" ? t : base "/" t)
    if (p == "\n") { err(f, n, "[link] " t " points outside the repository"); return }
    if (p != "" && !(p in exists) && !(p in isdir)) {
      err(f, n, "[link] " t " does not exist (resolved to " p ")"); return
    }
  }
  if (frag != "" && (p in ismd)) { np++; pf[np] = f; pn[np] = n; pp[np] = p; pfrag[np] = frag }
}
BEGIN {
  while ((getline l < files) > 0) {
    exists[l] = 1
    d = l
    while (match(d, /\/[^\/]*$/)) { d = substr(d, 1, RSTART - 1); isdir[d] = 1 }
  }
  close(files)
  nmd = 0
  while ((getline l < mdlist) > 0) { ismd[l] = 1; md[++nmd] = l }
  close(mdlist)
  usage = "docs/USAGE.md"; dev = "docs/DEVELOPMENT.md"

  for (k = 1; k <= nmd; k++) {
    f = md[k]; n = 0; fence = 0; intable = 0; split("", seen)
    while ((getline line < f) > 0) {
      n++
      if (line ~ /^[ \t]*```/) { fence = !fence; continue }
      if (fence) continue
      s = nocode(line)

      # Headings and explicit <a id/name> anchors.
      if (line ~ /^ ? ? ?#+([ \t]|$)/ && match(line, /#+/) && RLENGTH <= 6) {
        a = slug(line)
        if (a in seen) { seen[a]++; a = a "-" (seen[a] - 1) } else seen[a] = 1
        anchor[f, a] = 1
      }
      t = s
      while (match(t, /<a [^>]*(id|name)="[^"]*"/)) {
        m = substr(t, RSTART, RLENGTH); t = substr(t, RSTART + RLENGTH)
        sub(/^.*(id|name)="/, "", m); sub(/"$/, "", m); anchor[f, m] = 1
      }

      # Inline links and images, reference definitions, href= and src=.
      t = s
      # (target() calls match() too: take the match before calling it.)
      while (match(t, /\]\([^)]*\)/)) {
        m = substr(t, RSTART + 2, RLENGTH - 3); t = substr(t, RSTART + RLENGTH); target(f, n, m)
      }
      if (match(s, /^ ? ? ?\[[^]]+\]:[ \t]+[^ \t]+/)) {
        t = substr(s, RSTART, RLENGTH); sub(/^[^]]*\]:[ \t]+/, "", t); target(f, n, t)
      }
      t = s
      while (match(t, /(href|src)="[^"]*"/)) {
        m = substr(t, RSTART, RLENGTH); t = substr(t, RSTART + RLENGTH)
        sub(/^[a-z]*="/, "", m); sub(/"$/, "", m); target(f, n, m)
      }
      if (index(s, "![](") > 0) err(f, n, "[image] image without alt text")

      if (f == usage) {
        if (line ~ /^[ \t]*>/)
          err(f, n, "[console] blockquote or GitHub alert: the OpenShift console drops it from the CSV description")
        if (line ~ /^ ? ? ?#####/)
          err(f, n, "[console] h5/h6 heading: the OpenShift console drops it; use h2-h4")
        if (tolower(s) ~ /<(img|picture|details|summary|br|blockquote|h5|h6)([ \t\/>]|$)/)
          err(f, n, "[console] raw HTML the OpenShift console drops: use plain Markdown")
        t = s
        while ((i = index(t, "![")) > 0) {
          t = substr(t, i)
          if (match(t, /^!\[[^]]+\]\(diagrams\/[A-Za-z0-9._-]+\.svg\)/)) t = substr(t, RLENGTH + 1)
          else {
            err(f, n, "[console] write images on one line as ![<alt text>](diagrams/<name>.svg)")
            t = substr(t, 3)
          }
        }
      }

      # The make targets table: first header cell "Target".
      if (f == dev && !tabledone) {
        if (!intable && tolower(line) ~ /^\|[ \t]*target[ \t]*\|/) { intable = 1; tableline = n; continue }
        if (intable && line !~ /^[ \t]*\|/) { intable = 0; tabledone = 1 }
        else if (intable && line !~ /^[ \t]*\|[ \t:|-]*$/) {
          c = line; sub(/^[ \t]*\|/, "", c); sub(/\|.*$/, "", c)
          while (match(c, /`[^`]+`/)) {
            w = substr(c, RSTART + 1, RLENGTH - 2); c = substr(c, RSTART + RLENGTH)
            sub(/^make[ \t]+/, "", w); sub(/[ \t].*$/, "", w)
            if (!(w in row)) { row[w] = n; nrow++ }
          }
        }
      }
    }
    close(f)
    if (f == dev && intable) tabledone = 1
  }

  for (k = 1; k <= np; k++)
    if (!((pp[k], pfrag[k]) in anchor))
      err(pf[k], pn[k], "[anchor] #" pfrag[k] " is not a heading anchor in " pp[k])

  if (dev in ismd) {
    while ((getline l < "Makefile") > 0)
      if (l ~ /^[a-zA-Z_0-9-]+:.*##/) { sub(/:.*$/, "", l); mk[l] = 1 }
    close("Makefile")
    if (!tabledone)
      err(dev, 1, "[targets] no make targets table (a table whose first header cell is Target)")
    else {
      for (w in mk) if (!(w in row))
        err(dev, tableline, "[targets] make " w " (in make help) is missing from the targets table")
      for (w in row) if (!(w in mk))
        err(dev, row[w], "[targets] " w " is not a Makefile target that make help shows")
    }
  }
}' >> "$tmp/errors"

# [diagram]
grep -E '^docs/diagrams/[^/]+\.svg$' "$tmp/files" > "$tmp/svgs" || true
while IFS= read -r f; do cat "$f"; done < "$tmp/md" > "$tmp/md-text"
while IFS= read -r svg; do
  if ! grep -qF "${svg#docs/}" "$tmp/md-text"; then
    echo "$svg:1: [diagram] no Markdown file embeds ${svg#docs/}: embed it or delete it and its .mmd" >> "$tmp/errors"
  fi
done < "$tmp/svgs"

# [owner]
git grep --untracked -n -I -o -E \
  '(github\.com|raw\.githubusercontent\.com|ghcr\.io)/[A-Za-z0-9_.-]+/openshift-node-upgrade-mutex-operator' \
  -- . ':(exclude)docs/HANDOFF.md' > "$tmp/owners" || [ $? = 1 ]
awk -v owner="$owner" -v owner_lc="$owner_lc" '{
  f = $0; sub(/:.*/, "", f); r = substr($0, length(f) + 2); n = r; sub(/:.*/, "", n)
  m = substr(r, length(n) + 2); split(m, p, "/")
  ok = (p[1] == "ghcr.io") ? (tolower(p[2]) == owner_lc) : (p[2] == owner)
  if (!ok) printf "%s:%s: [owner] %s does not use the owner %s of REPO_URL\n", f, n, m, owner
}' "$tmp/owners" >> "$tmp/errors"

# [private]
oct='[0-9][0-9]?[0-9]?'
ip="(^|[^0-9.])(10\\.$oct\\.$oct\\.$oct|172\\.(1[6-9]|2[0-9]|3[01])\\.$oct\\.$oct|192\\.168\\.$oct\\.$oct)([^0-9]|$)"
git grep --untracked -n -I -E -e "$ip" -e '[A-Za-z0-9-]\.(lan|home\.arpa)([^A-Za-z0-9-]|$)' \
  -- '*.md' '*.mmd' > "$tmp/private" || [ $? = 1 ]
awk '{
  f = $0; sub(/:.*/, "", f); n = substr($0, length(f) + 2); sub(/:.*/, "", n)
  printf "%s:%s: [private] a private (RFC 1918) address or a .lan/.home.arpa host name\n", f, n
}' "$tmp/private" >> "$tmp/errors"

if [ -s "$tmp/errors" ]; then
  sort -u "$tmp/errors" | sort -t: -k1,1 -k2,2n >&2
  echo "docs-lint: $(sort -u "$tmp/errors" | wc -l | tr -d ' ') problem(s)" >&2
  exit 1
fi
echo "docs OK"
