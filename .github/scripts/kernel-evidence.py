#!/usr/bin/env python3
"""Check the exported single-platform OCI artifact without executing its contents."""
import hashlib
import json
from pathlib import Path
import posixpath
import tarfile

layout = Path("oci")


def blob(descriptor):
    algorithm, digest = descriptor["digest"].split(":", 1)
    if algorithm != "sha256":
        raise ValueError("Only sha256 OCI blobs are supported")
    path = layout / "blobs" / algorithm / digest
    if hashlib.file_digest(path.open("rb"), "sha256").hexdigest() != digest:
        raise ValueError(f"Corrupt OCI blob: {descriptor['digest']}")
    return path


index = json.loads((layout / "index.json").read_text())
if len(index["manifests"]) != 1:
    raise ValueError("Expected exactly one x86_64 image")
manifest_descriptor = index["manifests"][0]
manifest = json.loads(blob(manifest_descriptor).read_text())
config = json.loads(blob(manifest["config"]).read_text())
if (config["architecture"], config["os"]) != ("amd64", "linux"):
    raise ValueError("Expected linux/amd64")
release = "7.3.0-rc5-8-generic-dakota"
base = f"usr/lib/modules/{release}"
required = {f"{base}/{name}" for name in ("vmlinuz", "vmlinux", "System.map", "config", "build")}
required.add("usr/share/licenses/dakota-kernel-ubuntu/LICENSE")
required.update(f"usr/src/linux-{release}/{name}" for name in ("Makefile", ".config", "Module.symvers"))
seen = set()
module_count = 0
headers = False
kernel_config = None
for layer in manifest["layers"]:
    with tarfile.open(blob(layer), "r:*") as archive:
        for member in archive:
            name = member.name.removeprefix("./").lstrip("/")
            if "/../" in f"/{name}/" or ".wh." in name:
                raise ValueError(f"Unexpected path or whiteout: {name}")
            if name.startswith(("bin/", "sbin/", "usr/bin/", "usr/sbin/", "boot/")):
                raise ValueError(f"Not a kernel-only image: {name}")
            if name in required:
                seen.add(name)
                if name.endswith("/build") and (not member.issym() or posixpath.normpath(posixpath.join("/" + posixpath.dirname(name), member.linkname)) != f"/usr/src/linux-{release}"):
                    raise ValueError("Kernel build symlink does not reference packaged headers")
                if name.endswith("/config"):
                    kernel_config = archive.extractfile(member).read().decode()
            if name.startswith(f"{base}/kernel/") and ".ko" in name and member.isfile():
                module_count += 1
            if name == f"usr/src/linux-{release}/Makefile" and member.isfile():
                headers = True
if required - seen or not module_count or not headers or kernel_config is None:
    raise ValueError(f"Incomplete kernel artifact: missing={sorted(required - seen)}, modules={module_count}, headers={headers}")
for setting in ("CONFIG_RUST=y", "CONFIG_CRYPTO_ZSTD=y", "# CONFIG_MODULE_SIG_ALL is not set", 'CONFIG_MODULE_SIG_KEY=""'):
    if setting not in kernel_config.splitlines():
        raise ValueError(f"Kernel configuration missing: {setting}")
evidence = {"kernel_release": release, "architecture": "x86_64", "modules": module_count,
            "headers": True, "rust": True, "crypto_zstd": True, "unsigned_modules": True,
            "manifest_digest": manifest_descriptor["digest"],
            "dakota_commit": "39d128aa9dfa66d73a6b48cefc70efdc1808766d",
            "ubuntu_source_tag": "Ubuntu-7.3.0-8.8"}
Path("logs").mkdir(exist_ok=True)
Path("logs/kernel-evidence.json").write_text(json.dumps(evidence, indent=2) + "\n")
print(json.dumps(evidence, indent=2))
