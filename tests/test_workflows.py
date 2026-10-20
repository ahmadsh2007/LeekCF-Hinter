import re
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = ROOT / ".github" / "workflows"
WIZARD = ROOT / "scripts" / "setup-github-automation.sh"
PIPELINE = WORKFLOWS / "daily-pipeline.yml"

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
        self.assertEqual(names, {"SUPABASE_DATABASE_URL", "SUPABASE_DATABASE_SECRET_KEY", "GEMINI_API_KEY",
                                 "CLOUDFLARE_ACCOUNT_ID", "CLOUDFLARE_API_TOKEN"})
        for name in names:
            self.assertIn(f"secrets.{name}", workflowTexts(), name)

    def test_every_variable_it_sets_is_one_a_workflow_reads(self):
        names = set(re.findall(r"^\s*set_var ([A-Z_]+) ", self.text, re.M))
        self.assertEqual(names, {"LLM_PROVIDER", "GEMINI_MODEL", "GEMINI_THINKING_LEVEL", "HINT_LIMIT",
                                 "TUTORIAL_CONTEST_LIMIT", "USAGE_EXPORT_ENABLED", "PIPELINE_ENABLED"})
        for name in names:
            self.assertIn(f"vars.{name}", workflowTexts(), name)

    def test_the_schedule_is_switched_on_only_after_the_test_runs_are_started(self):
        self.assertLess(self.text.index("gh workflow run daily-pipeline.yml"), self.text.index("set_var PIPELINE_ENABLED"))
        self.assertLess(self.text.index("gh workflow run usage-export.yml"), self.text.index("set_var PIPELINE_ENABLED"))

    def test_the_model_list_does_not_include_the_slow_lite_model(self):
        # gemini-3.1-flash-lite needs about 175 s per problem at high thinking and would eat the job's time
        models = re.search(r'GEMINI_MODEL_LIST="([^"]+)"', self.text).group(1)
        self.assertNotIn("3.1-flash-lite", models)
        self.assertIn("gemini-3.5-flash-lite", models)

    def test_the_token_is_typed_hidden_and_never_printed(self):
        self.assertIn("ask_secret CLOUDFLARE_API_TOKEN", self.text)
        self.assertIn("ask_secret SUPABASE_DATABASE_SECRET_KEY", self.text)
        self.assertIn("ask_secret GEMINI_API_KEY", self.text)
        self.assertNotRegex(self.text, r"(echo|printf|say|note|step)[^\n]*\$\{?GEMINI_API_KEY")
        self.assertNotRegex(self.text, r"(echo|printf|say|note|step)[^\n]*\$\{?CLOUDFLARE_API_TOKEN")
        self.assertNotRegex(self.text, r"(echo|printf|say|note|step)[^\n]*\$\{?SUPABASE_DATABASE_SECRET_KEY")

    def test_it_never_writes_into_the_repository_when_no_env_file_is_given(self):
        self.assertIn("leekcf-env/staging.env", self.text)

    def test_its_stage_count_matches_the_stages_it_has(self):
        total = int(re.findall(r"^TOTAL_STAGES=(\d+)", self.text, re.M)[-1])  # the library declares 0 first; the wizard sets its own
        self.assertEqual(total, len(re.findall(r'^stage "', self.text, re.M)))


class DailyPipelineWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.text = PIPELINE.read_text()

    def test_it_starts_after_the_free_model_quotas_reset(self):
        # Google resets the free daily quotas at midnight US Pacific: 07:00 UTC, or 08:00 UTC when the US clocks go back
        minute, hour = re.search(r'cron: "(\d+) (\d+) \* \* \*"', self.text).groups()
        self.assertGreater(int(hour) * 60 + int(minute), 8 * 60)
        self.assertLess(int(hour), 12)

    def test_it_stays_off_until_the_repository_variable_is_set(self):
        self.assertIn("vars.PIPELINE_ENABLED == 'true'", self.text)

    def test_it_gets_the_model_key_and_the_database_settings(self):
        for name in ("SUPABASE_DATABASE_URL", "SUPABASE_DATABASE_SECRET_KEY", "GEMINI_API_KEY"):
            self.assertIn(f"{name}: ${{{{ secrets.{name} }}}}", self.text)

    def test_it_ends_before_github_would_cut_it_off(self):
        # a cut-off job is marked failed; the run itself should stop on its own limits well inside this
        self.assertRegex(self.text, r"timeout-minutes: 3[0-5]\d")


if __name__ == "__main__":
    unittest.main()