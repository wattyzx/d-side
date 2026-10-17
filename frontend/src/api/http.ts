import { session } from "../session.ts";

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

export class SessionExpiredError extends Error {
  constructor() {
    super("Your session expired. Connect with Discogs again.");
    this.name = "SessionExpiredError";
  }
}

export class SessionChangedError extends Error {
  constructor() {
    super("Your session has changed.");
    this.name = "SessionChangedError";
  }
}

export function assertCurrentSession(revision: number) {
  if (session.getSnapshot().revision !== revision) {
    throw session.getSnapshot().expired ? new SessionExpiredError() : new SessionChangedError();
  }
}

export async function apiFetch(
  url: string,
  options: RequestInit = {},
  { allowAnonymous = false, fallback = "Request failed. Please try again." } = {},
): Promise<Response> {
  options.signal?.throwIfAborted();
  const revision = session.getSnapshot().revision;
  const signal = options.signal
    ? AbortSignal.any([session.getSignal(), options.signal])
    : session.getSignal();
  let response: Response;
  try {
    response = await fetch(url, { ...options, credentials: "include", signal });
  } catch (error) {
    assertCurrentSession(revision);
    throw error;
  }
  assertCurrentSession(revision);
  options.signal?.throwIfAborted();
  if (response.status === 401) {
    session.expire(allowAnonymous);
    throw new SessionExpiredError();
  }
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    assertCurrentSession(revision);
    const validationMessage = Array.isArray(body?.detail)
      ? body.detail.find((item: { msg?: unknown }) => typeof item?.msg === "string")?.msg
      : undefined;
    throw new ApiError(typeof body?.detail === "string" ? body.detail
      : typeof validationMessage === "string" ? validationMessage.replace(/^Value error, /, "")
      : fallback, response.status);
  }
  return response;
}
