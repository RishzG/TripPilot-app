import { useMutation, useQueryClient } from '@tanstack/react-query';
import { CircleAlert } from 'lucide-react';
import { type FormEvent, useId, useRef, useState } from 'react';
import { toast } from 'sonner';
import { shownName } from '../../components/Avatar';
import { api, unwrap } from '../../lib/api';
import type { components } from '../../lib/api-types';
import { AvatarPicker, choiceOf, INITIALS_CHOICE } from './AvatarPicker';

type MeData = components['schemas']['MeResponse'];

export const NICKNAME_MAX_LENGTH = 40;
const EMPTY_NAME_MESSAGE = 'Add a name your friends will recognise.';
const LONG_NAME_MESSAGE = 'Keep it under 40 characters.';
const SUBMIT_FAILED_MESSAGE =
  "Couldn't save that. Nothing was changed, so try again.";

export interface LookFormProps {
  me: MeData;
  /** The visible label of the nickname field (`Nickname` on the account page). */
  nicknameLabel?: string;
  /** Called after the server accepted the new nickname and avatar. */
  onSaved?: () => void;
}

/**
 * The nickname field, the avatar picker and `Save my look`, shared by the account page and the
 * welcome step (D-09, D-45). The nickname starts as the saved nickname or the PayPal display name
 * and the picker starts on the saved look. Saving calls PATCH /api/me; the answer replaces the
 * cached `me` and any open trip refetches so friends see the new look.
 */
export function LookForm({
  me,
  nicknameLabel = 'Nickname',
  onSaved,
}: LookFormProps) {
  const queryClient = useQueryClient();
  const fieldId = useId();
  const nicknameField = useRef<HTMLInputElement>(null);
  const [nickname, setNickname] = useState(me.nickname ?? me.display_name);
  const [choice, setChoice] = useState(choiceOf(me.avatar_kind, me.avatar_key));
  const [error, setError] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  const save = useMutation({
    mutationFn: async (body: {
      nickname: string;
      avatar_kind: 'initials' | 'illustrated';
      avatar_key: string | null;
    }) => unwrap(await api.PATCH('/api/me', { body })),
    onSuccess: (updated) => {
      setFailed(false);
      queryClient.setQueryData(['me'], updated);
      void queryClient.invalidateQueries({ queryKey: ['trip'] });
      toast('Saved');
      onSaved?.();
    },
    onError: () => setFailed(true),
  });

  function reject(message: string) {
    setError(message);
    nicknameField.current?.focus();
  }

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = nickname.trim();
    if (trimmed.length === 0) {
      reject(EMPTY_NAME_MESSAGE);
      return;
    }
    if (trimmed.length > NICKNAME_MAX_LENGTH) {
      reject(LONG_NAME_MESSAGE);
      return;
    }
    setError(null);
    setFailed(false);
    save.mutate({
      nickname: trimmed,
      avatar_kind: choice === INITIALS_CHOICE ? 'initials' : 'illustrated',
      avatar_key: choice === INITIALS_CHOICE ? null : choice,
    });
  }

  const previewName = nickname.trim() || shownName(me);
  return (
    <form noValidate onSubmit={onSubmit} className="flex flex-col gap-4">
      <div className="flex flex-col gap-2">
        <label htmlFor={fieldId} className="text-sm font-semibold">
          {nicknameLabel}
        </label>
        <input
          id={fieldId}
          ref={nicknameField}
          type="text"
          value={nickname}
          autoComplete="off"
          aria-invalid={error !== null}
          aria-describedby={error === null ? undefined : `${fieldId}-error`}
          onChange={(event) => setNickname(event.target.value)}
          className="min-h-11 w-full rounded-lg border border-muted-foreground bg-background px-4 text-base"
        />
        <p className="text-sm text-muted-foreground">Friends see this name.</p>
        {error !== null && (
          <p
            id={`${fieldId}-error`}
            role="alert"
            className="flex items-center gap-2 text-sm text-destructive"
          >
            <CircleAlert aria-hidden="true" size={16} />
            {error}
          </p>
        )}
      </div>
      <AvatarPicker name={previewName} value={choice} onChange={setChoice} />
      {failed && (
        <p role="alert" className="text-sm text-destructive">
          {SUBMIT_FAILED_MESSAGE}
        </p>
      )}
      <button
        type="submit"
        disabled={save.isPending}
        aria-busy={save.isPending}
        className="min-h-11 w-full rounded-lg bg-accent px-4 text-base font-semibold text-accent-foreground disabled:opacity-50"
      >
        Save my look
      </button>
    </form>
  );
}
