#!/bin/bash
# Runs as root INSIDE the RHCOS live env (kexec'd, nothing installed yet).
#   live-install.sh check    -> go/no-go gate; touches nothing
#   live-install.sh install  -> gate again, then write disk + create UEFI boot entry (no reboot)
# Files expected next to it: worker.ign, mcs-ca.pem, disk-by-id, net/*.nmconnection
# Env: EXPECT_IP (172.16.10.9 hub / 172.16.10.10 spoke)
set -uo pipefail
cd "$(dirname "$0")"
MODE=${1:-check}
DISK=/dev/disk/by-id/$(cat disk-by-id)
OLD_ESP_PARTUUID=0cac9b5d-3760-d248-be28-b81e5b264ec1
fail=0
check() { local d=$1; shift; if "$@" >/dev/null 2>&1; then echo "PASS $d"; else echo "FAIL $d"; fail=1; fi; }

check "live env" test -f /run/ostree-live
check "bond0 has $EXPECT_IP/20" bash -c "ip -4 -o addr show bond0 | grep -q ' $EXPECT_IP/20 '"
check "default route via 172.16.0.1 dev bond0" bash -c "ip route show default | grep -q 'via 172.16.0.1 dev bond0'"
check "bond 802.3ad with 2 slaves up" bash -c "grep -q 802.3ad /proc/net/bonding/bond0 && [ \$(grep -c 'MII Status: up' /proc/net/bonding/bond0) -ge 3 ]"
check "api-int.sage resolves to 172.16.10.11" bash -c "getent ahostsv4 api-int.sage.k8socp.com | grep -q 172.16.10.11"
check "MCS /config/worker via pointer CA" bash -c "curl -sf --max-time 20 --cacert mcs-ca.pem -H 'Accept: application/vnd.coreos.ignition+json;version=3.5.0' https://api-int.sage.k8socp.com:22623/config/worker -o /tmp/served.ign && [ \$(stat -c %s /tmp/served.ign) -gt 100000 ]"
check "API readyz" bash -c "curl -sk --max-time 10 https://api-int.sage.k8socp.com:6443/readyz | grep -qx ok"
check "quay.io reachable" bash -c "curl -s -o /dev/null --max-time 15 -w '%{http_code}' https://quay.io/v2/ | grep -qE '^(200|401)$'"
check "efivars populated" bash -c "ls /sys/firmware/efi/efivars | grep -q '^Boot'"
check "efibootmgr works" efibootmgr
check "target disk $DISK" test -b "$DISK"
check "sgdisk available" command -v sgdisk
check "4 network keyfiles" bash -c "[ \$(ls net/*.nmconnection | wc -l) -eq 4 ]"
[ $fail = 0 ] && echo "GATE: GO" || { echo "GATE: NO-GO (disk untouched; 'systemctl reboot' returns to the old SNO)"; exit 2; }
[ "$MODE" = install ] || exit 0

set -e
echo "== installing to $DISK"
# tty0 LAST => /dev/console (emergency shells, PID1 status) is the KVM-visible VT;
# ttyS2 (AMT SOL) still mirrors kernel messages.
coreos-installer install "$DISK" --ignition-file worker.ign -n --network-dir net \
  --append-karg console=ttyS2,115200n8 --append-karg console=tty0
udevadm settle
DEV=$(readlink -f "$DISK")
NEW=$(blkid -s PARTUUID -o value "${DEV}p2")
echo "new ESP PARTUUID=$NEW"
set +e
STALE=$(efibootmgr -v | awk -v u="$OLD_ESP_PARTUUID" 'index($0,u){print substr($1,5,4)}')
if efibootmgr -c -d "$DEV" -p 2 -L 'Red Hat Enterprise Linux' -l '\EFI\redhat\shimx64.efi' && efibootmgr -v | grep -qi "$NEW"; then
  for b in $STALE; do efibootmgr -b "$b" -B >/dev/null; done
  echo "EFI: created entry for $NEW, removed stale [$STALE]"
else
  echo "EFI: efibootmgr failed; re-stamping new ESP with old PARTUUID so the existing entry matches"
  sgdisk --partition-guid=2:"$OLD_ESP_PARTUUID" "$DISK" && partprobe "$DEV"; udevadm settle
  blkid -s PARTUUID -o value "${DEV}p2"
fi
efibootmgr -v
lsblk -o NAME,SIZE,FSTYPE,LABEL,PARTUUID "$DEV"
echo INSTALL_DONE
