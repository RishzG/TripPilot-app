import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Sparkles } from 'lucide-react';
import { type FormEvent, useRef, useState } from 'react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { ApiError, api, unwrap } from '@/lib/api';
import type { components } from '@/lib/api-types';

type Context = components['schemas']['TripPlanningContext'];
type Trip = components['schemas']['TripView'];
const PILOT = '/api/trips/{trip_id}/pilot';

function ContextForm({
  initial,
  saving,
  error,
  onSave,
  onClose,
}: {
  initial: Context | null;
  saving: boolean;
  error: boolean;
  onSave: (value: Context) => void;
  onClose: () => void;
}) {
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const fields = new FormData(event.currentTarget);
    onSave({
      destination: String(fields.get('destination') ?? ''),
      start_date: String(fields.get('start') ?? ''),
      end_date: String(fields.get('end') ?? ''),
      timezone: String(fields.get('timezone') ?? ''),
    });
  }

  return (
    <form onSubmit={submit} className="space-y-3">
      <fieldset disabled={saving} className="grid gap-3 sm:grid-cols-2">
        <div>
          <label htmlFor="planning-destination">Destination</label>
          <Input
            id="planning-destination"
            name="destination"
            required
            maxLength={100}
            defaultValue={initial?.destination ?? ''}
            placeholder="London"
          />
        </div>
        <div>
          <label htmlFor="planning-timezone">Timezone</label>
          <Input
            id="planning-timezone"
            name="timezone"
            required
            maxLength={80}
            defaultValue={initial?.timezone ?? 'Europe/London'}
          />
        </div>
        <div>
          <label htmlFor="planning-start">Start date</label>
          <Input
            id="planning-start"
            name="start"
            required
            type="date"
            defaultValue={initial?.start_date ?? ''}
          />
        </div>
        <div>
          <label htmlFor="planning-end">End date</label>
          <Input
            id="planning-end"
            name="end"
            required
            type="date"
            defaultValue={initial?.end_date ?? ''}
          />
        </div>
      </fieldset>
      <div className="flex flex-wrap gap-2">
        <Button type="submit" disabled={saving}>
          {saving ? 'Saving…' : 'Save trip details'}
        </Button>
        <Button
          type="button"
          variant="ghost"
          disabled={saving}
          onClick={onClose}
        >
          Cancel
        </Button>
      </div>
      {error && (
        <p role="alert" className="text-sm text-destructive">
          Check the date order and use an IANA timezone such as Europe/London.
        </p>
      )}
    </form>
  );
}

export function PilotPanel({
  tripId,
  context,
  isOrganiser,
  onOpenDraft,
}: {
  tripId: string;
  context: Context | null;
  isOrganiser: boolean;
  onOpenDraft: (version: number) => void;
}) {
  const client = useQueryClient();
  const [editing, setEditing] = useState(false);
  const attempt = useRef<string | null>(null);
  const params = { path: { trip_id: tripId } };
  const pilotKey = ['trip-pilot', tripId];
  const pilot = useQuery({
    queryKey: pilotKey,
    queryFn: async ({ signal }) =>
      unwrap(await api.GET(PILOT, { params, signal })),
    refetchInterval: (query) => {
      const state = query.state.data?.run?.state;
      return state === 'queued' || state === 'running' ? 1500 : false;
    },
    retry: false,
  });
  const save = useMutation({
    mutationFn: async (body: Context) =>
      unwrap(
        await api.PUT('/api/trips/{trip_id}/planning-context', {
          params,
          body,
        }),
      ),
    onSuccess: async (planning_context) => {
      const key = ['trip', tripId];
      await client.cancelQueries({ queryKey: key, exact: true });
      client.setQueryData<Trip>(
        key,
        (trip) => trip && { ...trip, planning_context },
      );
      void client.invalidateQueries({ queryKey: key, exact: true });
      setEditing(false);
    },
  });
  const start = useMutation({
    mutationFn: async (request_id: string) =>
      unwrap(await api.POST(PILOT, { params, body: { request_id } })),
    onSuccess: async (run) => {
      attempt.current = null;
      await client.cancelQueries({ queryKey: pilotKey, exact: true });
      client.setQueryData(pilotKey, { run });
      void client.invalidateQueries({ queryKey: pilotKey, exact: true });
    },
    onError: (error) => {
      if (error instanceof ApiError && error.status < 500)
        attempt.current = null;
      void client.invalidateQueries({ queryKey: pilotKey, exact: true });
    },
  });
  const run = pilot.data?.run;
  const active = run?.state === 'queued' || run?.state === 'running';

  return (
    <Card>
      <CardHeader>
        <h3 className="flex items-center gap-2 font-semibold">
          <Sparkles size={16} aria-hidden="true" /> Pilot preview
        </h3>
        <p className="text-sm text-muted-foreground">
          The London preview matches recent group-chat topics against a curated
          set of places. Private preferences and concerns stay outside the run.
        </p>
      </CardHeader>
      <CardContent className="space-y-3">
        {editing && isOrganiser ? (
          <ContextForm
            initial={context}
            saving={save.isPending}
            error={save.isError}
            onSave={save.mutate}
            onClose={() => setEditing(false)}
          />
        ) : (
          <div className="flex flex-wrap items-center gap-3 text-sm">
            <p>
              {context
                ? `${context.destination} · ${context.start_date} to ${context.end_date} · ${context.timezone}`
                : 'Destination, dates and timezone are needed to start Pilot.'}
            </p>
            {isOrganiser && (
              <Button
                type="button"
                variant="outline"
                onClick={() => {
                  save.reset();
                  setEditing(true);
                }}
              >
                {context ? 'Edit trip details' : 'Set trip details'}
              </Button>
            )}
            {isOrganiser && context && (
              <Button
                type="button"
                disabled={active || start.isPending}
                onClick={() => {
                  attempt.current ??= crypto.randomUUID();
                  start.mutate(attempt.current);
                }}
              >
                {run?.state === 'failed' ? 'Retry Pilot' : 'Start Pilot'}
              </Button>
            )}
          </div>
        )}
        {active && (
          <p role="status" className="text-sm">
            {run.state === 'queued'
              ? 'Pilot queued. Waiting for the planning worker.'
              : 'Pilot is preparing a draft…'}
          </p>
        )}
        {run?.state === 'ready' && run.draft_version !== null && (
          <Button
            type="button"
            variant="outline"
            onClick={() => {
              const version = run.draft_version;
              if (version !== null) onOpenDraft(version);
            }}
          >
            Open Pilot draft v{run.draft_version}
          </Button>
        )}
        {run?.message && (
          <p role="alert" className="text-sm text-destructive">
            {run.message}
          </p>
        )}
        {start.isError && (
          <p role="alert" className="text-sm text-destructive">
            {start.error instanceof ApiError
              ? start.error.message
              : 'Could not start Pilot. Try again.'}
          </p>
        )}
        {pilot.isError && (
          <Button
            type="button"
            variant="outline"
            onClick={() => void pilot.refetch()}
          >
            Retry loading Pilot status
          </Button>
        )}
      </CardContent>
    </Card>
  );
}
