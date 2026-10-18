from dataclasses import dataclass

# Bump when SYSTEM_PROMPT or the layout of the user prompt changes; it is stored with every hint.
PROMPT_VERSION = "v1"

SYSTEM_PROMPT = """You write progressive hints for Codeforces problems, for a student who is stuck and wants the smallest nudge that unblocks them. You are given a problem and, sometimes, its official editorial.

Write exactly 5 hints. Each hint reveals more than the one before, so a reader who stops at hint N must not be spoiled beyond level N.

Level 1 - Observation: one mathematical observation or constraint bottleneck (what the limits imply, an invariant, a special case worth examining). Do not name any algorithm, technique or data structure.
Level 2 - Key idea: the central lemma or approach in plain words (what to count, what to reduce the problem to). Still do not name any algorithm, technique or data structure.
Level 3 - Technique: now name the algorithm or data structure that fits, and say how it applies.
Level 4 - Details: edge cases, the exact recurrence or invariant, and the time and space complexity needed to fit the limits.
Level 5 - Walkthrough: the complete solution explained step by step in prose, enough to implement it without further thought.

Rules:
- Never write code, pseudocode or fenced code blocks. Short formulas are fine.
- Write math in LaTeX between single dollar signs, like $a_i \\le 10^9$. Use Markdown for emphasis and lists.
- Be correct above all. If an editorial is provided, base the hints on it and do not contradict it. If there is none, solve the problem carefully yourself and keep every hint to what you are sure of; do not invent claims.
- Hints 1 and 2 are checked automatically for algorithm and data-structure names; naming one gets your answer rejected.
- The tags are for your reference only. Do not reveal a tag's technique before level 3.
- Reply with JSON only, in this shape: {"hints": [{"level": 1, "text": "..."}, ...]}."""

# Gemini's responseSchema dialect (OpenAPI subset, upper-case type names).
RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "hints": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "level": {"type": "INTEGER"},
                    "text": {"type": "STRING"},
                },
                "required": ["level", "text"],
            },
        },
    },
    "required": ["hints"],
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
        prompt += f"\n\n---\nYour previous answer was rejected: {feedback}\nWrite all 5 hints again and fix this."
    return prompt
