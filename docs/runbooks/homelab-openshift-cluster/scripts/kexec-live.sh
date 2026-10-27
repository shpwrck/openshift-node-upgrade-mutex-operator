#!/bin/bash
# Runs ON the target node (chroot /host), after stage.sh. Builds a live-only
# initramfs (network keyfiles + operator ssh key; NO --dest-* so nothing is
# installed automatically), loads it with signed kexec and, if ARM=1, boots it.
set -euo pipefail
cd /var/tmp/reinstall
KF=()
for f in *.nmconnection; do KF+=(--network-keyfile "$f"); done
rm -f initramfs-live.img live-combined.img
coreos-installer pxe customize --live-ignition live-ssh.ign "${KF[@]}" -o initramfs-live.img initramfs.img
cat initramfs-live.img rootfs.img > live-combined.img
# live-env only: serial console for AMT SOL, reboot (=> old SNO, disk untouched) on any early failure
CMDLINE="ignition.firstboot ignition.platform.id=metal console=ttyS2,115200n8 console=tty0 rd.emergency=reboot panic=10"
kexec -s -u || true
kexec -s -l vmlinuz --initrd=live-combined.img --command-line="$CMDLINE"
echo "kexec_loaded=$(cat /sys/kernel/kexec_loaded) cmdline=$CMDLINE"
if [ "${ARM:-0}" = 1 ]; then
  echo "ARMED: systemctl kexec at $(date -u +%FT%TZ)"
  systemctl kexec
fi
