# hack/docs-links.awk: rewrite Markdown link and image targets that are written
# relative to docs/ (the way GitHub resolves them in docs/*.md).
#   awk -v mode=readme -f hack/docs-links.awk docs/USAGE.md docs/DEVELOPMENT.md > README.md
#       targets become relative to the repository root; files are joined by a blank line
#   awk -v mode=csv -v base=REPO_URL -v ref=BRANCH -f hack/docs-links.awk docs/USAGE.md
#       targets become REPO_URL/blob/BRANCH/...; images become plain links, because
#       the OpenShift console strips <img> from the CSV description
# Absolute URLs (any target with a ':'), #anchors and ``` fenced blocks are left alone.
# A leading ./ is dropped. `make document` and `make bundle` run this script.
FNR == 1 && NR != 1 { print ""; fence = 0 }
/^[ \t]*```/ { fence = !fence; print; next }
fence { print; next }
{
  docs = (mode == "csv") ? base "/blob/" ref "/docs/" : "docs/"
  root = (mode == "csv") ? base "/blob/" ref "/" : ""
  out = ""
  while (match($0, /(!\[[^]]*)?\]\([^):]*\)/)) {
    m = substr($0, RSTART, RLENGTH)
    img = (substr(m, 1, 1) == "!")
    tgt = m; sub(/^.*\]\(/, "", tgt); sub(/\)$/, "", tgt)
    while (tgt ~ /^\.\//) tgt = substr(tgt, 3)
    if (tgt ~ /^\.\.\//) { tgt = root substr(tgt, 4); if (tgt == "") tgt = "./" }
    else if (tgt ~ /^[A-Za-z0-9_]/) tgt = docs tgt
    if (img) {
      alt = m; sub(/^!\[/, "", alt); sub(/\]\(.*$/, "", alt)
      m = (mode == "csv") ? "[Diagram (opens on GitHub): " alt "](" tgt ")" : "![" alt "](" tgt ")"
    } else m = "](" tgt ")"
    out = out substr($0, 1, RSTART - 1) m
    $0 = substr($0, RSTART + RLENGTH)
  }
  print out $0
}
