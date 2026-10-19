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


class ScrapeAllTests(unittest.TestCase):
    """scripts/scrape-all.sh repeats the scraper until nothing is left, or until a batch scrapes nothing."""

    def runWithOutputs(self, outputs, **env):
        with tempfile.TemporaryDirectory() as directory:
            counter, log = Path(directory) / "counter", Path(directory) / "calls.log"
            counter.write_text("0")
            replies = Path(directory) / "replies"
            replies.write_text("\n".join(outputs))
            program = Path(directory) / "py"
            program.write_text(
                "#!/bin/sh\n"
                f'echo "$*" >> "{log}"\n'
                f'n=$(($(cat "{counter}") + 1)); echo $n > "{counter}"\n'
                f'sed -n "${{n}}p" "{replies}"\n'
            )
            program.chmod(program.stat().st_mode | stat.S_IEXEC)
            completed = subprocess.run(
                ["bash", "scripts/scrape-all.sh"], cwd=ROOT, capture_output=True, text=True, timeout=20,
                env={"PATH": os.environ["PATH"], "PYTHON": str(program), **env},
            )
            return completed, log.read_text().splitlines() if log.exists() else []

    def test_repeats_until_no_problem_is_left(self):
        completed, calls = self.runWithOutputs([
            "Done. Scraped: 1000, failed: 3, will retry: 0.",
            "Done. Scraped: 40, failed: 0, will retry: 1.",
            "No problems found with status 'DISCOVERED'.",
        ])
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(len(calls), 3)
        self.assertIn("ALL DONE", completed.stdout)

    def test_stops_when_a_batch_scrapes_nothing_because_that_means_being_blocked(self):
        completed, calls = self.runWithOutputs([
            "Done. Scraped: 500, failed: 0, will retry: 0.",
            "Done. Scraped: 0, failed: 0, will retry: 5.",
            "Done. Scraped: 500, failed: 0, will retry: 0.",
        ])
        self.assertEqual(len(calls), 2)
        self.assertIn("scraped nothing", completed.stdout)

    def test_passes_the_batch_size_and_the_polite_delay(self):
        _, calls = self.runWithOutputs(["No problems found with status 'DISCOVERED'."])
        self.assertIn("mainChecker --limit 1000 --delay 2", calls[0])

    def test_a_crash_of_the_scraper_stops_the_loop(self):
        with tempfile.TemporaryDirectory() as directory:
            program = Path(directory) / "py"
            program.write_text("#!/bin/sh\nexit 3\n")
            program.chmod(program.stat().st_mode | stat.S_IEXEC)
            completed = subprocess.run(["bash", "scripts/scrape-all.sh"], cwd=ROOT, capture_output=True, text=True, timeout=20,
                                       env={"PATH": os.environ["PATH"], "PYTHON": str(program)})
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("exited with 3", completed.stdout)


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
