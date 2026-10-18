import { test } from 'node:test'
import assert from 'node:assert/strict'
import { toProblemRow } from '../src/utils/toProblemRow.ts'

const problem = {
  contestId: 1800,
  index: 'A',
  name: 'Fancy Fence',
  rating: 1500,
  type: 'PROGRAMMING' as const,
  tags: ['dp', 'greedy'],
}

const now = '2026-10-18T12:00:00.000Z'

test('maps a Codeforces problem to a database row', () => {
  assert.deepEqual(toProblemRow(problem, now), {
    id: '1800_A',
    contest_id: 1800,
    index: 'A',
    name: 'Fancy Fence',
    rating: 1500,
    tags: ['dp', 'greedy'],
    updated_at: now,
  })
})

test('an unrated problem has a null rating, not -1', () => {
  const { rating, ...unrated } = problem
  assert.equal(toProblemRow(unrated, now).rating, null)
})

test('the row never carries stage_status or created_at, so an upsert cannot reset them', () => {
  const columns = Object.keys(toProblemRow(problem, now)).sort()
  assert.deepEqual(columns, ['contest_id', 'id', 'index', 'name', 'rating', 'tags', 'updated_at'])
})

test('ids combine contest id and index, including multi-character indexes', () => {
  assert.equal(toProblemRow({ ...problem, contestId: 1902, index: 'B1' }, now).id, '1902_B1')
})
