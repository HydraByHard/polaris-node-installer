# Real ACME HTTP-01 fixture

`acme_lab.py` runs official Pebble 2.10.3 pinned by its Linux amd64 manifest
digest. Its ACME TLS key and CA are generated privately outside Git. It uses
real validation on HTTP port 80, disables authorization reuse, and issues
90-day certificates. It never enables validation bypass or disables TLS
verification. The optional no-sleep setting only removes artificial delays.

The official release, image workflow and configuration are documented at:

- <https://github.com/letsencrypt/pebble/releases/tag/v2.10.3>
- <https://github.com/letsencrypt/pebble/blob/v2.10.3/.github/workflows/release.yml>
- <https://github.com/letsencrypt/pebble/blob/v2.10.3/test/config/pebble-config.json>
- <https://github.com/letsencrypt/pebble/blob/v2.10.3/README.md>

From the exported installer root, using an existing isolated `pni-` Docker
bridge and the disposable QEMU container's bridge address:

```bash
acme_work="$(mktemp -d /tmp/pni-acme.XXXXXX)"
python3 tests/lab/acme_lab.py start --pull --work-dir "$acme_work" \
  --network <isolated-test-network> --node-host jammy.node.pni.test \
  --node-address <qemu-container-bridge-ip>
python3 tests/lab/acme_lab.py probe --pull --work-dir "$acme_work"
python3 tests/lab/acme_lab.py status --work-dir "$acme_work"
```

The private `fixture.json` records the dynamic Pebble address, directory URL,
image digest, and public CA certificate paths. Pebble is available to peers as
`https://pebble.pni.test:14000/dir`; only loopback ports 31400/31500 are
published on its host. Its container runs as the current UID/GID, drops all
capabilities, mounts only its server certificate/key and configuration, and
never mounts the Docker socket or uses host networking.

`probe` launches a separate digest-pinned Nginx webroot and Certbot 5.10.0 on
the isolated bridge. It verifies real issuance, a trusted certificate valid for
more than 24 hours, a changed serial after forced renewal, and additional
successful HTTP-01 validation requests. Both client operations use strict TLS
with an explicit CA bundle. Access logs count only method/status and contain
no challenge URLs. Local test containers explicitly bypass configured proxies
for their isolated service traffic. Probe clients and Nginx are removed after
the run; private account/certificate state and sanitized evidence remain in
the work directory.

For the Ubuntu integration test, trust `transport-ca.crt` and the generated
`issuer-root.crt` only in the disposable guest. Docker/QEMU DNS must resolve
`pebble.pni.test` to the fixture bridge address, including inside a temporary
host-network client container. Configure the test ACME directory above and
use the installer's actual `System.acme()` path through its Nginx webroot.
A renewal must actually issue a new certificate; a fresh certificate skipped
as not due is not a renewal proof. Preserve snapshots and coordinate guest
ownership before replacing any test TLS material.

```bash
python3 tests/lab/acme_lab.py stop --work-dir "$acme_work"
```

Stop removes only this fixture's labeled Pebble container and retains private
PKI for inspection. Pebble's issuer state is ephemeral; keep the fixture
running through issuance and renewal tests. This fixture cannot use production
Node domains and does not contact public ACME services.
