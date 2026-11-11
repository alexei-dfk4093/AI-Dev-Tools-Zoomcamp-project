export async function readApiResponse(
  response: Response,
  serviceName: string,
): Promise<unknown> {
  const body = await response.text()
  if (!body.trim()) {
    if (response.status === 429) {
      throw new Error(
        `${serviceName} request was rate-limited (HTTP 429). Please wait before trying again.`,
      )
    }

    throw new Error(
      `${serviceName} returned an empty response (HTTP ${response.status}). Check that the backend is running and inspect its logs.`,
    )
  }

  try {
    return JSON.parse(body) as unknown
  } catch {
    if (response.status === 429) {
      throw new Error(
        `${serviceName} request was rate-limited (HTTP 429). Please wait before trying again.`,
      )
    }

    throw new Error(
      `${serviceName} returned an invalid response (HTTP ${response.status}). Check the backend and provider logs.`,
    )
  }
}
