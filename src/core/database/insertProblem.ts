import { supabaseAdmin } from './supabase.ts'
import { getProblemList } from '../../services/codeforces/getProblemList.ts'
import { text } from 'node:stream/consumers';
import { fetchCodeforcesApi } from '../../services/codeforces/fetchCodeforcesApi.ts';
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

const existingStatuses = new Map<string, string>();
if (updateExistingMetadata) {
  const { data } = await supabaseAdmin.from('problems').select('id, stage_status');
  data?.forEach(p => existingStatuses.set(p.id, p.stage_status));
}

const dataToInsert = problemList
  .filter((problem: CodeforcesProblem) => {
    if (ignoredIds.has(problem.contestId)) {
      console.log(`Skipping ignored problem from Contest ID: ${problem.contestId}`);
      return false;
    }
    if (problem.type === 'QUESTION' && !includeQuestions) {
      return false;
    }
    return true; 
  })
  .map((problem: CodeforcesProblem) => {
    const id = `${problem.contestId}_${problem.index}`;
    return {
      id,
      contest_id: problem.contestId,
      index: problem.index,
      name: problem.name,
      rating: (problem.rating ?? -1),
      tags: problem.tags,
      stage_status: existingStatuses.get(id) ?? 'DISCOVERED',
      created_at: now,
      updated_at: now
    };
  });

if (dataToInsert.length > 0) {
  const { error } = await supabaseAdmin
    .from('problems')
    .upsert(dataToInsert, {
      onConflict: 'id',
      ignoreDuplicates: true
    });

  if (error) {
    console.error('Error upserting problems:', error);
  }
  else {
    console.log(`Successfully synced ${dataToInsert.length} problems!`);
  }
}
else {
  // console.log('No problems matched your filters.');
}