/** Coaching happens in Claude: these links open a new Claude chat (the Claude app on a phone) with a message ready. */
export function claudeLink(message: string): string {
  return `https://claude.ai/new?q=${encodeURIComponent(message)}`
}
