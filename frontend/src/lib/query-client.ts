import { QueryClient } from "@tanstack/react-query";

// One retry covers a dropped connection or a brief 5xx without hiding an outage.
const MAX_RETRIES = 1;

/** The HTTP status an error carries as a numeric `status`, if it carries one. */
function statusOf(error: unknown): number | undefined {
  if (typeof error === "object" && error !== null && "status" in error) {
    const { status } = error;
    return typeof status === "number" ? status : undefined;
  }
  return undefined;
}

/**
 * Whether a failed query runs again.
 *
 * A 4xx is the server's answer to this request, so sending it again cannot
 * change the outcome; anything else (a 5xx, a network error with no status)
 * gets one retry. Reads only `error.status`, which the API client's error type
 * sets.
 */
export function shouldRetry(failureCount: number, error: unknown): boolean {
  const status = statusOf(error);
  if (status !== undefined && status >= 400 && status <= 499) {
    return false;
  }
  return failureCount < MAX_RETRIES;
}

/**
 * The app's query client: queries retry through `shouldRetry`; mutations and
 * every other option keep TanStack Query's defaults.
 */
export function createQueryClient(): QueryClient {
  return new QueryClient({ defaultOptions: { queries: { retry: shouldRetry } } });
}
