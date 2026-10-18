import { createClient } from '@supabase/supabase-js'
import type { HintRow, HintsRepository } from '../types.ts'

const COLUMNS = 'problem_id, contest_id, index, name, rating, tags, hints_problem_id, hint_level, content, grounded_in_tutorial, generated_at'

// Reads only the public_hints view (migrations/004): the spoiler gate lives in the database, so this code
// cannot read hints of a contest that is still running even if it tried.
export function createSupabaseHintsRepository(url: string, publishableKey: string, fetchImpl?: typeof fetch): HintsRepository {
  const client = createClient(url, publishableKey, {
    auth: { persistSession: false, autoRefreshToken: false, detectSessionInUrl: false },
    global: fetchImpl ? { fetch: fetchImpl } : {},
  })

  return {
    async findHints(contestId: number, index: string): Promise<HintRow[]> {
      const { data, error } = await client
        .from('public_hints')
        .select(COLUMNS)
        .eq('contest_id', contestId)
        .eq('index', index)
        .order('hint_level', { ascending: true })
      if (error) throw new Error(error.message)
      return (data ?? []) as HintRow[]
    },
  }
}
