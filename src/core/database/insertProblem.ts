import { supabaseAdmin } from './supabase.ts'
import { getProblemList } from '../../services/codeforces/getProblemList.ts'
import { text } from 'node:stream/consumers';
import { fetchCodeforcesApi } from '../../services/codeforces/fetchCodeforcesApi.ts';
import './insertContest.ts'

const problemList = await getProblemList();

const includeQuestions = false;

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

const dataToInsert = problemList
  .filter((problem: CodeforcesProblem) => {
    if (problem.type === 'QUESTION' && !includeQuestions) {
      return false;
    }
    return true; 
  })
  .map((problem: CodeforcesProblem) => ({
    id: `${problem.contestId}_${problem.index}`,
    contest_id: problem.contestId,
    index: problem.index,
    name: problem.name,
    rating: (problem.rating ?? -1),
    tags: problem.tags,
    stage_status: 'DISCOVERED',
    created_at: now,
    updated_at: now
  }));

if (dataToInsert.length > 0) {
  const { error } = await supabaseAdmin
    .from('problems')
    .upsert(dataToInsert, { onConflict: 'id' });

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