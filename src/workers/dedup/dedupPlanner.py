from dataclasses import dataclass
from src.utils.statementHash import normalizeText

# Only problems that were scraped can be compared. DISCOVERED and FAILED have no usable statement.
# The rank orders how far along the pipeline a problem is: the furthest one is kept as the canonical
# so a problem that already has a tutorial or hints is never demoted to a duplicate.
STAGE_RANK = {
    "SCRAPED_WAITING_FOR_CONTEST": 1,
    "WAITING_FOR_TUTORIAL": 2,
    "TUTORIAL_FOUND": 3,
    "HINTS_GENERATED": 4,
}

@dataclass(frozen=True)
class DedupProblem:
    id: str
    name: str
    contestId: int
    stageStatus: str
    canonicalProblemId: str | None
    startTime: str
    statementHash: str | None

@dataclass
class DedupPlan:
    links: list[tuple[str, str]]  # (duplicate problem id, canonical problem id)
    reviews: list[list[DedupProblem]]  # same name and start time, but the statements differ: a human decides

def isComparable(problem: DedupProblem) -> bool:
    return problem.statementHash is not None and (
        problem.stageStatus in STAGE_RANK or problem.stageStatus == "DUPLICATE"
    )

def chooseCanonical(members: list[DedupProblem], candidates: list[DedupProblem]) -> DedupProblem:
    # Keep the canonical that existing duplicates already point at, so reruns are stable.
    candidatesById = {candidate.id: candidate for candidate in candidates}
    for member in members:
        if member.stageStatus == "DUPLICATE" and member.canonicalProblemId in candidatesById:
            return candidatesById[member.canonicalProblemId]
    return min(candidates, key=lambda c: (-STAGE_RANK[c.stageStatus], c.contestId, c.id))

def planLinks(sameStatement: list[DedupProblem]) -> list[tuple[str, str]]:
    # Problems already marked DUPLICATE are never canonical and never re-linked.
    candidates = [member for member in sameStatement if member.stageStatus != "DUPLICATE"]
    if len(sameStatement) < 2 or not candidates:
        return []
    canonical = chooseCanonical(sameStatement, candidates)
    return [(candidate.id, canonical.id) for candidate in candidates if candidate.id != canonical.id]

def planDedup(problems: list[DedupProblem]) -> DedupPlan:
    """
    Candidates share a normalized name and a contest start time (Div1/Div2 rounds run together).
    Candidates with an identical statement hash are linked; candidates whose hashes differ are
    reported for review and never auto-merged.
    """
    groups: dict[tuple[str, str], list[DedupProblem]] = {}
    for problem in problems:
        if isComparable(problem):
            key = (normalizeText(problem.name).casefold(), problem.startTime)
            groups.setdefault(key, []).append(problem)

    links: list[tuple[str, str]] = []
    reviews: list[list[DedupProblem]] = []

    for members in groups.values():
        if len(members) < 2:
            continue

        byHash: dict[str, list[DedupProblem]] = {}
        for member in members:
            byHash.setdefault(member.statementHash, []).append(member)

        if len(byHash) > 1:
            reviews.append(sorted(members, key=lambda m: (m.contestId, m.id)))

        for sameStatement in byHash.values():
            links.extend(planLinks(sameStatement))

    return DedupPlan(links=sorted(links), reviews=sorted(reviews, key=lambda group: group[0].id))
