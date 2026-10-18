import unittest

from bs4 import BeautifulSoup

from src.services.scraper.errors import ScrapingValidationError
from src.services.scraper.problemParser import parse_problem_details_strictly
from src.utils.statementHash import computeStatementHash

DEFAULT_SAMPLES = """
<div class="sample-tests">
  <div class="section-title">Examples</div>
  <div class="sample-test">
    <div class="input"><div class="title">Input</div><pre>1
2</pre></div>
    <div class="output"><div class="title">Output</div><pre>3</pre></div>
  </div>
</div>
"""

NO_SECTION = object()


def buildPage(
    timeLimit="2 seconds",
    memoryLimit="256 megabytes",
    statementDiv='<div><p>You are given $$$n$$$ integers.</p><p>Second paragraph.</p></div>',
    inputSection='<div class="input-specification"><div class="section-title">Input</div><p>The first line contains $$$n$$$.</p></div>',
    outputSection='<div class="output-specification"><div class="section-title">Output</div><p>Print the answer.</p></div>',
    interactionSection="",
    samples=DEFAULT_SAMPLES,
    note='<div class="note"><div class="section-title">Note</div><p>In the first sample, ...</p></div>',
    header=None,
    outside="",
) -> BeautifulSoup:
    if header is None:
        header = f"""
        <div class="header">
          <div class="title">A. Foo</div>
          <div class="time-limit"><div class="property-title">time limit per test</div>{timeLimit}</div>
          <div class="memory-limit"><div class="property-title">memory limit per test</div>{memoryLimit}</div>
        </div>"""
    html = f"""
    <html><body>
      <div class="problem-statement">
        {header}
        {statementDiv}
        {inputSection}
        {outputSection}
        {interactionSection}
        {samples}
        {note}
      </div>
      {outside}
    </body></html>"""
    return BeautifulSoup(html, "html.parser")


class StandardProblemTests(unittest.TestCase):
    def setUp(self):
        self.specs, self.samples = parse_problem_details_strictly(buildPage())

    def test_limits_are_converted_to_ms_and_mb(self):
        self.assertEqual(self.specs["time_limit_ms"], 2000)
        self.assertEqual(self.specs["memory_limit_mb"], 256)

    def test_statement_keeps_latex_delimiters_and_paragraph_breaks(self):
        self.assertEqual(self.specs["statement_text"], "You are given $$$n$$$ integers.\n\nSecond paragraph.")

    def test_input_and_output_sections_are_captured(self):
        self.assertEqual(self.specs["input_specification"], "Input\nThe first line contains $$$n$$$.")
        self.assertEqual(self.specs["output_specification"], "Output\nPrint the answer.")

    def test_a_standard_problem_has_no_interaction_section(self):
        self.assertIsNone(self.specs["interaction_specification"])

    def test_notes_are_captured(self):
        self.assertEqual(self.specs["notes"], "Note\nIn the first sample, ...")

    def test_samples_are_numbered_from_one(self):
        self.assertEqual(self.samples, [{"test_order": 1, "input_text": "1\n2", "output_text": "3"}])

    def test_hash_matches_the_hash_of_the_returned_specs(self):
        hashInput = {key: value for key, value in self.specs.items() if key != "statement_hash"}
        self.assertEqual(self.specs["statement_hash"], computeStatementHash(hashInput))

    def test_fractional_time_limit(self):
        specs, _ = parse_problem_details_strictly(buildPage(timeLimit="1.5 seconds"))
        self.assertEqual(specs["time_limit_ms"], 1500)

    def test_missing_note_is_none(self):
        specs, _ = parse_problem_details_strictly(buildPage(note=""))
        self.assertIsNone(specs["notes"])

    def test_newer_sample_markup_with_one_div_per_line(self):
        samples = """
        <div class="sample-tests"><div class="sample-test">
          <div class="input"><pre><div class="test-example-line test-example-line-even test-example-line-0">1</div><div class="test-example-line test-example-line-odd test-example-line-1">2</div></pre></div>
          <div class="output"><pre><div class="test-example-line test-example-line-even test-example-line-0">3</div></pre></div>
        </div></div>"""
        _, parsed = parse_problem_details_strictly(buildPage(samples=samples))
        self.assertEqual(parsed, [{"test_order": 1, "input_text": "1\n2", "output_text": "3"}])

    def test_several_samples_keep_their_order(self):
        samples = """
        <div class="sample-tests"><div class="sample-test">
          <div class="input"><pre>a</pre></div><div class="output"><pre>b</pre></div>
          <div class="input"><pre>c</pre></div><div class="output"><pre>d</pre></div>
        </div></div>"""
        _, parsed = parse_problem_details_strictly(buildPage(samples=samples))
        self.assertEqual([s["test_order"] for s in parsed], [1, 2])
        self.assertEqual([s["input_text"] for s in parsed], ["a", "c"])
        self.assertEqual([s["output_text"] for s in parsed], ["b", "d"])


class InteractiveProblemTests(unittest.TestCase):
    INTERACTION = '<div><div class="section-title">Interaction</div><p>Print "? x" to query.</p></div>'

    def test_interaction_without_output_is_detected_as_interactive(self):
        page = buildPage(outputSection="", interactionSection=self.INTERACTION)
        specs, _ = parse_problem_details_strictly(page)
        self.assertEqual(specs["interaction_specification"], 'Interaction\nPrint "? x" to query.')
        self.assertIsNone(specs["output_specification"])

    def test_page_with_both_output_and_interaction_keeps_both(self):
        page = buildPage(interactionSection=self.INTERACTION)
        specs, _ = parse_problem_details_strictly(page)
        self.assertEqual(specs["output_specification"], "Output\nPrint the answer.")
        self.assertIn("Print", specs["interaction_specification"])

    def test_an_interaction_title_outside_the_problem_statement_is_ignored(self):
        page = buildPage(outputSection="", outside=self.INTERACTION)
        with self.assertRaises(ScrapingValidationError):
            parse_problem_details_strictly(page)


class ValidationFailureTests(unittest.TestCase):
    def assertRejected(self, page: BeautifulSoup, messagePart: str):
        with self.assertRaises(ScrapingValidationError) as raised:
            parse_problem_details_strictly(page)
        self.assertIn(messagePart, str(raised.exception))

    def test_neither_output_nor_interaction(self):
        self.assertRejected(buildPage(outputSection=""), "Neither an Output nor an Interaction")

    def test_missing_time_limit(self):
        header = '<div class="header"><div class="memory-limit">256 megabytes</div></div>'
        self.assertRejected(buildPage(header=header), "Time limit")

    def test_missing_memory_limit(self):
        header = '<div class="header"><div class="time-limit">2 seconds</div></div>'
        self.assertRejected(buildPage(header=header), "Memory limit")

    def test_non_numeric_time_limit(self):
        self.assertRejected(buildPage(timeLimit="unlimited"), "numeric time limit")

    def test_statement_div_missing(self):
        self.assertRejected(buildPage(statementDiv=""), "Problem statement text div")

    def test_statement_div_that_has_a_class_is_not_the_statement(self):
        self.assertRejected(buildPage(statementDiv='<div class="oops"><p>x</p></div>'), "Problem statement text div")

    def test_empty_input_specification(self):
        empty = '<div class="input-specification"> </div>'
        self.assertRejected(buildPage(inputSection=empty), "input_specification")

    def test_present_but_empty_output_section(self):
        empty = '<div class="output-specification"> </div>'
        self.assertRejected(buildPage(outputSection=empty), "output_specification")

    def test_missing_sample_container(self):
        self.assertRejected(buildPage(samples=""), "Sample tests container")

    def test_sample_container_without_pre_tags(self):
        samples = '<div class="sample-tests"><div class="sample-test"></div></div>'
        self.assertRejected(buildPage(samples=samples), "<pre>")

    def test_mismatched_sample_counts(self):
        samples = """
        <div class="sample-tests"><div class="sample-test">
          <div class="input"><pre>a</pre></div><div class="input"><pre>b</pre></div>
          <div class="output"><pre>c</pre></div>
        </div></div>"""
        self.assertRejected(buildPage(samples=samples), "Mismatched samples")

    def test_empty_sample_text(self):
        samples = """
        <div class="sample-tests"><div class="sample-test">
          <div class="input"><pre> </pre></div><div class="output"><pre>c</pre></div>
        </div></div>"""
        self.assertRejected(buildPage(samples=samples), "Sample test #1")

    def test_page_that_is_not_a_problem_page(self):
        self.assertRejected(BeautifulSoup("<html><body>Just a moment...</body></html>", "html.parser"), "Time limit")


if __name__ == "__main__":
    unittest.main()
