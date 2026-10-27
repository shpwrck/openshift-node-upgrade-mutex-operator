#!/bin/bash
# Typed into hub's dracut emergency shell as: curl -fsS http://172.16.10.10:18090/fix.sh | bash
# Stages the RHCOS live kernel+initramfs onto hub's /boot and makes it GRUB's default
# entry (via /boot/grub2/user.cfg, sourced by RHCOS grub.cfg before blscfg), then reboots.
# The live env fetches its rootfs from spoke and comes up with bond0 + operator ssh key.
# Uses only bash builtins + curl/mount/umount/systemctl (the initramfs has no coreutils
# like df, sha256sum, mountpoint, sleep).
set -uo pipefail
SRV=http://172.16.10.10:18090
B=/run/fixboot
fail() { echo "FIXBOOT_FAIL: $*"; exit 1; }
mkdir -p "$B" || fail mkdir
grep -qs " $B " /proc/mounts || mount /dev/disk/by-label/boot "$B" || fail "mount boot"
mount -o remount,rw "$B" || fail "remount rw"
mkdir -p "$B/live" || fail "mkdir live"
get() { # remote-name local-name expected-bytes
  local n
  n=$(curl -fsS -o "$B/live/$2" -w '%{size_download}' "$SRV/$1") || fail "download $1"
  [ "$n" = "$3" ] || fail "size $1 got $n want $3"
  echo "ok $2 $n bytes"
}
get vmlinuz vmlinuz 14964856
get initramfs-live-hub.img initramfs.img 108733004
printf '%s\n' \
  "menuentry 'RHCOS live (reinstall)' --id live-reinstall {" \
  "  search --no-floppy --label boot --set lboot" \
  "  linux (\$lboot)/live/vmlinuz ignition.firstboot ignition.platform.id=metal rd.neednet=1 coreos.live.rootfs_url=http://172.16.10.10:18090/rootfs.img console=ttyS2,115200n8 console=tty0 rd.emergency=reboot panic=10" \
  "  initrd (\$lboot)/live/initramfs.img" \
  "}" \
  "set default=live-reinstall" > "$B/grub2/user.cfg" || fail "write user.cfg"
echo "--- $B/grub2/user.cfg:"; while IFS= read -r l; do echo "$l"; done < "$B/grub2/user.cfg"
umount "$B" || fail "umount boot"
echo "FIXBOOT_OK $(< /proc/sys/kernel/hostname)" > /dev/tcp/172.16.0.1/18080 2>/dev/null || true
echo "FIXBOOT_OK - rebooting into the live environment in 3s"
read -r -t 3 _ < /dev/zero 2>/dev/null; read -r -t 3 _ <> <(:) 2>/dev/null || true
systemctl --force --force reboot
