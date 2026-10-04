#!/usr/bin/env python3
"""Annotate the OCI config before registry conversion, hashing every changed blob."""
import argparse
import hashlib
import json
from pathlib import Path
import re


def prepare(layout, evidence, revision, created, image):
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("Producer revision must be an immutable commit")
    release = evidence["kernel_release"]
    match = re.match(r"^(\d+)\.(\d+)\.(\d+)(-rc\d+)?(?:-|$)", release)
    if not match:
        raise ValueError("Unsupported kernel release")
    series = f"{match[1]}.{match[2]}"
    upstream = f"{series}.{match[3]}{match[4] or ''}"
    ubuntu = evidence["ubuntu_release"]
    tags = ["latest", f"ubuntu-{ubuntu}", f"ubuntu-{ubuntu}-amd64", series,
            upstream, f"kernel-{release}", evidence["ubuntu_source_tag"].lower()]
    if any(not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}", tag) for tag in tags):
        raise ValueError("Invalid registry tag")
    labels = {
        "org.opencontainers.image.title": "Dakota Ubuntu kernel",
        "org.opencontainers.image.description": f"Ubuntu {ubuntu} kernel {release}; modules and matching development headers; not a bootable OS",
        "org.opencontainers.image.url": "https://github.com/projectbluefin/dakota-kernel-ubuntu",
        "org.opencontainers.image.documentation": "https://github.com/projectbluefin/dakota-kernel-ubuntu/blob/development/README.md",
        "org.opencontainers.image.source": "https://github.com/projectbluefin/dakota-kernel-ubuntu",
        "org.opencontainers.image.vendor": "Project Bluefin",
        "org.opencontainers.image.authors": "Project Bluefin",
        "org.opencontainers.image.licenses": "GPL-2.0-only",
        "org.opencontainers.image.version": release,
        "org.opencontainers.image.revision": revision,
        "org.opencontainers.image.created": created,
        "io.projectbluefin.kernel.release": release,
        "io.projectbluefin.kernel.upstream-version": upstream,
        "io.projectbluefin.kernel.series": series,
        "io.projectbluefin.kernel.architecture": evidence["architecture"],
        "io.projectbluefin.ubuntu.release": ubuntu,
        "io.projectbluefin.ubuntu.codename": evidence["ubuntu_codename"],
        "io.projectbluefin.ubuntu.source-tag": evidence["ubuntu_source_tag"],
        "io.projectbluefin.ubuntu.source-revision": evidence["ubuntu_source_revision"],
        "io.projectbluefin.ubuntu.source-url": evidence["ubuntu_source_url"],
        "io.projectbluefin.dakota.config-revision": evidence["dakota_commit"],
    }

    def load(descriptor):
        return json.loads((layout / "blobs" / "sha256" / descriptor["digest"].removeprefix("sha256:")).read_text())

    def store(value, descriptor):
        data = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
        digest = hashlib.sha256(data).hexdigest()
        (layout / "blobs" / "sha256" / digest).write_bytes(data)
        descriptor.update(digest=f"sha256:{digest}", size=len(data))

    index = json.loads((layout / "index.json").read_text())
    if len(index["manifests"]) != 1:
        raise ValueError("Expected one kernel image")
    descriptor = index["manifests"][0]
    manifest = load(descriptor)
    config = load(manifest["config"])
    if config["architecture"] != "amd64" or evidence["architecture"] != "x86_64":
        raise ValueError("Metadata and image architecture must match")
    config.setdefault("config", {}).setdefault("Labels", {}).update(labels)
    config["created"] = created
    store(config, manifest["config"])
    store(manifest, descriptor)
    (layout / "index.json").write_text(json.dumps(index, sort_keys=True, separators=(",", ":")))
    return {"labels": labels, "tags": tags, "image": image, "producer_revision": revision}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--layout", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--created", required=True)
    parser.add_argument("--image", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = prepare(args.layout, json.loads(args.evidence.read_text()), args.revision, args.created, args.image)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
