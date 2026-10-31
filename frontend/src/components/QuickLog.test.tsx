import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { api } from '../lib/api'
import QuickLog from './QuickLog'

vi.mock('../lib/api', () => ({ api: vi.fn() }))
const mocked = vi.mocked(api)

function show() {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <QuickLog day="2026-11-02" goals={[{ id: 7, title: 'Senior AI Engineer' }]} />
    </QueryClientProvider>,
  )
}

describe('QuickLog', () => {
  beforeEach(() => {
    mocked.mockReset()
    mocked.mockImplementation(async (path: string) => (path.startsWith('/goals/') ? { phases: [] } : []) as never)
  })
  afterEach(cleanup)

  it('adds the chosen time to the day', async () => {
    show()
    await userEvent.click(screen.getByRole('button', { name: 'Add time' }))
    await userEvent.click(screen.getByRole('button', { name: '2h' }))
    await userEvent.click(screen.getByRole('button', { name: 'Add 2h' }))
    await waitFor(() =>
      expect(mocked).toHaveBeenCalledWith('/time-logs', {
        method: 'POST',
        json: { day: '2026-11-02', goal_id: 7, minutes: 120, roadmap_item_id: null, note: '' },
      }),
    )
  })

  it('shows what is already logged, and only your own entries can be removed here', async () => {
    mocked.mockImplementation(async () =>
      [
        { id: 1, minutes: 30, note: 'Reading', source: 'manual' },
        { id: 2, minutes: 60, note: 'Block', source: 'block' },
      ] as never,
    )
    show()
    expect(await screen.findByText(/1h 30m added/)).toBeTruthy()
    expect(screen.getAllByRole('button', { name: 'Remove this time' })).toHaveLength(1)
  })

  it('stays out of the way with no goals', () => {
    render(
      <QueryClientProvider client={new QueryClient()}>
        <QuickLog day="2026-11-02" goals={[]} />
      </QueryClientProvider>,
    )
    expect(screen.queryByText('Log time')).toBeNull()
  })
})
