// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, screen } from '@testing-library/react'

import App from './App'

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

describe('App news feed error handling', () => {
  it('shows an actionable error with a retry button when the news API is unreachable', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => Promise.reject(new TypeError('Network failure'))),
    )

    render(<App />)

    expect(
      await screen.findByText(
        /Unable to reach the news service/,
      ),
    ).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Try again' })).toBeTruthy()
    expect(vi.mocked(fetch).mock.calls[0][0]).toContain('/api/v1/news')
  })
})

describe('App news feed refresh', () => {
  it('pulls the newest headlines from the provider when the feed is refreshed', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes('refresh=true')) {
        return new Response(
          JSON.stringify([
            {
              id: 'fresh-story',
              source: 'Example News',
              published_at: '2026-11-10T18:00:00Z',
              url: 'https://example.com/fresh-story',
              title: 'Central bank signals a new rate path',
              summary: 'A source-grounded summary of the decision.',
              summary_source: 'ai',
              importance: 'important',
              category: 'economic',
            },
          ]),
          { status: 200, headers: { 'Content-Type': 'application/json' } },
        )
      }

      return new Response(
        JSON.stringify([
          {
            id: 'cached-story',
            source: 'Example News',
            published_at: '2026-11-10T12:00:00Z',
            url: 'https://example.com/cached-story',
            title: 'Earlier market story',
            summary: 'A source-grounded summary of the earlier report.',
            summary_source: 'ai',
            importance: 'other',
            category: 'economic',
          },
        ]),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      )
    })
    vi.stubGlobal('fetch', fetchMock)

    render(<App />)

    expect(await screen.findByText('Earlier market story')).toBeTruthy()

    const refreshButton = screen.getByRole('button', { name: 'Refresh the news feed' })
    refreshButton.click()

    expect(await screen.findByText('Central bank signals a new rate path')).toBeTruthy()
    expect(
      fetchMock.mock.calls.some((call) => String(call[0]).includes('refresh=true')),
    ).toBe(true)
  })
})
