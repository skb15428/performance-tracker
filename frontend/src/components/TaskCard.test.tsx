import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { api } from '../lib/api'
import TaskCard, { type TaskBlock } from './TaskCard'

vi.mock('../lib/api', () => ({ api: vi.fn() }))
const mocked = vi.mocked(api)

const block: TaskBlock = {
  id: 5,
  title: 'Tokenization',
  time_block: '09:00-11:00',
  minutes: 120,
  status: 'open',
  done_minutes: null,
  details: { topic_id: 3, steps: [{ text: 'Learn', minutes: 120 }], done_when: 'You pass' },
}

function show(b: TaskBlock) {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>
        <TaskCard block={b} />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('TaskCard', () => {
  beforeEach(() => mocked.mockReset().mockResolvedValue({} as never))
  afterEach(cleanup)

  it('marks a block done', async () => {
    show(block)
    await userEvent.click(screen.getByRole('button', { name: '✓ Mark done' }))
    await waitFor(() => expect(mocked).toHaveBeenCalledWith('/plan/5', { method: 'PATCH', json: { status: 'done' } }))
  })

  it("links to the block's study topic", () => {
    show(block)
    expect(screen.getByRole('link', { name: 'Open topic' }).getAttribute('href')).toBe('/study/3')
  })

  it('offers undo once it is done', () => {
    show({ ...block, status: 'done' })
    expect(screen.getByRole('button', { name: 'Undo' })).toBeTruthy()
    expect(screen.queryByRole('button', { name: '✓ Mark done' })).toBeNull()
  })
})
