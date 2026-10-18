export interface CodeforcesProblem {
  contestId: number;
  index: string;
  name: string;
  rating?: number;
  type: 'PROGRAMMING' | 'QUESTION';
  tags: string[];
}

// stage_status and created_at are deliberately absent: an upsert only touches the columns it sends,
// so existing rows keep their pipeline state and new rows get the database defaults.
export function toProblemRow(problem: CodeforcesProblem, now: string) {
  return {
    id: `${problem.contestId}_${problem.index}`,
    contest_id: problem.contestId,
    index: problem.index,
    name: problem.name,
    rating: problem.rating ?? null,
    tags: problem.tags,
    updated_at: now,
  };
}
