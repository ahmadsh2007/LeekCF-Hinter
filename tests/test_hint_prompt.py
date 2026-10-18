import unittest

from src.services.llm.hintPrompt import (
    PROMPT_VERSION,
    RESPONSE_SCHEMA,
    SYSTEM_PROMPT,
    ProblemForHints,
    buildUserPrompt,
)

def sampleProblem(**overrides) -> ProblemForHints:
    fields = dict(
        id="1943_A", name="MEX Game 1", rating=1500, tags=["games", "greedy"],
        timeLimitMs=2000, memoryLimitMb=256,
        statementText="Alice and Bob play a game on $$$a$$$.",
        inputSpecification="Input\n\nThe first line contains $$$t$$$.",
        outputSpecification="Output\n\nPrint the score.",
        interactionSpecification=None,
        notes="Note\n\nIn the first test, Alice wins.",
        samples=[("3\n0 1 2", "3"), ("1\n5", "0")],
        tutorialText=None,
    )
    fields.update(overrides)
    return ProblemForHints(**fields)


class SystemPromptTests(unittest.TestCase):
    def test_describes_all_five_levels_and_the_spoiler_rule(self):
        for fragment in ("Level 1", "Level 2", "Level 3", "Level 4", "Level 5", "observation", "algorithm"):
            self.assertIn(fragment, SYSTEM_PROMPT)
        self.assertIn("before level 3", SYSTEM_PROMPT)

    def test_forbids_code_and_asks_for_dollar_latex(self):
        self.assertIn("Never write code", SYSTEM_PROMPT)
        self.assertIn("$a_i", SYSTEM_PROMPT)

    def test_version_is_a_non_empty_label(self):
        self.assertTrue(PROMPT_VERSION)


class SchemaTests(unittest.TestCase):
    def test_schema_asks_for_a_list_of_level_and_text(self):
        hints = RESPONSE_SCHEMA["properties"]["hints"]
        self.assertEqual(hints["type"], "ARRAY")
        self.assertEqual(hints["items"]["properties"]["level"]["type"], "INTEGER")
        self.assertEqual(hints["items"]["properties"]["text"]["type"], "STRING")
        self.assertEqual(sorted(hints["items"]["required"]), ["level", "text"])
        self.assertEqual(RESPONSE_SCHEMA["required"], ["hints"])


class UserPromptTests(unittest.TestCase):
    def test_contains_the_problem_and_its_metadata(self):
        prompt = buildUserPrompt(sampleProblem())
        for fragment in ("1943_A", "MEX Game 1", "1500", "2 seconds", "256 MB", "games, greedy",
                         "Alice and Bob play", "The first line contains $$$t$$$.", "Print the score.", "Alice wins."):
            self.assertIn(fragment, prompt)

    def test_tags_are_marked_as_not_to_reveal(self):
        prompt = buildUserPrompt(sampleProblem())
        self.assertIn("do not reveal", prompt.lower())

    def test_unrated_problem(self):
        self.assertIn("unrated", buildUserPrompt(sampleProblem(rating=None)))

    def test_samples_are_numbered(self):
        prompt = buildUserPrompt(sampleProblem())
        self.assertIn("Sample 1", prompt)
        self.assertIn("Sample 2", prompt)
        self.assertIn("0 1 2", prompt)

    def test_the_editorial_is_included_when_there_is_one(self):
        prompt = buildUserPrompt(sampleProblem(tutorialText="Hint 1:\n\nAlice can adapt."))
        self.assertIn("Official editorial", prompt)
        self.assertIn("Alice can adapt.", prompt)

    def test_without_an_editorial_the_prompt_says_so(self):
        prompt = buildUserPrompt(sampleProblem())
        self.assertIn("No official editorial", prompt)

    def test_interactive_problem_shows_the_interaction_section(self):
        prompt = buildUserPrompt(sampleProblem(outputSpecification=None, interactionSpecification="Interaction\n\nPrint a query."))
        self.assertIn("Print a query.", prompt)
        self.assertNotIn("Print the score.", prompt)

    def test_missing_notes_are_left_out(self):
        self.assertNotIn("In the first test", buildUserPrompt(sampleProblem(notes=None)))

    def test_feedback_from_a_rejected_answer_is_appended(self):
        prompt = buildUserPrompt(sampleProblem(), feedback="Hint 1 mentions 'dp'.")
        self.assertIn("rejected", prompt)
        self.assertIn("Hint 1 mentions 'dp'.", prompt)
        self.assertNotIn("rejected", buildUserPrompt(sampleProblem()))


if __name__ == "__main__":
    unittest.main()
