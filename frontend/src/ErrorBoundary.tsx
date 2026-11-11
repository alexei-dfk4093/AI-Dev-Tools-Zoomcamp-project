import { Component, type ErrorInfo, type ReactNode } from 'react'

interface ErrorBoundaryProps {
  children: ReactNode
}

interface ErrorBoundaryState {
  hasError: boolean
}

/**
 * Last-resort render guard: shows a recovery prompt instead of a blank
 * page when an unexpected rendering error occurs.
 */
class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { hasError: false }

  static getDerivedStateFromError(): ErrorBoundaryState {
    return { hasError: true }
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error('Unexpected interface error:', error, info.componentStack)
  }

  render(): ReactNode {
    if (this.state.hasError) {
      return (
        <section className="feed-message error-message" role="alert">
          <p>
            Something went wrong while rendering the page. Please reload to
            continue.
          </p>
          <button
            className="retry-button"
            onClick={() => window.location.reload()}
            type="button"
          >
            Reload
          </button>
        </section>
      )
    }

    return this.props.children
  }
}

export default ErrorBoundary
