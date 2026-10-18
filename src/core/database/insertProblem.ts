import { supabaseAdmin } from './supabase.ts'
import { getProblemList } from '../../services/codeforces/getProblemList.ts'
import { ignoredIds } from './insertContest.ts'
import './insertContest.ts'
import { toProblemRow, type CodeforcesProblem } from '../../utils/toProblemRow.ts'

const problemList = await getProblemList();

const includeQuestions = false;

const now = new Date().toISOString();

// Only metadata is sent (see toProblemRow), so re-running this never resets a problem's stage_status.
const dataToInsert = problemList
  .filter((problem: CodeforcesProblem) => {
    if (ignoredIds.has(problem.contestId)) {
      // console.log(`Skipping ignored problem from Contest ID: ${problem.contestId}`);
      return false;
    }
    if (problem.type === 'QUESTION' && !includeQuestions) return false;
    if (problem.tags?.includes('*special')) return false;
    return true;
  })
  .map((problem: CodeforcesProblem) => toProblemRow(problem, now));

const BATCH_SIZE = 500;
let totalUpserted = 0;

for (let i = 0; i < dataToInsert.length; i += BATCH_SIZE) {
  const batch = dataToInsert.slice(i, i + BATCH_SIZE);
  const { error } = await supabaseAdmin
    .from('problems')
    .upsert(batch, {
      onConflict: 'id',
      ignoreDuplicates: false
    });

  if (error) {
    console.error(`Error upserting batch ${i / BATCH_SIZE + 1}:`, error);
  } else {
    totalUpserted += batch.length;
  }
}

console.log(`Successfully synced ${totalUpserted} / ${dataToInsert.length} problems!`);
