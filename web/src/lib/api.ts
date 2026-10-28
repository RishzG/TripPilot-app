import createClient from 'openapi-fetch';
import type { paths } from './api-types';

/** A non-2xx answer from the API, carrying the HTTP status so callers can branch on 404 and 401. */
export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

/** Typed client generated from FastAPI's OpenAPI schema; same-origin so the session cookie rides along. */
export const api = createClient<paths>({
  baseUrl: '',
  credentials: 'same-origin',
});

interface FetchResult<T> {
  data?: T;
  error?: unknown;
  response: Response;
}

function messageFrom(error: unknown, status: number): string {
  if (typeof error === 'object' && error !== null && 'detail' in error) {
    const { detail } = error as { detail: unknown };
    if (typeof detail === 'string') {
      return detail;
    }
  }
  return `Request failed (${status})`;
}

/** Return the body of a successful call, or throw an ApiError for any non-2xx answer. */
export function unwrap<T>({ data, error, response }: FetchResult<T>): T {
  if (!response.ok || data === undefined) {
    throw new ApiError(response.status, messageFrom(error, response.status));
  }
  return data;
}
