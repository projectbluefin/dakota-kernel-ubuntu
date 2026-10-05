#!/usr/bin/env python3
"""Track the newest released Ubuntu desktop kernel, with Stonking as bootstrap."""
from datetime import datetime, timezone
from email.parser import Parser
from email.utils import parsedate_to_datetime
import json
from pathlib import Path
import re
import subprocess
from urllib.parse import urlencode
from urllib.request import urlopen

FEED = "https://changelogs.ubuntu.com/meta-release"
ARCHIVE = "https://api.launchpad.net/1.0/ubuntu/+archive/primary"
VERSION = r"[0-9]+\.[0-9]+\.[0-9]+-[0-9]+\.[0-9]+(?:\.[0-9]+)*"
SOURCE = re.compile(
    r"url: launchpad:~ubuntu-kernel/ubuntu/\+source/linux/\+git/(?P<codename>[a-z]+)\n"
    rf"  track: Ubuntu-\*\n  ref: Ubuntu-{VERSION}-0-g[0-9a-f]{{40}}(?=\n|$)"
)
RELEASE = re.compile(r"^  ubuntu-release: ['\"](?P<version>[0-9]{2}\.[0-9]{2})['\"]$", re.MULTILINE)
UBUNTU_VERSION = re.compile(r"([0-9]{2})\.([0-9]{2})(?:\.[0-9]+)?(?: LTS)?")


def latest_release(feed):
    releases = []
    for block in re.split(r"\n\s*\n", feed.strip()):
        entry = Parser().parsestr(block)
        if entry.get("Supported") != "1":
            continue
        codename = entry.get("Dist", "")
        version = UBUNTU_VERSION.fullmatch(entry.get("Version", ""))
        if not re.fullmatch(r"[a-z]+", codename) or not version:
            raise ValueError("Invalid supported release in Ubuntu meta-release feed")
        releases.append((tuple(map(int, version.group(1, 2))), codename))
    if not releases:
        raise ValueError("Ubuntu meta-release feed has no supported desktop release")
    return max(releases)


def ubuntu_release_version(codename, require_unreleased=False):
    if not re.fullmatch(r"[a-z]+", codename):
        raise ValueError("Invalid Ubuntu source codename")
    for url in (FEED, FEED + "-development"):
        with urlopen(url, timeout=30) as response:
            feed = response.read().decode("utf-8")
        for block in re.split(r"\n\s*\n", feed.strip()):
            entry = Parser().parsestr(block)
            if entry.get("Dist") == codename:
                version = UBUNTU_VERSION.fullmatch(entry.get("Version", ""))
                if not version:
                    raise ValueError(f"Invalid Ubuntu release version for {codename}")
                if require_unreleased and (
                    entry.get("Supported") != "0"
                    or parsedate_to_datetime(entry["Date"]) <= datetime.now(timezone.utc)
                ):
                    raise ValueError("Bootstrap series is no longer an upcoming Ubuntu release")
                return f"{int(version[1]):02d}.{int(version[2]):02d}"
    raise ValueError(f"Ubuntu source codename {codename} is absent from the release feeds")


def version_key(version):
    if not re.fullmatch(VERSION, version):
        raise ValueError(f"Unsupported Ubuntu generic kernel version: {version}")
    return tuple(map(int, re.findall(r"[0-9]+", version)))


def published_tag(codename):
    series = f"https://api.launchpad.net/1.0/ubuntu/{codename}"
    url = ARCHIVE + "?" + urlencode({
        "ws.op": "getPublishedSources", "source_name": "linux", "exact_match": "true",
        "distro_series": series, "status": "Published", "ws.size": "100",
    })
    versions = []
    while url:
        if not url.startswith(ARCHIVE + "?"):
            raise ValueError("Unexpected Launchpad archive pagination URL")
        with urlopen(url, timeout=30) as response:
            page = json.load(response)
        for entry in page["entries"]:
            if (entry["status"] == "Published" and entry["source_package_name"] == "linux"
                    and entry["distro_series_link"] == series and entry["component_name"] == "main"
                    and entry["pocket"] in {"Release", "Updates", "Security"}):
                versions.append(entry["source_package_version"])
        url = page.get("next_collection_link")
    if not versions:
        raise ValueError(f"No shipped generic kernel in Ubuntu {codename}")
    return "Ubuntu-" + max(versions, key=version_key)


def advance_source(kernel, feed):
    source = SOURCE.search(kernel)
    release = RELEASE.search(kernel)
    if not source or not release:
        raise ValueError("Missing pinned Ubuntu source or desktop release")
    current = tuple(map(int, release["version"].split(".")))
    version, codename = latest_release(feed)
    bootstrap = version < current
    if bootstrap:
        if current != (26, 10) or source["codename"] != "stonking":
            raise ValueError("Stable release feed is older than the pinned Ubuntu series")
        if ubuntu_release_version("stonking", require_unreleased=True) != "26.10":
            raise ValueError("Stonking bootstrap release metadata disagrees")
        version, codename = current, "stonking"
    elif version == current and codename != source["codename"]:
        raise ValueError("Ubuntu release metadata and source codename disagree")
    tag = None if bootstrap else published_tag(codename)
    url = f"https://git.launchpad.net/~ubuntu-kernel/ubuntu/+source/linux/+git/{codename}"
    output = subprocess.check_output(
        ["git", "ls-remote", url, f"refs/tags/{tag or 'Ubuntu-*'}*"], text=True, timeout=60
    )
    refs = {}
    for line in output.splitlines():
        match = re.fullmatch(r"([0-9a-f]{40})\s+refs/tags/(.+)", line)
        if match:
            refs[match[2]] = match[1]
    if tag is None:
        tags = [ref for ref in refs if re.fullmatch("Ubuntu-" + VERSION, ref)]
        if not tags:
            raise ValueError(f"No generic Ubuntu kernel release tags in {url}")
        tag = max(tags, key=lambda name: version_key(name.removeprefix("Ubuntu-")))
    if tag not in refs:
        raise ValueError(f"Published Ubuntu source tag {tag} is missing from {url}")
    digest = refs.get(tag + "^{}", refs[tag])
    updated = SOURCE.sub(
        f"url: launchpad:~ubuntu-kernel/ubuntu/+source/linux/+git/{codename}\n"
        f"  track: Ubuntu-*\n  ref: {tag}-0-g{digest}", kernel, count=1
    )
    return RELEASE.sub(f"  ubuntu-release: '{version[0]:02d}.{version[1]:02d}'", updated, count=1)


if __name__ == "__main__":
    path = Path("elements/kernel.bst")
    kernel = path.read_text()
    with urlopen(FEED, timeout=30) as response:
        updated = advance_source(kernel, response.read().decode("utf-8"))
    if updated != kernel:
        path.write_text(updated)
        print("Updated Ubuntu desktop source:\n" + SOURCE.search(updated)[0])
    else:
        print("Already tracking the selected Ubuntu desktop kernel")
