import DOMPurify from 'dompurify'
import { marked } from 'marked'

export function renderSafeMarkdown(text: string): string {
  if (!text) return ''
  const html = marked.parse(text, { async: false }) as string
  return DOMPurify.sanitize(html, {
    USE_PROFILES: { html: true },
    ADD_ATTR: ['target'],
  })
}
