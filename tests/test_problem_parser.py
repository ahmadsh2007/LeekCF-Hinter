import unittest

from bs4 import BeautifulSoup

from src.services.scraper.errors import ScrapingValidationError
from src.services.scraper.problemParser import parse_problem_details_strictly
from src.utils.statementHash import computeStatementHash
from tests.fixtures import buildPage

class StandardProblemTests(unittest.TestCase):
    def setUp(self):
        self.specs, self.samples = parse_problem_details_strictly(buildPage())

    def test_limits_are_converted_to_ms_and_mb(self):
        self.assertEqual(self.specs["time_limit_ms"], 2000)
        self.assertEqual(self.specs["memory_limit_mb"], 256)

    def test_statement_keeps_latex_delimiters_and_paragraph_breaks(self):
        self.assertEqual(self.specs["statement_text"], "You are given $$$n$$$ integers.\n\nSecond paragraph.")

    def test_input_and_output_sections_are_captured(self):
        self.assertEqual(self.specs["input_specification"], "Input\n\nThe first line contains $$$n$$$.")
        self.assertEqual(self.specs["output_specification"], "Output\n\nPrint the answer.")

    def test_a_standard_problem_has_no_interaction_section(self):
        self.assertIsNone(self.specs["interaction_specification"])

    def test_notes_are_captured(self):
        self.assertEqual(self.specs["notes"], "Note\n\nIn the first sample, ...")

    def test_samples_are_numbered_from_one(self):
        self.assertEqual(self.samples, [{"test_order": 1, "input_text": "1\n2", "output_text": "3"}])

    def test_hash_matches_the_hash_of_the_returned_specs(self):
        hashInput = {key: value for key, value in self.specs.items() if key != "statement_hash"}
        self.assertEqual(self.specs["statement_hash"], computeStatementHash(hashInput))

    def test_fractional_time_limit(self):
        specs, _ = parse_problem_details_strictly(buildPage(timeLimit="1.5 seconds"))
        self.assertEqual(specs["time_limit_ms"], 1500)

    def test_inline_markup_does_not_split_statement_input_or_notes(self):
        page = buildPage(
            statementDiv='<div><p>The size is <span class="tex-span"><i>n</i> × <i>m</i></span> meters, print <span class="tex-font-style-tt">YES</span>.</p></div>',
            inputSection='<div class="input-specification"><div class="section-title">Input</div><p>Line with <span class="tex-span"><i>a</i><sub class="lower-index">i</sub></span> and <b>bold</b>.</p></div>',
            note='<div class="note"><div class="section-title">Note</div><p>Take <i>x</i> = <span class="tex-span">10<sup class="upper-index">9</sup></span>.</p></div>',
        )
        specs, _ = parse_problem_details_strictly(page)
        self.assertEqual(specs["statement_text"], "The size is $$$n × m$$$ meters, print YES.")
        self.assertEqual(specs["input_specification"], "Input\n\nLine with $$$a_i$$$ and bold.")
        self.assertEqual(specs["notes"], "Note\n\nTake x = $$$10^9$$$.")

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
        self.assertEqual(specs["interaction_specification"], 'Interaction\n\nPrint "? x" to query.')
        self.assertIsNone(specs["output_specification"])

    def test_page_with_both_output_and_interaction_keeps_both(self):
        page = buildPage(interactionSection=self.INTERACTION)
        specs, _ = parse_problem_details_strictly(page)
        self.assertEqual(specs["output_specification"], "Output\n\nPrint the answer.")
        self.assertIn("Print", specs["interaction_specification"])

    def test_an_interactive_problem_may_have_no_input_section_at_all(self):
        # e.g. Codeforces 1155E: the statement is followed directly by the Interaction section
        page = buildPage(inputSection="", outputSection="", interactionSection=self.INTERACTION)
        specs, samples = parse_problem_details_strictly(page)
        self.assertIsNone(specs["input_specification"])
        self.assertIsNone(specs["output_specification"])
        self.assertEqual(specs["interaction_specification"], 'Interaction\n\nPrint "? x" to query.')
        self.assertEqual(len(samples), 1)

    def test_the_hash_of_such_a_problem_is_stable_and_differs_from_one_with_an_input_section(self):
        without, _ = parse_problem_details_strictly(buildPage(inputSection="", outputSection="", interactionSection=self.INTERACTION))
        again, _ = parse_problem_details_strictly(buildPage(inputSection="", outputSection="", interactionSection=self.INTERACTION))
        withInput, _ = parse_problem_details_strictly(buildPage(outputSection="", interactionSection=self.INTERACTION))
        self.assertEqual(without["statement_hash"], again["statement_hash"])
        self.assertNotEqual(without["statement_hash"], withInput["statement_hash"])

    def test_a_present_but_empty_input_section_is_still_a_broken_page_even_when_interactive(self):
        empty = '<div class="input-specification"> </div>'
        with self.assertRaises(ScrapingValidationError) as raised:
            parse_problem_details_strictly(buildPage(inputSection=empty, outputSection="", interactionSection=self.INTERACTION))
        self.assertIn("input_specification", str(raised.exception))

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

    def test_older_pages_put_the_statement_in_a_div_called_legend(self):
        # e.g. Codeforces 238E and 505C
        specs, _ = parse_problem_details_strictly(buildPage(statementDiv='<div class="legend"><p>Old layout.</p></div>'))
        self.assertEqual(specs["statement_text"], "Old layout.")

    def test_a_standard_problem_must_have_an_input_section(self):
        self.assertRejected(buildPage(inputSection=""), "input_specification")

    def test_empty_input_specification(self):
        empty = '<div class="input-specification"> </div>'
        self.assertRejected(buildPage(inputSection=empty), "input_specification")

    def test_present_but_empty_output_section(self):
        empty = '<div class="output-specification"> </div>'
        self.assertRejected(buildPage(outputSection=empty), "output_specification")

    def test_a_problem_may_have_no_sample_box_at_all(self):
        # e.g. Codeforces 1060H says "This problem has no sample tests"
        specs, samples = parse_problem_details_strictly(buildPage(samples=""))
        self.assertEqual(samples, [])
        self.assertTrue(specs["statement_text"])

    def test_a_sample_section_without_any_sample_is_still_a_broken_page(self):
        self.assertRejected(buildPage(samples='<div class="sample-tests"><div class="section-title">Examples</div></div>'), "Sample tests container")

    def test_an_examples_heading_over_an_empty_box_means_the_problem_has_no_samples(self):
        # e.g. Codeforces 207D1, 178E1, 241G: the heading is there but the box is empty (the tests are data files)
        samples = '<div class="sample-tests"><div class="section-title">Examples</div><div class="sample-test"></div></div>'
        specs, parsed = parse_problem_details_strictly(buildPage(samples=samples))
        self.assertEqual(parsed, [])
        self.assertTrue(specs["statement_text"])

    def test_a_sample_box_with_inputs_but_no_outputs_is_a_broken_page(self):
        samples = '<div class="sample-tests"><div class="sample-test"><div class="input"><pre>a</pre></div></div></div>'
        self.assertRejected(buildPage(samples=samples), "<pre>")

    def test_a_sample_box_with_outputs_but_no_inputs_is_a_broken_page(self):
        samples = '<div class="sample-tests"><div class="sample-test"><div class="output"><pre>a</pre></div></div></div>'
        self.assertRejected(buildPage(samples=samples), "<pre>")

    def test_mismatched_sample_counts(self):
        samples = """
        <div class="sample-tests"><div class="sample-test">
          <div class="input"><pre>a</pre></div><div class="input"><pre>b</pre></div>
          <div class="output"><pre>c</pre></div>
        </div></div>"""
        self.assertRejected(buildPage(samples=samples), "Mismatched samples")

    def test_a_sample_may_have_an_empty_output(self):
        # e.g. Codeforces 1179A: a sample with zero queries has an empty correct output
        samples = """
        <div class="sample-tests"><div class="sample-test">
          <div class="input"><pre>
2 0
0 0
</pre></div><div class="output"><pre>
</pre></div>
        </div></div>"""
        _, parsed = parse_problem_details_strictly(buildPage(samples=samples))
        self.assertEqual(parsed, [{"test_order": 1, "input_text": "2 0\n0 0", "output_text": ""}])

    def test_a_sample_may_have_an_empty_input(self):
        samples = """
        <div class="sample-tests"><div class="sample-test">
          <div class="input"><pre> </pre></div><div class="output"><pre>c</pre></div>
        </div></div>"""
        _, parsed = parse_problem_details_strictly(buildPage(samples=samples))
        self.assertEqual(parsed, [{"test_order": 1, "input_text": "", "output_text": "c"}])

    def test_a_sample_with_nothing_on_either_side_is_a_broken_page(self):
        samples = """
        <div class="sample-tests"><div class="sample-test">
          <div class="input"><pre> </pre></div><div class="output"><pre> </pre></div>
        </div></div>"""
        self.assertRejected(buildPage(samples=samples), "Sample test #1")

    def test_page_that_is_not_a_problem_page(self):
        self.assertRejected(BeautifulSoup("<html><body>Just a moment...</body></html>", "html.parser"), "Time limit")


if __name__ == "__main__":
    unittest.main()
