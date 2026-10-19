import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

def dryRun(script: str, **env) -> list[str]:
    """Runs a script with PIPELINE_DRY_RUN=1 and returns the commands it announced, in order."""
    completed = subprocess.run(
        ["bash", script], cwd=ROOT, capture_output=True, text=True,
        env={"PATH": os.environ["PATH"], "PIPELINE_DRY_RUN": "1", **env},
    )
    assert completed.returncode == 0, completed.stderr
    return [line[3:-3] for line in completed.stdout.splitlines() if line.startswith("== ") and line.endswith(" ==")]


class DailyScriptTests(unittest.TestCase):
    def test_runs_the_whole_flow_in_dependency_order(self):
        commands = dryRun("scripts/daily.sh", PYTHON="py")
        self.assertEqual([c.split(" -m ")[-1].split(" ")[0] if " -m " in c else c.split(" ")[1] for c in commands], [
            "src/core/database/insertProblem.ts",
            "src.services.scraper.mainChecker",
            "src.workers.dedup.dedupProblems",
            "src.workers.contest_monitor.contestProtector",
            "src.workers.tutorial_finder.findTutorials",
            "src.workers.hint_generator.generateHints",
        ])

    def test_new_problems_are_detected_by_the_sync_before_anything_is_scraped(self):
        commands = dryRun("scripts/daily.sh", PYTHON="py")
        self.assertTrue(commands[0].startswith("node "))
        self.assertIn("insertProblem.ts", commands[0])

    def test_duplicates_are_applied_not_just_reported(self):
        commands = dryRun("scripts/daily.sh", PYTHON="py")
        self.assertTrue(any("dedupProblems --apply" in c for c in commands))

    def test_the_limits_can_be_set_from_the_environment(self):
        commands = dryRun("scripts/daily.sh", PYTHON="py", SCRAPE_LIMIT="25", TUTORIAL_CONTEST_LIMIT="7", HINT_LIMIT="3")
        text = "\n".join(commands)
        self.assertIn("mainChecker --limit 25", text)
        self.assertIn("findTutorials --limit 7", text)
        self.assertIn("generateHints --limit 3", text)

    def test_hints_without_a_tutorial_are_off_unless_asked_for(self):
        self.assertNotIn("--include-without-tutorial", "\n".join(dryRun("scripts/daily.sh", PYTHON="py")))
        self.assertIn("--include-without-tutorial", "\n".join(dryRun("scripts/daily.sh", PYTHON="py", INCLUDE_WITHOUT_TUTORIAL="true")))

    def test_the_python_interpreter_is_configurable_for_ci(self):
        commands = dryRun("scripts/daily.sh", PYTHON="python3.14")
        self.assertTrue(all(c.startswith("python3.14 ") for c in commands[1:]), commands)

    def test_a_failing_stage_stops_the_run(self):
        completed = subprocess.run(
            ["bash", "scripts/daily.sh"], cwd=ROOT, capture_output=True, text=True,
            env={"PATH": os.environ["PATH"], "PYTHON": "false", "PIPELINE_SKIP_SYNC": "1"},
        )
        self.assertNotEqual(completed.returncode, 0)
        self.assertNotIn("contestProtector", completed.stdout)


class RealRunTests(unittest.TestCase):
    """Runs the script for real, with stand-in programs that only record how they were called."""

    def runWithRecorders(self, **env):
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "calls.log"
            for name in ("node", "py"):
                program = Path(directory) / name
                program.write_text(f'#!/bin/sh\necho "{name} $*" >> "{log}"\n')
                program.chmod(program.stat().st_mode | stat.S_IEXEC)
            completed = subprocess.run(
                ["bash", "scripts/daily.sh"], cwd=ROOT, capture_output=True, text=True,
                env={"PATH": f"{directory}:{os.environ['PATH']}", "PYTHON": f"{directory}/py", **env},
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            return log.read_text().splitlines()

    def test_the_sync_really_runs_first_and_every_stage_follows(self):
        calls = self.runWithRecorders()
        self.assertEqual(calls[0], "node src/core/database/insertProblem.ts")
        self.assertEqual([c.split(" -m ")[1].split(" ")[0] for c in calls[1:]], [
            "src.services.scraper.mainChecker",
            "src.workers.dedup.dedupProblems",
            "src.workers.contest_monitor.contestProtector",
            "src.workers.tutorial_finder.findTutorials",
            "src.workers.hint_generator.generateHints",
        ])

    def test_the_sync_can_be_skipped(self):
        calls = self.runWithRecorders(PIPELINE_SKIP_SYNC="1")
        self.assertFalse(any(c.startswith("node ") for c in calls))
        self.assertEqual(len(calls), 5)


class PipelineScriptTests(unittest.TestCase):
    def test_the_container_pipeline_runs_the_python_stages_in_order(self):
        commands = dryRun("deploy/run-pipeline.sh", PYTHON="python")
        modules = [c.split(" -m ")[1].split(" ")[0] for c in commands]
        self.assertEqual(modules, [
            "src.services.scraper.mainChecker",
            "src.workers.dedup.dedupProblems",
            "src.workers.contest_monitor.contestProtector",
            "src.workers.tutorial_finder.findTutorials",
            "src.workers.hint_generator.generateHints",
        ])


if __name__ == "__main__":
    unittest.main()
