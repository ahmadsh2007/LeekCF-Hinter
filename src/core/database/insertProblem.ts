import { supabaseAdmin } from './supabase.ts'
import { getProblemList } from '../../services/codeforces/getProblemList.ts'
import { ignoredIds } from './insertContest.ts'
import './insertContest.ts'

const problemList = await getProblemList();

const includeQuestions = false;
const updateExistingMetadata = true;

interface CodeforcesProblem {
  id: string;
  contestId: number;
  index: string;
  name: string;
  rating?: number;
  type: 'PROGRAMMING' | 'QUESTION';
  tags: string[];
  stage_status: 'DISCOVERED' | 'SCRAPED_WAITING_FOR_CONTEST' |
                'WAITING_FOR_TUTORIAL' | 'TUTORIAL_FOUND' |
                'HINTS_GENERATED' | 'FAILED';
  created_at: number;
  updated_at: number;
}

const now = new Date().toISOString();

const existingProblems = new Map<string, { stage_status: string; created_at: string }>();
if (updateExistingMetadata) {
  const pageSize = 1000;
  let page = 0;
  let hasMore = true;

  while (hasMore) {
    const from = page * pageSize;
    const to = from + pageSize - 1;

    const { data, error } = await supabaseAdmin
      .from('problems')
      .select('id, stage_status, created_at')
      .range(from, to);

    if (error) {
      console.error('Error fetching existing problems:', error);
      break;
    }

    data?.forEach(p => existingProblems.set(p.id, {
      stage_status: p.stage_status,
      created_at: p.created_at
    }));

    if (!data || data.length < pageSize) hasMore = false;
    else page++;
  }
}

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
  .map((problem: CodeforcesProblem) => {
    const id = `${problem.contestId}_${problem.index}`;
    const existing = existingProblems.get(id);
    
    return {
      id,
      contest_id: problem.contestId,
      index: problem.index,
      name: problem.name,
      rating: (problem.rating ?? -1),
      tags: problem.tags,
      stage_status: existing?.stage_status ?? 'DISCOVERED',
      created_at: existing?.created_at ?? now,
      updated_at: now
    };
  });

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