export type Timeline = {
  planned_hours: number
  done_hours: number
  behind_hours: number
  behind_days: number
  behind_pct: number
  overdue_items: number
  hours_per_day: number
  state: 'on_track' | 'behind' | 'ahead' | 'not_started'
}

export type Resource = { title: string; url: string }

export type ItemDraft = {
  type: ItemType
  title: string
  description: string
  est_hours: number
  resources: Resource[]
}
export type PhaseDraft = { title: string; items: ItemDraft[] }
export type RoadmapDraft = { summary: string; suggested_target_date: string | null; phases: PhaseDraft[] }

export type Goal = {
  id: number
  title: string
  description: string
  why: string
  category: string
  priority: number
  target_date: string | null
  status: 'active' | 'paused' | 'done'
  intake_status: 'interviewing' | 'roadmap_proposed' | 'commitment_pending' | 'active'
  context: Record<string, string>
  proposed_roadmap: RoadmapDraft | null
  created_at: string
  progress_pct: number
  timeline: Timeline | null
  pending_replan_id: number | null
  statement: string
  success_criteria: string[]
  hours_per_day: number | null
  days_per_week: number | null
  routine: { days: string[]; start: string; end: string; activity: string }[]
}

export type ChatMessage = { id: number; role: 'user' | 'assistant'; content: string; created_at: string }
export type ChatOut = { messages: ChatMessage[]; goal: Goal }

export type ItemType = 'topic' | 'skill' | 'task' | 'milestone'
export type ItemStatus = 'todo' | 'in_progress' | 'done' | 'skipped'
export type RoadmapItem = {
  id: number
  order: number
  type: ItemType
  title: string
  description: string
  resources: Resource[]
  est_hours: number
  planned_start: string | null
  planned_due: string | null
  status: ItemStatus
  hours_logged: number
  completed_at: string | null
  source: 'ai' | 'user' | 'trend'
  proof: 'interview' | 'log' | 'deliverable'
  proof_links: { title: string; url: string }[]
}
export type RoadmapPhase = {
  id: number
  title: string
  order: number
  start_date: string | null
  due_date: string | null
  items: RoadmapItem[]
}
export type Feasibility = { feasible: boolean; realistic_date: string; required_hours_per_day: number | null }
export type RoadmapOut = { goal: Goal; phases: RoadmapPhase[]; feasibility: Feasibility | null }

export const KINDS = ['learn', 'build', 'ship', 'network', 'apply', 'admin', 'job', 'leisure', 'waste', 'other'] as const
export type Kind = (typeof KINDS)[number]

export type ScheduleBlock = {
  start: string
  end: string
  activity: string
  notes?: string
  kind?: Kind | null
  goal_id?: number | null
  roadmap_item_id?: number | null
}

export type LinkDraft = { goal_id: number; roadmap_item_id: number | null; relevance: number; reason: string }
export type ActivityDraft = { description: string; minutes: number; kind: Kind; links: LinkDraft[] }
export type PlanDraft = {
  time_block: string
  title: string
  minutes: number
  goal_id: number | null
  roadmap_item_id: number | null
}
export type DayAnalysis = {
  activities: ActivityDraft[]
  goal_impacts: { goal_id: number; impact: number; note: string }[]
  item_progress: { roadmap_item_id: number; hours: number; completed: boolean }[]
  went_well: string[]
  went_badly: string[]
  tomorrow: PlanDraft[]
  tip: string
}
export type DraftOut = { draft: DayAnalysis; used_llm: boolean }

export type GoalDayScore = {
  title: string
  minutes: number
  rule: number
  llm: number | null
  score: number
  note: string
  timeline: string
  behind_days: number
  extra?: boolean
}
export type Review = {
  total_score: number
  per_goal: Record<string, GoalDayScore>
  went_well: string[]
  went_badly: string[]
  tip: string
  drift_minutes: number
  adherence: number | null
  used_llm: boolean
  rest_day: boolean
  breakdown: { explanation?: string; bonus_minutes?: number }
}
export type Entry = {
  id: number | null
  date: string
  schedule: ScheduleBlock[]
  free_text: string
  energy: number | null
  draft: { analysis: DayAnalysis; used_llm: boolean } | null
  analyzed_at: string | null
  activities: { id: number; description: string; minutes: number; kind: Kind; links: LinkDraft[] }[]
  review: Review | null
}

export type PlanDetails = {
  why?: string
  steps?: { text: string; minutes: number; done?: boolean }[]
  resources?: { title: string; url: string }[]
  done_when?: string
  topic_id?: number | null
}

export type PlanItem = {
  id: number
  date_for: string
  time_block: string
  title: string
  minutes: number
  goal_id: number | null
  roadmap_item_id: number | null
  status: 'open' | 'done' | 'partial' | 'skipped'
  done_minutes: number | null
  details?: PlanDetails
}

export type Replan = {
  id: number
  goal_id: number
  reason: string
  status: string
  created_at: string
  diff: {
    strategy: string
    changes: { item_id: number; title: string; action: 'shift' | 'skip'; old_due: string | null; new_due: string | null }[]
    new_finish_date: string | null
    target_date: string | null
    goal_hours_per_day: number
    daily_available_hours: number | null
    status?: Timeline
  }
}

export type TrendSuggestion = {
  id: number
  goal_id: number
  title: string
  why_relevant: string
  est_hours: number
  links: Resource[]
  status: string
  created_at: string
}
export type TrendSource = { id: number; name: string; kind: string; url: string; enabled: boolean; user_id: string | null }

export type WeeklyReview = {
  id: number
  week_start: string
  stats: {
    days_logged: number
    week_score?: WeekScore
    avg_score: number | null
    drift_minutes: number
    plan_items: number
    plan_done: number
    trends_adopted: number
    goals: {
      goal_id: number
      title: string
      minutes: number
      committed_hours?: number
      pct_of_commitment?: number | null
      completed_items: string[]
      timeline: string
    }[]
  }
  summary: string
  wins: string[]
  gaps: string[]
  recommendations: string[]
  focus: { text: string; kept: boolean | null }[]
  created_at: string
}

export type Settings = {
  name: string | null
  email: string
  timezone: string
  reminder_time: string
  morning_push: boolean
  email_reminders: boolean
  daily_available_hours: number
  email_enabled: boolean
  calendar_token: string | null
  vapid_public_key: string
}

export type AppStatus = {
  scheduler_last_run: string | null
  last_reminder_day: string | null
  email_enabled: boolean
  push_devices: number
  calendar_connected: boolean
  last_backup: string | null
  errors_last_7_days: number
  last_error: { where?: string; error?: string; at: string } | null
  default_secrets: boolean
}

export type WeekDay = {
  date: string
  state: 'done' | 'rest' | 'bonus' | 'before' | 'covered' | 'missed' | 'today' | 'upcoming'
  is_today: boolean
  minutes: number
  planned_minutes: number
  day_type: 'rest' | 'work' | null
  goal_day_types: Record<string, 'rest' | 'work'>
  usual: boolean
}

export type WeekScore = {
  week_start: string
  final: boolean
  score: number | null
  explanation: string | null
  hours_done: number
  hours_target: number
  hours_expected_so_far: number
  ahead_hours: number
  average_hours?: number | null // reviews saved before this field existed don't have it
  planned_hours_per_day?: number
  rest_days_marked: number
  goals: {
    goal_id: number
    title: string
    hours_done: number
    hours_target: number
    quality: number | null
    sessions_done?: number
    sessions_target?: number
  }[]
}

export type ScorecardRow = {
  goal: string
  id: number
  name: string
  unit: string
  start_value: number
  target_value: number
  latest_value: number | null
  progress_pct: number
  state: Metric['state']
  source: string | null
}

export type TimeLog = { id: number; day: string; goal_id: number; roadmap_item_id: number | null; minutes: number; note: string; source: 'manual' | 'block' | 'interview' }

export type JobStage = 'saved' | 'applied' | 'screen' | 'technical' | 'final' | 'offer' | 'rejected' | 'withdrawn'

export type Application = {
  id: number
  company: string
  role: string
  url: string
  referral: string
  stage: JobStage
  reached_final: boolean
  applied_on: string | null
  next_step: string
  notes: string
  updated_at: string
}

export type ProofItem = {
  id: number
  goal: string
  title: string
  status: string
  completed_at: string | null
  links: { title: string; url: string }[]
  passed_topics: string[]
}

export type Readiness = {
  passed: number
  total: number
  pct: number | null
  items: { id: number; title: string; passed: number; total: number; planned_due: string | null }[]
  weakest: { concept: string; topic: string; topic_id: number; score: number | null }[]
  retests_due: number
  unprepared_items: number
}

export type Dashboard = {
  today: string
  reviewed_today: boolean
  this_week: WeekScore
  week: WeekDay[]
  next_week: WeekDay[]
  attention: string[]
  scorecard: ScorecardRow[]
  week_scores: { week: string; score: number }[]
  heatmap: { date: string; minutes: number; rest?: boolean }[]
  weekly_effort: ({ week: string } & Record<string, number | string>)[]
  goals: (Goal & {
    burnup: { date: string; planned: number | null; actual: number }[]
    insight?: {
      likely_cause: string
      actual_hours_per_week: number
      planned_hours_per_week: number
      forecast_finish_at_actual_pace: string | null
      forecast_misses_target: boolean
      target_date: string | null
    }
  })[]
  latest: {
    date: string
    score: number
    per_goal: Record<string, GoalDayScore>
    went_well: string[]
    went_badly: string[]
    tip: string
    explanation: string | null
  } | null
  streak: number
  adherence_avg: number | null
  today_plan: {
    id: number
    title: string
    time_block: string
    minutes: number
    goal_id: number | null
    roadmap_item_id: number | null
    status: 'open' | 'done' | 'partial' | 'skipped'
    done_minutes: number | null
    details?: PlanDetails
  }[]
  new_trends: number
  weekly_focus: string[]
}

export type Concept = { name: string; core?: boolean }

export type StudyTopic = {
  id: number
  goal_id: number
  roadmap_item_id: number | null
  title: string
  concepts: Concept[]
  est_minutes: number
  status: 'new' | 'learning' | 'passed'
  source: 'roadmap' | 'offplan'
  attempts: number
  best_pct: number | null
  last_pct: number | null
  concept_scores: Record<string, number>
  weak_concepts: string[]
  passed_on: string | null
  next_review_on: string | null
}

export type NoteSummary = { id: number; topic_id: number | null; title: string; snippet: string; updated_at: string }

export type Note = { id: number; topic_id: number | null; title: string; content: string; updated_at: string }

export type TodayTopic = StudyTopic & { goal: string; mode: 'retest' | 'carryover' | 'new' | 'done'; minutes: number }

export type InterviewResult = {
  id: number
  topic_id: number
  topic: string | null
  day: string
  kind: 'first' | 'retest'
  minutes: number
  overall_pct: number
  passed: boolean
  concept_scores: Record<string, number>
  weak_concepts: string[]
  questions: { question: string; concept: string; is_follow_up?: boolean; answer_summary?: string; score: number; gap?: string }[]
}

export type StudyToday = { date: string; available_minutes: number; rest_day: boolean; topics: TodayTopic[]; interviews: InterviewResult[] }

export type UpcomingDay = { date: string; minutes: number; topics: TodayTopic[] }

export type UpcomingStep = {
  id: number
  goal: string
  title: string
  proof: 'interview' | 'log' | 'deliverable'
  status: 'todo' | 'in_progress'
  planned_start: string | null
  planned_due: string | null
  est_hours: number
  topics: StudyTopic[]
  needs_topics: boolean
}

export type StudyUpcoming = { days: UpcomingDay[]; steps: UpcomingStep[] }

export type Metric = {
  id: number
  name: string
  unit: string
  start_value: number
  target_value: number
  start_date: string
  latest_value: number | null
  entries: { day: string; value: number }[]
  state: 'no_data' | 'no_target_date' | 'behind' | 'on_track' | 'ahead'
  progress_pct: number
  expected_value: number | null
  source: string | null
}

export type GoalStudy = { items: Record<string, { passed: number; total: number }>; metrics: Metric[] }

