import { supabaseAdmin } from './supabase.ts';
import { readContestsID } from '../../utils/read_IGNORE_THESE_CONTESTS_file.ts';

export async function deleteIgnoredContests() {
  const ignoredContestIds = await readContestsID();

  if (ignoredContestIds.length === 0) {
    console.log('No contest IDs found in ignore file.');
    return;
  }

  console.log(`Processing removal check for ignored contests:`, ignoredContestIds);

  // Fetch contests that exist in DB from the ignored list
  const { data: existingContests, error: contestFetchError } = await supabaseAdmin
    .from('contests')
    .select('id, name')
    .in('id', ignoredContestIds);

  if (contestFetchError) {
    console.error('Error fetching target contests:', contestFetchError.message);
    return;
  }

  if (!existingContests || existingContests.length === 0) {
    console.log('None of the ignored contests currently exist in the database.');
    return;
  }

  // Check each contest to ensure no problems are associated with it before deleting
  const contestsToDelete: number[] = [];

  for (const contest of existingContests) {
    const { count, error: problemCheckError } = await supabaseAdmin
      .from('problems')
      .select('id', { count: 'exact', head: true })
      .eq('contest_id', contest.id);

    if (problemCheckError) {
      console.error(`Error checking problems for contest ID ${contest.id}:`, problemCheckError.message);
      continue;
    }

    if (count !== null && count > 0) {
      console.warn(`Skipping deletion for Contest ID ${contest.id} ("${contest.name}"): ${count} problem(s) still exist under it.`);
    } else {
      contestsToDelete.push(contest.id);
    }
  }

  if (contestsToDelete.length === 0) {
    console.log('No contests eligible for deletion (all targets still have linked problems or do not exist).');
    return;
  }

  const { error: deleteContestsError } = await supabaseAdmin
    .from('contests')
    .delete()
    .in('id', contestsToDelete);

  if (deleteContestsError) {
    console.error('Error deleting contests:', deleteContestsError.message);
  } else {
    console.log(`Successfully deleted ${contestsToDelete.length} contest(s):`, contestsToDelete);
  }
}