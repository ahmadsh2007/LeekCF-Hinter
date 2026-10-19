import json
import unittest

from src.workers.hint_generator.hintValidator import (
    EARLY_LEVELS,
    MAX_HINT_CHARS,
    MAX_HINTS,
    MIN_HINT_CHARS,
    MIN_HINTS,
    Hint,
    HintValidationError,
    validateHints,
)

def text(label: str) -> str:
    return f"{label}: a perfectly ordinary sentence about the quantities in the problem."

def payload(texts=None, levels=None) -> str:
    levels = levels or [1, 2, 3, 4, 5]
    texts = texts or {level: text(f"level {level}") for level in levels}
    return json.dumps({"hints": [{"level": level, "text": texts[level]} for level in levels]})

def withText(level: int, newText: str) -> str:
    texts = {n: text(f"level {n}") for n in range(1, 6)}
    texts[level] = newText
    return payload(texts)


class VariableCountTests(unittest.TestCase):
    def test_every_count_from_two_to_five_is_accepted_and_keeps_its_levels(self):
        for count in range(2, 6):
            hints = validateHints(payload(levels=list(range(1, count + 1))))
            self.assertEqual([hint.level for hint in hints], list(range(1, count + 1)), count)

    def test_in_a_two_hint_answer_the_last_hint_may_name_the_technique(self):
        texts = {1: text("one"), 2: text("two") + " Use dynamic programming with a segment tree."}
        self.assertEqual(len(validateHints(payload(texts, levels=[1, 2]))), 2)

    def test_in_a_two_hint_answer_the_first_hint_still_may_not(self):
        texts = {1: text("one") + " Think greedy.", 2: text("two")}
        with self.assertRaises(HintValidationError) as caught:
            validateHints(payload(texts, levels=[1, 2]))
        self.assertIn("Hint 1", str(caught.exception))

    def test_in_a_three_hint_answer_the_middle_hint_may_not_name_it_but_the_last_may(self):
        middle = {1: text("one"), 2: text("two") + " Use binary search.", 3: text("three")}
        with self.assertRaises(HintValidationError) as caught:
            validateHints(payload(middle, levels=[1, 2, 3]))
        self.assertIn("Hint 2", str(caught.exception))
        last = {1: text("one"), 2: text("two"), 3: text("three") + " Use binary search."}
        self.assertEqual(len(validateHints(payload(last, levels=[1, 2, 3]))), 3)

    def test_in_a_four_hint_answer_hint_three_may_name_it(self):
        texts = {n: text(f"level {n}") for n in range(1, 5)}
        texts[3] += " Use a segment tree."
        self.assertEqual(len(validateHints(payload(texts, levels=[1, 2, 3, 4]))), 4)


class ValidPayloadTests(unittest.TestCase):
    def test_five_levels_come_back_sorted(self):
        hints = validateHints(payload(levels=[3, 1, 5, 2, 4]))
        self.assertEqual([hint.level for hint in hints], [1, 2, 3, 4, 5])
        self.assertEqual(hints[0], Hint(level=1, content=text("level 1")))

    def test_text_is_stripped(self):
        hints = validateHints(withText(1, "  \n" + text("padded") + "\n "))
        self.assertEqual(hints[0].content, text("padded"))

    def test_math_and_markdown_are_fine(self):
        self.assertEqual(len(validateHints(withText(2, r"Look at $a_i \le 10^9$ and **notice** the sum of all $a_i$."))), 5)

    def test_early_levels_are_one_and_two(self):
        self.assertEqual(EARLY_LEVELS, (1, 2))


class ShapeTests(unittest.TestCase):
    def assertRejected(self, raw, fragment):
        with self.assertRaises(HintValidationError) as caught:
            validateHints(raw)
        self.assertIn(fragment, str(caught.exception))

    def test_not_json(self):
        self.assertRejected("here are your hints!", "JSON")

    def test_json_without_a_hints_list(self):
        self.assertRejected(json.dumps({"answer": []}), "hints")
        self.assertRejected(json.dumps([1, 2, 3]), "hints")

    def test_the_number_of_hints_must_be_between_two_and_five(self):
        self.assertEqual((MIN_HINTS, MAX_HINTS), (2, 5))
        self.assertRejected(payload(levels=[1]), "between 2 and 5")
        self.assertRejected(json.dumps({"hints": []}), "between 2 and 5")
        extra = json.loads(payload())
        extra["hints"].append({"level": 6, "text": text("six")})
        self.assertRejected(json.dumps(extra), "between 2 and 5")

    def test_repeated_or_missing_levels(self):
        raw = json.loads(payload())
        raw["hints"][4]["level"] = 4
        self.assertRejected(json.dumps(raw), "numbered 1 to 5")

    def test_levels_must_start_at_one_and_have_no_gaps(self):
        self.assertRejected(payload(levels=[1, 2, 4]), "numbered 1 to 3")
        self.assertRejected(payload(levels=[2, 3]), "numbered 1 to 2")

    def test_level_must_be_an_integer(self):
        raw = json.loads(payload())
        raw["hints"][0]["level"] = "1"
        self.assertRejected(json.dumps(raw), "numbered 1 to 5")

    def test_text_must_be_a_string(self):
        raw = json.loads(payload())
        raw["hints"][2]["text"] = None
        self.assertRejected(json.dumps(raw), "Hint 3")

    def test_blank_and_too_short_text(self):
        self.assertRejected(withText(4, "   "), "Hint 4")
        self.assertRejected(withText(4, "x" * (MIN_HINT_CHARS - 1)), "too short")

    def test_too_long_text(self):
        self.assertRejected(withText(5, "word " * MAX_HINT_CHARS), "too long")

    def test_code_is_not_allowed_at_any_level(self):
        for level in range(1, 6):
            self.assertRejected(withText(level, text("x") + "\n```cpp\nint main(){}\n```"), "code")


class EarlyHintSpoilerTests(unittest.TestCase):
    def assertSpoiler(self, level, sentence, term):
        with self.assertRaises(HintValidationError) as caught:
            validateHints(withText(level, text("x") + " " + sentence))
        message = str(caught.exception)
        self.assertIn(f"Hint {level}", message)
        self.assertIn(term, message.lower().replace("-", " "))

    def test_algorithm_and_data_structure_names_are_rejected_in_levels_one_and_two(self):
        cases = [
            ("Think about dynamic programming here.", "dynamic programming"),
            ("This is a classic DP problem.", "dp"),
            ("A greedy choice works.", "greedy"),
            ("Use binary search on the answer.", "binary search"),
            ("Use Binary-Search on the answer.", "binary search"),
            ("Two pointers will do.", "two pointers"),
            ("Try a segment tree.", "segment tree"),
            ("Build the graph and run BFS.", "bfs"),
            ("A DSU keeps components.", "dsu"),
            ("Union-Find helps.", "union find"),
            ("Prefix sums make queries fast.", "prefix sum"),
            ("Run Dijkstra from the start.", "dijkstra"),
            ("This needs a trie.", "trie"),
            ("Consider a bitmask of the chosen items.", "bitmask"),
            ("Compute dp[i] from dp[i-1].", "dp"),
        ]
        for level in EARLY_LEVELS:
            for sentence, term in cases:
                with self.subTest(level=level, sentence=sentence):
                    self.assertSpoiler(level, sentence, term)

    def test_the_same_words_are_fine_from_level_three_on(self):
        sentence = "Use dynamic programming with a segment tree, or a greedy choice with binary search."
        for level in (3, 4, 5):
            self.assertEqual(len(validateHints(withText(level, text("x") + " " + sentence))), 5)

    def test_words_that_merely_contain_a_term_are_not_flagged(self):
        harmless = "The bandpass filter and the deadpool of values, a greedily-named helper, adp, tries and retries are unrelated."
        self.assertEqual(len(validateHints(withText(1, text("x") + " " + harmless))), 5)

    def test_an_ordinary_observation_passes(self):
        observation = "Notice that the sum of the array never changes, so only the parity of $n$ matters."
        self.assertEqual(len(validateHints(withText(1, observation))), 5)


if __name__ == "__main__":
    unittest.main()
