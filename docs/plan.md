# Polaris Node Installer Implementation Plan

> **For agentic workers:** implement scoped independent domains, then fresh whole-component review. Track task status in progress.json.

**Goal:** полноценный проверяемый installer для новыхUbuntuVPS без измененийproduction.
**Architecture:** Bash embeddedPython, native scopedRemnaAPI, host-network Node+Nginx, isolatediptables chains, ownedstate/systemd, ACME or validatedBYO.
**Tech Stack:** Ubuntu22.04/24.04amd64, Python3.10+, Docker29/Compose2.40+, Remna3.4.11/Node3.4.6/Xray26.11.9.
**Spec:** design.md and original owner specification held outsidepublicexport.

## Global Constraints

- PRODUCTION_CHANGES=NONE; no oldsudo, no existingNode/Host/user/Squad/DNS mutation during development.
- No adminpassword or persistedAPItoken on newVPS; TLSverification mandatory; no secretarguments/logs.
- No blindretryPOST; disabled+hiddenHost; separate explicitpublish.
- PreserveSSH/defaultpolicies/foreignDocker/assets. No newpaidresource or permanentmanager.

## Review Focus

- InterruptedAPIcommit/statewrite: sameIDs, no duplicateHost/Node/profile, preservednodekey.
- Firewallstartup andDockerrestart: no interval with untrustedNodeAPI; IPv4 ANDIPv6.
- Partialpublish and concurrentSquadedit: retainoldpermissions, no accidentalvisibility.
- Rootfiles/symlinks/credentialerror/logdata: no leak or foreignoverwrite.
- Partialrollback/update/TLSfailure: preserveprotection and independentSSH.

## Tasks

1. **core.py/render.py**: strictpublicconfig, atomicownedstate, redaction, locks, pinnedconfigtemplates; tests/test_core.py,test_render.py. RED→GREEN for secrets/domain/symlink/interrupt/Nodebind/hiddenflags.
2. **api.py/registrar.py**: exactsource-backednativecontracts, HTTPSno-redirectscopedclient, idempotentread/create, confirmedpublish; tests/test_api.py,test_registrar.py plus realRemnaAPI fixture andpreservation checks.
3. **system.py**: safeRunner, systempreflight, DockerAPTwithGPGfingerprint/versionpins, ownfirewall/systemd/lifecycle/TLS/DNS/diagnostics/rollback; test_system.py + genuineUbuntuVM tests clean/existingDocker/reboot/firewall.
4. **cli.py/bootstrap/build**: Russianquestions, tokengetpass/FD, install/status/doctor/logs/update/rollback/publish/scopes; self-containedversionedscript, trustedhashflow; test_cli.py and corruptdownload/preflightfail tests.
5. **integration/release**: 20 requiredfailureclasses; realnativeAPI/container/Xraytraffic andUbuntuVM; secret-scan; fulltests; freshreview; fixImportant once; package/README/recovery/owner-first-live checklist; realGitHubrelease ifavailable, neverinventURL.
