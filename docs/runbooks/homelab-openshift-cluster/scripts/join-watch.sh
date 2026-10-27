#!/bin/bash
# Usage: join-watch.sh <node-name> <node-ip> [timeout-seconds]
# Watches a reinstalled worker join sage: ping/ssh state, MCS fetches from its IP,
# and approves ONLY that node's kubelet client CSR (via node-bootstrapper) and serving CSR.
# Exits 0 once the node is Ready with no pending CSRs of its own.
N=$1; IP=$2; TMO=${3:-3000}
CTX="--context sage"
SSHO="-o BatchMode=yes -o ConnectTimeout=5 -o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=no -o LogLevel=ERROR"
BOOT="system:serviceaccount:openshift-machine-config-operator:node-bootstrapper"
prev=""; mcs_seen=0; end=$((SECONDS+TMO))
log() { echo "$(date -u +%T) $*"; }
while [ $SECONDS -lt $end ]; do
  ping -c1 -W2 "$IP" >/dev/null 2>&1 && p=up || p=down
  s=$(ssh $SSHO core@"$IP" 'test -f /run/ostree-live && echo live || echo "installed:$(rpm-ostree status --json 2>/dev/null | python3 -c "import json,sys; d=json.load(sys.stdin)[\"deployments\"]; print(len(d), d[0].get(\"version\",\"?\"))" 2>/dev/null)"' 2>/dev/null || echo nossh)
  ns=$(oc $CTX get node "$N" -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}' 2>/dev/null || true)
  st="ping=$p ssh=$s node=${ns:-absent}"
  [ "$st" != "$prev" ] && log "$st" && prev=$st
  if [ $mcs_seen = 0 ] && oc $CTX -n openshift-machine-config-operator logs -l k8s-app=machine-config-server --since=60m 2>/dev/null | grep -q "address:\"$IP:"; then
    mcs_seen=1; log "MCS served config to $IP: $(oc $CTX -n openshift-machine-config-operator logs -l k8s-app=machine-config-server --since=60m | grep "address:\"$IP:" | tail -1 | cut -c1-200)"
  fi
  pending_mine=0
  for csr in $(oc $CTX get csr --no-headers 2>/dev/null | awk '$NF=="Pending"{print $1}'); do
    u=$(oc $CTX get csr "$csr" -o jsonpath='{.spec.username}')
    cn=$(oc $CTX get csr "$csr" -o jsonpath='{.spec.request}' | base64 -d | openssl req -noout -subject 2>/dev/null | sed -n 's/.*CN *= *\([^,]*\).*/\1/p')
    if { [ "$u" = "$BOOT" ] || [ "$u" = "system:node:$N" ]; } && [ "$cn" = "system:node:$N" ]; then
      oc $CTX adm certificate approve "$csr" >/dev/null && log "approved $csr (user=$u cn=$cn)"; pending_mine=1
    fi
  done
  if [ "$ns" = True ] && [ $pending_mine = 0 ]; then log "node $N Ready"; exit 0; fi
  sleep 10
done
log "TIMEOUT after ${TMO}s: $prev"; exit 1
