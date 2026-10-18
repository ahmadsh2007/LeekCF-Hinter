import json
import re
from dataclasses import dataclass

HINT_COUNT = 5
EARLY_LEVELS = (1, 2)  # may only describe observations, never name a technique
MIN_HINT_CHARS = 20
MAX_HINT_CHARS = 4000

# Names of algorithms and data structures that must not appear before hint 3. Multi-word terms also match their
# plural and a hyphen for a space ("two-pointers"). Single words stay exact so ordinary words ("tries") are safe.
EARLY_FORBIDDEN_TERMS = (
    "dynamic programming", "dp", "greedy", "binary search", "ternary search", "two pointer", "sliding window",
    "dsu", "union find", "disjoint set", "segment tree", "fenwick", "binary indexed tree", "sparse table",
    "bfs", "dfs", "breadth first", "depth first", "dijkstra", "bellman ford", "floyd warshall", "kruskal",
    "topological sort", "trie", "hashing", "sqrt decomposition", "bitmask", "meet in the middle",
    "divide and conquer", "prefix sum", "priority queue", "convex hull", "fft", "kmp", "z function",
    "manacher", "lca", "sieve", "matrix exponentiation", "inclusion exclusion", "monotonic stack",
    "monotone stack", "mo's algorithm", "heavy light", "centroid decomposition", "max flow", "min cost flow",
    "bipartite matching", "2-sat", "knapsack",
)

def termPattern(term: str) -> str:
    words = [re.escape(word) for word in re.split(r"[ -]+", term)]
    pattern = r"[\s-]+".join(words)
    return pattern + ("s?" if len(words) > 1 else "")

EARLY_FORBIDDEN = re.compile(
    r"(?<![A-Za-z0-9])(?:" + "|".join(termPattern(term) for term in EARLY_FORBIDDEN_TERMS) + r")(?![A-Za-z0-9])",
    re.IGNORECASE,
)

@dataclass(frozen=True)
class Hint:
    level: int
    content: str

class HintValidationError(ValueError):
    """The model's answer is unusable. The message is fed back to the model when the generator retries."""

def isRealInt(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)

def validateHints(raw: str) -> list[Hint]:
    try:
        data = json.loads(raw)
    except (TypeError, ValueError) as e:
        raise HintValidationError(f"The answer is not valid JSON ({e}).") from e

    if not isinstance(data, dict) or not isinstance(data.get("hints"), list):
        raise HintValidationError('The answer must be a JSON object with a "hints" list.')

    entries = data["hints"]
    if len(entries) != HINT_COUNT:
        raise HintValidationError(f"The answer must contain exactly {HINT_COUNT} hints, found {len(entries)}.")

    levels = [entry.get("level") if isinstance(entry, dict) else None for entry in entries]
    if not all(isRealInt(level) for level in levels) or sorted(levels) != list(range(1, HINT_COUNT + 1)):
        raise HintValidationError(f"The hints must be numbered with the levels 1 to {HINT_COUNT}, each used once.")

    hints = []
    for entry in sorted(entries, key=lambda item: item["level"]):
        level, content = entry["level"], entry.get("text")
        if not isinstance(content, str) or not content.strip():
            raise HintValidationError(f"Hint {level} has no text.")
        content = content.strip()
        if len(content) < MIN_HINT_CHARS:
            raise HintValidationError(f"Hint {level} is too short ({len(content)} characters).")
        if len(content) > MAX_HINT_CHARS:
            raise HintValidationError(f"Hint {level} is too long ({len(content)} characters, at most {MAX_HINT_CHARS}).")
        if "```" in content:
            raise HintValidationError(f"Hint {level} contains a code block; hints must not contain code.")
        if level in EARLY_LEVELS:
            found = EARLY_FORBIDDEN.search(content)
            if found:
                raise HintValidationError(
                    f"Hint {level} mentions '{found.group(0).lower()}', but no algorithm or data structure "
                    "may be named before hint 3. Describe the observation without naming the technique."
                )
        hints.append(Hint(level=level, content=content))
    return hints
