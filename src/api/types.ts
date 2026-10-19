export interface ApiRequest {
  method: string
  path: string // the URL path without the query string
  ip: string
  client?: string // a short label of the calling app (see middlewares/clientLabel.ts)
}

export interface ApiResponse {
  status: number
  headers: Record<string, string>
  body: string
}

// One row of the public_hints view (migrations/004): one hint of one requested problem.
export interface HintRow {
  problem_id: string
  contest_id: number
  index: string
  name: string
  rating: number | null
  tags: string[] | null
  hints_problem_id: string // the problem that holds the hints (the canonical one, for a duplicate)
  hint_level: number
  content: string
  grounded_in_tutorial: boolean
  generated_at: string
}

export interface HintsRepository {
  findHints(contestId: number, index: string): Promise<HintRow[]>
}
