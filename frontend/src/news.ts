export interface NewsArticle {
  id: string
  source: string | null
  published_at: string | null
  url: string
  title: string
  summary: string | null
  article_content?: string | null
  summary_source: 'ai' | 'publisher' | 'unavailable'
  importance: 'important' | 'other'
  category?: 'economic' | 'other'
}

export function isNewsArticle(value: unknown): value is NewsArticle {
  if (typeof value !== 'object' || value === null) return false

  const article = value as Record<string, unknown>
  if (typeof article.url !== 'string') return false
  try {
    const protocol = new URL(article.url).protocol
    if (protocol !== 'http:' && protocol !== 'https:') return false
  } catch {
    return false
  }

  return (
    typeof article.id === 'string' &&
    (typeof article.source === 'string' || article.source === null) &&
    (typeof article.published_at === 'string' ||
      article.published_at === null) &&
    typeof article.title === 'string' &&
    (typeof article.summary === 'string' || article.summary === null) &&
    (article.article_content === undefined ||
      typeof article.article_content === 'string' ||
      article.article_content === null) &&
    (article.summary_source === 'ai' ||
      article.summary_source === 'publisher' ||
      article.summary_source === 'unavailable') &&
    (article.importance === 'important' || article.importance === 'other') &&
    (article.category === undefined ||
      article.category === 'economic' ||
      article.category === 'other')
  )
}

/**
 * Converts an unexpected failure into a message suitable for the UI.
 * TypeErrors typically mean a network failure (fetch refused, CORS, offline),
 * where the browser's raw message is not actionable for the user.
 */
export function describeError(error: unknown, fallback: string): string {
  if (error instanceof TypeError) {
    return fallback
  }
  if (error instanceof Error && error.message) {
    return error.message
  }
  return fallback
}

/**
 * Extracts the human-readable `detail` message from a FastAPI JSON error
 * body, falling back to a default message for other response shapes.
 */
export function apiErrorDetail(
  payload: unknown,
  defaultMessage: string,
): string {
  if (
    typeof payload === 'object' &&
    payload !== null &&
    'detail' in payload &&
    typeof (payload as { detail?: unknown }).detail === 'string'
  ) {
    return (payload as { detail: string }).detail
  }
  return defaultMessage
}
