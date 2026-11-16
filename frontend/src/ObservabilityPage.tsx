import { useEffect, useMemo, useState } from 'react'
import { readApiResponse } from './api'
import { apiErrorDetail, describeError } from './news'

type RouteMetric = {
  method: string
  route: string
  request_count: number
  error_count: number
  avg_duration_ms: number
  p95_duration_ms: number
}

type JourneySummary = {
  trace_id: string
  name: string
  started_at: string
  duration_ms: number
  status: string
  span_count: number
  error_count: number
  log_count: number
}

type TraceSpan = {
  trace_id: string
  span_id: string
  parent_span_id: string | null
  name: string
  started_at: string
  duration_ms: number
  status: string
  attributes: Record<string, unknown>
}

type TraceLog = {
  trace_id: string | null
  span_id: string | null
  level: string
  logger_name: string
  message: string
  recorded_at: string
}

type TraceMetric = {
  name: string
  value: number
  dimensions: Record<string, unknown>
  trace_id: string | null
  recorded_at: string
}

type TraceDetail = {
  trace_id: string
  spans: TraceSpan[]
  logs: TraceLog[]
  metrics: TraceMetric[]
}

type ObservabilityMetrics = {
  generated_at: string
  total_requests: number
  total_errors: number
  routes: RouteMetric[]
  ai_requests: Array<{ model: string; outcome: string; count: number }>
  ai_quota_pauses: number
  provider_fetches: Array<{ provider: string; outcome: string; count: number }>
  refreshes: number
  articles_saved: number
}

type AlertStatus = {
  active: boolean
  severity: string
  message: string
  error_rate: number
  total_requests: number
  total_errors: number
  threshold: number
  checked_at: string
}

type OnCallInvestigation = {
  active: boolean
  status: string
  severity: string
  summary: string
  human_approval_required: boolean
  recommended_actions: string[]
  verification_steps: string[]
  approval_required_for: string[]
  checked_at: string
}

type PageState = 'loading' | 'ready' | 'error'

function formatTimestamp(isoString: string | null | undefined): string {
  if (!isoString) return '—'

  const date = new Date(isoString)
  if (Number.isNaN(date.getTime())) return '—'

  return date.toLocaleString(undefined, {
    dateStyle: 'medium',
    timeStyle: 'short',
    timeZone: 'UTC',
  })
}

function formatDuration(value: number): string {
  return `${Number(value).toFixed(1)} ms`
}

function toSafeString(value: unknown): string {
  if (typeof value === 'string') return value
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  return JSON.stringify(value)
}

function getRouteAttributes(attributes: Record<string, unknown>): string[] {
  const allowedKeys = new Set([
    'method',
    'route',
    'http.route',
    'http.status_code',
    'status',
    'provider',
    'model',
    'outcome',
  ])

  return Object.entries(attributes)
    .filter(([key]) => allowedKeys.has(key))
    .map(([key, value]) => `${key}: ${toSafeString(value)}`)
    .slice(0, 4)
}

export default function ObservabilityPage() {
  const [metrics, setMetrics] = useState<ObservabilityMetrics | null>(null)
  const [journeys, setJourneys] = useState<JourneySummary[]>([])
  const [alert, setAlert] = useState<AlertStatus | null>(null)
  const [onCall, setOnCall] = useState<OnCallInvestigation | null>(null)
  const [selectedTraceId, setSelectedTraceId] = useState<string | null>(null)
  const [traceDetail, setTraceDetail] = useState<TraceDetail | null>(null)
  const [pageState, setPageState] = useState<PageState>('loading')
  const [errorMessage, setErrorMessage] = useState('')
  const [loadingTrace, setLoadingTrace] = useState(false)

  useEffect(() => {
    let active = true

    async function loadObservability() {
      setPageState('loading')
      setErrorMessage('')

      try {
        const [metricsResponse, journeysResponse, alertResponse, onCallResponse] = await Promise.all([
          fetch('/api/v1/observability/metrics'),
          fetch('/api/v1/observability/journeys'),
          fetch('/api/v1/observability/alerts'),
          fetch('/api/v1/observability/oncall'),
        ])

        const metricsPayload = await readApiResponse(metricsResponse, 'Observability API')
        const journeyPayload = await readApiResponse(journeysResponse, 'Observability API')
        const alertPayload = await readApiResponse(alertResponse, 'Observability API')
        const onCallPayload = await readApiResponse(onCallResponse, 'Observability API')

        if (!metricsResponse.ok) {
          throw new Error(apiErrorDetail(metricsPayload, 'Unable to load observability metrics.'))
        }

        if (!journeysResponse.ok) {
          throw new Error(apiErrorDetail(journeyPayload, 'Unable to load recent journeys.'))
        }

        if (!alertResponse.ok) {
          throw new Error(apiErrorDetail(alertPayload, 'Unable to load alert status.'))
        }

        if (!onCallResponse.ok) {
          throw new Error(apiErrorDetail(onCallPayload, 'Unable to load the on-call investigation.'))
        }

        const nextMetrics = metricsPayload as ObservabilityMetrics
        const nextJourneys = (journeyPayload as { journeys?: JourneySummary[] })?.journeys ?? []
        const nextAlert = alertPayload as AlertStatus
        const nextOnCall = onCallPayload as OnCallInvestigation

        if (!nextMetrics || !Array.isArray(nextJourneys) || !nextAlert || !nextOnCall) {
          throw new Error('The observability API returned an unexpected payload.')
        }

        if (!active) return

        setMetrics(nextMetrics)
        setJourneys(nextJourneys)
        setAlert(nextAlert)
        setOnCall(nextOnCall)
        setSelectedTraceId(nextJourneys[0]?.trace_id ?? null)
        setPageState('ready')
      } catch (error) {
        if (!active) return
        setErrorMessage(
          describeError(error, 'Unable to load the observability dashboard right now.'),
        )
        setPageState('error')
      }
    }

    void loadObservability()
    return () => {
      active = false
    }
  }, [])

  useEffect(() => {
    if (!selectedTraceId) {
      setTraceDetail(null)
      return
    }

    let active = true

    async function loadTrace() {
      setLoadingTrace(true)
      try {
        const response = await fetch(`/api/v1/observability/traces/${selectedTraceId}`)
        const payload = await readApiResponse(response, 'Observability API')

        if (!response.ok) {
          throw new Error(apiErrorDetail(payload, 'Unable to load this trace.'))
        }

        const nextDetail = payload as TraceDetail
        if (!active) return
        setTraceDetail(nextDetail)
      } catch (error) {
        if (!active) return
        setTraceDetail(null)
        setErrorMessage(
          describeError(error, 'Unable to load the selected trace detail right now.'),
        )
      } finally {
        if (active) {
          setLoadingTrace(false)
        }
      }
    }

    void loadTrace()
    return () => {
      active = false
    }
  }, [selectedTraceId])

  const selectedJourney = useMemo(
    () => journeys.find((journey) => journey.trace_id === selectedTraceId) ?? null,
    [journeys, selectedTraceId],
  )

  if (pageState === 'error') {
    return (
      <section className="observability-page" aria-live="polite">
        <div className="observability-shell">
          <div className="feed-message error-message" role="alert">
            <p>{errorMessage}</p>
          </div>
        </div>
      </section>
    )
  }

  if (pageState === 'loading' && !metrics) {
    return (
      <section className="observability-page" aria-live="polite">
        <div className="observability-shell">
          <p className="feed-message feed-loading">Loading observability data…</p>
        </div>
      </section>
    )
  }

  if (!metrics) {
    return null
  }

  const traceStatus = selectedJourney?.status ?? 'ok'

  return (
    <section className="observability-page">
      <div className="observability-shell">
        <div className="observability-header">
          <div>
            <p className="eyebrow">System health</p>
            <h2>Observability</h2>
          </div>
          <p className="observability-generated">
            Updated {formatTimestamp(metrics.generated_at)}
          </p>
        </div>

        {alert && alert.active && (
          <div className={'alert-banner ' + alert.severity} role="alert">
            <strong>User-impact alert</strong>
            <span>{alert.message}</span>
          </div>
        )}

        {onCall && onCall.active && (
          <div className="alert-banner warning" role="alert">
            <strong>On-call review</strong>
            <span>{onCall.summary}</span>
          </div>
        )}

        <div className="observability-summary" aria-label="Telemetry summary">
          <article className="summary-card">
            <span>Total requests</span>
            <strong>{metrics.total_requests}</strong>
          </article>
          <article className="summary-card">
            <span>Errors</span>
            <strong>{metrics.total_errors}</strong>
          </article>
          <article className="summary-card">
            <span>Quota pauses</span>
            <strong>{metrics.ai_quota_pauses}</strong>
          </article>
          <article className="summary-card">
            <span>Articles saved</span>
            <strong>{metrics.articles_saved}</strong>
          </article>
        </div>

        {onCall && onCall.active && (
          <section className="observability-panel" aria-label="On-call investigation summary">
            <h3>On-call investigation</h3>
            <p>{onCall.summary}</p>
            <ul className="attribute-list">
              {onCall.recommended_actions.map((action) => (
                <li key={action}>{action}</li>
              ))}
            </ul>
            <p className="empty-panel">Human approval required before production-impacting actions.</p>
          </section>
        )}

        <div className="observability-grid">
          <section className="observability-panel">
            <h3>Request routes</h3>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Route</th>
                    <th>Count</th>
                    <th>Errors</th>
                    <th>Avg</th>
                    <th>P95</th>
                  </tr>
                </thead>
                <tbody>
                  {metrics.routes.length === 0 ? (
                    <tr>
                      <td colSpan={5}>No request telemetry recorded yet.</td>
                    </tr>
                  ) : (
                    metrics.routes.map((route) => (
                      <tr key={`${route.method}:${route.route}`}>
                        <td>
                          {route.method} {route.route}
                        </td>
                        <td>{route.request_count}</td>
                        <td>{route.error_count}</td>
                        <td>{formatDuration(route.avg_duration_ms)}</td>
                        <td>{formatDuration(route.p95_duration_ms)}</td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </section>

          <aside className="observability-panel">
            <h3>Recent journeys</h3>
            <div className="journey-list" role="list">
              {journeys.length === 0 ? (
                <p className="empty-panel">No request traces have been captured yet.</p>
              ) : (
                journeys.map((journey) => (
                  <button
                    key={journey.trace_id}
                    className={
                      'journey-item' + (selectedTraceId === journey.trace_id ? ' selected' : '')
                    }
                    onClick={() => setSelectedTraceId(journey.trace_id)}
                    type="button"
                  >
                    <span className="journey-topline">
                      <span className="journey-name">{journey.name}</span>
                      <span className={'status-pill ' + journey.status}>{journey.status}</span>
                    </span>
                    <span className="journey-meta">
                      {journey.trace_id} · {formatDuration(journey.duration_ms)}
                    </span>
                    <span className="journey-meta">
                      {journey.span_count} spans · {journey.log_count} logs · {journey.error_count}{' '}
                      errors
                    </span>
                  </button>
                ))
              )}
            </div>
          </aside>
        </div>

        <section className="observability-panel trace-panel">
          <div className="trace-header">
            <div>
              <h3>Selected trace</h3>
              <p>{selectedTraceId ?? 'No trace selected'}</p>
            </div>
            {selectedJourney && (
              <span className={'status-pill ' + traceStatus}>{traceStatus}</span>
            )}
          </div>

          {loadingTrace ? (
            <p className="feed-message feed-loading">Loading trace details…</p>
          ) : traceDetail ? (
            <div className="trace-columns">
              <div className="trace-column">
                <h4>Spans</h4>
                <ul className="trace-list">
                  {traceDetail.spans.map((span) => (
                    <li key={span.span_id}>
                      <div className="trace-line-top">
                        <strong>{span.name}</strong>
                        <span className={'status-pill ' + span.status}>{span.status}</span>
                      </div>
                      <small>{formatDuration(span.duration_ms)}</small>
                      {getRouteAttributes(span.attributes).length > 0 && (
                        <ul className="attribute-list">
                          {getRouteAttributes(span.attributes).map((attribute) => (
                            <li key={`${span.span_id}:${attribute}`}>{attribute}</li>
                          ))}
                        </ul>
                      )}
                    </li>
                  ))}
                </ul>
              </div>

              <div className="trace-column">
                <h4>Logs</h4>
                <ul className="trace-list">
                  {traceDetail.logs.length === 0 ? (
                    <li>No log entries for this journey.</li>
                  ) : (
                    traceDetail.logs.map((log, index) => (
                      <li key={`${log.trace_id ?? 'trace'}:${log.recorded_at}:${index}`}>
                        <div className="trace-line-top">
                          <strong>{log.level}</strong>
                          <small>{log.logger_name}</small>
                        </div>
                        <p>{log.message}</p>
                        <small>{formatTimestamp(log.recorded_at)}</small>
                      </li>
                    ))
                  )}
                </ul>
              </div>

              <div className="trace-column">
                <h4>Metric samples</h4>
                <ul className="trace-list">
                  {traceDetail.metrics.length === 0 ? (
                    <li>No metric samples for this trace.</li>
                  ) : (
                    traceDetail.metrics.map((metric, index) => (
                      <li key={`${metric.name}:${metric.recorded_at}:${index}`}>
                        <div className="trace-line-top">
                          <strong>{metric.name}</strong>
                          <span>{metric.value}</span>
                        </div>
                        <small>
                          {Object.entries(metric.dimensions)
                            .map(([key, value]) => `${key}=${toSafeString(value)}`)
                            .join(', ') || 'No dimensions'}
                        </small>
                      </li>
                    ))
                  )}
                </ul>
              </div>
            </div>
          ) : (
            <p className="empty-panel">Select a journey to inspect its trace.</p>
          )}
        </section>
      </div>
    </section>
  )
}
