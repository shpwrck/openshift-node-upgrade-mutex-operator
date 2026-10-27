#!/bin/bash
# Runs ON the target node (chroot /host). Non-destructive: stages the RHCOS live
# installer in /var/tmp/reinstall and test-loads it with kexec, then unloads it.
# Expects STAGE_TGZ_B64 in the environment (keyfiles, worker.ign, live-ssh.ign, pxe.env, disk-by-id).
set -euo pipefail
D=/var/tmp/reinstall
mkdir -p "$D" && cd "$D"
echo "$STAGE_TGZ_B64" | base64 -d | tar xzf -
. ./pxe.env
DISK=/dev/disk/by-id/$(cat disk-by-id)
[ -b "$DISK" ] || { echo "FATAL: $DISK missing"; exit 1; }
echo "target disk: $DISK -> $(readlink -f "$DISK")"

fetch() { # url sha out
  if [ -f "$3" ] && echo "$2  $3" | sha256sum -c --quiet - 2>/dev/null; then echo "$3 cached ok"; return; fi
  curl -fsSL --retry 3 -o "$3" "$1"
  echo "$2  $3" | sha256sum -c -
}
fetch "$KERNEL_URL" "$KERNEL_SHA" vmlinuz
fetch "$INITRAMFS_URL" "$INITRAMFS_SHA" initramfs.img
fetch "$ROOTFS_URL" "$ROOTFS_SHA" rootfs.img

KF=()
for f in *.nmconnection; do KF+=(--network-keyfile "$f"); done
rm -f initramfs-custom.img
coreos-installer pxe customize \
  --dest-device "$DISK" \
  --dest-ignition worker.ign \
  --live-ignition live-ssh.ign \
  "${KF[@]}" \
  -o initramfs-custom.img initramfs.img
cat initramfs-custom.img rootfs.img > combined.img
ls -la "$D"

CMDLINE="ignition.firstboot ignition.platform.id=metal console=tty0"
echo "$CMDLINE" > cmdline
echo "kexec_loaded before: $(cat /sys/kernel/kexec_loaded)"
kexec -s -l vmlinuz --initrd=combined.img --command-line="$CMDLINE"
echo "kexec_loaded after load: $(cat /sys/kernel/kexec_loaded)"
kexec -s -u
echo "kexec_loaded after unload: $(cat /sys/kernel/kexec_loaded)"
echo STAGE_OK
