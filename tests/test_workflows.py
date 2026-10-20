import re
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = ROOT / ".github" / "workflows"
WIZARD = ROOT / "scripts" / "setup-github-automation.sh"
PIPELINE = WORKFLOWS / "daily-pipeline.yml"
BACKUP = WORKFLOWS / "backup.yml"
DEPLOY = WORKFLOWS / "deploy-worker.yml"
EXTRAS_WIZARD = ROOT / "scripts" / "setup-github-deploy-and-backup.sh"

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


class DailyPipelineWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.text = PIPELINE.read_text()

    def test_the_status_report_runs_last_even_when_the_pipeline_crashed(self):
        self.assertLess(self.text.index("scripts/daily.sh"), self.text.index("src.workers.status.pipelineStatus"))
        step = self.text[self.text.index("- name: Status report"):]
        self.assertIn("if: always()", step)

    def test_a_stall_fails_the_run_and_the_report_lands_on_the_run_page(self):
        self.assertIn("pipelineStatus --strict --append-to \"$GITHUB_STEP_SUMMARY\"", self.text)


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


class BackupWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.text = BACKUP.read_text()

    def test_it_runs_every_day_after_the_usage_export_and_can_be_started_by_hand(self):
        self.assertRegex(self.text, r"schedule:\s*\n\s*- cron:")
        self.assertIn("workflow_dispatch:", self.text)
        usage = re.search(r'cron: "(\d+) (\d+) ', (WORKFLOWS / "usage-export.yml").read_text()).groups()
        backup = re.search(r'cron: "(\d+) (\d+) ', self.text).groups()
        self.assertGreater(int(backup[1]) * 60 + int(backup[0]), int(usage[1]) * 60 + int(usage[0]))  # the new day's numbers are in the backup

    def test_it_stays_off_until_the_repository_variable_is_set(self):
        self.assertIn("vars.BACKUP_ENABLED == 'true'", self.text)

    def test_it_checks_the_backup_can_be_read_before_it_keeps_it(self):
        self.assertLess(self.text.index("exportDatabase"), self.text.index("restoreDatabase"))
        self.assertLess(self.text.index("restoreDatabase"), self.text.index("publish-backup.sh"))
        self.assertNotIn("--apply", self.text)  # checking must never write into the database

    def test_it_gets_only_the_database_key_and_the_key_for_the_backup_repository(self):
        for name in ("SUPABASE_DATABASE_URL", "SUPABASE_DATABASE_SECRET_KEY", "BACKUP_DEPLOY_KEY"):
            self.assertIn(f"secrets.{name}", self.text)
        for name in ("GEMINI_API_KEY", "CLOUDFLARE_API_TOKEN", "CLOUDFLARE_DEPLOY_TOKEN"):
            self.assertNotIn(name, self.text)
        self.assertIn("vars.BACKUP_REPO", self.text)

    def test_the_backups_go_to_a_private_repository_never_into_this_public_one_or_its_artifacts(self):
        # statements and editorials are Codeforces' text: they must not be published from a public repository
        self.assertNotIn("upload-artifact", self.text)
        self.assertNotIn("git push origin", self.text)

    def test_it_cannot_run_twice_at_once(self):
        self.assertRegex(self.text, r"concurrency:\s*\n\s*group: backup")


class DeployWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.text = DEPLOY.read_text()

    def test_it_deploys_when_the_api_changes_on_main_and_can_be_started_by_hand(self):
        self.assertRegex(self.text, r"push:\s*\n\s*branches: \[main\]")
        for path in ("src/api/**", "wrangler.toml"):
            self.assertIn(path, self.text)
        self.assertIn("workflow_dispatch:", self.text)

    def test_it_is_never_run_for_other_peoples_pull_requests(self):
        self.assertNotIn("pull_request", self.text)

    def test_it_stays_off_until_the_repository_variable_is_set(self):
        self.assertIn("vars.DEPLOY_ENABLED == 'true'", self.text)

    def test_it_runs_the_api_tests_before_it_deploys(self):
        self.assertLess(self.text.index("node --test"), self.text.index("wrangler@"))

    def test_the_deploy_token_is_its_own_secret_and_reaches_nothing_else(self):
        self.assertIn("CLOUDFLARE_API_TOKEN: ${{ secrets.CLOUDFLARE_DEPLOY_TOKEN }}", self.text)
        for path in (PIPELINE, WORKFLOWS / "usage-export.yml", BACKUP):
            self.assertNotIn("CLOUDFLARE_DEPLOY_TOKEN", path.read_text(), path.name)

    def test_wrangler_is_pinned_so_a_new_release_cannot_change_a_deploy(self):
        self.assertRegex(self.text, r"wrangler@\d+\.\d+\.\d+ deploy")

    def test_it_checks_the_live_api_answers_after_deploying(self):
        self.assertLess(self.text.index("wrangler@"), self.text.index("/v1/health"))

    def test_deploys_queue_instead_of_overlapping(self):
        self.assertRegex(self.text, r"concurrency:\s*\n\s*group: deploy-worker\s*\n\s*cancel-in-progress: false")


class DeployAndBackupWizardTests(unittest.TestCase):
    def setUp(self):
        self.text = EXTRAS_WIZARD.read_text()

    def test_it_is_valid_bash_and_executable(self):
        self.assertEqual(subprocess.run(["bash", "-n", str(EXTRAS_WIZARD)], capture_output=True).returncode, 0)
        self.assertTrue(EXTRAS_WIZARD.stat().st_mode & 0o100)

    def test_the_library_is_the_same_as_the_other_wizard(self):
        marker = "# ──────────────────────────────────────────────────────────────────────────\n\nrun_wizard() {"
        self.assertEqual(self.text.split(marker)[0], WIZARD.read_text().split(marker)[0])

    def test_every_secret_and_variable_it_sets_is_one_a_workflow_reads(self):
        secrets = set(re.findall(r"^\s*set_secret ([A-Z_]+) ", self.text, re.M))
        self.assertEqual(secrets, {"CLOUDFLARE_DEPLOY_TOKEN", "BACKUP_DEPLOY_KEY"})
        variables = set(re.findall(r"^\s*set_var ([A-Z_]+) ", self.text, re.M))
        self.assertEqual(variables, {"BACKUP_REPO", "BACKUP_ENABLED", "DEPLOY_ENABLED"})
        for name in secrets:
            self.assertIn(f"secrets.{name}", workflowTexts(), name)
        for name in variables:
            self.assertIn(f"vars.{name}", workflowTexts(), name)

    def test_its_stage_count_matches_the_stages_it_has(self):
        total = int(re.findall(r"^TOTAL_STAGES=(\d+)", self.text, re.M)[-1])
        self.assertEqual(total, len(re.findall(r'^stage "', self.text, re.M)))

    def test_the_token_is_typed_hidden_and_never_printed_or_put_on_a_command_line(self):
        self.assertIn("ask_secret CLOUDFLARE_DEPLOY_TOKEN", self.text)
        self.assertNotRegex(self.text, r"(echo|printf|say|note|step)[^\n]*\$\{?CLOUDFLARE_DEPLOY_TOKEN")
        self.assertNotRegex(self.text, r"curl[^\n]*\$\{?CLOUDFLARE_DEPLOY_TOKEN")  # a command line can be read by other processes

    def test_the_backup_key_is_limited_to_the_backup_repository_and_the_private_copy_is_removed(self):
        self.assertIn("gh repo deploy-key add", self.text)
        self.assertIn("--allow-write", self.text)
        self.assertIn("--private", self.text)
        self.assertRegex(self.text, r"rm -rf \"\$keydir\"")

    def test_the_workflows_are_switched_on_only_after_their_test_runs(self):
        for workflow in ("backup.yml", "deploy-worker.yml"):
            self.assertLess(self.text.index(f"gh workflow run {workflow}"), self.text.index("set_var BACKUP_ENABLED"))
        self.assertLess(self.text.index("gh workflow run deploy-worker.yml"), self.text.index("set_var DEPLOY_ENABLED"))


if __name__ == "__main__":
    unittest.main()