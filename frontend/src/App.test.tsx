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

describe('Observability page', () => {
  it('renders the telemetry dashboard and the selected trace detail', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input)

        if (url.includes('/api/v1/observability/metrics')) {
          return new Response(
            JSON.stringify({
              generated_at: '2026-11-10T12:00:00Z',
              total_requests: 12,
              total_errors: 1,
              routes: [
                {
                  method: 'GET',
                  route: '/api/v1/news',
                  request_count: 12,
                  error_count: 1,
                  avg_duration_ms: 340.5,
                  p95_duration_ms: 782.1,
                },
              ],
              ai_requests: [],
              ai_quota_pauses: 0,
              provider_fetches: [],
              refreshes: 3,
              articles_saved: 8,
            }),
            { status: 200, headers: { 'Content-Type': 'application/json' } },
          )
        }

        if (url.includes('/api/v1/observability/journeys')) {
          return new Response(
            JSON.stringify({
              journeys: [
                {
                  trace_id: 'trace-123',
                  name: 'GET /api/v1/news',
                  started_at: '2026-11-10T12:00:00Z',
                  duration_ms: 421.2,
                  status: 'ok',
                  span_count: 3,
                  error_count: 0,
                  log_count: 1,
                },
              ],
            }),
            { status: 200, headers: { 'Content-Type': 'application/json' } },
          )
        }

        if (url.includes('/api/v1/observability/alerts')) {
          return new Response(
            JSON.stringify({
              active: false,
              severity: 'info',
              message: 'API health is stable.',
              error_rate: 0.04,
              total_requests: 12,
              total_errors: 1,
              threshold: 0.2,
              checked_at: '2026-11-10T12:00:00Z',
            }),
            { status: 200, headers: { 'Content-Type': 'application/json' } },
          )
        }

        if (url.includes('/api/v1/observability/oncall')) {
          return new Response(
            JSON.stringify({
              active: false,
              status: 'clear',
              severity: 'info',
              summary: 'API health is stable.',
              human_approval_required: false,
              recommended_actions: [],
              verification_steps: ['Monitor the route for the next interval.'],
              approval_required_for: [],
              checked_at: '2026-11-10T12:00:00Z',
            }),
            { status: 200, headers: { 'Content-Type': 'application/json' } },
          )
        }

        if (url.includes('/api/v1/observability/traces/trace-123')) {
          return new Response(
            JSON.stringify({
              trace_id: 'trace-123',
              spans: [
                {
                  trace_id: 'trace-123',
                  span_id: 'span-1',
                  parent_span_id: null,
                  name: 'GET /api/v1/news',
                  started_at: '2026-11-10T12:00:00Z',
                  duration_ms: 421.2,
                  status: 'ok',
                  attributes: { method: 'GET', route: '/api/v1/news', 'http.status_code': 200 },
                },
              ],
              logs: [
                {
                  trace_id: 'trace-123',
                  span_id: 'span-1',
                  level: 'INFO',
                  logger_name: 'app.middleware.observability',
                  message: 'request completed without warnings',
                  recorded_at: '2026-11-10T12:00:01Z',
                },
              ],
              metrics: [
                {
                  name: 'api.request.count',
                  value: 1,
                  dimensions: { method: 'GET', route: '/api/v1/news', status: 200 },
                  trace_id: 'trace-123',
                  recorded_at: '2026-11-10T12:00:01Z',
                },
              ],
            }),
            { status: 200, headers: { 'Content-Type': 'application/json' } },
          )
        }

        return new Response(JSON.stringify([]), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        })
      }),
    )

    window.history.pushState(null, '', '/observability')

    render(<App />)

    expect(await screen.findByRole('heading', { name: 'Observability' })).toBeTruthy()
    expect(screen.getAllByText('GET /api/v1/news').length).toBeGreaterThan(0)
    expect(screen.getAllByText('trace-123').length).toBeGreaterThan(0)
    expect(screen.getByText('Selected trace')).toBeTruthy()
  })

  it('shows the on-call review when an alert requires investigation', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input)

        if (url.includes('/api/v1/observability/metrics')) {
          return new Response(
            JSON.stringify({
              generated_at: '2026-11-10T12:00:00Z',
              total_requests: 50,
              total_errors: 15,
              routes: [
                {
                  method: 'GET',
                  route: '/api/v1/news',
                  request_count: 50,
                  error_count: 15,
                  avg_duration_ms: 500,
                  p95_duration_ms: 1000,
                },
              ],
              ai_requests: [],
              ai_quota_pauses: 0,
              provider_fetches: [],
              refreshes: 3,
              articles_saved: 8,
            }),
            { status: 200, headers: { 'Content-Type': 'application/json' } },
          )
        }

        if (url.includes('/api/v1/observability/journeys')) {
          return new Response(JSON.stringify({ journeys: [] }), {
            status: 200,
            headers: { 'Content-Type': 'application/json' },
          })
        }

        if (url.includes('/api/v1/observability/alerts')) {
          return new Response(
            JSON.stringify({
              active: true,
              severity: 'warning',
              message: 'User-impacting API errors exceeded the threshold.',
              error_rate: 0.3,
              total_requests: 50,
              total_errors: 15,
              threshold: 0.2,
              checked_at: '2026-11-10T12:00:00Z',
            }),
            { status: 200, headers: { 'Content-Type': 'application/json' } },
          )
        }

        if (url.includes('/api/v1/observability/oncall')) {
          return new Response(
            JSON.stringify({
              active: true,
              status: 'investigating',
              severity: 'warning',
              summary: 'The system is above the alert threshold (30.00% vs. 20.00%).',
              human_approval_required: true,
              recommended_actions: [
                'Inspect the highest-error route in the observability dashboard and confirm the failure pattern.',
              ],
              verification_steps: ['Review the selected trace for the failing route.'],
              approval_required_for: ['Rollback or redeploy a service change'],
              checked_at: '2026-11-10T12:00:00Z',
            }),
            { status: 200, headers: { 'Content-Type': 'application/json' } },
          )
        }

        return new Response(JSON.stringify([]), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        })
      }),
    )

    window.history.pushState(null, '', '/observability')

    render(<App />)

    expect(await screen.findByText('On-call review')).toBeTruthy()
    expect(screen.getByText(/Human approval required/i)).toBeTruthy()
  })
})
