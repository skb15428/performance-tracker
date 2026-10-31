import { describe, expect, it } from 'vitest'
import { addDays, fmtMinutes, minutesBetween } from './dates'

describe('dates', () => {
  it('adds days across a month end', () => {
    expect(addDays('2026-10-31', 1)).toBe('2026-11-01')
  })

  it('writes minutes the way the app shows them', () => {
    expect(fmtMinutes(45)).toBe('45m')
    expect(fmtMinutes(120)).toBe('2h')
    expect(fmtMinutes(90)).toBe('1h 30m')
  })

  it('handles a block that runs past midnight', () => {
    expect(minutesBetween('23:30', '00:30')).toBe(60)
  })
})
