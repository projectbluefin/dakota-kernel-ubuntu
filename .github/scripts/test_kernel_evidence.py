import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest


class KernelEvidenceTests(unittest.TestCase):
    def test_dynamic_derivation_from_oci_and_sources(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            layout = root / "oci"
            blobs = layout / "blobs" / "sha256"
            blobs.mkdir(parents=True)
            logs = root / "logs"
            logs.mkdir()

            rel = "7.3.0-rc5-9-generic-dakota"
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
            upstream_repo = root / "upstream-repo" / "+git" / "stonking"
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

            synth_tag = "Ubuntu-7.3.0-9.9"
            subprocess.run(["git", "tag", "-a", synth_tag, "-m", f"Release {synth_tag}"], cwd=work_repo, check=True)
            tag_obj = subprocess.check_output(["git", "rev-parse", f"refs/tags/{synth_tag}"], cwd=work_repo, text=True).strip()
            subprocess.run(["git", "push", str(upstream_repo), "--tags", "HEAD"], cwd=work_repo, check=True, capture_output=True)

            (root / "elements").mkdir(parents=True)
            synth_dakota = "1" * 40
            (root / "elements" / "dakota.bst").write_text(f"kind: junction\nsources:\n- kind: git_repo\n  ref: {synth_dakota}\n")

            upstream_url = f"file://{upstream_repo.resolve()}"
            (root / "project.conf").write_text(f"name: dakota-kernel-ubuntu\naliases:\n  local_repo: {upstream_url}\n")
            (root / "elements" / "kernel.bst").write_text(
                f"kind: make\nsources:\n- kind: git_repo\n  url: {upstream_url}\n  track: Ubuntu-7.3.0-*\n  ref: {synth_tag}-0-g{tag_obj}\n"
            )

            repo_root = Path(__file__).resolve().parents[2]
            script_path = repo_root / ".github" / "scripts" / "kernel-evidence.py"
            proc = subprocess.run(
                ["python3", str(script_path)],
                cwd=root,
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 0, msg=f"Script failed:\n{proc.stderr}\n{proc.stdout}")
            evidence = json.loads((root / "logs" / "kernel-evidence.json").read_text())
            self.assertEqual(evidence["kernel_release"], rel)
            self.assertEqual(evidence["ubuntu_source_tag"], synth_tag)
            self.assertEqual(evidence["ubuntu_source_revision"], peeled_commit)
            self.assertEqual(evidence["ubuntu_codename"], "stonking")
            self.assertEqual(evidence["ubuntu_release"], "26.10")
            self.assertEqual(evidence["dakota_commit"], synth_dakota)


if __name__ == "__main__":
    unittest.main()
