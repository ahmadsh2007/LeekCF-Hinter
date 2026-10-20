import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "publish-backup.sh"


class PublishBackupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.remote = self.root / "remote.git"
        subprocess.run(["git", "init", "--bare", "-q", "--initial-branch=main", str(self.remote)], check=True)

    def tearDown(self):
        self.tmp.cleanup()

    def makeBackup(self, name: str, content: str = "rows") -> Path:
        folder = self.root / "out" / name
        folder.mkdir(parents=True)
        (folder / "manifest.json").write_text("{}")
        (folder / "problems.ndjson.gz").write_text(content)
        return folder

    def publish(self, backup: Path, keep: int = 3, remote: Path | None = None):
        return subprocess.run(["bash", str(SCRIPT), str(backup), str(remote or self.remote), str(keep)], capture_output=True, text=True)

    def git(self, *args: str) -> str:
        return subprocess.run(["git", "--git-dir", str(self.remote), *args], capture_output=True, text=True, check=True).stdout

    def folders(self) -> list[str]:
        return sorted({path.split("/")[0] for path in self.git("ls-tree", "-r", "--name-only", "main").split()})

    def test_the_first_backup_goes_into_an_empty_repository(self):
        result = self.publish(self.makeBackup("2026-10-20_0430"))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.git("ls-tree", "-r", "--name-only", "main").split(),
                         ["2026-10-20_0430/manifest.json", "2026-10-20_0430/problems.ndjson.gz"])

    def test_only_the_newest_backups_are_kept(self):
        for day in range(1, 6):
            result = self.publish(self.makeBackup(f"2026-10-{day:02d}_0430"), keep=3)
            self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.folders(), ["2026-10-03_0430", "2026-10-04_0430", "2026-10-05_0430"])

    def test_the_history_stays_one_commit_so_the_repository_does_not_grow_without_end(self):
        for day in range(1, 5):
            self.publish(self.makeBackup(f"2026-10-{day:02d}_0430"), keep=2)
        self.assertEqual(self.git("rev-list", "--count", "main").strip(), "1")

    def test_kept_backups_keep_their_content(self):
        self.publish(self.makeBackup("2026-10-01_0430", "first"))
        self.publish(self.makeBackup("2026-10-02_0430", "second"))
        self.assertEqual(self.git("show", "main:2026-10-01_0430/problems.ndjson.gz"), "first")
        self.assertEqual(self.git("show", "main:2026-10-02_0430/problems.ndjson.gz"), "second")

    def test_running_it_again_for_the_same_backup_changes_nothing_else(self):
        backup = self.makeBackup("2026-10-01_0430")
        self.publish(backup)
        result = self.publish(backup)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.folders(), ["2026-10-01_0430"])

    def test_a_folder_that_is_not_a_backup_is_refused_and_nothing_is_published(self):
        self.publish(self.makeBackup("2026-10-01_0430"))
        notABackup = self.root / "out" / "random"
        notABackup.mkdir()
        (notABackup / "notes.txt").write_text("hi")
        result = self.publish(notABackup)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("manifest.json", result.stdout + result.stderr)
        self.assertEqual(self.folders(), ["2026-10-01_0430"])

    def test_an_unreachable_repository_is_an_error_not_a_silent_success(self):
        result = self.publish(self.makeBackup("2026-10-01_0430"), remote=self.root / "does-not-exist.git")
        self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
