import { describe, expect, it } from 'vitest'

import { apiErrorDetail, isNewsArticle } from './news'

const validArticle = {
  id: 'abc123',
  source: 'Example News',
  published_at: '2026-11-10T10:00:00Z',
  url: 'https://example.com/story',
  title: 'A financial headline',
  summary: 'A short summary.',
  article_content: 'Full text.',
  summary_source: 'ai',
  importance: 'important',
  category: 'economic',
}

describe('isNewsArticle', () => {
  it('accepts a fully valid article', () => {
    expect(isNewsArticle(validArticle)).toBe(true)
  })

  it('accepts a minimal article without optional fields', () => {
    expect(
      isNewsArticle({
        id: 'abc123',
        source: null,
        published_at: null,
        url: 'http://example.com/story',
        title: 'Minimal',
        summary: null,
        summary_source: 'unavailable',
        importance: 'other',
      }),
    ).toBe(true)
  })

  it('rejects non-object values', () => {
    expect(isNewsArticle(null)).toBe(false)
    expect(isNewsArticle('article')).toBe(false)
    expect(isNewsArticle(undefined)).toBe(false)
  })

  it('rejects articles without a URL', () => {
    const { url: _url, ...noUrl } = validArticle
    expect(isNewsArticle(noUrl)).toBe(false)
  })

  it('rejects javascript: URLs', () => {
    expect(isNewsArticle({ ...validArticle, url: 'javascript:alert(1)' })).toBe(
      false,
    )
  })

  it('rejects malformed URLs', () => {
    expect(isNewsArticle({ ...validArticle, url: 'not-a-url' })).toBe(false)
  })

  it('rejects unknown enum values', () => {
    expect(
      isNewsArticle({ ...validArticle, summary_source: 'guess' }),
    ).toBe(false)
    expect(isNewsArticle({ ...validArticle, importance: 'critical' })).toBe(
      false,
    )
    expect(isNewsArticle({ ...validArticle, category: 'markets' })).toBe(false)
  })

  it('rejects articles with wrong field types', () => {
    expect(isNewsArticle({ ...validArticle, id: 42 })).toBe(false)
    expect(isNewsArticle({ ...validArticle, source: 123 })).toBe(false)
    expect(isNewsArticle({ ...validArticle, summary: true })).toBe(false)
    expect(isNewsArticle({ ...validArticle, article_content: 1 })).toBe(false)
  })
})

describe('apiErrorDetail', () => {
  it('returns the detail string from API error payloads', () => {
    expect(
      apiErrorDetail({ detail: 'The service is unavailable.' }, 'Fallback.'),
    ).toBe('The service is unavailable.')
  })

  it('returns the default message when detail is missing', () => {
    expect(apiErrorDetail(null, 'Fallback.')).toBe('Fallback.')
    expect(apiErrorDetail({}, 'Fallback.')).toBe('Fallback.')
    expect(apiErrorDetail({ detail: 404 }, 'Fallback.')).toBe('Fallback.')
  })

  it('returns the default message for non-object payloads', () => {
    expect(apiErrorDetail('error text', 'Fallback.')).toBe('Fallback.')
  })
})
