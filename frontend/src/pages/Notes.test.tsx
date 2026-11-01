import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { api } from '../lib/api'
import Notes, { NoteDetail } from './Notes'

vi.mock('../lib/api', () => ({ api: vi.fn() }))
const mermaid = vi.hoisted(() => ({ initialize: vi.fn(), parse: vi.fn(), render: vi.fn() }))
vi.mock('mermaid', () => ({ default: mermaid }))
const mocked = vi.mocked(api)

function show(path: string) {
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/notes" element={<Notes />} />
          <Route path="/notes/:id" element={<NoteDetail />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

describe('Notes', () => {
  it('searches as you type and links to the note', async () => {
    mocked.mockImplementation(async (path: string) =>
      (path.endsWith('q=') ? [{ id: 1, topic_id: 2, title: 'Attention', snippet: 'Keys', updated_at: '2026-11-01' }, { id: 2, topic_id: 3, title: 'Tokens', snippet: 'BPE', updated_at: '2026-11-01' }]
        : [{ id: 2, topic_id: 3, title: 'Tokens', snippet: 'BPE', updated_at: '2026-11-01' }]) as never,
    )
    show('/notes')
    expect(await screen.findByText('Attention')).toBeTruthy()
    await userEvent.type(screen.getByRole('searchbox'), 'bpe merges')
    await waitFor(() => expect(mocked).toHaveBeenCalledWith('/notes?q=bpe%20merges'))
    await waitFor(() => expect(screen.queryByText('Attention')).toBeNull())
    expect(screen.getByRole('link', { name: /Tokens/ }).getAttribute('href')).toBe('/notes/2')
  })

  it('says when nothing matches', async () => {
    mocked.mockResolvedValue([] as never)
    show('/notes')
    expect(await screen.findByText('No notes yet')).toBeTruthy()
    await userEvent.type(screen.getByRole('searchbox'), 'xyz')
    expect(await screen.findByText('Nothing found')).toBeTruthy()
  })

  const note = (content: string) => ({ id: 1, topic_id: 2, title: 'Attention', updated_at: '2026-11-01T10:00:00Z', content })

  it('draws Mermaid diagrams', async () => {
    window.matchMedia = vi.fn().mockReturnValue({ matches: false })
    mermaid.parse.mockResolvedValue(true)
    mermaid.render.mockResolvedValue({ svg: '<svg data-testid="drawn"></svg>' })
    mocked.mockResolvedValue(note('```mermaid\ngraph TD; A-->B\n```') as never)
    show('/notes/1')
    expect(await screen.findByTestId('drawn')).toBeTruthy()
    expect(mermaid.render.mock.calls[0][1]).toBe('graph TD; A-->B')
  })

  it('shows the code when a diagram is broken', async () => {
    window.matchMedia = vi.fn().mockReturnValue({ matches: false })
    mermaid.parse.mockRejectedValue(new Error('bad'))
    mocked.mockResolvedValue(note('```mermaid\nnot a diagram\n```') as never)
    show('/notes/1')
    expect((await screen.findByText('not a diagram')).tagName).toBe('CODE')
  })

  it('shows Markdown with headings, code and tables, and no raw HTML', async () => {
    mocked.mockResolvedValue({
      id: 1, topic_id: 2, title: 'Attention', updated_at: '2026-11-01T10:00:00Z',
      content: '## Why\n\n```python\nprint("hi")\n```\n\n| A | B |\n|---|---|\n| 1 | 2 |\n\n<img src=x onerror=alert(1)>',
    } as never)
    show('/notes/1')
    expect((await screen.findByRole('heading', { name: 'Why' })).tagName).toBe('H2')
    expect(screen.getByText('print("hi")').tagName).toBe('CODE')
    expect(screen.getByRole('table')).toBeTruthy()
    expect(document.querySelector('.note-body img')).toBeNull()
  })
})
