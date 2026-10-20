import re
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = ROOT / ".github" / "workflows"
WIZARD = ROOT / "scripts" / "setup-usage-stats.sh"

def workflowTexts() -> str:
    return "\n".join(path.read_text() for path in sorted(WORKFLOWS.glob("*.yml")))


class UsageExportWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.text = (WORKFLOWS / "usage-export.yml").read_text()

    def test_it_runs_every_day_and_can_be_started_by_hand(self):
        self.assertRegex(self.text, r"schedule:\s*\n\s*- cron:")
        self.assertIn("workflow_dispatch:", self.text)

    def test_it_stays_off_until_the_repository_variable_is_set(self):
        self.assertIn("vars.USAGE_EXPORT_ENABLED == 'true'", self.text)

    def test_it_runs_the_export_without_the_skip_flag_so_missing_settings_fail_loudly(self):
        self.assertIn("python -u -m src.workers.usage.rollupUsage", self.text)
        self.assertNotIn("--if-configured", self.text)

    def test_it_is_given_exactly_the_settings_the_export_needs(self):
        for name in ("SUPABASE_DATABASE_URL", "SUPABASE_DATABASE_SECRET_KEY", "CLOUDFLARE_ACCOUNT_ID", "CLOUDFLARE_API_TOKEN"):
            self.assertIn(f"{name}: ${{{{ secrets.{name} }}}}", self.text)

    def test_it_cannot_run_twice_at_once(self):
        self.assertRegex(self.text, r"concurrency:\s*\n\s*group: usage-export")


class SetupWizardTests(unittest.TestCase):
    def setUp(self):
        self.text = WIZARD.read_text()

    def test_it_is_valid_bash_and_executable(self):
        self.assertEqual(subprocess.run(["bash", "-n", str(WIZARD)], capture_output=True).returncode, 0)
        self.assertTrue(WIZARD.stat().st_mode & 0o100)

    def test_every_github_secret_it_sets_is_one_a_workflow_reads(self):
        names = set(re.findall(r"^\s*set_secret ([A-Z_]+) ", self.text, re.M))
        self.assertEqual(names, {"SUPABASE_DATABASE_URL", "SUPABASE_DATABASE_SECRET_KEY", "CLOUDFLARE_ACCOUNT_ID", "CLOUDFLARE_API_TOKEN"})
        for name in names:
            self.assertIn(f"secrets.{name}", workflowTexts(), name)

    def test_the_variable_it_sets_is_the_one_that_switches_the_export_on(self):
        self.assertEqual(set(re.findall(r"^\s*set_var ([A-Z_]+) ", self.text, re.M)), {"USAGE_EXPORT_ENABLED"})
        self.assertIn("vars.USAGE_EXPORT_ENABLED", workflowTexts())

    def test_the_token_is_typed_hidden_and_never_printed(self):
        self.assertIn("ask_secret CLOUDFLARE_API_TOKEN", self.text)
        self.assertIn("ask_secret SUPABASE_DATABASE_SECRET_KEY", self.text)
        self.assertNotRegex(self.text, r"(echo|printf|say|note|step)[^\n]*\$\{?CLOUDFLARE_API_TOKEN")
        self.assertNotRegex(self.text, r"(echo|printf|say|note|step)[^\n]*\$\{?SUPABASE_DATABASE_SECRET_KEY")

    def test_it_never_writes_into_the_repository_when_no_env_file_is_given(self):
        self.assertIn("leekcf-env/staging.env", self.text)

    def test_its_stage_count_matches_the_stages_it_has(self):
        total = int(re.findall(r"^TOTAL_STAGES=(\d+)", self.text, re.M)[-1])  # the library declares 0 first; the wizard sets its own
        self.assertEqual(total, len(re.findall(r'^stage "', self.text, re.M)))


if __name__ == "__main__":
    unittest.main()
