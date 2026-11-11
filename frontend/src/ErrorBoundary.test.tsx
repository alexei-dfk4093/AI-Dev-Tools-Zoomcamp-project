// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, screen } from '@testing-library/react'

import ErrorBoundary from './ErrorBoundary'

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

function ThrowingChild(): never {
  throw new Error('boom')
}

describe('ErrorBoundary', () => {
  it('renders children when no error occurs', () => {
    render(
      <ErrorBoundary>
        <p>Working content</p>
      </ErrorBoundary>,
    )
    expect(screen.getByText('Working content')).toBeTruthy()
  })

  it('shows a recovery message when rendering fails', () => {
    const silenceConsole = vi
      .spyOn(console, 'error')
      .mockImplementation(() => {})
    render(
      <ErrorBoundary>
        <ThrowingChild />
      </ErrorBoundary>,
    )

    expect(
      screen.getByText(/Something went wrong while rendering/),
    ).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Reload' })).toBeTruthy()
    expect(silenceConsole).toHaveBeenCalled()
  })
})
