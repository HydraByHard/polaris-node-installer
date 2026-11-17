#!/usr/bin/env python3
"""Real Ubuntu VMs under QEMU/TCG inside unprivileged, project-scoped Docker.

Private state belongs outside Git. This helper never accesses production hosts,
mounts the Docker socket into a container, or installs packages on its host.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import ssl
import subprocess
import sys
import time
import urllib.request
import urllib.parse

TOOL_IMAGE = "pni/qemu-tools:ubuntu24"
TOOL_BASE = "ubuntu:24.04@sha256:73b999393d07f2bf65a40373778a44dc9a6d54ad7718d29247d8ff9413c4d6a8"
VERSIONS = {
    "24.04": ("noble", 22024, 24080, 24443, 24222),
    "22.04": ("jammy", 22022, 22080, 22443, 22222),
}
PROXY_KEYS = ("HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "http_proxy", "https_proxy", "no_proxy")


def run(*args: str, **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(list(args), check=True, **kwargs)


def docker(*args: str, **kwargs) -> subprocess.CompletedProcess:
    return run("docker", *args, **kwargs)


def private_write(path: Path, contents: str | bytes) -> None:
    # Atomic replacement is unnecessary in this private, single-runner directory.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as output:
        output.write(contents.encode() if isinstance(contents, str) else contents)
    path.chmod(0o600)


class Lab:
    def __init__(self, args):
        self.args = args
        self.root = args.lab_root.expanduser().resolve()
        if any((p / ".git").is_file() or (p / ".git" / "HEAD").exists()
               for p in (self.root, *self.root.parents)):
            raise ValueError("Lab state must be outside a Git checkout: it contains keys and private proxy configuration")
        if not re.fullmatch(r"pni-[a-z0-9-]+", args.network):
            raise ValueError("The isolated network name must start with pni-")
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.root.chmod(0o700)
        self.codename, self.ssh_port, self.http_port, self.https_port, self.api_port = VERSIONS[args.version]
        self.name = "pni-" + self.codename

    def tool(self, *args):
        docker("run", "--rm", "--user", f"{os.getuid()}:{os.getgid()}",
               "--cap-drop=ALL", "--security-opt=no-new-privileges",
               "--mount", f"type=bind,src={self.root},dst=/lab", TOOL_IMAGE, *args)

    def build_tools(self):
        context = self.root / "tool-context"
        context.mkdir(mode=0o700, exist_ok=True)
        dockerfile = f"""# syntax=docker/dockerfile:1
FROM {TOOL_BASE}
RUN --mount=type=secret,id=pni_ca_bundle,mode=0444 --mount=type=secret,id=pni_extra_ca,mode=0444,required=false \\
    if [ -f /run/secrets/pni_extra_ca ]; then install -D -m 0644 /run/secrets/pni_extra_ca /usr/local/share/ca-certificates/pni-cloud-proxy.crt; fi && \\
    sed -i 's|http://archive.ubuntu.com/ubuntu|https://archive.ubuntu.com/ubuntu|;s|http://security.ubuntu.com/ubuntu|https://security.ubuntu.com/ubuntu|' /etc/apt/sources.list.d/ubuntu.sources && \\
    apt-get -o Acquire::https::CaInfo=/run/secrets/pni_ca_bundle update && \\
    DEBIAN_FRONTEND=noninteractive apt-get -o Acquire::https::CaInfo=/run/secrets/pni_ca_bundle install -y --no-install-recommends qemu-system-x86 qemu-utils genisoimage ca-certificates curl openssh-client python3 && \\
    apt-get clean && rm -rf /var/lib/apt/lists/*
USER 1000:1000
"""
        private_write(context / "Dockerfile", dockerfile)
        private_write(context / ".dockerignore", "*\n!Dockerfile\n")
        ca_bundle = self.args.ca_bundle or Path(ssl.get_default_verify_paths().cafile or "/etc/ssl/certs/ca-certificates.crt")
        command = ["build", "--tag", TOOL_IMAGE, "--secret", f"id=pni_ca_bundle,src={ca_bundle}"]
        if self.args.proxy_ca:
            command += ["--secret", f"id=pni_extra_ca,src={self.args.proxy_ca}"]
        docker(*command, str(context))

    def download_image(self):
        filename = self.codename + "-server-cloudimg-amd64.img"
        base = f"https://cloud-images.ubuntu.com/{self.codename}/current/"
        with urllib.request.urlopen(base + "SHA256SUMS", timeout=60) as response:
            manifest = response.read()
        private_write(self.root / (self.codename + "-SHA256SUMS"), manifest)
        records = {line.split()[1].lstrip("*"): line.split()[0]
                   for line in manifest.decode().splitlines() if len(line.split()) == 2}
        expected = records[filename]
        destination = self.root / filename
        if not destination.exists() or self.digest(destination) != expected:
            temporary = destination.with_suffix(".download")
            with urllib.request.urlopen(base + filename, timeout=60) as response, temporary.open("wb") as output:
                while chunk := response.read(1024 * 1024):
                    output.write(chunk)
            if self.digest(temporary) != expected:
                temporary.unlink()
                raise ValueError("Official Ubuntu cloud image SHA256 mismatch")
            temporary.replace(destination)
            destination.chmod(0o600)
        private_write(self.root / (self.codename + "-provenance.json"), json.dumps({
            "image_url": base + filename, "manifest_url": base + "SHA256SUMS",
            "sha256": expected, "verification": "HTTPS official manifest and exact image SHA256",
        }, indent=2) + "\n")
        print(filename, expected, "verified")

    @staticmethod
    def digest(path: Path) -> str:
        with path.open("rb") as source:
            return hashlib.file_digest(source, "sha256").hexdigest()

    def prepare(self):
        if (self.root / (self.codename + "-disk.qcow2")).exists():
            raise ValueError("Guest disk already exists; preserve its matching base image and seed, and use start instead")
        self.download_image()
        key = self.root / "id_ed25519"
        if not key.exists():
            run("ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", "pni-isolated-lab", "-f", str(key))
        key.chmod(0o600)
        proxy = {key: os.environ[key] for key in PROXY_KEYS if key in os.environ}
        node_host = self.args.node_host or self.codename + ".node.pni.test"
        exclusions = ["127.0.0.1", "localhost", "10.0.2.2", "10.0.2.15", node_host]
        if self.args.panel_address:
            exclusions += [self.args.panel_address, self.args.panel_host]
        for key in ("NO_PROXY", "no_proxy"):
            proxy[key] = ",".join(filter(None, [proxy.get(key, ""), *exclusions]))
        files = [{"path": "/etc/environment", "permissions": "0600",
                  "content": "".join(key + "=" + json.dumps(value) + "\n" for key, value in proxy.items())},
                 {"path": "/etc/systemd/system/docker.service.d/proxy.conf", "permissions": "0600",
                  "content": "[Service]\n" + "".join("Environment=" + json.dumps(key + "=" + value) + "\n"
                                                      for key, value in proxy.items())}]
        apt_proxy = "".join("Acquire::" + scheme + "::Proxy " + json.dumps(proxy.get(scheme + "_proxy") or proxy[scheme.upper() + "_PROXY"]) + ";\n"
                            for scheme in ("http", "https")
                            if proxy.get(scheme + "_proxy") or proxy.get(scheme.upper() + "_PROXY"))
        if apt_proxy:
            files.append({"path": "/etc/apt/apt.conf.d/90pni-lab-proxy", "permissions": "0600", "content": apt_proxy})
        for name, source in (("cloud-proxy", self.args.proxy_ca), ("pni-lab", self.args.panel_ca)):
            if source:
                files.append({"path": f"/usr/local/share/ca-certificates/{name}.crt", "permissions": "0644", "content": source.read_text()})
        commands = [["update-ca-certificates"], ["systemctl", "daemon-reload"]]
        hosts = "10.0.2.15 " + node_host + "\n"
        # Managed Cloud proxy hostnames may exist only in the outer host's hosts
        # file. Preserve proxy URL/credentials and TLS, and supply guest DNS data.
        proxy_hosts = {urllib.parse.urlsplit(value).hostname for key, value in proxy.items()
                       if key.lower() in ("http_proxy", "https_proxy") and value}
        for hostname in sorted(filter(None, proxy_hosts)):
            address = socket.getaddrinfo(hostname, None, socket.AF_INET, socket.SOCK_STREAM)[0][4][0]
            hosts += address + " " + hostname + "\n"
        if self.args.panel_address:
            hosts += self.args.panel_address + " " + self.args.panel_host + "\n"
        files.append({"path": "/root/pni-lab-hosts", "permissions": "0600", "content": hosts})
        commands += [["sh", "-c", "cat /root/pni-lab-hosts >> /etc/hosts"],
                     ["sh", "-c", "touch /var/lib/pni-lab-ready"]]
        cloud_config = {"hostname": self.name, "manage_etc_hosts": False, "disable_root": False,
                        "ssh_pwauth": False, "users": [{"name": "root", "ssh_authorized_keys": [(self.root / "id_ed25519.pub").read_text().strip()]}],
                        "write_files": files, "runcmd": commands}
        private_write(self.root / (self.codename + "-user-data"), "#cloud-config\n" + json.dumps(cloud_config, indent=2) + "\n")
        private_write(self.root / (self.codename + "-meta-data"), f"instance-id: {self.name}-01\nlocal-hostname: {self.name}\n")
        self.tool("genisoimage", "-quiet", "-output", f"/lab/{self.codename}-seed.iso",
                  "-volid", "cidata", "-joliet", "-rock", "-graft-points",
                  f"user-data=/lab/{self.codename}-user-data", f"meta-data=/lab/{self.codename}-meta-data")
        (self.root / (self.codename + "-seed.iso")).chmod(0o600)
        if not (self.root / (self.codename + "-disk.qcow2")).exists():
            self.tool("qemu-img", "create", "-f", "qcow2", "-F", "qcow2", "-b",
                      f"/lab/{self.codename}-server-cloudimg-amd64.img", f"/lab/{self.codename}-disk.qcow2", "20G")
            (self.root / (self.codename + "-disk.qcow2")).chmod(0o600)

    def start(self):
        if not (self.root / (self.codename + "-disk.qcow2")).exists():
            raise ValueError("Run prepare before start")
        found = subprocess.run(["docker", "network", "inspect", self.args.network], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if found.returncode:
            docker("network", "create", "--label", "com.polaris.lab=true", self.args.network)
        docker("run", "-d", "--name", self.name, "--label", "com.polaris.lab=true",
               "--network", self.args.network, "--user", f"{os.getuid()}:{os.getgid()}",
               "--cap-drop=ALL", "--security-opt=no-new-privileges", "--memory", "3g",
               "--cpus", "2", "--pids-limit", "128", "--mount", f"type=bind,src={self.root},dst=/lab",
               "-p", f"127.0.0.1:{self.ssh_port}:10022", "-p", f"127.0.0.1:{self.http_port}:80",
               "-p", f"127.0.0.1:{self.https_port}:443", "-p", f"127.0.0.1:{self.api_port}:2222",
               TOOL_IMAGE, "qemu-system-x86_64", "-machine", "q35", "-accel", "tcg,thread=multi",
               "-cpu", "max", "-smp", "2", "-m", "2048", "-display", "none",
               "-serial", f"file:/lab/{self.codename}-console.log",
               "-monitor", f"unix:/lab/{self.codename}-monitor.sock,server=on,wait=off",
               "-drive", f"file=/lab/{self.codename}-disk.qcow2,if=virtio,format=qcow2",
               "-drive", f"file=/lab/{self.codename}-seed.iso,format=raw,media=cdrom,readonly=on",
               "-nic", "user,model=virtio-net-pci,hostfwd=tcp:0.0.0.0:10022-:22,"
                       "hostfwd=tcp:0.0.0.0:2222-:2222,hostfwd=tcp:0.0.0.0:80-:80,hostfwd=tcp:0.0.0.0:443-:443")

    def ssh_args(self):
        # Ignore unrelated host SSH configuration; keep a dedicated host-key store.
        return ["ssh", "-F", "/dev/null", "-i", str(self.root / "id_ed25519"), "-p", str(self.ssh_port),
                "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", "-o", "StrictHostKeyChecking=accept-new",
                "-o", f"UserKnownHostsFile={self.root}/known_hosts", "root@127.0.0.1"]

    def wait(self):
        # Bounded attempts permit callers to provide progress updates between polls.
        for _ in range(8):
            ready = subprocess.run(self.ssh_args() + ["test -f /var/lib/pni-lab-ready"],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if ready.returncode == 0:
                print("Guest cloud-init bootstrap ready:", self.args.version)
                return
            time.sleep(2)
        raise RuntimeError("Guest still booting; inspect its private console log and retry wait")

    def monitor(self, command: str):
        def read_prompt(connection):
            data = b""
            while not data.rstrip().endswith(b"(qemu)"):
                part = connection.recv(65536)
                if not part:
                    raise RuntimeError("QEMU monitor disconnected before prompt")
                data += part
            return data
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(180)
            connection.connect(str(self.root / (self.codename + "-monitor.sock")))
            read_prompt(connection)
            connection.sendall(command.encode() + b"\n")
            output = read_prompt(connection).decode(errors="replace")
        # HMP line editing echoes terminal controls; the final response is what matters.
        response = output.split("\r\n", 1)[-1].replace("\r", "")
        print(response.strip())
        if re.search(r"\b(error|failed)\b", response, flags=re.I):
            raise RuntimeError("QEMU monitor operation failed")

    def remove(self):
        label = docker("inspect", "--format", '{{index .Config.Labels "com.polaris.lab"}}', self.name,
                       capture_output=True, text=True).stdout.strip()
        if label != "true":
            raise ValueError("Refusing to remove a container without the exact Polaris lab ownership label")
        docker("stop", "-t", "10", self.name)
        docker("rm", self.name)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lab-root", type=Path, required=True)
    parser.add_argument("--network", default="pni-lab")
    parser.add_argument("--ca-bundle", type=Path)
    parser.add_argument("--proxy-ca", type=Path, default=Path(os.environ["CODEX_PROXY_CERT"]) if os.environ.get("CODEX_PROXY_CERT") else None)
    parser.add_argument("--panel-ca", type=Path)
    parser.add_argument("--panel-address")
    parser.add_argument("--panel-host", default="panel.pni.test")
    parser.add_argument("--node-host")
    parser.add_argument("operation", choices=["build-tools", "prepare", "start", "ssh", "wait", "snapshot", "restore", "snapshots", "status", "remove"])
    parser.add_argument("version", choices=VERSIONS)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if args.command[:1] == ["--"]:
        args.command = args.command[1:]
    lab = Lab(args)
    if args.operation == "build-tools":
        lab.build_tools()
    elif args.operation == "prepare":
        lab.prepare()
    elif args.operation == "start":
        lab.start()
    elif args.operation == "ssh":
        sys.exit(subprocess.call(lab.ssh_args() + args.command))
    elif args.operation == "wait":
        lab.wait()
    elif args.operation in ("snapshot", "restore"):
        if len(args.command) != 1 or not re.fullmatch(r"[a-zA-Z0-9_-]+", args.command[0]):
            parser.error("Supply one snapshot name containing letters, digits, dash, underscore")
        lab.monitor(("savevm " if args.operation == "snapshot" else "loadvm ") + args.command[0])
    elif args.operation == "snapshots":
        lab.monitor("info snapshots")
    elif args.operation == "status":
        docker("inspect", "--format", "{{.State.Status}}", lab.name)
    else:
        lab.remove()


if __name__ == "__main__":
    try:
        main()
    except (ValueError, RuntimeError, OSError, subprocess.CalledProcessError) as error:
        # Never display the environment, cloud-config, HTTP authorization, or SSH keys.
        sys.exit(str(error))
