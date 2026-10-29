#!/usr/bin/env bash
# Smoke-test a built operator image without a cluster. Runs as an arbitrary
# UID in group 0 (as OpenShift does), lists the installed collections,
# imports the python libraries the roles need and syntax-checks a play that
# includes every role from watches.yaml.
#
# Usage: hack/image-smoke-test.sh IMAGE
#
# Set CONTAINER_TOOL to docker to use docker (default: podman).
set -euo pipefail

image=${1:?usage: hack/image-smoke-test.sh IMAGE}
tool=${CONTAINER_TOOL:-podman}

roles=$(sed -n 's/^ *role: *//p' watches.yaml)
[ -n "$roles" ] || { echo "error: no roles found in watches.yaml" >&2; exit 1; }

# shellcheck disable=SC2086 # split the role names on purpose
syntax_play="---
- name: Syntax check all operator roles
  hosts: localhost
  gather_facts: false
  roles:
$(printf '    - %s\n' $roles)"

# shellcheck disable=SC2016 # the script below runs inside the container
"$tool" run --rm --user 12345:0 --entrypoint /bin/bash \
  -e SYNTAX_PLAY="$syntax_play" \
  "$image" -c '
set -euo pipefail
cd "$HOME"
id
ansible --version | head -n 1
ansible-galaxy collection list 2>/dev/null
python3 -c "import kubernetes, yaml, jinja2; print(\"kubernetes\", kubernetes.__version__)"
printf "%s\n" "$SYNTAX_PLAY" > /tmp/syntax.yml
ANSIBLE_ROLES_PATH="$HOME/roles" ansible-playbook --syntax-check /tmp/syntax.yml
'
echo "image smoke test passed: $image"
