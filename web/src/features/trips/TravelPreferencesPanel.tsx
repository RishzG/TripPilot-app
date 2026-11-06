import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { type FormEvent, useId, useState } from 'react';
import { ErrorRetry } from '@/components/ErrorRetry';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { api, unwrap } from '@/lib/api';
import type { components } from '@/lib/api-types';

type Preferences = components['schemas']['TravelPreferences'];
const PACE_LABELS = {
  relaxed: 'Relaxed',
  balanced: 'Balanced',
  active: 'Active',
} as const;
const TEXTAREA =
  'min-h-24 w-full rounded-lg border border-input bg-background p-3 text-base placeholder:text-muted-foreground/60 placeholder:italic focus-visible:outline-2 focus-visible:outline-ring';
const EXAMPLE_STYLE = 'placeholder:text-muted-foreground/60 placeholder:italic';

/** Parse decimal dollars as integer cents; blank means unspecified, zero is a valid budget. */
export function budgetCents(value: string): number | null {
  const trimmed = value.trim();
  if (trimmed === '') return null;
  if (/^-\d/.test(trimmed)) throw new Error('Budget cannot be negative.');
  if (!/^\d{1,7}(\.\d{1,2})?$/.test(trimmed)) {
    throw new Error('Enter a USD amount with up to two decimal places.');
  }
  const [dollars = '0', fraction = ''] = trimmed.split('.');
  const cents = Number(dollars) * 100 + Number(fraction.padEnd(2, '0'));
  if (cents > 100_000_000)
    throw new Error('Keep the budget at or below $1,000,000.');
  return cents;
}

function budgetText(cents: number | null | undefined): string {
  if (cents == null) return '';
  return `${Math.floor(cents / 100)}.${String(cents % 100).padStart(2, '0')}`;
}

function PreferencesForm({
  initial,
  tripId,
  onSaved,
}: {
  initial: Preferences;
  tripId: string;
  onSaved?: () => void;
}) {
  const id = useId();
  const queryClient = useQueryClient();
  const [origin, setOrigin] = useState(initial.origin ?? '');
  const [interests, setInterests] = useState(initial.interests ?? '');
  const [pace, setPace] = useState<NonNullable<Preferences['pace']>>(
    initial.pace ?? 'balanced',
  );
  const [budget, setBudget] = useState(budgetText(initial.budget_cents));
  const [diet, setDiet] = useState(initial.dietary_notes ?? '');
  const [error, setError] = useState('');
  const save = useMutation({
    mutationFn: async (body: Preferences) =>
      unwrap(
        await api.PUT('/api/trips/{trip_id}/preferences/me', {
          params: { path: { trip_id: tripId } },
          body,
        }),
      ),
    onSuccess: async (updated) => {
      // A stream-triggered GET may still be in flight. Do not let an older snapshot overwrite
      // the committed response, or make a successful save depend on another network request.
      await queryClient.cancelQueries({
        queryKey: ['trip-preferences', tripId],
      });
      queryClient.setQueryData(['trip-preferences', tripId], updated);
      setOrigin(updated.mine.origin ?? '');
      setInterests(updated.mine.interests ?? '');
      setPace(updated.mine.pace ?? 'balanced');
      setBudget(budgetText(updated.mine.budget_cents));
      setDiet(updated.mine.dietary_notes ?? '');
      onSaved?.();
    },
  });

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError('');
    let cents: number | null;
    try {
      cents = budgetCents(budget);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Check your budget.');
      return;
    }
    save.mutate({
      origin: origin.trim(),
      interests: interests.trim(),
      pace,
      budget_cents: cents,
      dietary_notes: diet.trim(),
    });
  }

  return (
    <form
      onSubmit={submit}
      onChange={() => {
        save.reset();
        setError('');
      }}
      className="flex flex-col gap-4"
    >
      <p className="text-sm text-muted-foreground">
        Preferences apply to this trip. Your origin, interests and pace are
        shared with the group.
      </p>
      <fieldset disabled={save.isPending} className="grid min-w-0 gap-4">
        <div className="grid gap-1">
          <label htmlFor={`${id}-origin`} className="font-semibold">
            Starting city
          </label>
          <Input
            id={`${id}-origin`}
            maxLength={160}
            value={origin}
            onChange={(event) => setOrigin(event.target.value)}
            placeholder="Ex. Chicago, IL"
            className={EXAMPLE_STYLE}
          />
        </div>
        <div className="grid gap-1">
          <label htmlFor={`${id}-interests`} className="font-semibold">
            Interests
          </label>
          <textarea
            id={`${id}-interests`}
            maxLength={1000}
            value={interests}
            onChange={(event) => setInterests(event.target.value)}
            className={TEXTAREA}
            placeholder="Ex. easy hikes, local food, museums"
          />
        </div>
        <div className="grid gap-1">
          <label htmlFor={`${id}-pace`} className="font-semibold">
            Travel pace
          </label>
          <select
            id={`${id}-pace`}
            value={pace}
            onChange={(event) => setPace(event.target.value as typeof pace)}
            className="h-11 rounded-lg border border-input bg-background px-3"
          >
            {Object.entries(PACE_LABELS).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </div>
        <fieldset className="grid min-w-0 gap-4 rounded-lg border border-border p-4">
          <legend className="px-1 font-semibold">Private preferences</legend>
          <p id={`${id}-privacy`} className="text-sm text-muted-foreground">
            Only you can view your budget and dietary notes here. They are
            excluded from group views and live updates.
          </p>
          <div className="grid gap-1">
            <label htmlFor={`${id}-budget`} className="font-semibold">
              Your trip budget (USD)
            </label>
            <Input
              id={`${id}-budget`}
              inputMode="decimal"
              value={budget}
              maxLength={10}
              onChange={(event) => setBudget(event.target.value)}
              aria-describedby={`${id}-privacy ${id}-budget-help`}
              aria-invalid={error !== ''}
              placeholder="Ex. 400.00"
              className={EXAMPLE_STYLE}
            />
            <p
              id={`${id}-budget-help`}
              className="text-sm text-muted-foreground"
            >
              Optional total per person. Leave blank if undecided.
            </p>
          </div>
          <div className="grid gap-1">
            <label htmlFor={`${id}-diet`} className="font-semibold">
              Dietary notes
            </label>
            <textarea
              id={`${id}-diet`}
              value={diet}
              maxLength={1000}
              onChange={(event) => setDiet(event.target.value)}
              aria-describedby={`${id}-privacy`}
              className={TEXTAREA}
            />
          </div>
        </fieldset>
        <Button type="submit" aria-busy={save.isPending}>
          {save.isPending ? 'Saving preferences…' : 'Save preferences'}
        </Button>
      </fieldset>
      {error && (
        <p role="alert" className="text-destructive">
          {error}
        </p>
      )}
      {save.isError && (
        <p role="alert" className="text-destructive">
          Couldn’t save your preferences. Your changes are still here; try
          again.
        </p>
      )}
      {save.isSuccess && <p role="status">Preferences saved.</p>}
      {save.isSuccess && onSaved && (
        <Button type="button" variant="outline" onClick={onSaved}>
          Open group chat
        </Button>
      )}
    </form>
  );
}

export function TravelPreferencesPanel({
  tripId,
  onSaved,
}: {
  tripId: string;
  onSaved?: () => void;
}) {
  const query = useQuery({
    queryKey: ['trip-preferences', tripId],
    queryFn: async () =>
      unwrap(
        await api.GET('/api/trips/{trip_id}/preferences', {
          params: { path: { trip_id: tripId } },
        }),
      ),
    retry: false,
  });
  return (
    <Card className="min-w-0 rounded-2xl">
      <CardHeader>
        <h2 className="text-xl font-semibold">Travel preferences</h2>
      </CardHeader>
      <CardContent className="flex flex-col gap-6">
        {query.isPending ? (
          <p aria-busy="true">Loading preferences…</p>
        ) : query.isError ? (
          <ErrorRetry onRetry={() => void query.refetch()} />
        ) : (
          <>
            <PreferencesForm
              key={tripId}
              tripId={tripId}
              initial={query.data.mine}
              onSaved={onSaved}
            />
            <details>
              <summary className="cursor-pointer font-semibold">
                Group preferences
              </summary>
              <ul aria-label="Group preferences" className="mt-3 grid gap-3">
                {query.data.members.map((member) => (
                  <li
                    key={member.account_id}
                    className="break-words rounded-lg bg-muted p-3"
                  >
                    <p className="font-semibold">{member.display_name}</p>
                    <p>
                      {member.origin || 'Starting city not shared'} ·{' '}
                      {PACE_LABELS[member.pace]} pace
                    </p>
                    <p className="whitespace-pre-wrap text-sm">
                      {member.interests || 'No interests shared yet.'}
                    </p>
                  </li>
                ))}
              </ul>
            </details>
          </>
        )}
      </CardContent>
    </Card>
  );
}
