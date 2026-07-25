import { supabaseAdmin } from './supabase.ts';
import { readContestsID } from '../../utils/read_IGNORE_THESE_CONTESTS_file.ts';
import { deleteIgnoredContests } from './deleteContest.ts';

export async function deleteProblemsFromIgnoredContests() {
  const ignoredContestIds = await readContestsID();

  if (ignoredContestIds.length === 0) {
    console.log('No contest IDs found in ignore file.');
    return;
  }

  console.log(`Checking database for problems belonging to ignored contests:`, ignoredContestIds);

  // Fetch all problem IDs that belong to the ignored contest IDs
  const { data: problemsToDelete, error: fetchError } = await supabaseAdmin
    .from('problems')
    .select('id')
    .in('contest_id', ignoredContestIds);

  if (fetchError) {
    console.error('Error fetching problems to delete:', fetchError.message);
    return;
  }

  if (!problemsToDelete || problemsToDelete.length === 0) {
    console.log('No problems found under the specified ignored contest IDs.');
  } else {
    const problemIds = problemsToDelete.map((p) => p.id);
    console.log(`Found ${problemIds.length} problem(s) to remove. Cleaning up child records...`);

    // Cascade cleanup across related problem tables
    const { error: samplesError } = await supabaseAdmin
      .from('sample_tests')
      .delete()
      .in('problem_id', problemIds);

    if (samplesError) console.error('Error deleting sample tests:', samplesError.message);

    const { error: specsError } = await supabaseAdmin
      .from('problem_specifications')
      .delete()
      .in('problem_id', problemIds);

    if (specsError) console.error('Error deleting problem specifications:', specsError.message);

    const { error: interactiveSpecsError } = await supabaseAdmin
      .from('interactive_problem_specifications')
      .delete()
      .in('problem_id', problemIds);

    if (interactiveSpecsError) console.error('Error deleting interactive problem specifications:', interactiveSpecsError.message);

    // Delete the parent records from the problems table
    const { error: deleteProblemsError } = await supabaseAdmin
      .from('problems')
      .delete()
      .in('id', problemIds);

    if (deleteProblemsError) {
      console.error('Error deleting problems:', deleteProblemsError.message);
      return;
    } else {
      console.log(`Successfully deleted ${problemIds.length} problem(s) and all linked details!`);
    }
  }

  console.log('\n--- Running contest deletion cleanup ---');
  await deleteIgnoredContests();
}

await deleteProblemsFromIgnoredContests();