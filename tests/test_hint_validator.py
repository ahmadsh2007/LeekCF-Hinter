import json
import unittest

from src.workers.hint_generator.hintValidator import (
    EARLY_LEVELS,
    MAX_HINT_CHARS,
    MIN_HINT_CHARS,
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

    def test_wrong_number_of_hints(self):
        self.assertRejected(payload(levels=[1, 2, 3, 4]), "exactly 5")
        extra = json.loads(payload())
        extra["hints"].append({"level": 6, "text": text("six")})
        self.assertRejected(json.dumps(extra), "exactly 5")

    def test_repeated_or_missing_levels(self):
        raw = json.loads(payload())
        raw["hints"][4]["level"] = 4
        self.assertRejected(json.dumps(raw), "levels 1 to 5")

    def test_level_must_be_an_integer(self):
        raw = json.loads(payload())
        raw["hints"][0]["level"] = "1"
        self.assertRejected(json.dumps(raw), "levels 1 to 5")

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
