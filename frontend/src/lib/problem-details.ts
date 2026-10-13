export type ApiError =
  | {
      kind: "problem";
      status: number;
      title: string;
      detail?: string;
      code?: string;
      requestId?: string;
      fieldErrors: Record<string, string[]>;
    }
  | { kind: "unknown" };

/** Normalize the arbitrary values thrown by the generated fetch client. */
export function toApiError(error: unknown): ApiError {
  if (!isRecord(error)) return { kind: "unknown" };
  const { status, title, detail, code, request_id: requestId, errors } = error;
  if (typeof status !== "number" || typeof title !== "string") {
    return { kind: "unknown" };
  }
  const fields = new Map<string, string[]>();
  if (Array.isArray(errors)) {
    for (const entry of errors) {
      if (!isRecord(entry)) continue;
      const { loc, message } = entry;
      if (!isLocation(loc) || loc[0] !== "body" || typeof message !== "string")
        continue;
      // The body prefix means there is at least one location element.
      const field = String(loc[loc.length - 1]);
      const messages = fields.get(field) ?? [];
      messages.push(message);
      fields.set(field, messages);
    }
  }
  return {
    kind: "problem",
    status,
    title,
    fieldErrors: Object.fromEntries(fields),
    ...(typeof detail === "string" ? { detail } : {}),
    ...(typeof code === "string" ? { code } : {}),
    ...(typeof requestId === "string" ? { requestId } : {}),
  };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function isLocation(value: unknown): value is Array<string | number> {
  return (
    Array.isArray(value) &&
    value.every((part: unknown) => typeof part === "string" || typeof part === "number")
  );
}
