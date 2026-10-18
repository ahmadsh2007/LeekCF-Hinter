import type { HintRow } from '../types.ts'

export interface HintsPayload {
  problem: { id: string; contestId: number; index: string; name: string; rating: number | null; tags: string[] }
  duplicateOf: string | null
  hints: Array<{ level: number; content: string }>
  groundedInTutorial: boolean
  generatedAt: string
}

// Rows of the public_hints view for one problem -> the JSON the public sees. Statements and editorials are
// deliberately absent: the API serves hints and basic metadata only.
export function toHintsPayload(rows: HintRow[]): HintsPayload | null {
  if (rows.length === 0) return null

  const first = rows[0]
  const newest = rows.reduce((a, b) => (Date.parse(b.generated_at) > Date.parse(a.generated_at) ? b : a))

  return {
    problem: {
      id: first.problem_id,
      contestId: first.contest_id,
      index: first.index,
      name: first.name,
      rating: first.rating,
      tags: first.tags ?? [],
    },
    duplicateOf: first.hints_problem_id === first.problem_id ? null : first.hints_problem_id,
    hints: rows
      .map((row) => ({ level: row.hint_level, content: row.content }))
      .sort((a, b) => a.level - b.level),
    groundedInTutorial: rows.every((row) => row.grounded_in_tutorial),
    generatedAt: newest.generated_at,
  }
}
