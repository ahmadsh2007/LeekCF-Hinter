import unittest

from src.workers.dedup.dedupPlanner import DedupProblem, planDedup

START = "2024-01-01T12:00:00+00:00"
LATER = "2024-06-01T12:00:00+00:00"


def problem(problemId, name="Foo", contestId=1000, status="SCRAPED_WAITING_FOR_CONTEST",
            canonical=None, startTime=START, statementHash="h1") -> DedupProblem:
    return DedupProblem(
        id=problemId, name=name, contestId=contestId, stageStatus=status,
        canonicalProblemId=canonical, startTime=startTime, statementHash=statementHash,
    )


def reviewedIds(plan) -> list:
    return sorted(sorted(member.id for member in group) for group in plan.reviews)


class LinkingTests(unittest.TestCase):
    def test_same_name_start_time_and_hash_are_linked_to_the_lowest_contest(self):
        plan = planDedup([problem("1001_C", contestId=1001), problem("1000_A", contestId=1000)])
        self.assertEqual(plan.links, [("1001_C", "1000_A")])
        self.assertEqual(plan.reviews, [])

    def test_three_appearances_all_point_at_one_canonical(self):
        plan = planDedup([
            problem("1002_B", contestId=1002),
            problem("1000_A", contestId=1000),
            problem("1001_C", contestId=1001),
        ])
        self.assertEqual(plan.links, [("1001_C", "1000_A"), ("1002_B", "1000_A")])

    def test_same_contest_ties_are_broken_by_id(self):
        plan = planDedup([problem("1000_B", contestId=1000), problem("1000_A", contestId=1000)])
        self.assertEqual(plan.links, [("1000_B", "1000_A")])

    def test_name_matching_ignores_case_and_spacing(self):
        plan = planDedup([problem("1000_A", name="Foo  Bar"), problem("1001_C", name="foo bar", contestId=1001)])
        self.assertEqual(plan.links, [("1001_C", "1000_A")])


class NonMatchesTests(unittest.TestCase):
    def test_same_name_and_hash_in_different_start_times_are_not_linked(self):
        plan = planDedup([problem("1000_A"), problem("2000_A", contestId=2000, startTime=LATER)])
        self.assertEqual(plan.links, [])
        self.assertEqual(plan.reviews, [])

    def test_same_hash_but_different_names_are_not_linked(self):
        plan = planDedup([problem("1000_A", name="Foo"), problem("1001_C", name="Bar", contestId=1001)])
        self.assertEqual(plan.links, [])
        self.assertEqual(plan.reviews, [])

    def test_same_name_and_start_time_but_different_statements_go_to_review_not_linked(self):
        plan = planDedup([problem("1000_A", statementHash="h1"), problem("1001_C", contestId=1001, statementHash="h2")])
        self.assertEqual(plan.links, [])
        self.assertEqual(reviewedIds(plan), [["1000_A", "1001_C"]])

    def test_matching_pair_is_linked_while_the_odd_one_out_is_reviewed(self):
        plan = planDedup([
            problem("1000_A", statementHash="h1"),
            problem("1001_C", contestId=1001, statementHash="h1"),
            problem("1002_B", contestId=1002, statementHash="h2"),
        ])
        self.assertEqual(plan.links, [("1001_C", "1000_A")])
        self.assertEqual(reviewedIds(plan), [["1000_A", "1001_C", "1002_B"]])

    def test_unscraped_and_failed_problems_are_ignored(self):
        plan = planDedup([
            problem("1000_A"),
            problem("1001_C", contestId=1001, statementHash=None),
            problem("1002_B", contestId=1002, status="FAILED"),
            problem("1003_D", contestId=1003, status="DISCOVERED"),
        ])
        self.assertEqual(plan.links, [])
        self.assertEqual(plan.reviews, [])


class CanonicalChoiceTests(unittest.TestCase):
    def test_the_problem_furthest_along_the_pipeline_is_canonical_even_with_a_higher_contest_id(self):
        plan = planDedup([
            problem("1000_A", contestId=1000, status="SCRAPED_WAITING_FOR_CONTEST"),
            problem("1001_C", contestId=1001, status="HINTS_GENERATED"),
        ])
        self.assertEqual(plan.links, [("1000_A", "1001_C")])

    def test_stage_order_is_respected_between_intermediate_stages(self):
        plan = planDedup([
            problem("1000_A", contestId=1000, status="WAITING_FOR_TUTORIAL"),
            problem("1001_C", contestId=1001, status="TUTORIAL_FOUND"),
        ])
        self.assertEqual(plan.links, [("1000_A", "1001_C")])


class RerunTests(unittest.TestCase):
    def test_an_already_linked_group_produces_no_new_links(self):
        plan = planDedup([
            problem("1000_A"),
            problem("1001_C", contestId=1001, status="DUPLICATE", canonical="1000_A"),
        ])
        self.assertEqual(plan.links, [])
        self.assertEqual(plan.reviews, [])

    def test_a_new_appearance_joins_the_existing_canonical_even_with_a_lower_contest_id(self):
        plan = planDedup([
            problem("1001_C", contestId=1001),
            problem("1002_B", contestId=1002, status="DUPLICATE", canonical="1001_C"),
            problem("1000_A", contestId=1000),
        ])
        self.assertEqual(plan.links, [("1000_A", "1001_C")])

    def test_a_duplicate_is_never_chosen_as_canonical(self):
        plan = planDedup([
            problem("1000_A", contestId=1000, status="DUPLICATE", canonical="0999_Z"),
            problem("1001_C", contestId=1001),
            problem("1002_B", contestId=1002),
        ])
        self.assertEqual(plan.links, [("1002_B", "1001_C")])


if __name__ == "__main__":
    unittest.main()
