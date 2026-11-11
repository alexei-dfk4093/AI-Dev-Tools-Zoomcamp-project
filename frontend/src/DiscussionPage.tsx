import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from 'react'
import { readApiResponse } from './api'
import { apiErrorDetail, describeError, isNewsArticle, type NewsArticle } from './news'

type Speaker = 'user' | 'assistant'

interface DiscussionMessage {
  speaker: Speaker
  content: string
}

interface DiscussionResponse {
  reply: string
}

interface DiscussionModelOption {
  id: string
  label: string
}

interface DiscussionModelsResponse {
  models: DiscussionModelOption[]
  default_model: string
}

type MarketAssetKind = 'company' | 'etf' | 'index'

interface AffectedAsset {
  name: string
  symbol: string | null
  kind: MarketAssetKind
  relationship: 'mentioned' | 'potential'
  rationale: string
}

type ImpactDirection = 'positive' | 'neutral' | 'negative'

const IMPACT_LABELS: Record<ImpactDirection, string> = {
  positive: 'Positive',
  neutral: 'Neutral',
  negative: 'Negative',
}

interface ArticleImpact {
  direction: ImpactDirection
  summary: string
  rationale: string
}

interface ArticleInsightsResponse {
  assets: AffectedAsset[]
  impact: ArticleImpact
  suggested_questions: string[]
  research_notes?: string | null
}

function isDiscussionResponse(value: unknown): value is DiscussionResponse {
  if (typeof value !== 'object' || value === null) return false

  const response = value as Record<string, unknown>
  return typeof response.reply === 'string' && response.reply.trim().length > 0
}

function isDiscussionModelsResponse(value: unknown): value is DiscussionModelsResponse {
  if (typeof value !== 'object' || value === null) return false
  const response = value as Record<string, unknown>
  return (
    typeof response.default_model === 'string' &&
    Array.isArray(response.models) &&
    response.models.every(
      (model) =>
        typeof model === 'object' &&
        model !== null &&
        typeof (model as Record<string, unknown>).id === 'string' &&
        typeof (model as Record<string, unknown>).label === 'string',
    )
  )
}

function isArticleInsightsResponse(
  value: unknown,
): value is ArticleInsightsResponse {
  if (typeof value !== 'object' || value === null) return false
  const response = value as Record<string, unknown>

  const impact = response.impact
  if (typeof impact !== 'object' || impact === null) return false
  const impactRecord = impact as Record<string, unknown>
  if (
    (impactRecord.direction !== 'positive' &&
      impactRecord.direction !== 'neutral' &&
      impactRecord.direction !== 'negative') ||
    typeof impactRecord.summary !== 'string' ||
    typeof impactRecord.rationale !== 'string'
  ) {
    return false
  }

  if (
    !Array.isArray(response.assets) ||
    !response.assets.every((asset) => {
      if (typeof asset !== 'object' || asset === null) return false
      const item = asset as Record<string, unknown>
      return (
        typeof item.name === 'string' &&
        (typeof item.symbol === 'string' || item.symbol === null) &&
        (item.kind === 'company' || item.kind === 'etf' || item.kind === 'index') &&
        (item.relationship === 'mentioned' || item.relationship === 'potential') &&
        typeof item.rationale === 'string'
      )
    })
  ) {
    return false
  }

  return (
    Array.isArray(response.suggested_questions) &&
    response.suggested_questions.every(
      (question) => typeof question === 'string',
    )
  )
}

function DiscussionPage({ article }: { article: NewsArticle }) {
  const [story, setStory] = useState(article)
  const [messages, setMessages] = useState<DiscussionMessage[]>([])
  const [question, setQuestion] = useState('')
  const [isSending, setIsSending] = useState(false)
  const [errorMessage, setErrorMessage] = useState('')
  const [availableModels, setAvailableModels] = useState<DiscussionModelOption[]>([])
  const [selectedModel, setSelectedModel] = useState('')
  const [modelError, setModelError] = useState('')
  const [insights, setInsights] = useState<ArticleInsightsResponse | null>(null)
  const [insightsLoading, setInsightsLoading] = useState(true)
  const [insightsError, setInsightsError] = useState('')
  const transcriptRef = useRef<HTMLDivElement | null>(null)
  const composerRef = useRef<HTMLTextAreaElement | null>(null)

  // Keep the newest message and the "analysts thinking" indicator visible.
  useEffect(() => {
    const transcript = transcriptRef.current
    if (transcript) {
      transcript.scrollTop = transcript.scrollHeight
    }
  }, [messages, isSending, errorMessage])

  useEffect(() => {
    const controller = new AbortController()

    async function loadModels() {
      try {
        const response = await fetch('/api/v1/discussions/models', {
          signal: controller.signal,
        })
        const payload = await readApiResponse(response, 'Discussion models')
        if (!response.ok) {
          throw new Error('Available discussion models could not be loaded.')
        }
        if (!isDiscussionModelsResponse(payload)) {
          throw new Error('The discussion service returned invalid model options.')
        }
        setAvailableModels(payload.models)
        setSelectedModel(payload.default_model)
      } catch (error) {
        if (controller.signal.aborted) return
        setModelError(
          describeError(error, 'Available discussion models could not be loaded.'),
        )
      }
    }

    void loadModels()
    return () => controller.abort()
  }, [])

  useEffect(() => {
    const controller = new AbortController()

    async function loadInsights() {
      setInsightsLoading(true)
      setInsightsError('')
      try {
        const response = await fetch(
          `/api/v1/news/${encodeURIComponent(article.id)}/insights`,
          { signal: controller.signal },
        )
        const payload = await readApiResponse(response, 'Article analysis service')
        if (!response.ok) {
          throw new Error(
            apiErrorDetail(
              payload,
              'The article analysis could not be loaded.',
            ),
          )
        }
        if (!isArticleInsightsResponse(payload)) {
          throw new Error('The article analysis service returned invalid data.')
        }
        setInsights(payload)
      } catch (error) {
        if (controller.signal.aborted) return
        setInsightsError(
          describeError(error, 'The article analysis could not be loaded.'),
        )
      } finally {
        if (!controller.signal.aborted) setInsightsLoading(false)
      }
    }

    void loadInsights()
    return () => controller.abort()
  }, [article.id])

  useEffect(() => {
    if (article.article_content) return

    const controller = new AbortController()
    async function loadArticleText() {
      try {
        const response = await fetch(
          `/api/v1/news/${encodeURIComponent(article.id)}`,
          { signal: controller.signal },
        )
        if (response.status === 404) return
        if (!response.ok) {
          throw new Error('The original article text could not be loaded.')
        }

        const payload = await readApiResponse(response, 'Article service')
        if (!isNewsArticle(payload) || payload.id !== article.id) {
          throw new Error('The news service returned unexpected article data.')
        }
        setStory(payload)
      } catch (error) {
        if (controller.signal.aborted) return
        console.warn('Could not load provider-supplied article text.', error)
      }
    }

    void loadArticleText()
    return () => controller.abort()
  }, [article])

  async function submitQuestion(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const message = question.trim()
    if (!message || isSending) return

    setQuestion('')
    setErrorMessage('')
    setMessages((previous) => [...previous, { speaker: 'user', content: message }])
    setIsSending(true)

    try {
      const response = await fetch('/api/v1/discussions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          article: {
            ...story,
            summary: story.summary?.slice(0, 2500) ?? null,
            article_content: story.article_content?.slice(0, 30000) ?? null,
          },
          message,
          history: messages.slice(-12),
          model: selectedModel || undefined,
        }),
      })
      const payload = await readApiResponse(response, 'Discussion service')

      if (!response.ok) {
        throw new Error(
          apiErrorDetail(payload, 'The analyst could not respond right now.'),
        )
      }

      if (!isDiscussionResponse(payload)) {
        throw new Error('The discussion service returned an unexpected response.')
      }

      setMessages((previous) => [
        ...previous,
        { speaker: 'assistant', content: payload.reply },
      ])
    } catch (error) {
      setMessages((previous) => previous.slice(0, -1))
      setQuestion(message)
      setErrorMessage(
        describeError(
          error,
          'An unexpected error occurred while contacting the analysts.',
        ),
      )
    } finally {
      setIsSending(false)
    }
  }

  function applySuggestedQuestion(suggestedQuestion: string) {
    setQuestion(suggestedQuestion)
    composerRef.current?.focus()
  }

  function handleComposerKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (
      event.key === 'Enter' &&
      !event.shiftKey &&
      !event.nativeEvent.isComposing
    ) {
      event.preventDefault()
      event.currentTarget.form?.requestSubmit()
    }
  }

  return (
    <section className="discussion-page" aria-labelledby="discussion-heading">
      <div
        aria-label="Article analysis"
        className="discussion-heading"
        role="region"
      >
        <p className="discussion-eyebrow">Headline discussion</p>
        <h2 id="discussion-heading">{story.title}</h2>
        <div className="discussion-source">
          {story.source && <span className="source">{story.source}</span>}
          {story.published_at && (
            <time dateTime={story.published_at}>
              {new Date(story.published_at).toLocaleString(undefined, {
                dateStyle: 'medium',
                timeStyle: 'short',
              })}
            </time>
          )}
          <a href={story.url} rel="noreferrer" target="_blank">
            Read original source ↗
          </a>
        </div>
        <div className="discussion-assets" aria-live="polite">
          {insightsLoading && (
            <p className="discussion-assets-status">
              Analysing the article: related companies, reported effect, and
              questions this story can answer…
            </p>
          )}
          {insightsError && (
            <p className="discussion-assets-status" role="status">
              {insightsError}
            </p>
          )}
          {insights && (
            <>
              <div
                className={`impact-badge impact-${insights.impact.direction}`}
              >
                <p className="impact-label">Reported effect</p>
                <p className="impact-direction">
                  {IMPACT_LABELS[insights.impact.direction]}
                </p>
                <p className="impact-summary">{insights.impact.summary}</p>
                <p className="impact-rationale">{insights.impact.rationale}</p>
                {insights.research_notes && (
                  <p className="impact-research">
                    <span>Verified online</span>
                    {insights.research_notes}
                  </p>
                )}
              </div>

              {insights.assets.length > 0 && (
                <>
                  <h3 className="discussion-subhead">
                    Related companies &amp; markets
                  </h3>
                  <ul
                    aria-label="Related companies and markets"
                    className="discussion-assets-list"
                    tabIndex={0}
                  >
                    {insights.assets.map((asset, index) => (
                      <li key={`${asset.kind}-${asset.symbol ?? asset.name}-${index}`}>
                        <strong>
                          {asset.name}
                          {asset.symbol && ` (${asset.symbol})`}
                        </strong>
                        <span className="asset-relationship">
                          {asset.relationship === 'mentioned'
                            ? 'named in the article'
                            : 'potential exposure'}
                        </span>
                        <p>{asset.rationale}</p>
                      </li>
                    ))}
                  </ul>
                </>
              )}

            </>
          )}
        </div>
      </div>

      {insights && insights.suggested_questions.length > 0 && (
        <section
          aria-labelledby="suggested-questions-heading"
          className="discussion-suggestions"
        >
          <h3 className="discussion-subhead" id="suggested-questions-heading">
            Questions this article can answer
          </h3>
          <ul
            aria-label="Suggested questions"
            className="suggested-questions"
            tabIndex={0}
          >
            {insights.suggested_questions.map((suggestedQuestion) => (
              <li key={suggestedQuestion}>
                <button
                  className="suggested-question"
                  onClick={() => applySuggestedQuestion(suggestedQuestion)}
                  type="button"
                >
                  {suggestedQuestion}
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}

      <section
        className="discussion-conversation"
        aria-labelledby="conversation-heading"
      >
        <div className="discussion-conversation-heading">
          <div>
            <p className="discussion-eyebrow">Analyst chat</p>
            <h3 id="conversation-heading">Conversation</h3>
          </div>
          <span className="conversation-count">
            {messages.length} {messages.length === 1 ? 'message' : 'messages'}
          </span>
        </div>
        <div
          ref={transcriptRef}
          className="discussion-transcript"
          aria-label="Conversation messages"
          aria-live="polite"
          aria-relevant="additions text"
          role="log"
          tabIndex={0}
        >
          {messages.length === 0 && !isSending && !errorMessage && (
            <div className="transcript-empty">
              <p>Start with a question about this headline.</p>
              <p className="transcript-empty-hint">
                Ask about the reported facts, what changed, or which companies
                and markets may be exposed. Responses are AI-generated analysis,
                not investment advice.
              </p>
            </div>
          )}
          {messages.map((item, index) => (
            <article
              className={`transcript-message ${item.speaker}`}
              key={`${item.speaker}-${index}`}
            >
              <p className="transcript-speaker">
                {item.speaker === 'user' ? 'You' : 'EcoMind analyst'}
              </p>
              <p>{item.content}</p>
            </article>
          ))}
          {isSending && (
            <p className="analysts-thinking" role="status">
              Considering the headline…
            </p>
          )}
          {errorMessage && (
            <p className="discussion-error" role="alert">
              {errorMessage}
            </p>
          )}
        </div>
      </section>

      <form className="discussion-form" onSubmit={submitQuestion}>
        <textarea
          aria-label="Your question"
          id="discussion-question"
          onKeyDown={handleComposerKeyDown}
          maxLength={2000}
          onChange={(event) => setQuestion(event.target.value)}
          placeholder="Ask a follow-up about this story…"
          ref={composerRef}
          rows={1}
          value={question}
        />
        <div className="discussion-form-footer">
          <p className="discussion-composer-hint">
            Enter to send · Shift+Enter for a new line
            <span aria-label={`${question.length} of 2000 characters`}>
              {question.length}/2000
            </span>
          </p>
          {availableModels.length > 0 && (
            <label className="discussion-model-picker">
              <span className="visually-hidden">Response model</span>
              <select
                aria-label="Response model"
                disabled={isSending}
                onChange={(event) => setSelectedModel(event.target.value)}
                value={selectedModel}
              >
                {availableModels.map((model) => (
                  <option key={model.id} value={model.id}>
                    {model.label}
                  </option>
                ))}
              </select>
            </label>
          )}
          {modelError && (
            <span className="discussion-model-error" role="status">
              {modelError}
            </span>
          )}
          <button
            aria-label={isSending ? 'Waiting for response' : 'Send message'}
            disabled={isSending || !question.trim()}
            type="submit"
          >
            {isSending ? '…' : '↑'}
          </button>
        </div>
      </form>
    </section>
  )
}

export default DiscussionPage
