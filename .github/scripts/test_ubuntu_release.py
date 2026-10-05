from datetime import datetime, timezone
import io
import json
import unittest
from unittest.mock import patch

from track_ubuntu_release import ARCHIVE, FEED, advance_source, latest_release, published_tag


SOURCE = """variables:
  ubuntu-release: '26.10'
sources:
- kind: git_repo
  url: launchpad:~ubuntu-kernel/ubuntu/+source/linux/+git/stonking
  track: Ubuntu-*
  ref: Ubuntu-7.3.0-8.8-0-g{digest}
- kind: git_repo
  url: github:projectbluefin/dakota.git
  ref: {sdk}
""".format(digest="a" * 40, sdk="b" * 40)


def entry(codename, version, supported=1):
    return f"Dist: {codename}\nVersion: {version}\nSupported: {supported}\n\n"


def refs(tag, commit="a" * 40):
    return f"{'c' * 40}\trefs/tags/{tag}\n{commit}\trefs/tags/{tag}^{{}}\n"


def bootstrap_response(url, **kwargs):
    feeds = {
        FEED: entry("resolute", "26.04.1 LTS"),
        FEED + "-development": "Dist: stonking\nVersion: 26.10\nSupported: 0\nDate: Thu, 15 Oct 2026 00:26:10 UTC\n",
    }
    return io.BytesIO(feeds[url].encode())


class UbuntuReleaseTests(unittest.TestCase):
    def setUp(self):
        clock = patch("track_ubuntu_release.datetime")
        self.clock = clock.start()
        self.clock.now.return_value = datetime(2026, 10, 4, tzinfo=timezone.utc)
        self.addCleanup(clock.stop)

    def test_bootstrap_never_downgrades_to_latest_released_lts(self):
        feed = entry("resolute", "26.04.1 LTS") + entry("stonking", "26.10", 0)
        with patch("track_ubuntu_release.published_tag") as archive, patch("track_ubuntu_release.urlopen", side_effect=bootstrap_response):
            with patch("track_ubuntu_release.subprocess.check_output", return_value=refs("Ubuntu-7.3.0-8.8")):
                self.assertEqual(advance_source(SOURCE, feed), SOURCE)
        archive.assert_not_called()

    def test_kernel_bump_within_bootstrap_series_is_not_locked_to_7_3(self):
        feed = entry("resolute", "26.04.1 LTS")
        tags = refs("Ubuntu-7.3.0-100.100") + refs("Ubuntu-7.4.0-2.9") + refs("Ubuntu-7.4.0-2.10", "e" * 40)
        tags += refs("Ubuntu-7.4.0-2.10i1", "f" * 40)
        with patch("track_ubuntu_release.subprocess.check_output", return_value=tags), patch("track_ubuntu_release.urlopen", side_effect=bootstrap_response):
            updated = advance_source(SOURCE, feed)
        self.assertEqual(updated, SOURCE.replace(f"Ubuntu-7.3.0-8.8-0-g{'a' * 40}", f"Ubuntu-7.4.0-2.10-0-g{'e' * 40}"))

    def test_stale_feed_cannot_reenable_bootstrap_after_release(self):
        self.clock.now.return_value = datetime(2026, 10, 16, tzinfo=timezone.utc)
        with patch("track_ubuntu_release.urlopen", side_effect=bootstrap_response), self.assertRaises(ValueError):
            advance_source(SOURCE, entry("resolute", "26.04.1 LTS"))
        later_series = SOURCE.replace("'26.10'", "'27.04'").replace("/stonking", "/future")
        with self.assertRaises(ValueError):
            advance_source(later_series, entry("stonking", "26.10"))

    def test_bootstrap_switches_to_shipped_kernel_even_when_tag_is_older(self):
        shipped = "Ubuntu-7.3.0-7.7"
        with patch("track_ubuntu_release.published_tag", return_value=shipped):
            with patch("track_ubuntu_release.subprocess.check_output", return_value=refs(shipped, "d" * 40)):
                updated = advance_source(SOURCE, entry("stonking", "26.10"))
        self.assertEqual(updated, SOURCE.replace(f"Ubuntu-7.3.0-8.8-0-g{'a' * 40}", f"{shipped}-0-g{'d' * 40}"))

    def test_released_series_updates_use_shipped_kernel_not_newest_git_tag(self):
        feed = entry("stonking", "26.10.1")
        shipped = "Ubuntu-7.3.0-9.9"
        tags = refs(shipped, "d" * 40) + refs("Ubuntu-7.4.0-2.10", "e" * 40)
        with patch("track_ubuntu_release.published_tag", return_value=shipped):
            with patch("track_ubuntu_release.subprocess.check_output", return_value=tags):
                updated = advance_source(SOURCE, feed)
        self.assertEqual(updated, SOURCE.replace(f"Ubuntu-7.3.0-8.8-0-g{'a' * 40}", f"{shipped}-0-g{'d' * 40}"))

    def test_newest_supported_desktop_not_newest_lts_or_development(self):
        feed = entry("resolute", "26.04.2 LTS") + entry("future", "27.04") + entry("next", "27.10", 0)
        self.assertEqual(latest_release(feed), ((27, 4), "future"))

    def test_series_switch_updates_source_commit_and_metadata_together(self):
        feed = entry("stonking", "26.10") + entry("future", "27.04")
        tag = "Ubuntu-7.4.0-2.10"
        with patch("track_ubuntu_release.published_tag", return_value=tag):
            with patch("track_ubuntu_release.subprocess.check_output", return_value=refs(tag, "e" * 40)):
                updated = advance_source(SOURCE, feed)
                self.assertEqual(advance_source(updated, feed), updated)
        expected = SOURCE.replace("'26.10'", "'27.04'").replace("/stonking", "/future").replace(
            f"Ubuntu-7.3.0-8.8-0-g{'a' * 40}", f"{tag}-0-g{'e' * 40}"
        )
        self.assertEqual(updated, expected)

    def test_empty_or_malformed_feed_and_series_mismatch_fail_closed(self):
        for feed in ("", entry("future", "27.04", 0), entry("future;bad", "27.04"), entry("future", "nonsense"), entry("wrong", "26.10")):
            with self.subTest(feed=feed), self.assertRaises(ValueError):
                advance_source(SOURCE, feed)

    def test_missing_kernel_tags_or_network_failure_do_not_create_update(self):
        feed = entry("future", "27.04")
        with patch("track_ubuntu_release.published_tag", return_value="Ubuntu-7.4.0-2.10"):
            with patch("track_ubuntu_release.subprocess.check_output", return_value=""):
                with self.assertRaises(ValueError):
                    advance_source(SOURCE, feed)
            with patch("track_ubuntu_release.subprocess.check_output", side_effect=OSError("offline")):
                with self.assertRaises(OSError):
                    advance_source(SOURCE, feed)

    def test_published_archive_excludes_proposed_and_paginates(self):
        def publication(version, pocket, **changes):
            return dict(status="Published", source_package_name="linux", component_name="main",
                        distro_series_link="https://api.launchpad.net/1.0/ubuntu/future",
                        source_package_version=version, pocket=pocket, **changes)
        pages = [
            {"entries": [publication("7.4.0-100.100", "Proposed"), publication("7.4.0-2.9", "Updates")],
             "next_collection_link": ARCHIVE + "?ws.start=2"},
            {"entries": [publication("7.4.0-1.1", "Release"), publication("7.4.0-2.10", "Security")]},
        ]
        with patch("track_ubuntu_release.urlopen", side_effect=[io.BytesIO(json.dumps(page).encode()) for page in pages]):
            self.assertEqual(published_tag("future"), "Ubuntu-7.4.0-2.10")

    def test_empty_archive_and_untrusted_pagination_fail_closed(self):
        for page in ({"entries": []}, {"entries": [], "next_collection_link": "http://untrusted.example/"}):
            with self.subTest(page=page):
                with patch("track_ubuntu_release.urlopen", return_value=io.BytesIO(json.dumps(page).encode())):
                    with self.assertRaises(ValueError):
                        published_tag("future")


if __name__ == "__main__":
    unittest.main()
