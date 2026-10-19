from dataclasses import dataclass

# Bump when SYSTEM_PROMPT or the layout of the user prompt changes; it is stored with every hint.
PROMPT_VERSION = "v2"

SYSTEM_PROMPT = """You write progressive hints for Codeforces problems, for a student who is stuck and wants the smallest nudge that unblocks them. You are given a problem and, sometimes, its official editorial.

First decide how many hints the problem needs, from 2 to 5, and use as few as the solution allows: a problem with one short idea needs 2 hints, a problem with several distinct steps needs more. As a guideline by rating: up to about 1000 -> 2 hints, 1000 to 1500 -> 3, 1500 to 2000 -> 4, above 2000 -> 5. Adjust by one when the statement and editorial show the problem is clearly simpler or harder than its rating suggests. If the problem is unrated, judge its difficulty yourself.

Number the hints 1 to N. Each reveals more than the one before, so a reader who stops at hint k must not be spoiled beyond hint k.
- Hint 1 is always one mathematical observation or constraint bottleneck (what the limits imply, an invariant, a special case worth examining).
- The last hint (number N) is always the complete solution explained step by step in prose, enough to implement it without further thought.
- Hints in between move from the key idea toward the details. When N is 3 or more, hint 2 gives the central lemma or approach in plain words. From hint 3 on, the hint may name the algorithm or data structure that fits, and give edge cases, the exact recurrence or invariant, and the time and space complexity needed to fit the limits.
- Do not name any algorithm, technique or data structure in hints 1 and 2, unless that hint is the last one. This is checked automatically, and naming one gets your answer rejected. Say what to notice, not what to use, before hint 3.

Rules:
- Never write code, pseudocode or fenced code blocks. Short formulas are fine.
- Write math in LaTeX between single dollar signs, like $a_i \\le 10^9$. Use Markdown for emphasis and lists.
- Be correct above all. If an editorial is provided, base the hints on it and do not contradict it. If there is none, solve the problem carefully yourself and keep every hint to what you are sure of; do not invent claims.
- The tags are for your reference only. Do not reveal a tag's technique before hint 3.
- Reply with JSON only, in this shape: {"hints": [{"level": 1, "text": "..."}, ...]}, with between 2 and 5 hints."""

# A standard JSON Schema, accepted as it is by Claude's structured outputs (hence additionalProperties: false and no
# count limits: the 2-5 count is checked by the validator). The Gemini client converts it to Gemini's dialect.
RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "hints": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "level": {"type": "integer"},
                    "text": {"type": "string"},
                },
                "required": ["level", "text"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["hints"],
    "additionalProperties": False,
}

@dataclass(frozen=True)
class ProblemForHints:
    id: str
    name: str
    rating: int | None
    tags: list[str]
    timeLimitMs: int
    memoryLimitMb: int
    statementText: str
    inputSpecification: str
    outputSpecification: str | None
    interactionSpecification: str | None
    notes: str | None
    samples: list[tuple[str, str]]   # (input, output)
    tutorialText: str | None

def formatSeconds(timeLimitMs: int) -> str:
    seconds = timeLimitMs / 1000
    return f"{seconds:g} {'second' if seconds == 1 else 'seconds'}"

def buildUserPrompt(problem: ProblemForHints, feedback: str | None = None) -> str:
    # The stored sections already start with their own title line ("Input", "Output", "Interaction", "Note").
    sections = [
        f"# Problem {problem.id}: {problem.name}",
        f"Rating: {problem.rating if problem.rating is not None else 'unrated'} | "
        f"Time limit: {formatSeconds(problem.timeLimitMs)} | Memory limit: {problem.memoryLimitMb} MB",
        f"Tags (for your reference only, do not reveal before level 3): {', '.join(problem.tags) or 'none'}",
        "## Statement",
        problem.statementText,
        problem.inputSpecification,
    ]
    for optional in (problem.outputSpecification, problem.interactionSpecification, problem.notes):
        if optional:
            sections.append(optional)

    sections.append("## Sample tests")
    for number, (sampleInput, sampleOutput) in enumerate(problem.samples, start=1):
        sections.append(f"### Sample {number}\nInput:\n```\n{sampleInput}\n```\nOutput:\n```\n{sampleOutput}\n```")

    sections.append("## Official editorial")
    sections.append(
        problem.tutorialText
        if problem.tutorialText
        else "No official editorial is available. Solve the problem yourself, carefully."
    )

    prompt = "\n\n".join(sections)
    if feedback:
        prompt += f"\n\n---\nYour previous answer was rejected: {feedback}\nWrite the hints again and fix this."
    return prompt
