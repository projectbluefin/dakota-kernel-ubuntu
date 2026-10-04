import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest

from registry_metadata import prepare


class KernelEvidenceTests(unittest.TestCase):
    def test_dynamic_derivation_from_oci_and_sources(self):
        for release, tag, codename, ubuntu in (
            ("7.3.0-rc5-9-generic-dakota", "Ubuntu-7.3.0-9.9", "stonking", "26.10"),
            ("7.4.0-12-generic-dakota", "Ubuntu-7.4.0-12.13", "future", "27.04"),
        ):
            with self.subTest(release=release):
                self.check_dynamic_derivation(release, tag, codename, ubuntu)

    def test_rejects_codename_and_declared_release_mismatch(self):
        self.check_dynamic_derivation(
            "7.3.0-rc5-9-generic-dakota", "Ubuntu-7.3.0-9.9", "stonking", "26.10",
            declared_release="26.04", expected_error="Ubuntu release metadata mismatch",
        )

    def test_rejects_source_tag_not_matching_pinned_revision(self):
        self.check_dynamic_derivation(
            "7.3.0-rc5-9-generic-dakota", "Ubuntu-7.3.0-9.9", "stonking", "26.10",
            source_pin="f" * 40, expected_error="Pinned Ubuntu revision does not match",
        )

    def check_dynamic_derivation(self, rel, synth_tag, codename, ubuntu, declared_release=None, source_pin=None, expected_error=None):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            layout = root / "oci"
            blobs = layout / "blobs" / "sha256"
            blobs.mkdir(parents=True)
            logs = root / "logs"
            logs.mkdir()

            base = f"usr/lib/modules/{rel}"

            tar_buf = io.BytesIO()
            with tarfile.open(fileobj=tar_buf, mode="w") as tar:
                def add_file(name, data=b""):
                    ti = tarfile.TarInfo(name=name)
                    ti.size = len(data)
                    ti.type = tarfile.REGTYPE
                    tar.addfile(ti, io.BytesIO(data))

                def add_symlink(name, target):
                    ti = tarfile.TarInfo(name=name)
                    ti.type = tarfile.SYMTYPE
                    ti.linkname = target
                    tar.addfile(ti)

                add_file(f"{base}/vmlinuz")
                add_file(f"{base}/vmlinux")
                add_file(f"{base}/System.map")
                add_file(
                    f"{base}/config",
                    b'CONFIG_RUST=y\nCONFIG_CRYPTO_ZSTD=y\n# CONFIG_MODULE_SIG_ALL is not set\nCONFIG_MODULE_SIG_KEY=""\n',
                )
                add_symlink(f"{base}/build", f"../../../src/linux-{rel}")
                add_file("usr/share/licenses/dakota-kernel-ubuntu/LICENSE", b"GPL")
                add_file(f"usr/src/linux-{rel}/Makefile", b"all:\n")
                add_file(f"usr/src/linux-{rel}/.config", b"")
                add_file(f"usr/src/linux-{rel}/Module.symvers", b"")
                add_file(f"{base}/kernel/drivers/net/dummy.ko", b"")

            layer_bytes = tar_buf.getvalue()
            layer_digest = hashlib.sha256(layer_bytes).hexdigest()
            (blobs / layer_digest).write_bytes(layer_bytes)

            config_bytes = json.dumps({"architecture": "amd64", "os": "linux"}).encode()
            config_digest = hashlib.sha256(config_bytes).hexdigest()
            (blobs / config_digest).write_bytes(config_bytes)

            manifest = {
                "schemaVersion": 2,
                "config": {
                    "digest": f"sha256:{config_digest}",
                    "size": len(config_bytes),
                    "mediaType": "application/vnd.oci.image.config.v1+json",
                },
                "layers": [
                    {
                        "digest": f"sha256:{layer_digest}",
                        "size": len(layer_bytes),
                        "mediaType": "application/vnd.oci.image.layer.v1.tar",
                    }
                ],
            }
            manifest_bytes = json.dumps(manifest).encode()
            manifest_digest = hashlib.sha256(manifest_bytes).hexdigest()
            (blobs / manifest_digest).write_bytes(manifest_bytes)

            index = {
                "schemaVersion": 2,
                "manifests": [
                    {
                        "digest": f"sha256:{manifest_digest}",
                        "size": len(manifest_bytes),
                        "mediaType": "application/vnd.oci.image.manifest.v1+json",
                    }
                ],
            }
            (layout / "index.json").write_text(json.dumps(index))

            # Initialize a synthetic local git repository to act as upstream Launchpad repo
            upstream_repo = root / "upstream-repo" / "+git" / codename
            upstream_repo.mkdir(parents=True)
            subprocess.run(["git", "init", "--bare", str(upstream_repo)], check=True, capture_output=True)
            work_repo = root / "work-repo"
            work_repo.mkdir()
            subprocess.run(["git", "init", str(work_repo)], check=True, capture_output=True)
            subprocess.run(["git", "config", "user.name", "Tester"], cwd=work_repo, check=True)
            subprocess.run(["git", "config", "user.email", "tester@example.com"], cwd=work_repo, check=True)
            (work_repo / "README").write_text("kernel source\n")
            subprocess.run(["git", "add", "README"], cwd=work_repo, check=True)
            subprocess.run(["git", "commit", "--no-verify", "-m", "feat: initial commit"], cwd=work_repo, check=True, capture_output=True)
            peeled_commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=work_repo, text=True).strip()

            subprocess.run(["git", "tag", "-a", synth_tag, "-m", f"Release {synth_tag}"], cwd=work_repo, check=True)
            subprocess.run(["git", "push", str(upstream_repo), "--tags", "HEAD"], cwd=work_repo, check=True, capture_output=True)

            (root / "elements").mkdir(parents=True)
            synth_dakota = "1" * 40
            (root / "elements" / "dakota.bst").write_text(f"kind: junction\nsources:\n- kind: git_repo\n  ref: {synth_dakota}\n")

            upstream_url = f"file://{upstream_repo.resolve()}"
            (root / "project.conf").write_text(f"name: dakota-kernel-ubuntu\naliases:\n  local_repo: {upstream_url}\n")
            (root / "elements" / "kernel.bst").write_text(
                f"kind: make\nvariables:\n  ubuntu-release: '{declared_release or ubuntu}'\nsources:\n- kind: git_repo\n  url: {upstream_url}\n  track: Ubuntu-*\n  ref: {synth_tag}-0-g{source_pin or peeled_commit}\n"
            )

            repo_root = Path(__file__).resolve().parents[2]
            script_path = repo_root / ".github" / "scripts" / "kernel-evidence.py"
            feeds = {
                "https://changelogs.ubuntu.com/meta-release": f"Dist: {codename}\nVersion: {ubuntu}\nSupported: 1\n",
                "https://changelogs.ubuntu.com/meta-release-development": "",
            }
            if codename == "stonking":
                feeds["https://changelogs.ubuntu.com/meta-release"] = "Dist: resolute\nVersion: 26.04.1 LTS\nSupported: 1\n"
                feeds["https://changelogs.ubuntu.com/meta-release-development"] = f"Dist: stonking\nVersion: {ubuntu}\nSupported: 0\n"
            runner = """import io, json, runpy, sys
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(sys.argv[1]).parent))
feeds = json.loads(sys.argv[2])
with patch('track_ubuntu_release.urlopen', side_effect=lambda url, **kwargs: io.BytesIO(feeds[url].encode())):
    runpy.run_path(sys.argv[1], run_name='__main__')
"""
            proc = subprocess.run(
                ["python3", "-c", runner, str(script_path), json.dumps(feeds)],
                cwd=root,
                capture_output=True,
                text=True,
            )
            if expected_error:
                self.assertNotEqual(proc.returncode, 0)
                self.assertIn(expected_error, proc.stderr)
                self.assertFalse((root / "logs" / "kernel-evidence.json").exists())
                return
            self.assertEqual(proc.returncode, 0, msg=f"Script failed:\n{proc.stderr}\n{proc.stdout}")
            evidence = json.loads((root / "logs" / "kernel-evidence.json").read_text())
            self.assertEqual(evidence["kernel_release"], rel)
            self.assertEqual(evidence["ubuntu_source_tag"], synth_tag)
            self.assertEqual(evidence["ubuntu_source_revision"], peeled_commit)
            self.assertEqual(evidence["ubuntu_codename"], codename)
            self.assertEqual(evidence["ubuntu_release"], ubuntu)
            self.assertEqual(evidence["dakota_commit"], synth_dakota)
            result = prepare(layout, evidence, "e" * 40, "2026-10-04T00:00:00Z", "ghcr.io/projectbluefin/dakota-kernel-ubuntu")
            self.assertIn(f"ubuntu-{ubuntu}", result["tags"])
            self.assertIn(f"kernel-{rel}", result["tags"])
            self.assertEqual(result["labels"]["org.opencontainers.image.version"], rel)
            self.assertEqual(result["labels"]["io.projectbluefin.ubuntu.codename"], codename)


if __name__ == "__main__":
    unittest.main()
