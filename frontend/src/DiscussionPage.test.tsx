// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'

import DiscussionPage from './DiscussionPage'
import type { NewsArticle } from './news'

const article: NewsArticle = {
  id: 'insight-story',
  source: 'Example News',
  published_at: '2026-11-10T12:00:00Z',
  url: 'https://example.com/us-inflation',
  title: 'U.S. inflation cools more than expected',
  summary: 'The report may affect expectations for interest rates.',
  summary_source: 'ai',
  importance: 'important',
  category: 'economic',
}

const insightsPayload = {
  assets: [
    {
      name: 'Nvidia',
      symbol: 'NVDA',
      kind: 'company',
      relationship: 'mentioned',
      rationale: 'The article names Nvidia as a chip supplier.',
    },
    {
      name: 'Microsoft',
      symbol: 'MSFT',
      kind: 'company',
      relationship: 'potential',
      rationale: 'Data-centre demand links the story to Microsoft.',
    },
  ],
  impact: {
    direction: 'positive',
    summary: 'Cooler inflation supports the rate path priced by markets.',
    rationale: 'Consumer prices rose more slowly than expected.',
  },
  suggested_questions: [
    'How does the cooler CPI change the rate path priced by markets?',
  ],
}

function mockFetch(failDiscussionRequests = 0) {
  let discussionRequests = 0
  const fetchMock = vi.fn(async (input: RequestInfo | URL, _init?: RequestInit) => {
      const url = String(input)
      if (url.includes('/insights')) {
        return new Response(JSON.stringify(insightsPayload), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        })
      }
      if (url.includes('/discussions/models')) {
        return new Response(
          JSON.stringify({
            models: [{ id: 'test-model', label: 'Test Model' }],
            default_model: 'test-model',
          }),
          { status: 200, headers: { 'Content-Type': 'application/json' } },
        )
      }
      if (url.endsWith('/api/v1/discussions')) {
        discussionRequests += 1
        if (discussionRequests <= failDiscussionRequests) {
          return new Response(JSON.stringify({ detail: 'Service unavailable.' }), {
            status: 503,
            headers: { 'Content-Type': 'application/json' },
          })
        }
        return new Response(JSON.stringify({ reply: 'The article reports cooler inflation.' }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        })
      }
      return new Response(JSON.stringify([]), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      })
    })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

describe('DiscussionPage article insights', () => {
  it('shows the reported effect, the related companies and the article questions', async () => {
    mockFetch()
    render(<DiscussionPage article={article} />)

    expect(await screen.findByText('Positive')).toBeTruthy()
    expect(
      screen.getByText('Cooler inflation supports the rate path priced by markets.'),
    ).toBeTruthy()

    // Related companies, not only the one named in the headline.
    const assetItems = document.querySelectorAll('.discussion-assets-list li')
    expect(assetItems.length).toBe(2)
    expect(assetItems[0].textContent).toContain('Nvidia (NVDA)')
    expect(assetItems[1].textContent).toContain('Microsoft (MSFT)')
    expect(document.body.textContent).toContain('named in the article')
    expect(document.body.textContent).toContain('potential exposure')
    expect(
      screen.getAllByRole('link', { name: 'Read original source ↗' }),
    ).toHaveLength(1)

    const questionButton = await screen.findByRole('button', {
      name: 'How does the cooler CPI change the rate path priced by markets?',
    })
    expect(questionButton).toBeTruthy()
  })

  it('fills the composer with a suggested question when it is clicked', async () => {
    mockFetch()
    render(<DiscussionPage article={article} />)

    const questionButton = await screen.findByRole('button', {
      name: 'How does the cooler CPI change the rate path priced by markets?',
    })
    fireEvent.click(questionButton)

    const composer = screen.getByLabelText('Your question') as HTMLTextAreaElement
    await waitFor(() => {
      expect(composer.value).toBe(
        'How does the cooler CPI change the rate path priced by markets?',
      )
    })
  })

  it('labels conversation turns and shows the analyst response', async () => {
    mockFetch()
    render(<DiscussionPage article={article} />)

    const composer = screen.getByLabelText('Your question')
    fireEvent.change(composer, { target: { value: 'What changed?' } })
    fireEvent.click(screen.getByRole('button', { name: 'Send message' }))

    const conversation = screen.getByRole('log', {
      name: 'Conversation messages',
    })
    expect(await screen.findByText('The article reports cooler inflation.')).toBeTruthy()
    expect(conversation.textContent).toContain('You')
    expect(conversation.textContent).toContain('EcoMind analyst')
    expect(screen.getByText('2 messages')).toBeTruthy()
  })

  it('keeps a failed question in the composer without including it in retry history', async () => {
    const fetchMock = mockFetch(1)
    render(<DiscussionPage article={article} />)

    const composer = screen.getByLabelText('Your question')
    fireEvent.change(composer, { target: { value: 'What changed?' } })
    fireEvent.click(screen.getByRole('button', { name: 'Send message' }))

    expect(await screen.findByRole('alert')).toBeTruthy()
    expect((composer as HTMLTextAreaElement).value).toBe('What changed?')
    expect(screen.getByRole('log').textContent).not.toContain('What changed?')

    fireEvent.click(screen.getByRole('button', { name: 'Send message' }))
    expect(await screen.findByText('The article reports cooler inflation.')).toBeTruthy()

    const discussionCalls = fetchMock.mock.calls.filter(([input]) =>
      String(input).endsWith('/api/v1/discussions'),
    )
    const retryRequest = discussionCalls.at(-1)?.[1] as RequestInit | undefined
    const retryBody = JSON.parse(String(retryRequest?.body)) as {
      history: unknown[]
      message: string
    }
    expect(retryBody.message).toBe('What changed?')
    expect(retryBody.history).toEqual([])
  })
})
