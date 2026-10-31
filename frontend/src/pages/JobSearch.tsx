import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Badge, Button, Card, EmptyState, ErrorText, Input, Label, Loading, PageHeader, Select } from '../components/ui'
import type { Tone } from '../components/ui'
import { api } from '../lib/api'
import { prettyDate } from '../lib/dates'
import type { Application, JobStage } from '../lib/types'

const STAGES: { id: JobStage; label: string; tone: Tone }[] = [
  { id: 'saved', label: 'Saved', tone: 'zinc' },
  { id: 'applied', label: 'Applied', tone: 'brand' },
  { id: 'screen', label: 'Screen', tone: 'brand' },
  { id: 'technical', label: 'Technical', tone: 'amber' },
  { id: 'final', label: 'Final round', tone: 'amber' },
  { id: 'offer', label: 'Offer', tone: 'green' },
  { id: 'rejected', label: 'Rejected', tone: 'red' },
  { id: 'withdrawn', label: 'Withdrawn', tone: 'zinc' },
]
const stage = (id: JobStage) => STAGES.find((s) => s.id === id) ?? STAGES[0]

function Row({ job }: { job: Application }) {
  const qc = useQueryClient()
  const refresh = () => qc.invalidateQueries()
  const update = useMutation({ mutationFn: (json: Partial<Application>) => api(`/applications/${job.id}`, { method: 'PATCH', json }), onSuccess: refresh })
  const remove = useMutation({ mutationFn: () => api(`/applications/${job.id}`, { method: 'DELETE' }), onSuccess: refresh })
  const [next, setNext] = useState(job.next_step)
  return (
    <li className="rounded-3xl border border-line bg-surface p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="font-display text-2xl leading-tight">{job.url ? <a href={job.url} target="_blank" rel="noreferrer" className="hover:text-accent-ink">{job.company} ↗</a> : job.company}</p>
          <p className="mt-1 text-sm text-muted">
            {[job.role, job.referral && `Referral: ${job.referral}`, job.applied_on && `Applied ${prettyDate(job.applied_on)}`].filter(Boolean).join(' · ') || 'Not applied yet'}
          </p>
        </div>
        <Badge tone={stage(job.stage).tone}>{stage(job.stage).label}</Badge>
      </div>
      <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-[10rem_minmax(0,1fr)]">
        <Select aria-label={`Stage for ${job.company}`} value={job.stage} onChange={(e) => update.mutate({ stage: e.target.value as JobStage })}>
          {STAGES.map((s) => (
            <option key={s.id} value={s.id}>
              {s.label}
            </option>
          ))}
        </Select>
        <Input aria-label={`Next step for ${job.company}`} placeholder="Next step" value={next} onChange={(e) => setNext(e.target.value)} onBlur={() => next !== job.next_step && update.mutate({ next_step: next })} />
      </div>
      <button className="mt-3 text-xs text-muted hover:text-ink" onClick={() => window.confirm(`Remove ${job.company}?`) && remove.mutate()}>
        Remove
      </button>
    </li>
  )
}

export default function JobSearch() {
  const qc = useQueryClient()
  const { data: jobs, isLoading } = useQuery({ queryKey: ['applications'], queryFn: () => api<Application[]>('/applications') })
  const blank = { company: '', role: '', url: '', referral: '', stage: 'applied' as JobStage }
  const [form, setForm] = useState(blank)
  const add = useMutation({
    mutationFn: () => api('/applications', { method: 'POST', json: form }),
    onSuccess: () => {
      setForm(blank)
      qc.invalidateQueries()
    },
  })
  const sent = jobs?.filter((j) => j.stage !== 'saved').length ?? 0
  const finals = jobs?.filter((j) => j.reached_final).length ?? 0
  const offers = jobs?.filter((j) => j.stage === 'offer').length ?? 0
  return (
    <>
      <Link to="/goals" className="text-sm text-muted hover:text-ink">
        ← Goals
      </Link>
      <div className="mt-2">
        <PageHeader title="Job search" subtitle={`${sent} applied · ${finals} final round${finals === 1 ? '' : 's'} · ${offers} offer${offers === 1 ? '' : 's'}`} />
      </div>
      <Card title="Add an application" className="mb-4">
        <form
          className="grid grid-cols-1 gap-3 sm:grid-cols-2"
          onSubmit={(e) => {
            e.preventDefault()
            add.mutate()
          }}
        >
          <label>
            <Label>Company</Label>
            <Input required value={form.company} onChange={(e) => setForm({ ...form, company: e.target.value })} />
          </label>
          <label>
            <Label>Role</Label>
            <Input value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })} />
          </label>
          <label>
            <Label>Job link</Label>
            <Input type="url" value={form.url} onChange={(e) => setForm({ ...form, url: e.target.value })} />
          </label>
          <label>
            <Label>Referral</Label>
            <Input placeholder="Who referred you?" value={form.referral} onChange={(e) => setForm({ ...form, referral: e.target.value })} />
          </label>
          <label>
            <Label>Stage</Label>
            <Select value={form.stage} onChange={(e) => setForm({ ...form, stage: e.target.value as JobStage })}>
              {STAGES.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.label}
                </option>
              ))}
            </Select>
          </label>
          <div className="flex items-end">
            <Button type="submit" loading={add.isPending}>
              Add
            </Button>
          </div>
          <div className="sm:col-span-2">
            <ErrorText error={add.error} />
          </div>
        </form>
      </Card>
      {isLoading && <Loading />}
      {jobs && jobs.length === 0 && <EmptyState title="No applications yet">Add the companies you're aiming for, even before you apply.</EmptyState>}
      <ul className="space-y-3">{jobs?.map((j) => <Row key={j.id} job={j} />)}</ul>
    </>
  )
}
