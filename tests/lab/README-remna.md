# Disposable real API lab

This directory is self-contained in an exported installer checkout. It requires
Python 3, OpenSSL, and Docker Engine with the Compose plugin. Containers never
mount the Docker socket. The only published listener is a loopback HTTPS port;
the database, cache and backend use an isolated Docker network.

Run from the exported installer root:

```bash
export PNI_REMNA_LAB_DIR="$(mktemp -d /tmp/pni-api-lab.XXXXXX)"
python3 tests/lab/remna_lab.py start --pull --port 29443
python3 tests/lab/remna_lab.py status
python3 tests/lab/remna_lab.py contracts
python3 tests/lab/remna_lab.py stop
```

`--work-dir <private-directory>` is equivalent to `PNI_REMNA_LAB_DIR`. The
synthetic auth fixture is `<private-directory>/fixture.json` with mode 0600;
its parent and generated private working directory use mode 0700. Test secrets
are never printed. HTTP and command error bodies remain in private scratch
when diagnosis is needed. Cleanup removes only this random Compose project's
containers, networks and volumes.

The `contracts` command creates a synthetic existing Node, profile, Host,
`Fixture personal` Squad and user, then verifies scoped enrollment, hidden
Hosts, independent publication and throwaway remote DELETE contracts. It
retains the existing sentinels until `stop`. It does not read or contact any
production panel. A failed assertion retains the private lab for diagnosis.

For VM tests, first create a dedicated caller-owned Docker bridge and pass its
name explicitly:

```bash
python3 tests/lab/remna_lab.py connect --network <isolated-test-network>
```

This joins only this fixture's gateway and backend to that bridge. The private
fixture records `gatewayBridgeIp` and `backendBridgeIp`; the VM Node API
allowlist must use the actual backend address. QEMU user networking can
preserve external peer addresses. Recreating the backend loses a dynamic
attachment, so keep it running while testing an immutable guest allowlist.
The gateway certificate includes the synthetic `panel.pni.test` hostname and
its current bridge IP. Install the generated test CA in the guest trust store;
use normal TLS verification and an explicit local hostname mapping.

The exact official image pins are in `remna-templates/pins.json`. Adaptation
history and official contract references are recorded in `provenance.json`.
