import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import OpenClaude from '../components/OpenClaude'
import { Badge, Card, EmptyState, ErrorText, Loading, PageHeader, ProgressBar, ScoreRing, cx, scoreTone } from '../components/ui'
import type { Tone } from '../components/ui'
import { api } from '../lib/api'
import { fmtMinutes, prettyDate } from '../lib/dates'
import type { InterviewResult, StudyToday, StudyTopic, TodayTopic } from '../lib/types'

const MODE: Record<TodayTopic['mode'], { label: string; tone: Tone }> = {
  new: { label: 'New', tone: 'brand' },
  carryover: { label: 'Weak areas', tone: 'amber' },
  retest: { label: 'Re-test', tone: 'zinc' },
  done: { label: 'Studied today', tone: 'green' },
}

function TopicRow({ topic, index }: { topic: TodayTopic; index: number }) {
  const covered = topic.concepts.filter((c) => (topic.concept_scores[c.name] ?? 0) >= 4).length
  return (
    <Link to={`/study/${topic.id}`} className="rise block" style={{ animationDelay: `${index * 50}ms` }}>
      <article className="flex items-center gap-4 rounded-3xl border border-line bg-surface p-5 transition hover:border-accent/50">
        <div className="min-w-0 flex-1">
          <div className="mb-1.5 flex flex-wrap items-center gap-1.5">
            <Badge tone={topic.status === 'passed' && topic.mode === 'done' ? 'green' : MODE[topic.mode].tone}>
              {topic.status === 'passed' && topic.mode === 'done' ? 'Passed' : MODE[topic.mode].label}
            </Badge>
            {topic.source === 'offplan' && <Badge>Your pick</Badge>}
            {topic.minutes > 0 && <span className="text-xs text-muted tabular-nums">{fmtMinutes(topic.minutes)}</span>}
          </div>
          <h2 className="truncate font-display text-2xl leading-tight">{topic.title}</h2>
          <p className="mt-1 truncate text-xs text-muted">
            {topic.mode === 'carryover' && topic.weak_concepts.length ? `Focus: ${topic.weak_concepts.join(', ')}` : `${covered}/${topic.concepts.length} subtopics covered · ${topic.goal}`}
          </p>
        </div>
        {topic.last_pct !== null ? (
          <ScoreRing score={topic.last_pct} size={60} />
        ) : (
          <span aria-hidden className="text-xl text-muted">
            →
          </span>
        )}
      </article>
    </Link>
  )
}

export default function Study() {
  const { data, isLoading, error } = useQuery({ queryKey: ['study', 'today'], queryFn: () => api<StudyToday>('/study/today') })
  if (isLoading) return <Loading />
  if (!data) return <ErrorText error={error} />
  const queue = data.topics.filter((t) => t.mode !== 'done')
  const done = data.topics.filter((t) => t.mode === 'done')
  const scores = data.interviews.map((s) => s.overall_pct)
  const average = scores.length ? Math.round(scores.reduce((a, b) => a + b, 0) / scores.length) : null
  return (
    <>
      <PageHeader
        eyebrow={prettyDate(data.date, { weekday: 'long', month: 'long', day: 'numeric' })}
        title="Today's topics"
        subtitle={`${queue.length} to cover${data.available_minutes ? ` · ${fmtMinutes(data.available_minutes)} available` : ''}${average !== null ? ` · ${average}% average today` : ''}`}
      />
      {data.topics.length ? (
        <div className="space-y-3">
          {queue.map((t, i) => (
            <TopicRow key={t.id} topic={t} index={i} />
          ))}
          {done.length > 0 && <p className="pt-4 text-[11px] font-semibold tracking-[0.14em] text-muted uppercase">Studied today</p>}
          {done.map((t, i) => (
            <TopicRow key={t.id} topic={t} index={i} />
          ))}
        </div>
      ) : (
        <EmptyState title="No topics for today yet">
          Ask Claude to split your next roadmap item into topics and subtopics.
          <div className="mt-5">
            <OpenClaude message="Use GoalCoach. Prepare today's study topics with all their subtopics.">Prepare topics in Claude</OpenClaude>
          </div>
        </EmptyState>
      )}
      <p className="mt-6 text-center text-xs text-muted">
        Studied something else? Tell Claude, and it counts too.
      </p>
    </>
  )
}

function Session({ session }: { session: InterviewResult }) {
  const [open, setOpen] = useState(false)
  return (
    <li className="rounded-2xl border border-line p-4">
      <button className="flex w-full items-center justify-between gap-3 text-left" onClick={() => setOpen(!open)}>
        <span className="min-w-0 text-sm">
          <span className="font-medium">{session.kind === 'retest' ? 'Re-test' : 'Interview'}</span>
          <span className="text-muted"> · {prettyDate(session.day)} · {session.passed ? 'Passed' : 'Not yet'}</span>
        </span>
        <span className={cx('font-display text-2xl tabular-nums', scoreTone(session.overall_pct))}>{Math.round(session.overall_pct)}%</span>
      </button>
      {open && (
        <ol className="mt-3 space-y-3 border-t border-line pt-3">
          {session.questions.map((q, i) => (
            <li key={i} className="text-sm">
              <p className="font-medium">{q.question}</p>
              <p className="text-xs text-muted">
                {q.concept} · {q.score}/5{q.is_follow_up ? ' · follow-up' : ''}
              </p>
              {q.gap && <p className="mt-1 text-xs text-amber-700 dark:text-amber-300">Missing: {q.gap}</p>}
            </li>
          ))}
        </ol>
      )}
    </li>
  )
}

export function TopicDetail() {
  const id = Number(useParams().id)
  const { data: topic, isLoading, error } = useQuery({
    queryKey: ['study', 'topic', id],
    queryFn: () => api<StudyTopic & { sessions: InterviewResult[] }>(`/study/topics/${id}`),
  })
  const [picked, setPicked] = useState<string[]>([])

  if (isLoading) return <Loading />
  if (!topic) return <ErrorText error={error ?? 'Topic not found'} />

  const focus = picked.length ? picked : topic.status === 'learning' ? topic.weak_concepts : []
  const scope = focus.length ? ` Focus on these subtopics: ${focus.join(', ')}.` : ''
  const retest = topic.status === 'passed' && !!topic.next_review_on
  const learn = `Use GoalCoach. Learn mode for study topic ${topic.id}, "${topic.title}". I'll ask, you teach.${scope}`
  const interview = `Use GoalCoach. ${retest ? 'Re-test' : 'Interview'} me on study topic ${topic.id}, "${topic.title}", in Interview mode.${scope}`
  const toggle = (name: string) => setPicked((p) => (p.includes(name) ? p.filter((n) => n !== name) : [...p, name]))
  const statusLabel = topic.status === 'passed' ? 'Passed' : topic.status === 'learning' ? 'In progress' : 'Not started'

  return (
    <>
      <Link to="/study" className="text-sm text-muted hover:text-ink">
        ← Today's topics
      </Link>
      <div className="mt-3 mb-6 flex items-center justify-between gap-4">
        <div className="min-w-0">
          <Badge tone={topic.status === 'passed' ? 'green' : topic.status === 'learning' ? 'amber' : 'brand'}>{statusLabel}</Badge>
          <h1 className="mt-2 font-display text-4xl leading-[1.05] tracking-tight sm:text-5xl">{topic.title}</h1>
          {topic.next_review_on && <p className="mt-2 text-sm text-muted">Re-test on {prettyDate(topic.next_review_on)}</p>}
        </div>
        {topic.last_pct !== null && <ScoreRing score={topic.last_pct} size={96} />}
      </div>

      <div className="rise mb-4 rounded-3xl border border-accent/40 bg-surface p-5 ring-1 ring-accent/20 sm:p-6">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <div>
            <p className="mb-1 font-medium">1. Learn</p>
            <p className="mb-3 text-sm text-muted">You ask, Claude teaches.</p>
            <OpenClaude message={learn} className="w-full">
              Learn with Claude
            </OpenClaude>
          </div>
          <div>
            <p className="mb-1 font-medium">2. Get interviewed</p>
            <p className="mb-3 text-sm text-muted">Claude asks and scores you. Pass at 85%.</p>
            <OpenClaude message={interview} variant="secondary" className="w-full">
              {retest ? 'Re-test with Claude' : 'Interview me'}
            </OpenClaude>
          </div>
        </div>
        <p className="mt-4 text-xs text-muted">To talk instead of type, tap the sound wave icon in Claude. Your score appears here after the interview.</p>
      </div>

      <Card eyebrow="Subtopics" title={picked.length ? `${picked.length} selected for your next session` : 'Tap to pick what to cover'}>
        <ul className="space-y-2">
          {topic.concepts.map((c) => {
            const score = topic.concept_scores[c.name]
            const on = picked.includes(c.name)
            const weak = topic.weak_concepts.includes(c.name)
            return (
              <li key={c.name}>
                <button
                  onClick={() => toggle(c.name)}
                  aria-pressed={on}
                  className={cx('w-full rounded-2xl border p-3.5 text-left transition', on ? 'border-accent bg-accent-soft' : 'border-line hover:border-accent/40')}
                >
                  <span className="flex items-center justify-between gap-3">
                    <span className="min-w-0 text-sm font-medium">
                      {on ? '✓ ' : ''}
                      {c.name}
                      {c.core === false && <span className="ml-1.5 text-xs font-normal text-muted">optional</span>}
                    </span>
                    {weak ? <Badge tone="amber">Weak</Badge> : score !== undefined ? <span className="text-xs text-muted tabular-nums">{score}/5</span> : null}
                  </span>
                  {score !== undefined && <ProgressBar value={(score / 5) * 100} className="mt-2.5" />}
                </button>
              </li>
            )
          })}
        </ul>
      </Card>

      {topic.sessions.length > 0 && (
        <Card eyebrow="History" title="Past interviews" className="mt-4">
          <ul className="space-y-2">
            {topic.sessions.map((s) => (
              <Session key={s.id} session={s} />
            ))}
          </ul>
        </Card>
      )}
    </>
  )
}
