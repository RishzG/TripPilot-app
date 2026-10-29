import { Check } from 'lucide-react';
import { useId } from 'react';
import { AVATAR_KEYS, avatarUrl } from '../../assets/avatars';
import { initialsOf } from '../../components/Avatar';

export const INITIALS_CHOICE = 'initials';

/** The saved look as a picker value: the illustration's key, or 'initials'. */
export function choiceOf(kind: string, key: string | null): string {
  return kind === 'illustrated' && avatarUrl(key) !== undefined && key !== null
    ? key
    : INITIALS_CHOICE;
}

export interface AvatarPickerProps {
  /** The name the initials tile shows. */
  name: string;
  /** 'initials' or one of the 16 illustration keys. */
  value: string;
  onChange: (choice: string) => void;
}

/**
 * The avatar picker (D-45): 17 radio tiles, the first is coloured initials and the next 16 are the
 * bundled illustrations. Native radio inputs give the single-select group and arrow-key movement;
 * the selected tile gets a ring plus a check badge so selection is not colour-only.
 */
export function AvatarPicker({ name, value, onChange }: AvatarPickerProps) {
  const group = useId();
  const options: string[] = [INITIALS_CHOICE, ...AVATAR_KEYS];
  return (
    <div
      role="radiogroup"
      aria-label="Avatar"
      className="grid grid-cols-4 gap-2 md:grid-cols-6"
    >
      {options.map((option, index) => {
        const selected = value === option;
        const url = avatarUrl(option);
        return (
          <label
            key={option}
            className="relative flex size-16 min-h-11 min-w-11"
          >
            <input
              type="radio"
              name={group}
              value={option}
              checked={selected}
              onChange={() => onChange(option)}
              aria-label={index === 0 ? 'Initials' : `Avatar ${index}`}
              className="peer sr-only"
            />
            <span className="flex size-16 items-center justify-center overflow-hidden rounded-full bg-muted text-xl font-semibold ring-offset-2 ring-offset-background peer-checked:ring-2 peer-checked:ring-accent peer-focus-visible:ring-2 peer-focus-visible:ring-accent">
              {url === undefined ? (
                <span aria-hidden="true">{initialsOf(name)}</span>
              ) : (
                <img src={url} alt="" className="size-full object-cover" />
              )}
            </span>
            {selected && (
              <span
                aria-hidden="true"
                className="absolute -right-1 -top-1 flex size-4 items-center justify-center rounded-full bg-accent text-accent-foreground"
              >
                <Check size={12} />
              </span>
            )}
          </label>
        );
      })}
    </div>
  );
}
