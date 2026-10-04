import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from registry_metadata import prepare


class RegistryMetadataTests(unittest.TestCase):
    def fixture(self, root):
        blobs = root / "blobs" / "sha256"
        blobs.mkdir(parents=True)

        def blob(value, media_type):
            data = json.dumps(value).encode()
            digest = hashlib.sha256(data).hexdigest()
            (blobs / digest).write_bytes(data)
            return {"digest": f"sha256:{digest}", "size": len(data), "mediaType": media_type}

        config = {"architecture": "amd64", "os": "linux", "rootfs": {"type": "layers", "diff_ids": ["sha256:" + "a" * 64]}, "config": {"Labels": {"org.opencontainers.image.licenses": "GPL-2.0-only"}}}
        descriptor = blob(config, "application/vnd.oci.image.config.v1+json")
        manifest = {"schemaVersion": 2, "config": descriptor, "layers": [{"digest": "sha256:" + "b" * 64, "size": 1, "mediaType": "application/vnd.oci.image.layer.v1.tar"}]}
        image = blob(manifest, "application/vnd.oci.image.manifest.v1+json")
        (root / "index.json").write_text(json.dumps({"schemaVersion": 2, "manifests": [image]}))
        evidence = {"kernel_release": "7.3.0-rc5-8-generic-dakota", "architecture": "x86_64", "ubuntu_release": "26.10", "ubuntu_codename": "stonking", "ubuntu_source_tag": "Ubuntu-7.3.0-8.8", "ubuntu_source_revision": "c" * 40, "ubuntu_source_url": "https://git.launchpad.net/ubuntu", "dakota_commit": "d" * 40}
        return config, manifest, evidence

    def load(self, root, descriptor):
        path = root / "blobs" / "sha256" / descriptor["digest"].split(":")[1]
        data = path.read_bytes()
        self.assertEqual(descriptor["digest"], "sha256:" + hashlib.sha256(data).hexdigest())
        self.assertEqual(descriptor["size"], len(data))
        return json.loads(data)

    def test_followable_rc_tags_and_valid_hash_chain_preserve_filesystem(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source_config, source_manifest, evidence = self.fixture(root)
            result = prepare(root, evidence, "e" * 40, "2026-10-04T01:00:00+00:00", "ghcr.io/projectbluefin/dakota-kernel-ubuntu")
            self.assertEqual(result["tags"], ["latest", "ubuntu-26.10", "ubuntu-26.10-amd64", "7.3", "7.3.0-rc5", "kernel-7.3.0-rc5-8-generic-dakota", "ubuntu-7.3.0-8.8"])
            self.assertNotIn("stable", result["tags"])
            manifest = self.load(root, json.loads((root / "index.json").read_text())["manifests"][0])
            config = self.load(root, manifest["config"])
            self.assertEqual(manifest["layers"], source_manifest["layers"])
            self.assertEqual(config["rootfs"], source_config["rootfs"])
            self.assertEqual(config["config"]["Labels"]["org.opencontainers.image.revision"], "e" * 40)
            self.assertEqual(config["config"]["Labels"]["org.opencontainers.image.version"], evidence["kernel_release"])
            self.assertEqual(config["config"]["Labels"]["io.projectbluefin.ubuntu.source-revision"], evidence["ubuntu_source_revision"])
            before = (root / "index.json").read_bytes()
            prepare(root, evidence, "e" * 40, "2026-10-04T01:00:00+00:00", result["image"])
            self.assertEqual((root / "index.json").read_bytes(), before)

    def test_rejects_unsafe_release_tag_before_modifying_layout(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            _, _, evidence = self.fixture(root)
            evidence["kernel_release"] = "7.3.0-rc5/invalid"
            before = (root / "index.json").read_bytes()
            with self.assertRaises(ValueError):
                prepare(root, evidence, "e" * 40, "2026-10-04T01:00:00+00:00", "ghcr.io/projectbluefin/dakota-kernel-ubuntu")
            self.assertEqual((root / "index.json").read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
