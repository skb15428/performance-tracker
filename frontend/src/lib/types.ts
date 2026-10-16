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
  breakdown: { explanation?: string }
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
  daily_available_hours: number
  has_own_key: boolean
  server_llm_available: boolean
  vapid_public_key: string
}

export type Dashboard = {
  scores: { date: string; score: number }[]
  heatmap: { date: string; score: number; rest?: boolean }[]
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
  today_plan: { id: number; title: string; time_block: string; minutes: number; goal_id: number | null; status: string }[]
  new_trends: number
  weekly_focus: string[]
}
