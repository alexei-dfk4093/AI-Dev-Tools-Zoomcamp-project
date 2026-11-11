import { useCallback, useEffect, useState, type MouseEvent } from 'react'
import DiscussionPage from './DiscussionPage'
import { readApiResponse } from './api'
import {
  apiErrorDetail,
  describeError,
  isNewsArticle,
  type NewsArticle,
} from './news'
import './App.css'

type NewsState = 'loading' | 'ready' | 'error'

type StampParts = {
  date: string
  clock: string
}

/**
 * Split a publication timestamp into an exact UTC date and clock stamp.
 * Providers publish in UTC, so the stamp stays unambiguous for every reader.
 */
function getStampParts(isoString: string | null): StampParts | null {
  if (!isoString) return null
  try {
    const date = new Date(isoString)
    if (isNaN(date.getTime())) return null

    const month = new Intl.DateTimeFormat('en-US', {
      month: 'short',
      timeZone: 'UTC',
    })
      .format(date)
      .toUpperCase()
    const day = String(date.getUTCDate()).padStart(2, '0')
    const hours = String(date.getUTCHours()).padStart(2, '0')
    const minutes = String(date.getUTCMinutes()).padStart(2, '0')
    const seconds = String(date.getUTCSeconds()).padStart(2, '0')

    return { date: `${month} ${day}`, clock: `${hours}:${minutes}:${seconds}Z` }
  } catch {
    return null
  }
}

function formatTimeAgo(isoString: string | null): string {
  if (!isoString) return ''
  try {
    const date = new Date(isoString)
    if (isNaN(date.getTime())) return ''

    const now = new Date()
    const diffMs = now.getTime() - date.getTime()
    const diffSec = Math.floor(diffMs / 1000)
    const diffMin = Math.floor(diffSec / 60)
    const diffHours = Math.floor(diffMin / 60)
    const diffDays = Math.floor(diffHours / 24)

    if (diffSec < 60) {
      return 'Just now'
    }
    if (diffMin < 60) {
      return `${diffMin}m ago`
    }
    if (diffHours < 24) {
      return `${diffHours}h ago`
    }
    if (diffDays === 1) {
      return 'Yesterday'
    }
    if (diffDays < 7) {
      return `${diffDays}d ago`
    }
    return date.toLocaleDateString(undefined, {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
    })
  } catch {
    return ''
  }
}

function mergeArticles(
  incoming: NewsArticle[],
  existing: NewsArticle[],
): NewsArticle[] {
  const seen = new Set<string>()
  const merged: NewsArticle[] = []

  for (const article of [...incoming, ...existing]) {
    if (seen.has(article.id)) continue
    seen.add(article.id)
    merged.push(article)
  }

  return merged
}

function getDiscussionArticle(): NewsArticle | null {
  const serializedArticle = new URLSearchParams(window.location.search).get('article')
  if (!serializedArticle) return null

  try {
    const article: unknown = JSON.parse(serializedArticle)
    return isNewsArticle(article) ? article : null
  } catch {
    return null
  }
}

function getDiscussionUrl(article: NewsArticle): string {
  const query = new URLSearchParams({
    article: JSON.stringify({
      ...article,
      article_content: undefined,
      summary: article.summary?.slice(0, 2500) ?? null,
    }),
  })
  return `/discussion?${query.toString()}`
}

function App() {
  const [articles, setArticles] = useState<NewsArticle[]>([])
  const [isDiscussionPage, setIsDiscussionPage] = useState(
    () => window.location.pathname === '/discussion',
  )
  const [discussionArticle, setDiscussionArticle] = useState<NewsArticle | null>(
    getDiscussionArticle,
  )
  const [newsState, setNewsState] = useState<NewsState>('loading')
  const [errorMessage, setErrorMessage] = useState('')
  const [reloadCount, setReloadCount] = useState(0)
  const [loadingMore, setLoadingMore] = useState(false)
  const [loadMoreError, setLoadMoreError] = useState('')
  const [hasMore, setHasMore] = useState(true)
  const [isRefreshing, setIsRefreshing] = useState(false)

  useEffect(() => {
    function syncPageWithLocation() {
      const isDiscussion = window.location.pathname === '/discussion'
      setIsDiscussionPage(isDiscussion)
      setDiscussionArticle(isDiscussion ? getDiscussionArticle() : null)
    }

    window.addEventListener('popstate', syncPageWithLocation)
    return () => window.removeEventListener('popstate', syncPageWithLocation)
  }, [])

  useEffect(() => {
    // Keep the already-loaded feed (and scroll position) when returning
    // from a discussion page; fetch only when the feed is empty or the
    // user explicitly asked for a reload.
    if (isDiscussionPage || articles.length > 0) return

    const controller = new AbortController()

    async function loadNews() {
      setNewsState('loading')
      setErrorMessage('')
      setHasMore(true)

      try {
        const response = await fetch('/api/v1/news?limit=20&offset=0', {
          signal: controller.signal,
        })
        const payload = await readApiResponse(response, 'News service')

        if (!response.ok) {
          throw new Error(
            apiErrorDetail(payload, 'Unable to load news right now.'),
          )
        }

        if (!Array.isArray(payload) || !payload.every(isNewsArticle)) {
          throw new Error('The news service returned data in an unexpected format.')
        }

        setArticles(payload)
        setNewsState('ready')
        if (payload.length < 20) {
          setHasMore(false)
        }
      } catch (error) {
        if (controller.signal.aborted) return
        setErrorMessage(
          describeError(
            error,
            'Unable to reach the news service. Check your connection and try again.',
          ),
        )
        setNewsState('error')
      }
    }

    void loadNews()
    return () => controller.abort()
  }, [isDiscussionPage, reloadCount, articles.length])

  const handleRefresh = useCallback(async (force: boolean) => {
    if (isRefreshing) return
    setIsRefreshing(true)
    try {
      const response = await fetch(
        `/api/v1/news?limit=20&offset=0${force ? '&refresh=true' : ''}`,
      )
      const payload = await readApiResponse(response, 'News service')

      if (!response.ok) {
        throw new Error(
          apiErrorDetail(payload, 'Unable to refresh the news feed right now.'),
        )
      }

      if (!Array.isArray(payload) || !payload.every(isNewsArticle)) {
        throw new Error('The news service returned data in an unexpected format.')
      }

      setArticles((previous) => mergeArticles(payload, previous))
      setNewsState('ready')
      setHasMore((previous) => previous || payload.length >= 20)
    } catch (error) {
      setErrorMessage(
        describeError(error, 'Unable to refresh the news feed right now.'),
      )
    } finally {
      setIsRefreshing(false)
    }
  }, [isRefreshing])

  // Keep the visible feed current without a page reload.
  useEffect(() => {
    if (isDiscussionPage) return

    const intervalId = window.setInterval(() => {
      if (document.visibilityState === 'hidden') return
      void handleRefresh(false)
    }, 120000)

    return () => window.clearInterval(intervalId)
  }, [isDiscussionPage, handleRefresh])

  async function handleLoadMore() {
    if (loadingMore || !hasMore) return
    setLoadingMore(true)
    setLoadMoreError('')
    try {
      const response = await fetch(
        `/api/v1/news?limit=20&offset=${articles.length}`,
      )
      const payload = await readApiResponse(response, 'News service')
      if (!response.ok) {
        throw new Error(
          apiErrorDetail(payload, 'Unable to load more news right now.'),
        )
      }
      if (!Array.isArray(payload) || !payload.every(isNewsArticle)) {
        throw new Error('The news service returned data in an unexpected format.')
      }

      const existingIds = new Set(articles.map((article) => article.id))
      const newArticles = payload.filter((article) => !existingIds.has(article.id))
      if (payload.length === 0 || newArticles.length === 0) {
        setHasMore(false)
        return
      }

      setArticles((previous) => [...previous, ...newArticles])
    } catch (error) {
      setLoadMoreError(
        describeError(error, 'Unable to load more news right now.'),
      )
    } finally {
      setLoadingMore(false)
    }
  }

  function openDiscussion(
    event: MouseEvent<HTMLAnchorElement>,
    article: NewsArticle,
  ) {
    if (
      event.defaultPrevented ||
      event.button !== 0 ||
      event.metaKey ||
      event.ctrlKey ||
      event.shiftKey ||
      event.altKey
    ) {
      return
    }

    event.preventDefault()
    window.history.pushState(null, '', getDiscussionUrl(article))
    setDiscussionArticle(article)
    setIsDiscussionPage(true)
    window.scrollTo({ top: 0 })
  }

  function returnToNews() {
    window.history.replaceState(null, '', '/')
    setDiscussionArticle(null)
    setIsDiscussionPage(false)
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand-block">
          <div className="brand-mark" aria-hidden="true">
            <svg viewBox="0 0 48 48" focusable="false">
              <circle className="logo-orbit" cx="24" cy="24" r="20" />
              <path className="logo-chart" d="M12 30h5l4-8 5 5 5-10 5 3" />
              <circle className="logo-node" cx="31" cy="17" r="2.5" />
              <path className="logo-base" d="M12 36h24" />
            </svg>
          </div>
          <div>
            <p className="eyebrow">Economic intelligence</p>
            <h1>EcoMind</h1>
          </div>
        </div>
        {isDiscussionPage && (
          <button className="back-to-news" onClick={returnToNews} type="button">
            ← Back to headlines
          </button>
        )}
      </header>

      <main className={isDiscussionPage ? 'main-content discussion-main' : 'main-content'}>
        {isDiscussionPage ? (
          discussionArticle ? (
            <DiscussionPage article={discussionArticle} key={discussionArticle.id} />
          ) : (
            <section className="feed-message discussion-missing" role="alert">
              <p>This discussion link does not include a valid headline.</p>
              <button className="retry-button" onClick={returnToNews} type="button">
                Back to headlines
              </button>
            </section>
          )
        ) : (
          <>
            {(newsState === 'ready' || newsState === 'loading') && (
              <div className="news-toolbar">
                <p className="feed-mode">
                  Market <span>Wire</span>
                </p>
                <div className="feed-status">
                  <p className="feed-updated">
                    {newsState === 'ready' && articles.length > 0
                      ? `${articles.length} stories · latest ${
                          formatTimeAgo(articles[0]?.published_at ?? null) || '—'
                        }`
                      : 'Listening to the wire…'}
                  </p>
                  <button
                    aria-label="Refresh the news feed"
                    className="feed-refresh"
                    disabled={isRefreshing}
                    onClick={() => void handleRefresh(true)}
                    type="button"
                  >
                    {isRefreshing ? 'Refreshing…' : 'Refresh'}
                  </button>
                </div>
              </div>
            )}
            <section
              className={
                'news-feed' + (newsState === 'loading' ? ' is-loading' : '')
              }
              aria-label="News headlines and summaries"
            >
              {newsState === 'loading' && (
                <>
                  <p className="feed-message feed-loading" role="status">
                    Loading the latest news…
                  </p>
                  {[0, 1, 2].map((index) => (
                    <div className="news-skeleton" key={index} aria-hidden="true" />
                  ))}
                </>
              )}

              {newsState === 'error' && (
                <div className="feed-message error-message" role="alert">
                  <p>{errorMessage}</p>
                  <button
                    className="retry-button"
                    onClick={() => setReloadCount((count) => count + 1)}
                    type="button"
                  >
                    Try again
                  </button>
                </div>
              )}

              {newsState === 'ready' && articles.length === 0 && (
                <p className="feed-message">No economics headlines found.</p>
              )}

              {newsState === 'ready' &&
                articles.map((item) => {
                  const stamp = getStampParts(item.published_at)

                  return (
                    <article key={item.id} className="news-card">
                      {stamp ? (
                        <time
                          className="story-time"
                          dateTime={item.published_at ?? ''}
                          title={`${item.published_at} (UTC)`}
                        >
                          <span className="story-date">{stamp.date}</span>
                          <span className="story-clock">{stamp.clock}</span>
                        </time>
                      ) : (
                        <span aria-hidden="true" className="story-time story-time-empty">
                          —
                        </span>
                      )}
                      <div className="story-content">
                        <div className="news-meta">
                          {item.source && (
                            <span className="source">{item.source}</span>
                          )}
                          {item.published_at && (
                            <time
                              dateTime={item.published_at}
                              title={new Date(
                                item.published_at,
                              ).toLocaleString(undefined, {
                                dateStyle: 'medium',
                                timeStyle: 'short',
                              })}
                            >
                              {formatTimeAgo(item.published_at)}
                            </time>
                          )}
                        </div>

                        <h2>
                          <a
                            href={getDiscussionUrl(item)}
                            onClick={(event) => openDiscussion(event, item)}
                          >
                            {item.title}
                          </a>
                        </h2>
                        <div className="story-summary">
                          <p
                          className={
                            'story-summary-label' +
                            (item.summary_source === 'publisher'
                              ? ' publisher'
                              : item.summary_source === 'unavailable'
                                ? ' unavailable'
                                : '')
                          }
                        >
                            {item.summary_source === 'ai'
                              ? 'AI-generated summary'
                              : item.summary_source === 'publisher'
                                ? 'Publisher description'
                                : 'Summary unavailable'}
                          </p>
                          <p>
                            {item.summary ??
                              'No article summary is available from the source yet.'}
                          </p>
                        </div>
                      </div>
                      <a
                        aria-label={`Open article: ${item.title}`}
                        className="story-marker"
                        href={item.url}
                        rel="noreferrer"
                        target="_blank"
                      >
                        ↗
                      </a>
                    </article>
                  )
                })}
            </section>

            {newsState === 'ready' && articles.length > 0 && hasMore && (
              <div className="load-more-container">
                {loadMoreError && (
                  <p className="load-more-error" role="alert">
                    {loadMoreError}
                  </p>
                )}
                <button
                  className="load-more-button"
                  disabled={loadingMore}
                  onClick={handleLoadMore}
                  type="button"
                >
                  {loadingMore
                    ? 'Loading more stories…'
                    : loadMoreError
                      ? 'Try Again'
                      : 'Load More News'}
                </button>
              </div>
            )}
          </>
        )}
      </main>

      <footer className="app-foot">
        <div className="main-content">
          <p>EcoMind · AI-assisted financial intelligence · Not investment advice</p>
        </div>
      </footer>
    </div>
  )
}

export default App
