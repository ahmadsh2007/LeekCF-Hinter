import unittest

from src.utils.statementHash import computeStatementHash, normalizeText


def makeSpecs(**overrides) -> dict:
    specs = {
        "time_limit_ms": 1000,
        "memory_limit_mb": 256,
        "statement_text": "You are given $$$n$$$ integers.",
        "input_specification": "The first line contains $$$n$$$.",
        "output_specification": "Print the answer.",
        "interaction_specification": None,
        "notes": None,
    }
    specs.update(overrides)
    return specs


class NormalizeTextTests(unittest.TestCase):
    def test_collapses_whitespace_runs_and_strips(self):
        self.assertEqual(normalizeText("  a \t b\n\n c  "), "a b c")

    def test_non_breaking_space_becomes_a_normal_space(self):
        self.assertEqual(normalizeText("a b"), "a b")

    def test_zero_width_characters_are_removed(self):
        self.assertEqual(normalizeText("a​b‍c﻿d"), "abcd")

    def test_case_is_preserved_because_variables_are_case_sensitive(self):
        self.assertNotEqual(normalizeText("n"), normalizeText("N"))

    def test_latex_delimiters_are_preserved(self):
        self.assertEqual(normalizeText("sum of $$$a_i$$$"), "sum of $$$a_i$$$")


class ComputeStatementHashTests(unittest.TestCase):
    def test_hash_is_a_64_char_hex_digest_and_deterministic(self):
        first = computeStatementHash(makeSpecs())
        self.assertRegex(first, r"^[0-9a-f]{64}$")
        self.assertEqual(first, computeStatementHash(makeSpecs()))

    def test_formatting_only_difference_gives_the_same_hash(self):
        a = makeSpecs(statement_text="You are given $$$n$$$ integers.")
        b = makeSpecs(statement_text="You are  given\n$$$n$$$ integers.  ")
        self.assertEqual(computeStatementHash(a), computeStatementHash(b))

    def test_different_statement_gives_a_different_hash(self):
        self.assertNotEqual(
            computeStatementHash(makeSpecs()),
            computeStatementHash(makeSpecs(statement_text="You are given $$$m$$$ integers.")),
        )

    def test_different_time_limit_gives_a_different_hash(self):
        self.assertNotEqual(
            computeStatementHash(makeSpecs()),
            computeStatementHash(makeSpecs(time_limit_ms=2000)),
        )

    def test_different_memory_limit_gives_a_different_hash(self):
        self.assertNotEqual(
            computeStatementHash(makeSpecs()),
            computeStatementHash(makeSpecs(memory_limit_mb=512)),
        )

    def test_notes_do_not_affect_the_hash(self):
        self.assertEqual(
            computeStatementHash(makeSpecs(notes=None)),
            computeStatementHash(makeSpecs(notes="In the first sample, ...")),
        )

    def test_same_text_as_output_versus_interaction_gives_different_hashes(self):
        asOutput = makeSpecs(output_specification="talk", interaction_specification=None)
        asInteraction = makeSpecs(output_specification=None, interaction_specification="talk")
        self.assertNotEqual(computeStatementHash(asOutput), computeStatementHash(asInteraction))

    def test_text_moving_between_adjacent_fields_gives_different_hashes(self):
        a = makeSpecs(statement_text="ab", input_specification="c")
        b = makeSpecs(statement_text="a", input_specification="bc")
        self.assertNotEqual(computeStatementHash(a), computeStatementHash(b))


if __name__ == "__main__":
    unittest.main()
