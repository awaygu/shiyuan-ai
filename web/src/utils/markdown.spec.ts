import { describe, it, expect } from 'vitest'
import { renderSafeMarkdown } from './markdown'

describe('renderSafeMarkdown', () => {
  it('returns empty string for falsy input', () => {
    expect(renderSafeMarkdown('')).toBe('')
    expect(renderSafeMarkdown(null as any)).toBe('')
  })

  it('renders markdown to sanitized html', () => {
    const html = renderSafeMarkdown('# Hello\n\n[link](https://example.com)')
    expect(html).toContain('Hello')
    expect(html).toContain('<a href="https://example.com">link</a>')
    expect(html).not.toContain('<script')
  })
})
