---
leave-behind: v1
state-scope: homelab-openshift-cluster
status: current
---

# Homelab OpenShift cluster (sage control plane + hub/spoke workers) leave-behind

On 2026-10-27 three single-node OpenShift (SNO) clusters were consolidated into one cluster.
`sage` stayed as the cluster: one control-plane node that also runs workloads. `hub` and `spoke`
were wiped and rejoined it as RHCOS workers. The old `hub` and `spoke` clusters no longer exist.

## Operability

### State and access

| Node  | Role(s)                       | IP (bond0 / br-ex) | Hardware / out-of-band |
|-------|-------------------------------|--------------------|-------------------------|
| sage  | control-plane, master, worker | 172.16.10.11/20    | ASUS workstation; BMC with virtual media (see the Outline page "Sage's BMC") |
| hub   | worker                        | 172.16.10.9/20     | Minisforum MS-01 (i9-13900H, BIOS 1.26, 2×48 GB DDR5), NVMe `KINGSTON_SNV3S1000G_50026B768719E546` (fw SDQ00103), **Secure Boot on**; Intel AMT at 192.168.17.78 |
| spoke | worker                        | 172.16.10.10/20    | Same MS-01 build, NVMe `KINGSTON_SNV3S1000G_50026B7686FA3365` (fw ERFK1N.3), Secure Boot off; Intel AMT at 192.168.26.80 |

- **Cluster:**
  - OCP 4.21.20 on channel `stable-4.21`, platform `None` (user-managed networking).
  - clusterID `641b93d1-f036-45ee-92c6-8f4559c2b7cf`; OVN-Kubernetes, MTU 1400; clusterNetwork 10.128.0.0/14 /23; machine network 172.16.0.0/20 with gateway and DNS at 172.16.0.1.
  - Topology is still `SingleReplica`. Workers on an SNO control plane are supported.
- **API and admin access:**
  - API at `https://api.sage.k8socp.com:6443`, using kube context `sage` (user `sage-kube-admin`) in `~/.kube/config`.
  - The dead `hub`/`spoke` contexts, clusters and users were removed on 2026-10-27. The pre-cleanup copy is `~/.kube/config.bak-pre-consolidation-20261027`.
- **Host shell on a node:** `oc --context sage debug node/<name>`, or `ssh core@<IP>`.
  - The worker pool's `core` user trusts the workstation key `~/.ssh/id_ed25519.pub` (jskrzypek@DESKTOP-VQTUEVT). It was added to MachineConfig `99-worker-ssh` next to the existing RSA key.
  - The master pool's SSH config was not changed.
  - Use IPs for SSH, not the names `hub`/`spoke`: those UniFi client names resolve to the AMT interfaces.
- **Out-of-band for hub and spoke:** MeshCentral at https://meshcentral.skrzypek.dev, device group "OpenShift MS-01 Power". AMT gives:
  - power control;
  - KVM ("Remote Desktop");
  - Serial-over-LAN, which is `ttyS2` on the host.

  AMT Redirection, KVM and SOL were enabled on both machines on 2026-10-27. The login is the `meshadmin` item in the owner's Bitwarden vault; this repo holds no AMT credentials. Power-management conventions are on the Outline pages "MeshCentral — power management" and "Cluster Operations".
- **DNS:** UniFi Network "DNS Records" (the `static_dns` collection on the UDM Pro, 172.16.0.1, root SSH with the workstation key). Records for sage:
  - `api.sage.k8socp.com`
  - `*.apps.sage.k8socp.com`
  - `api-int.sage.k8socp.com` (added 2026-10-27, required by the workers)

  All three point to 172.16.10.11. Edit them only through the UniFi UI; the local Network API needs a UniFi login, which isn't stored here. The old `api.{hub,spoke}`/`*.apps.{hub,spoke}` records were deleted by the owner on 2026-10-27, and both now return NXDOMAIN.
- **Ingress:** the default router is HostNetwork and stays on sage. `ingresses.config/cluster` has `status.defaultPlacement=ControlPlane`, so it is pinned to the control plane without any IngressController patch, and `*.apps` traffic for workloads on hub and spoke enters through sage. Sage's pod-network throughput to the workers measured about 1 Gbit/s, against about 2 Gbit/s between hub and spoke.
- **Storage:** storage classes `truenas-nfs` and `truenas-iscsi` (the default) from the truenas-csi operator: CR `truenascsis.csi.truenas.io/truenas`, credentials in secret `truenas-csi/truenas-api-credentials`.
  - The driver is pinned to **v1.4.0**: `spec.driverImage: quay.io/truenas_solutions/truenas-csi:v1.4.0@sha256:fb669f220d1eea7c04f34757d2f3f414a702f4ae111c82bb65fa9e3280d33819`, for both the controller Deployment and the node DaemonSet on all three nodes.
  - v1.4.0 PVs carry no node affinity, so they schedule on any node.
  - Sage keeps stale labels `topology.truenas.io/{pool,node}` from v0.1.0. They're harmless.
  - The CSIDriver has `fsGroupPolicy=File`, so iSCSI volumes are writable only by pods with an `fsGroup`. The restricted-v2 SCC sets one automatically; custom SCCs may not.
- **ACM:**
  - sage is the ACM 2.17 hub. Its only ManagedCluster is now `sage` (local).
  - The ManagedClusters `hub` and `spoke` were removed by uninstalling Helm releases `acm-managed-cluster-hub` and `acm-managed-cluster-spoke` in `open-cluster-management`.
  - The Argo cluster secrets `openshift-gitops/{hub,spoke}-argocd-gitops-cluster-secret` were deleted first. They had been applied by hand, and no GitOpsCluster manages them.
  - The generated Applications targeting hub and spoke were deleted cleanly by their ApplicationSets. Sage's GitOps root app `hub-gitops-root`, from github.com/shpwrck/istio-scale-tests, was left alone and is Synced/Healthy. 9 of its 10 ApplicationSets now generate zero apps.
- **Outline API token** (for reading the homelab docs): `~/.config/outline-token`, mode 0600.

### Template map

- `openshift-machine-api/secret worker-user-data-managed` (sage) + `/etc/hostname=<node>` -> `worker.ign`. This is the per-node pointer Ignition config for `https://api-int.sage.k8socp.com:22623/config/worker`.
- `docs/runbooks/homelab-openshift-cluster/net/<node>/*.nmconnection` -> `/boot/coreos-firstboot-network/` on the installed disk -> `/etc/NetworkManager/system-connections/` on the worker. These are bond0 (802.3ad over enp2s0f0/f1, static IP), its two port profiles, and enp89s0 (the AMT-shared I226-LM) with `autoconnect=false`.
- `openshift-machine-config-operator/cm coreos-bootimages` (RHCOS `9.6.20260520-0` metal PXE kernel, initramfs, rootfs) -> `/var/tmp/reinstall/{vmlinuz,initramfs.img,rootfs.img}` on the node being reinstalled. Checksums come from the stream JSON.
- `coreos-installer pxe customize --network-keyfile ×4 --live-ignition live-ssh.ign` -> `initramfs-live.img`, then `cat initramfs-live.img rootfs.img` -> `live-combined.img`. That is the live environment booted with `kexec -s`; it has no `--dest-*` flags, so it never installs on its own.
- `scripts/live-install.sh install` -> NVMe image, then `/boot/ignition/config.ign`, kernel arguments `console=ttyS2,115200n8 console=tty0` (tty0 last), and a new UEFI entry `Red Hat Enterprise Linux` -> `\EFI\redhat\shimx64.efi` on the new ESP (PARTUUID `2d564e30-b933-694d-8a29-424660ebf395`).
- MachineConfig `99-worker-ssh` -> `rendered-worker-9c6024a7213dd362a26500ba6f558c97` -> `core` authorized keys on hub and spoke.
- `TrueNASCSI truenas` `spec.driverImage` (v1.4.0 digest) -> `truenas-csi/truenas-csi-controller` Deployment + `truenas-csi/truenas-csi-node` DaemonSet (operator-managed; edit only the CR).
- `scripts/fix.sh` (recovery only) -> `/boot/live/{vmlinuz,initramfs.img}` + `/boot/grub2/user.cfg`. This is a default GRUB entry that boots the live environment from `/boot`, fetching rootfs over HTTP.

### Re-run

Use this to reinstall or add an MS-01 worker. The scripts are in `scripts/`, and each one says where it runs.

1. **Prerequisites on sage:**
   - `api-int.sage.k8socp.com` resolves on the LAN.
   - `oc --context sage get mcp worker` shows not Degraded.
   - The target's AMT SOL and KVM work in MeshCentral. Keep one open for the whole install.
2. **Build the inputs** on the workstation:
   - `worker.ign`: extract `userData` from `oc --context sage extract -n openshift-machine-api secret/worker-user-data-managed --keys=userData --to=-` and add `/etc/hostname` (`storage.files`, `overwrite: true`).
   - `live-ssh.ign`: Ignition 3.4 with `core`'s `sshAuthorizedKeys`.
   - `pxe.env`: the kernel, initramfs and rootfs URLs and sha256 values from the `coreos-bootimages` stream.
   - `disk-by-id`.
   - The node's keyfiles from `net/<node>/`.
   - `mcs-ca.pem`: the CA from the pointer config.
3. **Stage on the running node** (still the old OS, reached through `oc debug node/<n> -- chroot /host`): run `scripts/stage.sh` with `STAGE_TGZ_B64` set. It downloads and verifies the artifacts, then test-loads and unloads `kexec`.
4. **Boot the live environment:** run `ARM=1 bash scripts/kexec-live.sh` on the node. It builds the live-only initramfs, runs `kexec -s -l` and `systemctl kexec`, and SSH as `core@<IP>` answers about 2–3 minutes later.
5. **Gate, trim, install.** From the workstation, copy the bundle in (`worker.ign`, `mcs-ca.pem`, `disk-by-id`, `net/`, `live-install.sh`) and run these inside the live environment:
   1. `sudo EXPECT_IP=<ip> ./live-install.sh check`. It must print `GATE: GO`. If not, `sudo systemctl reboot` returns to the untouched old OS.
   2. `sudo blkdiscard -f --step 1G /dev/nvme0n1p4` (old root partition only, so `/boot` stays usable for recovery).
   3. `sudo EXPECT_IP=<ip> ./live-install.sh install`.
   4. `sudo systemctl reboot`.
6. **Join:** `bash scripts/join-watch.sh <node> <ip>` on the workstation. It approves only that node's `node-bootstrapper` client CSR and its `system:node:<node>` serving CSR, and exits when the node is Ready.

   Expected timeline, as observed on spoke:
   1. About 1.5 minutes in: first-boot Ignition fetches its config, the root is rebuilt, and the real root comes up.
   2. About 2.5 minutes: the MCO pulls the 4.21.20 OS image and reboots. The harmless lines `Failed unmounting /sysroot`, `watchdog did not stop` and `snd_hda_intel … codec` appear here.
   3. About 4.5 minutes: CSRs are approved and the node is Ready.

### Verify and recover

- **Health checks:**
  - `oc --context sage get nodes` shows 3 Ready nodes.
  - `oc --context sage get mcp` shows master 1/1 and worker 2/2.
  - `oc --context sage get co` shows every operator `True False False`.
  - `oc --context sage get csr | grep Pending` returns nothing.
  - The router pod runs on sage.
  - A test pod pinned to each worker can reach the API service and quay.io.
- **Verified on 2026-10-27 after both workers joined:**
  - All 6 pod-to-pod node pairs; a ClusterIP Service with backends on both workers; cluster DNS; egress to quay.io and registry.redhat.io.
  - An edge Route on `*.apps.sage` to worker-only pods, through sage's router, with the Let's Encrypt certificate.
  - DF ping at 1400 bytes across nodes.
  - OVN 8/8 on all nodes.
  - ACM showing only `sage`; all Argo apps Synced/Healthy and in-cluster.
- **TrueNAS CSI: fixed on 2026-10-27.**
  - **Cause:** `driverImage` was `:latest` with `IfNotPresent`. Sage ran v0.1.0 (`sha256:1d1c7676…`), while the new workers pulled v1.4.0. v0.1.0 PVs carried `topology.truenas.io/pool` node affinity, which the v1.4.0 nodes don't publish, so dynamic PVs couldn't schedule on the workers.
  - **Fix:** all components were pinned to the v1.4.0 digest.
  - **Re-verified:** a dynamic `truenas-nfs` RWX PVC and a `truenas-iscsi` RWO PVC (ext4 on `/dev/sdX`), each mounted, written and read from a pod on sage, hub and spoke. The PVs were deleted afterwards, and there were no leftover VolumeAttachments.
  - **Health check:** `oc --context sage -n truenas-csi get pods -o wide`, then a PVC test pod with an `fsGroup` on the node in question.
- **Hub has a known hardware fault: occasional spontaneous resets.** The owner confirms it reset like this before the consolidation too, so it is not caused by the cluster or this procedure. Suspect a faulty component, the NVMe first. Hub's Kingston NV3 is a different controller and firmware variant (`SDQ00103`) from spoke's (`ERFK1N.3`), and it has logged more unsafe shutdowns (80 against 54). One reset was observed at 2026-10-27 18:58:14Z, about 17 minutes after hub joined:
  - The journal is cut mid-stream with no shutdown sequence. There's no panic text and no pstore, MCE or BERT record. The node auto-rebooted and rejoined in under 1 minute.
  - Side effect: one corrupted image layer (`readlink …/overlay/l: invalid argument` on `ubi9/ubi`). It was fixed with `crictl rmi` and a re-pull. Check for the same after any future unclean reset (`CreateContainerError` with that message).
  - The `EDAC igen6 … IBECC MEMORY ERROR` lines at boot appear on every boot of both MS-01s, clean ones included, with error counters at 0. They're harmless.
  - **If it recurs:** keep a MeshCommander SOL capture running on hub ("Start Capture"), check the AMT event log for the timestamp, and compare with spoke, which has never reset.
- **Node never comes back after `kexec` (live environment):** power-cycle it in MeshCentral (Power Actions → Power cycle). The disk is untouched until `live-install.sh install`, so it boots the old OS.
- **Second `Ignition/…` request from the same IP in the MCS log** (`oc -n openshift-machine-config-operator logs -l k8s-app=machine-config-server`): first boot failed and Ignition is rerunning on a disk it already touched. Stop power-cycling and reinstall. If the error is `ostree-prepare-root: Couldn't find specified OSTree root`, the first-boot root rebuild was interrupted and the root partition is empty. It cannot be repaired in place.
- **Recovery with no OS to `kexec` from:**
  1. In the dracut emergency shell, which is on KVM because tty0 is last, type `curl -fsS http://<server>:18090/fix.sh | bash`.
  2. `<server>` is any LAN host serving `vmlinuz`, the node's live `initramfs` and `rootfs.img`; for example `python3 -m http.server 18090` in a `/var/tmp` directory on a running node, via `oc debug`.
  3. `fix.sh` stages the live kernel and initramfs on `/boot` and writes `/boot/grub2/user.cfg`, which makes "RHCOS live (reinstall)" the default entry, then reboots into the live environment. Continue with Re-run step 5. The reinstall overwrites `/boot`, which removes `user.cfg`.
  4. `fix.sh` uses only bash built-ins plus `curl`/`mount`: the initramfs has no `df`, `sha256sum`, `mountpoint` or `sleep`. Edit its server address, file names and byte counts for the node in question.
- **The kernel arguments `console=ttyS2,115200n8 console=tty0`** were set by `coreos-installer` and are not managed by any MachineConfig. If AMT SOL is ever disabled again, consider removing `console=ttyS2,115200n8` with `rpm-ostree kargs --delete` on that node (see Decisions).

## Decision log

### Decisions

- **SNO plus workers rather than a 3-node reinstall.** This kept sage's ACM hub, GitOps, TrueNAS CSI, MetalLB and certificates, so only hub and spoke were rebuilt. The cost: one control-plane node, so there is no control-plane HA, and the topology stays `SingleReplica`. Pre-existing alerts on sage that this does not fix:
  - `HighOverallControlPlaneMemory` and `SystemMemoryExceedsReservation` (62 GiB);
  - `etcdDatabaseHighFragmentationRatio`;
  - ACM `SearchPVCNotPresent`;
  - UWM rejecting the MetalLB ServiceMonitors.

  Moving workloads to the workers relieves the memory pressure.
- **Pointer Ignition plus `coreos-installer`, not `oc adm node-image create`.** It follows the documented manual procedure for adding workers to SNO and needs no agent ISO. Its one hard requirement is `api-int` DNS, which UniFi lacked, and the user added it. Sage itself resolves `api-int` only through its own SNO dnsmasq MachineConfig.
- **Remote reinstall through signed `kexec`.** The MS-01s have no BMC, and hub has Secure Boot with lockdown=integrity, so `kexec -s` (kexec_file_load) is required. The RHCOS live kernel is Red Hat-signed and verifies against the platform keyring.
- **Two-stage live environment with a go/no-go gate.** An earlier review showed that `pxe customize --dest-device` erases the disk at boot with no network check and no SSH, so the destructive write is a separate, manual step after the gate passes.
- **UEFI entry created explicitly.** `coreos-installer` never touches NVRAM, and the old entry pointed at the previous ESP's PARTUUID, so `live-install.sh` creates the new entry and deletes the stale one. If `efibootmgr` fails, it falls back to stamping the old PARTUUID onto the new ESP with `sgdisk`.
- **No IngressController patch.** The router is already control-plane-placed. A partial `nodePlacement` patch would have dropped `kubernetes.io/os` and forced a router rollout, which is an outage with a single HostNetwork router.
- **ACM/Argo detach order:**
  1. Delete the hand-made Argo cluster secrets, so Argo drops the cascade finalizers without contacting the clusters.
  2. `helm uninstall` the two `acm-managed-cluster-*` releases while the clusters were still alive (`keepOnUninstall=false`).
  3. Check that the ManagedClusters and their namespaces were gone.

  The objects came from Terraform in github.com/shpwrck/istio-scale-tests (`terraform/platform`). Rerunning that Terraform will recreate hub/spoke ManagedClusters that point at dead API URLs. The owner decided no change to that repo is needed.
- **TrueNAS CSI upgraded to v1.4.0, pinned by tag@digest** (the user's choice over pinning everyone back to v0.1.0). It removes the mixed-version topology split. It also replaced a v0.1.0 controller that had restarted 580 times in 76 days. Never go back to `:latest` + `IfNotPresent`, because every new node pulls whatever `latest` is that day. Upgrade by changing the digest in the CR deliberately.
- **TrueNAS cleanup before the wipe.** The image-registry PVCs on hub and spoke (`Delete` reclaim, `truenas-nfs`) were removed (`managementState=Removed`, then the PVC deleted), so the CSI driver deleted their datasets rather than orphaning them.
- **Hub's first install failed. What happened:**
  - **Boot 1** died inside the first-boot root rebuild (`ignition-ostree-transposefs-autosave-xfs`, which reformats XFS roots that grow past about 400 allocation groups). That was after `mkfs`, before the restore. The proof: the root was empty with `agcount=4` dated 16:23, and the firstboot flag and keyfiles were still in `/boot`.
  - **Boot 2** (after a power cycle) reran Ignition over the empty root and stopped in `ostree-prepare-root`.
  - The kernel death itself was not captured. A chunked discard of the never-trimmed drive later took 1 s on both drives, which argues against a slow full-disk discard as the trigger. Given the owner-confirmed history of spontaneous resets on hub, the most likely cause is the same hardware fault, possibly made worse by `console=ttyS2` being the **last** console (making it `/dev/console`) while AMT SOL was disabled.
  - **Mitigations now standard:** `tty0` last; AMT SOL and KVM enabled and attached during the install; a chunked `blkdiscard` of the old root before install. With those in place, both hub's reinstall and spoke's install succeeded first time.
- **Rejected alternatives:**
  - IDE-R/USB-R ISO boot. It needs AMT redirection, and the large ISO is slow over the relay. The GRUB `user.cfg` trick was faster.
  - PXE. It needs DHCP and TFTP changes on the UDM.
  - Adding `rd.emergency=reboot panic=N` to installed first boots. That turns a debuggable stop into a loop of Ignition reruns.

### How to drive it

- **Day 2:** `oc --context sage get nodes,mcp,co`. Any node CSR that stays Pending more than a few minutes (only after node reinstalls or certificate expiry) is approved with `oc --context sage adm certificate approve`, after checking its CN is `system:node:<node>`.
- **Reinstall or add a worker:** follow Re-run step by step and keep SOL or KVM open. If the gate says NO-GO, reboot and fix the input; never skip the gate. Record anything new in this file, in the same commit as any script change.
- **Upgrades:** the worker pool follows normal MCO rollout one node at a time. The single control plane means API downtime during sage's own reboot. This repo's `openshift-node-upgrade-mutex-operator` is meant to sequence exactly these reboots.
- **Open items:**
  1. **Hub hardware:** expect occasional abrupt resets until the faulty part is found and replaced; the NVMe is the first suspect. Don't pin anything that can't tolerate abrupt node loss to hub. After each reset, check for `CreateContainerError … overlay/l: invalid argument` and remove the affected image with `crictl rmi`. If the NVMe is swapped, reinstall hub with Re-run: the new disk has a new by-id, so update `disk-by-id`.
  2. Revoke hub's and spoke's old TrueNAS API keys if they differ from sage's.
- **Closed on 2026-10-27 by the owner:**
  - Stale UniFi records deleted. The UniFi client names `hub`/`spoke` were kept: they point at AMT.
  - Old hub (`4331cb00-…`) and spoke (`88d1a668-…`) cluster IDs archived in OCM.
- **Not needed, per the owner:**
  - Changes to istio-scale-tests. Remember that re-running its Terraform recreates the hub/spoke ManagedClusters.
  - Turning AMT redirection back off. It stays enabled, and SOL is one of the nodes' consoles.
