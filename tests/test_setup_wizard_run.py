import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WIZARD = ROOT / "scripts" / "setup-github-automation.sh"

FAKE_GH = """#!/bin/sh
# Records what the wizard asks GitHub to do; keeps no secrets anywhere but the call log of this test.
case "$1 $2" in
  "auth status") exit 0 ;;
  "repo view") echo "owner/repo"; exit 0 ;;
  "secret set") echo "secret $3 $(cat)" >> "$FAKE_LOG"; exit 0 ;;
  "variable set") echo "var $3 $5" >> "$FAKE_LOG"; exit 0 ;;
  "variable get")
    value=$(grep "^$3=" "$FAKE_VARS" | head -n1 | cut -d= -f2-)
    [ -n "$value" ] && { echo "$value"; exit 0; }
    exit 1 ;;
  "workflow run") echo "workflow $3" >> "$FAKE_LOG"; exit 0 ;;
esac
exit 0
"""

FAKE_NPX = """#!/bin/sh
echo "account id 36d46ff2e69ff941121d65a7d48c2dc9"
"""

# Stands in for `python -m src.workers.usage.rollupUsage`: succeeds only with the database key the test calls valid.
FAKE_PYTHON = """#!/bin/sh
key=$(grep '^SUPABASE_DATABASE_SECRET_KEY=' "$ENV_FILE" | cut -d"'" -f2)
echo "export used $key" >> "$FAKE_LOG"
[ "$key" = "sb_secret_NEW" ]
"""

EXISTING_ENV = """SUPABASE_DATABASE_URL='https://abc.supabase.co'
SUPABASE_DATABASE_SECRET_KEY='sb_secret_OLD'
GEMINI_API_KEY='gemini-key'
CLOUDFLARE_API_TOKEN='cloudflare-old'
"""

# One line per prompt, in the order the wizard asks: Enter at "Ready to start?", the Cloudflare token, "use this
# account id?", Enter to keep the database URL, the NEW database key, run the export here, Enter after it, Enter to keep
# the Gemini key, store on GitHub, no test runs, Enter, switch the schedule on.
ANSWERS = ["", "cloudflare-new", "y", "", "sb_secret_NEW", "y", "", "", "y", "n", "", "y"]


def writeExecutable(path: Path, text: str) -> None:
    path.write_text(text)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


class SetupWizardRunTests(unittest.TestCase):
    def runWizard(self, existingVars: str = ""):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        (root / "bin").mkdir()
        writeExecutable(root / "bin" / "gh", FAKE_GH)
        writeExecutable(root / "bin" / "npx", FAKE_NPX)
        writeExecutable(root / "bin" / "open", "#!/bin/sh\nexit 0\n")
        writeExecutable(root / "python", FAKE_PYTHON)
        envFile = root / "staging.env"
        envFile.write_text(EXISTING_ENV)
        (root / "vars").write_text(existingVars)
        (root / "calls.log").write_text("")
        env = {**os.environ, "PATH": f"{root / 'bin'}:{os.environ['PATH']}", "ENV_FILE": str(envFile),
               "PYTHON": str(root / "python"), "FAKE_LOG": str(root / "calls.log"), "FAKE_VARS": str(root / "vars")}
        result = subprocess.run(["bash", str(WIZARD)], input="\n".join(ANSWERS) + "\n", env=env,
                                capture_output=True, text=True, timeout=60)
        return result, envFile.read_text(), (root / "calls.log").read_text()

    def test_a_new_database_key_is_used_by_the_trial_run_kept_on_this_computer_and_stored_on_github(self):
        result, envText, calls = self.runWizard()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("export used sb_secret_NEW", calls)  # the key was asked for before the trial export
        self.assertIn("SUPABASE_DATABASE_SECRET_KEY='sb_secret_NEW'", envText)  # and not left stale in the settings file
        self.assertNotIn("sb_secret_OLD", envText)
        self.assertIn("secret SUPABASE_DATABASE_SECRET_KEY sb_secret_NEW", calls)

    def test_no_key_is_ever_printed(self):
        result, _, _ = self.runWizard()
        for value in ("sb_secret_NEW", "sb_secret_OLD", "gemini-key", "cloudflare-new"):
            self.assertNotIn(value, result.stdout + result.stderr)

    def test_running_it_again_does_not_undo_settings_that_were_changed_on_purpose(self):
        result, _, calls = self.runWizard(existingVars="HINT_LIMIT=1000\nGEMINI_MODEL=gemini-3.5-flash-lite\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("var HINT_LIMIT", calls)
        self.assertNotIn("var GEMINI_MODEL", calls)
        self.assertIn("var TUTORIAL_CONTEST_LIMIT 400", calls)  # a setting nobody has chosen yet gets its default
        self.assertIn("var HINT_LIMIT", self.runWizard()[2])  # and so does HINT_LIMIT on a first run
        self.assertIn("var USAGE_EXPORT_ENABLED true", calls)  # the switches are always set
        self.assertIn("var PIPELINE_ENABLED true", calls)


if __name__ == "__main__":
    unittest.main()
