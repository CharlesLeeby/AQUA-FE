from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import p07_backend_formal_io_v1 as formal


class P07BackendFormalIOV1Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        (self.root / "papers/p07").mkdir(parents=True)
        self.flock = self.root / "formal.lock"

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_single_publish_is_no_clobber(self) -> None:
        relative = "papers/p07/lock.json"
        formal.publish_bytes_no_clobber(self.root, relative, b"first\n")
        with self.assertRaises(FileExistsError):
            formal.publish_bytes_no_clobber(self.root, relative, b"second\n")
        self.assertEqual((self.root / relative).read_bytes(), b"first\n")

    def test_post_unlink_guard_runs_at_single_link_with_staged_fd_open(self) -> None:
        relative = "papers/p07/post-unlink.json"
        observations: list[tuple[str, int, bytes]] = []

        def post_link() -> None:
            info = (self.root / relative).stat()
            observations.append(("post_link", info.st_nlink, b""))

        def post_unlink() -> None:
            path = self.root / relative
            info = path.stat()
            observations.append(("post_unlink", info.st_nlink, path.read_bytes()))

        formal.publish_bytes_no_clobber(
            self.root,
            relative,
            b"held\n",
            post_link_guard=post_link,
            post_unlink_guard=post_unlink,
        )
        self.assertEqual(
            observations,
            [("post_link", 2, b""), ("post_unlink", 1, b"held\n")],
        )
        self.assertFalse(
            any((self.root / "papers/p07").glob(".post-unlink.json.partial.*"))
        )

    def test_dangling_destination_symlink_is_never_replaced(self) -> None:
        external = self.root / "external"
        external.write_bytes(b"outside\n")
        destination = self.root / "papers/p07/lock.json"
        destination.symlink_to(self.root / "missing-target")
        with self.assertRaises(FileExistsError):
            formal.publish_bytes_no_clobber(
                self.root, "papers/p07/lock.json", b"formal\n"
            )
        self.assertTrue(destination.is_symlink())
        self.assertEqual(external.read_bytes(), b"outside\n")

    def test_symlink_parent_fails_closed(self) -> None:
        real = self.root / "real"
        real.mkdir()
        (self.root / "papers/link").symlink_to(real, target_is_directory=True)
        with self.assertRaises(formal.FormalIOError):
            formal.publish_bytes_no_clobber(
                self.root, "papers/link/formal.json", b"x\n"
            )
        self.assertFalse((real / "formal.json").exists())

    def test_eexist_race_never_unlinks_winner(self) -> None:
        relative = "papers/p07/race.json"
        destination = self.root / relative
        real_link = os.link

        def race_link(
            source: str,
            target: str,
            *,
            src_dir_fd: int,
            dst_dir_fd: int,
            follow_symlinks: bool,
        ) -> None:
            del source, src_dir_fd, follow_symlinks
            winner = os.open(
                target,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
                dir_fd=dst_dir_fd,
            )
            try:
                os.write(winner, b"winner\n")
                os.fsync(winner)
            finally:
                os.close(winner)
            raise FileExistsError(target)

        with mock.patch.object(os, "link", side_effect=race_link):
            with self.assertRaises(FileExistsError):
                formal.publish_bytes_no_clobber(self.root, relative, b"loser\n")
        self.assertEqual(destination.read_bytes(), b"winner\n")
        self.assertFalse(any(destination.parent.glob(".race.json.partial.*")))
        self.assertIsNotNone(real_link)

    def test_parent_fsync_error_keeps_published_destination(self) -> None:
        relative = "papers/p07/durable.json"
        with mock.patch.object(
            formal, "_fsync_directory", side_effect=formal.FormalIOError("fsync")
        ):
            with self.assertRaises(formal.FormalIOError):
                formal.publish_bytes_no_clobber(self.root, relative, b"durable\n")
        self.assertEqual((self.root / relative).read_bytes(), b"durable\n")

    def test_bundle_commit_is_last_and_exact_crash_resume(self) -> None:
        queue = "papers/p07/queue.csv"
        allocation = "papers/p07/allocation.csv"
        commit = "papers/p07/queue-lock.json"
        formal.publish_bytes_no_clobber(self.root, queue, b"queue\n")
        records = formal.publish_bundle_commit_last(
            self.root,
            [(queue, b"queue\n"), (allocation, b"allocation\n")],
            commit_artifact=(commit, b"lock\n"),
            flock_path=self.flock,
        )
        self.assertTrue(records[0]["resumed_exact_existing"])
        self.assertTrue((self.root / commit).is_file())
        with self.assertRaises(FileExistsError):
            formal.publish_bundle_commit_last(
                self.root,
                [(queue, b"queue\n"), (allocation, b"allocation\n")],
                commit_artifact=(commit, b"lock\n"),
                flock_path=self.flock,
            )

    def test_crash_resume_rejects_different_partial_data(self) -> None:
        queue = "papers/p07/queue.csv"
        formal.publish_bytes_no_clobber(self.root, queue, b"wrong\n")
        with self.assertRaises(formal.FormalIOError):
            formal.publish_bundle_commit_last(
                self.root,
                [(queue, b"expected\n")],
                commit_artifact=("papers/p07/lock.json", b"lock\n"),
                flock_path=self.flock,
            )
        self.assertFalse((self.root / "papers/p07/lock.json").exists())

    def test_bundle_revalidates_retained_data_immediately_before_commit(self) -> None:
        queue = "papers/p07/queue.csv"
        commit = "papers/p07/lock.json"
        original_publish = formal.publish_bytes_no_clobber
        attacked = False

        def attack_before_commit(root, relative, content, **kwargs):
            nonlocal attacked
            if relative == commit and not attacked:
                attacked = True
                target = self.root / queue
                target.unlink()
                target.write_bytes(b"ATTACK\n")
            return original_publish(root, relative, content, **kwargs)

        with mock.patch.object(
            formal, "publish_bytes_no_clobber", side_effect=attack_before_commit
        ):
            with self.assertRaises(formal.FormalIOError):
                formal.publish_bundle_commit_last(
                    self.root,
                    [(queue, b"queue\n")],
                    commit_artifact=(commit, b"lock\n"),
                    flock_path=self.flock,
                )
        self.assertTrue(attacked)
        self.assertEqual((self.root / queue).read_bytes(), b"ATTACK\n")
        self.assertFalse((self.root / commit).exists())

    def test_bundle_preflight_is_read_only_and_exact_reconcile_only(self) -> None:
        queue = "papers/p07/queue.csv"
        allocation = "papers/p07/allocation.csv"
        commit = "papers/p07/lock.json"
        formal.publish_bytes_no_clobber(self.root, queue, b"queue\n")
        state = formal.preflight_bundle_commit_absent(
            self.root,
            [(queue, b"queue\n"), (allocation, b"allocation\n")],
            commit_relative=commit,
        )
        self.assertEqual(state["exact_existing_data"], [queue])
        self.assertEqual(state["absent_data"], [allocation])
        with self.assertRaises(formal.FormalIOError):
            formal.preflight_bundle_commit_absent(
                self.root, [(queue, b"different\n")], commit_relative=commit
            )
        formal.publish_bytes_no_clobber(self.root, commit, b"lock\n")
        with self.assertRaises(FileExistsError):
            formal.preflight_bundle_commit_absent(
                self.root, [(queue, b"queue\n")], commit_relative=commit
            )

    def test_exact_leaf_creation_never_follows_or_builds_ancestors(self) -> None:
        identity = formal.ensure_exact_leaf_directory(
            self.root, "papers/p07", "backend_replacements"
        )
        leaf = self.root / "papers/p07/backend_replacements"
        self.assertTrue(leaf.is_dir())
        self.assertEqual(identity["inode"], leaf.stat().st_ino)
        formal.ensure_exact_leaf_directory(
            self.root, "papers/p07", "backend_replacements"
        )
        external = self.root / "external"
        external.mkdir()
        link = self.root / "papers/p07/link"
        link.symlink_to(external, target_is_directory=True)
        with self.assertRaises(formal.FormalIOError):
            formal.ensure_exact_leaf_directory(self.root, "papers/p07", "link")
        with self.assertRaises(formal.FormalIOError):
            formal.ensure_exact_leaf_directory(
                self.root, "papers/missing", "unexpected"
            )


if __name__ == "__main__":
    unittest.main()
