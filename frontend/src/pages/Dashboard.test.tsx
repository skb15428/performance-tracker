import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { api } from '../lib/api'
import type { WeekDay } from '../lib/types'
import { WeekStrip } from './Dashboard'

vi.mock('../lib/api', () => ({ api: vi.fn() }))
const mocked = vi.mocked(api)

const day = (date: string, extra: Partial<WeekDay>): WeekDay => ({
  date,
  state: 'upcoming',
  is_today: false,
  minutes: 0,
  planned_minutes: 120,
  day_type: null,
  goal_day_types: {},
  usual: true,
  ...extra,
})

const week = [
  day('2026-11-02', { state: 'done', minutes: 240 }),
  day('2026-11-03', { state: 'covered' }),
  day('2026-11-04', { state: 'rest', day_type: 'rest' }),
  day('2026-11-08', { state: 'rest', usual: false, planned_minutes: 0 }),
]
const nextWeek = [day('2026-11-09', {})]

function show(goals = [{ id: 1, title: 'Career' }]) {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>
        <WeekStrip week={week} nextWeek={nextWeek} goals={goals} />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

const tap = (name: RegExp) => userEvent.click(screen.getByRole('button', { name }))

describe('WeekStrip', () => {
  beforeEach(() => mocked.mockReset().mockResolvedValue({} as never))
  afterEach(cleanup)

  it('says what each day was, not just by colour', () => {
    show()
    expect(screen.getByText('4h')).toBeTruthy()
    expect(screen.getByText('Fine')).toBeTruthy()
    expect(screen.getAllByText('Rest')).toHaveLength(2)
  })

  it('turns a working day into a rest day', async () => {
    show()
    await tap(/Tuesday.*Covered/)
    await tap(/Make it a rest day/)
    await waitFor(() => expect(mocked).toHaveBeenCalledWith('/entries/2026-11-03/type', { method: 'PUT', json: { day_type: 'rest' } }))
  })

  it('turns a rest day into a work day, and undoes a marked one', async () => {
    show()
    await tap(/Sunday.*Rest/)
    expect(screen.getByRole('button', { name: 'Make it a work day' })).toBeTruthy()
    await tap(/Wednesday.*Rest/)
    await tap(/Back to normal/)
    await waitFor(() => expect(mocked).toHaveBeenCalledWith('/entries/2026-11-04/type', { method: 'PUT', json: { day_type: null } }))
  })

  it('rests one goal at a time when there are several', async () => {
    show([{ id: 1, title: 'Career' }, { id: 2, title: 'Fitness' }])
    await tap(/Tuesday.*Covered/)
    await tap(/Rest Fitness only/)
    await waitFor(() => expect(mocked).toHaveBeenCalledWith('/entries/2026-11-03/type', { method: 'PUT', json: { day_type: 'rest', goal_id: 2 } }))
  })

  it('plans next week ahead of time', async () => {
    show()
    await tap(/^Next week$/)
    await tap(/Monday.*Planned/)
    await tap(/Make it a rest day/)
    await waitFor(() => expect(mocked).toHaveBeenCalledWith('/entries/2026-11-09/type', { method: 'PUT', json: { day_type: 'rest' } }))
  })
})
