import type { ApiError } from "./problem-details";

export function ErrorMessage({ error }: { error: ApiError }) {
  const message =
    error.kind === "unknown"
      ? "Could not reach the server. Check your connection and try again."
      : error.status >= 500
        ? "Something went wrong on our side. Try again."
        : (error.detail ?? error.title);

  return (
    <div role="alert" className="space-y-1 text-red-700">
      <p>{message}</p>
      {error.kind === "problem" &&
        error.status >= 500 &&
        error.requestId !== undefined && (
          <p className="break-words text-sm">Request ID: {error.requestId}</p>
        )}
    </div>
  );
}
