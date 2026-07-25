import { supabaseAdmin } from './supabase.ts'
import { getContestList } from '../../services/codeforces/getContestList.ts'
import { text } from 'node:stream/consumers';
import { fetchCodeforcesApi } from '../../services/codeforces/fetchCodeforcesApi.ts';
import { readContestsID } from '../../utils/read_IGNORE_THESE_CONTESTS_file.ts'

// Set to true if you want to include 'BEFORE' or 'CODING' contests, false to skip them
const includeBefore = false;
const includeCoding = false;

const contestList = await getContestList();
const ignoredIds = new Set(await readContestsID());
interface CodeforcesContest {
  id: number;
  name: string;
  type: 'CF' | 'IOI' | 'ICPC';
  phase: 'BEFORE' | 'CODING' | 'PENDING_SYSTEM_TEST' | 'SYSTEM_TEST' | 'FINISHED';
  startTimeSeconds?: number; // Optional in API if contest is still draft
  durationSeconds: number;
}

const dataToInsert = contestList
  .filter((contest: CodeforcesContest) => {
    if (ignoredIds.has(contest.id)) {
      console.log(`Skipping ignored contest ID: ${contest.id} (${contest.name})`);
      return false;
    }
    if (contest.phase === 'BEFORE' && !includeBefore) {
      return false;
    }
    if (contest.phase === 'CODING' && !includeCoding) {
      return false;
    }
    return true; 
  })
  .map((contest: CodeforcesContest) => ({
    id: contest.id,
    name: contest.name,
    type: contest.type,
    phase: contest.phase,
    start_time: new Date((contest.startTimeSeconds ?? 0) * 1000).toISOString(),
    duration_seconds: contest.durationSeconds,
  }));

if (dataToInsert.length > 0) {
  const { error } = await supabaseAdmin
    .from('contests')
    .upsert(dataToInsert, { onConflict: 'id' });

  if (error) {
    console.error('Error upserting contests:', error);
  }
  else {
    console.log(`Successfully synced ${dataToInsert.length} contests!`);
  }
}
else {
  // console.log('No contests matched your filters.');
}