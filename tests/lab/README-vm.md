# Real Ubuntu VM test apparatus

`vm_runner.py` runs genuine Ubuntu cloud guests with their own Linux kernels,
systemd, netfilter and disks. QEMU uses TCG CPU emulation inside ordinary,
unprivileged Docker containers. KVM, host package installation, host networking,
privileged containers, Docker socket mounts and changes to the outer host's
firewall or cgroups are unnecessary.

Use Python 3.11+, Docker, OpenSSH client, `ssh-keygen`, network access to official
Ubuntu/Docker sources and an existing trusted CA bundle. Docker's configured
HTTP/HTTPS proxy settings must be available to builds and containers when the
environment requires them. The helper preserves certificate verification.

## Isolation and resources

Each guest has two virtual CPUs, 2 GiB RAM and a sparse 20 GiB qcow2 disk. Each
QEMU container requests a 3 GiB memory limit, including emulator overhead, and
two CPUs. Only two guest versions are defined. The containers run as the invoking
host user's UID/GID, drop every capability and enable `no-new-privileges`.

Only the private lab directory is mounted. The dedicated Docker network defaults
to `pni-lab`; it is separate from production. Every host port is explicitly bound
to `127.0.0.1`.

| Guest | Container | Host SSH | Host HTTP | Host HTTPS | Host Node API |
|---|---|---:|---:|---:|---:|
| Ubuntu 24.04 | `pni-noble` | 22024 | 24080 | 24443 | 24222 |
| Ubuntu 22.04 | `pni-jammy` | 22022 | 22080 | 22443 | 22222 |

Other containers on `pni-lab` can reach each QEMU container at ports 80, 443 and
2222, which forward to the same guest ports. The SSH forward uses container port
10022. The guest itself has address `10.0.2.15`. For forwarded connections from
other bridge containers, QEMU preserves their actual bridge source address: a
temporary guest TCP listener observed `172.18.0.2` for the HTTPS gateway. Host
loopback connections through Docker's published SSH port appeared as the bridge
gateway, `172.18.0.1`. Measure the real Panel backend's source address and use it
in `panel_ipv4`; do not assume the QEMU host address `10.0.2.2` is the peer.
Test the generated rules, packet counters and actual allowed/denied clients
inside this isolated network.
QEMU can finish the outer forwarded TCP handshake before the guest accepts the
inner connection, so `nc -z` alone can return success despite a guest firewall
DROP. Use TLS/application responses and changes in guest firewall counters.

After attaching the real Panel backend to `pni-lab`, the same TCP probe measured
its guest-visible source as `172.18.0.5`. That is the allowlist address used for
the native Node integration attempt, rather than the gateway's address.

The installer's `management_address` is the QEMU container's actual bridge IP
(`172.18.0.3`/`172.18.0.4` in the development run), which the Panel can reach on
port 2222. Its lab `public_ipv4` is `10.0.2.15`, matching the node hostname inside
the guest. These addresses describe different sides of the laboratory NAT.
The Panel backend must itself join `pni-lab` for outgoing Node connections; a
gateway joined to this network only provides the opposite, guest-to-Panel path.

Keep the lab directory outside a Git checkout. It contains fresh synthetic SSH
keys, cloud-init seeds, VM images, console logs and potentially private runtime
proxy configuration. The helper uses mode 0700 on that directory and mode 0600
on generated secret files. Never publish or add it to a release. No production
SSH key, API credential, enrollment token or configuration is needed.

## Build and prepare

From the exported installer root:

```bash
export PNI_LAB=/tmp/pni-ubuntu-vms
python3 tests/lab/vm_runner.py --lab-root "$PNI_LAB" build-tools 24.04
python3 tests/lab/vm_runner.py --lab-root "$PNI_LAB" prepare 24.04
python3 tests/lab/vm_runner.py --lab-root "$PNI_LAB" start 24.04
python3 tests/lab/vm_runner.py --lab-root "$PNI_LAB" wait 24.04
```

The tooling image is built from the official Ubuntu 24.04 OCI image at digest
`sha256:73b999393d07f2bf65a40373778a44dc9a6d54ad7718d29247d8ff9413c4d6a8`.
QEMU, `qemu-img`, `genisoimage`, CA certificates and OpenSSH come from official
Ubuntu HTTPS APT repositories with normal signed-package verification. BuildKit
secret mounts supply CA trust during the build. Private proxy URLs are not
written into the Dockerfile. `--ca-bundle /path/to/bundle.crt` can select a
different trust bundle. `--proxy-ca /path/to/proxy-ca.crt` supplies a managed
environment's extra CA; `CODEX_PROXY_CERT`, when set, supplies its default.

`prepare` downloads the official AMD64 image from
`https://cloud-images.ubuntu.com/{noble,jammy}/current/`, downloads its official
`SHA256SUMS` over verified HTTPS and checks the image's exact SHA256. It records
the source and digest in a private `*-provenance.json`. It creates a new lab-only
Ed25519 key, a cloud-init ISO and a disposable copy-on-write guest disk. `prepare`
refuses to replace an existing guest disk, its matching base image or seed. Use
`start` for an existing disk, or a new private lab directory for a fresh image.

The cloud-init seed enables key-only root SSH **inside the guest**, preserves
proxy settings and extra CA trust, and configures a private Docker systemd proxy
drop-in for the later installer. In managed environments where a proxy hostname
exists only in the outer host's hosts file, the helper resolves that hostname on
the host and adds its address to the guest hosts file; the original proxy URL and
TLS trust remain in use. It does not install Docker in the guest.

Seeds disable cloud-init regeneration of `/etc/hosts` so synthetic node, Panel
and proxy mappings persist across reboots. Older laboratory seeds used
`manage_etc_hosts=true`; those guests required the same laboratory records in
`/etc/cloud/templates/hosts.debian.tmpl` before reboot tests could verify DNS.

The first boot takes several minutes under TCG. `wait` makes bounded attempts;
retry it while checking the private `noble-console.log`. Repeat `prepare`,
`start` and `wait` with `22.04` for the second guest.

## Connect an isolated Panel fixture

Create the local Remnawave fixture using `remna_lab.py`. Attach its HTTPS gateway
to `pni-lab`, give it a laboratory hostname and include that hostname and its
bridge address in its test certificate. Do this before `prepare` so the seed can
trust the test CA and resolve its name:

```bash
python3 tests/lab/vm_runner.py \
  --lab-root "$PNI_LAB" \
  --panel-ca /private/fixture/tls/ca.crt \
  --panel-address 172.18.0.2 --panel-host panel.pni.test \
  prepare 24.04
```

Use the gateway's actual bridge address in place of the example. For the
development run, the gateway listened at `https://panel.pni.test:8443` and had a
synthetic CA-signed certificate. Both guests verified `/api/auth/status` with
Python's standard HTTPS trust. Keep all fixture tokens outside Git and pass them
through private files. This is a real, isolated Remnawave API fixture; it is not
evidence of production enrollment.

For BYO TLS tests, mint a synthetic CA-signed leaf for
`noble.node.pni.test`/`jammy.node.pni.test`, copy the leaf/key into the guest using
its dedicated SSH key, set root ownership and mode 0600, and trust the synthetic
CA through the standard guest store. `prepare` maps the node hostname to
`10.0.2.15` inside the guest. Outer test clients need their own hostname mapping
to the QEMU container's bridge IP. A BYO TLS run does not verify public DNS,
public ingress or ACME issuance.

## Run commands, snapshot and restore

```bash
python3 tests/lab/vm_runner.py --lab-root "$PNI_LAB" ssh 24.04 \
  'uname -r; systemd-detect-virt; systemctl is-active ssh; iptables --version'
python3 tests/lab/vm_runner.py --lab-root "$PNI_LAB" snapshot 24.04 clean-ubuntu
python3 tests/lab/vm_runner.py --lab-root "$PNI_LAB" snapshots 24.04
python3 tests/lab/vm_runner.py --lab-root "$PNI_LAB" restore 24.04 clean-ubuntu
```

Snapshots include both guest RAM and the writable disk, briefly pausing the VM.
Wait for active installer/package operations to finish before saving a baseline.
Restoring deliberately discards guest changes made after that snapshot. Coordinate
with any other test process using the same guest. Use separate snapshot names
for clean Ubuntu, Docker already installed, configured Node and failure states.

SSH ignores unrelated outer-host SSH configuration with `-F /dev/null`, uses only
the generated lab key and maintains a dedicated known-hosts file. For file copy:

```bash
scp -F /dev/null -i "$PNI_LAB/id_ed25519" -P 22024 \
  -o "UserKnownHostsFile=$PNI_LAB/known_hosts" \
  /path/to/release.tar.gz root@127.0.0.1:/root/pni-release.tar.gz
```

For boot persistence, run `systemctl reboot` **inside the guest**, then retry
`wait` and verify the actual services, listeners and rules. A QEMU snapshot
restore alone is not a boot-persistence test.

## Evidence collected during development

On 2026-11-17 this apparatus booted both real guests, without KVM:

| Guest | Ubuntu image | Guest kernel | Netfilter |
|---|---|---|---|
| 24.04 | Ubuntu 24.04.5 LTS | `6.8.0-147-generic` | iptables 1.8.10, nf_tables |
| 22.04 | Ubuntu 22.04.5 LTS | `5.15.0-203-generic` | iptables 1.8.7, nf_tables |

Both reported `systemd-detect-virt=qemu`, had working systemd SSH, accepted
creation/deletion of a dedicated `PNI_LAB_CAPABILITY` firewall chain, and reached
the local Panel over verified HTTPS. Docker was absent in the clean baselines.
Initial cloud-init completed in approximately 200 seconds under TCG; loading
certificate stores or package installation is also slower than on a VPS.

The first full installer attempt on cold Ubuntu 24.04 hit the initial 300-second
APT-update timeout after downloading about 299 MiB of indexes, before creating
any Docker repository, Node or Host. A diagnostic update with
`Acquire::Languages=none` succeeded. The laboratory then set that option in
`/etc/apt/apt.conf.d/99pni-lab-speed` to avoid translation metadata during later
integration attempts. The failed state and warmed cache were retained to test
partial-install recovery; this is distinct from a successful cold installation.

Official Docker APT metadata was checked for noble/jammy and AMD64/ARM64: the
release key fingerprint was
`9DC858229FC7DD38854AE2D88D81803C0EBFCD88`, both InRelease signatures were valid,
and each Packages.gz matched its signed SHA256. The following full versions
existed for both architectures:

| Package | Ubuntu 24.04 | Ubuntu 22.04 |
|---|---|---|
| docker-ce, docker-ce-cli | `5:29.9.2-1~ubuntu.24.04~noble` | `5:29.9.2-1~ubuntu.22.04~jammy` |
| docker-compose-plugin | `2.40.3-1~ubuntu.24.04~noble` | `2.40.3-1~ubuntu.22.04~jammy` |
| containerd.io | `2.2.6-1~ubuntu.24.04~noble` | `2.2.6-1~ubuntu.22.04~jammy` |

Metadata availability does not prove ARM64 runtime behavior; these VMs are AMD64.
Installer integration results belong in the main test report. The clean-VM
apparatus checks alone do not prove Docker installation, Node traffic, reboot
persistence, public TLS issuance or production connectivity.

## Cleanup

Power the guest off cleanly first when preserving its disk:

```bash
python3 tests/lab/vm_runner.py --lab-root "$PNI_LAB" ssh 24.04 'systemctl poweroff'
python3 tests/lab/vm_runner.py --lab-root "$PNI_LAB" remove 24.04
python3 tests/lab/vm_runner.py --lab-root "$PNI_LAB" remove 22.04
```

`remove` checks the exact `com.polaris.lab=true` container label before stopping
and removing its named QEMU container. It retains private images, snapshots and
logs, and leaves the shared laboratory network and Panel fixture alone. Remove
that network only after every project fixture has been disconnected. Do not use
global Docker prune or restart commands.
