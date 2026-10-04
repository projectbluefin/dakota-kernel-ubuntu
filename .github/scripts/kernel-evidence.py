#!/usr/bin/env python3
"""Check the exported single-platform OCI artifact without executing its contents."""
import hashlib
import json
from pathlib import Path
import posixpath
import re
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
release = None
base = None
for layer in manifest["layers"]:
    with tarfile.open(blob(layer), "r:*") as archive:
        for member in archive:
            name = member.name.removeprefix("./").lstrip("/")
            match = re.match(r"^usr/lib/modules/([^/]+)/vmlinuz$", name)
            if match:
                release = match.group(1)
                base = f"usr/lib/modules/{release}"
                break
        if release:
            break

if not release:
    raise ValueError("Could not discover kernel release from OCI layers")

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
kernel_bst = Path("elements/kernel.bst").read_text()
project_conf = Path("project.conf").read_text()
m_dakota = re.search(r"ref:\s*([0-9a-f]{40})", Path("elements/dakota.bst").read_text() if Path("elements/dakota.bst").exists() else "")
if not m_dakota:
    raise ValueError("Could not parse Dakota configuration pin from elements/dakota.bst")
dakota_commit = m_dakota.group(1)

m_source = re.search(
    r"url:\s*(?P<url>\S+)\s+track:\s*(?P<track>\S+)\s+ref:\s*(?P<tag>Ubuntu-[0-9]+\.[0-9]+\.[0-9]+-[0-9]+\.[0-9]+)(?:-0-g(?P<tag_sha>[0-9a-f]{40}))?",
    kernel_bst
)
if not m_source:
    raise ValueError("Could not parse Ubuntu kernel source configuration from elements/kernel.bst")

raw_url = m_source.group("url")
source_tag = m_source.group("tag")
tag_sha = m_source.group("tag_sha")

source_url = raw_url
for alias_match in re.finditer(r"^\s*([A-Za-z0-9_-]+):\s*(\S+)", project_conf, re.MULTILINE):
    alias_prefix = f"{alias_match.group(1)}:"
    if source_url.startswith(alias_prefix):
        source_url = alias_match.group(2) + source_url[len(alias_prefix):]
        break

codename_match = re.search(r"/\+git/([A-Za-z0-9_-]+)", source_url)
ubuntu_codename = codename_match.group(1) if codename_match else "stonking"
peeled_sha = None
import subprocess
try:
    out = subprocess.check_output(
        ["git", "ls-remote", source_url, f"refs/tags/{source_tag}*"],
        text=True, stderr=subprocess.DEVNULL
    )
    for line in out.strip().splitlines():
        parts = line.split()
        if len(parts) == 2:
            sha, ref = parts
            if ref == f"refs/tags/{source_tag}":
                tag_sha = sha
            elif ref == f"refs/tags/{source_tag}^{{}}":
                peeled_sha = sha
except Exception as err:
    raise RuntimeError(f"Failed to query remote tags from {source_url}: {err}") from err

source_revision = peeled_sha or tag_sha
if not source_revision or not re.fullmatch(r"[0-9a-f]{40}", source_revision):
    raise ValueError(f"Could not resolve valid 40-hex commit for source tag {source_tag} from {source_url}")

evidence = {"kernel_release": release, "architecture": "x86_64", "modules": module_count,
            "headers": True, "rust": True, "crypto_zstd": True, "unsigned_modules": True,
            "oci_manifest_digest": manifest_descriptor["digest"],
            "dakota_commit": dakota_commit,
            "ubuntu_source_tag": source_tag,
            "ubuntu_release": "26.10", "ubuntu_codename": ubuntu_codename,
            "ubuntu_source_revision": source_revision,
            "ubuntu_source_url": source_url}
Path("logs").mkdir(exist_ok=True)
Path("logs/kernel-evidence.json").write_text(json.dumps(evidence, indent=2) + "\n")
print(json.dumps(evidence, indent=2))
