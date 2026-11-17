# Isolated subscriber and real tunnel probe

`data_plane_lab.py` creates a dedicated synthetic Internal Squad, user and
short-lived test Host in an existing disposable Remnawave fixture. The test
Host uses the selected lab Node's actual profile/inbound and domain. The
installer-created Host remains hidden. No existing user or Squad is modified.

Save the disposable guest's public installer state privately outside Git, then
run from the exported installer root:

```bash
python3 tests/lab/data_plane_lab.py prepare \
  --remna-fixture <private-remna-directory>/fixture.json \
  --node-state <private-node-state.json> --work-dir <private-0700-test-directory>
```

The helper accepts only `.pni.test` Node domains and verifies the Node/profile
ownership markers. It obtains `client.json` from the actual generated
subscription, checking the native VLESS UUID and the dedicated
TLS/h2/XHTTP packet-up transport. The client file has mode 0600 and contains
subscriber credentials; transfer it only to the disposable guest as a root
0600 file. The helper never prints it or its subscription link.

The installer's actual client probe is:

```bash
polaris-node doctor --test-config /root/pni-test-client.json \
  --test-url https://<controlled-https-endpoint>/
```

The probe launches a temporary Xray client, sends the HTTPS request through its
SOCKS listener and requires the response to match the configured test Node
address. For the constrained Cloud VM lab, use an isolated Docker benchmark
network in `198.18.0.0/15` and a trusted HTTPS fixture returning the expected
`10.0.2.15` response. Attach only the caller-owned QEMU container to that test
network with a lower gateway priority, preserve its primary Panel network,
and remove the extra attachment afterward. Record the endpoint's observed
request source as additional evidence.

A successful controlled response proves VLESS authentication and the actual
XHTTP/TLS/h2 transport and forwarding path. It does not prove public Internet
egress, a real public Node IP, or Hiddify interoperability. Report those limits
explicitly. Do not change the installer's private-address denials to make a
fixture work; use the isolated benchmark network for the controlled endpoint.

After testing:

```bash
python3 tests/lab/data_plane_lab.py cleanup \
  --remna-fixture <private-remna-directory>/fixture.json \
  --work-dir <private-0700-test-directory>
```

Cleanup verifies the recorded generated markers and deletes only its own test
Host, user and Squad, plus its private exported client file. Remove the guest
client copy and the separately owned HTTPS fixture/network. Keep sanitized
result evidence outside the credential directory when preparing public reports.

## Recorded local boundary

The 2026-11-17 isolated VM run verified native subscriber delivery, strict
TLS/h2, and XHTTP GET/POST responses with status 200. Controlled HTTPS payload
probes on both the benchmark network and a `203.0.113.0/24` documentation
network timed out with curl exit 28. An explicit PNI-only DIRECT fallback did
not resolve the timeout and was removed. The payload roundtrip remains
**INCONCLUSIVE**; this run is not a VPN traffic or Hiddify compatibility pass.
The independent default ACME CLI issuance and actual installed-timer renewal
flow passed, with normal renewal policy/calendar restored afterward.
