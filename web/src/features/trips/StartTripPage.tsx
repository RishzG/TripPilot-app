import { CircleAlert } from 'lucide-react';
import { type FormEvent, useRef, useState } from 'react';
import { useNavigate } from 'react-router';
import { api, unwrap } from '../../lib/api';

const NAME_MAX_LENGTH = 80;
const EMPTY_NAME_MESSAGE = 'Give your trip a name to get started.';
const LONG_NAME_MESSAGE = 'Keep it under 80 characters.';
const SUBMIT_FAILED_MESSAGE =
  "Couldn't save that. Nothing was changed, so try again.";

/** Start a trip (D-20): the signed-in organiser names it, then lands on its page. */
export function StartTripPage() {
  const navigate = useNavigate();
  const nameField = useRef<HTMLInputElement>(null);
  const [name, setName] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  function reject(message: string) {
    setError(message);
    nameField.current?.focus();
  }

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = name.trim();
    if (trimmed.length === 0) {
      reject(EMPTY_NAME_MESSAGE);
      return;
    }
    if (trimmed.length > NAME_MAX_LENGTH) {
      reject(LONG_NAME_MESSAGE);
      return;
    }
    setError(null);
    setPending(true);
    try {
      const created = unwrap(
        await api.POST('/api/trips', { body: { name: trimmed } }),
      );
      navigate(`/trips/${created.id}`);
    } catch {
      setError(SUBMIT_FAILED_MESSAGE);
      setPending(false);
    }
  }

  return (
    <div className="mx-auto w-full max-w-md p-4 pt-6">
      <h1 className="text-balance break-words text-[1.75rem] font-semibold leading-[1.2]">
        Start a trip
      </h1>
      <form noValidate onSubmit={onSubmit} className="mt-6 flex flex-col gap-4">
        <div className="flex flex-col gap-2">
          <label htmlFor="trip-name" className="text-sm font-semibold">
            Trip name
          </label>
          <input
            id="trip-name"
            ref={nameField}
            type="text"
            value={name}
            placeholder="Tahoe weekend"
            autoComplete="off"
            aria-invalid={error !== null}
            aria-describedby={error === null ? undefined : 'trip-name-error'}
            onChange={(event) => setName(event.target.value)}
            className="min-h-11 w-full rounded-lg border border-muted-foreground bg-background px-4 text-base"
          />
          {error !== null && (
            <p
              id="trip-name-error"
              role="alert"
              className="flex items-center gap-2 text-sm text-destructive"
            >
              <CircleAlert aria-hidden="true" size={16} />
              {error}
            </p>
          )}
        </div>
        <button
          type="submit"
          disabled={pending}
          aria-busy={pending}
          className="min-h-11 w-full rounded-lg bg-accent px-4 text-base font-semibold text-accent-foreground disabled:opacity-50"
        >
          Start the trip
        </button>
      </form>
    </div>
  );
}
