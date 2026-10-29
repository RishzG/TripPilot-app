import { avatarUrl } from '../assets/avatars';

export type AvatarSize = 32 | 40 | 64;

const SIZE_CLASS: Record<AvatarSize, string> = {
  32: 'size-8 text-sm',
  40: 'size-10 text-sm',
  64: 'size-16 text-xl',
};

/** The name a group sees for someone: the nickname when set, else the PayPal display name. */
export function shownName(person: {
  display_name: string;
  nickname?: string | null;
}): string {
  const nickname = person.nickname?.trim();
  return nickname ? nickname : person.display_name;
}

/** Up to two uppercase initials from a name. */
export function initialsOf(name: string): string {
  return name
    .split(/\s+/)
    .filter((part) => part.length > 0)
    .slice(0, 2)
    .map((part) => part.charAt(0).toUpperCase())
    .join('');
}

export interface AvatarProps {
  /** The name shown next to the avatar; initials come from it. */
  name: string;
  /** `accounts.avatar_kind`: 'illustrated' or 'initials'. */
  kind: string;
  /** `accounts.avatar_key`; ignored unless it names one of the bundled illustrations. */
  avatarKey: string | null;
  size?: AvatarSize;
}

/**
 * A round avatar: one of the bundled illustrations (an <img>, never inline markup) or coloured
 * initials. Decorative: the adjacent name is the accessible label, so the image has an empty alt
 * and the initials are hidden from assistive technology (UI-SPEC "Avatar"). The tile behind a
 * transparent illustration is the `muted` token. Any key outside the set falls back to initials.
 */
export function Avatar({ name, kind, avatarKey, size = 40 }: AvatarProps) {
  const url = kind === 'illustrated' ? avatarUrl(avatarKey) : undefined;
  return (
    <span
      className={`flex shrink-0 items-center justify-center overflow-hidden rounded-full bg-muted font-semibold ${SIZE_CLASS[size]}`}
    >
      {url === undefined ? (
        <span aria-hidden="true">{initialsOf(name)}</span>
      ) : (
        <img src={url} alt="" className="size-full object-cover" />
      )}
    </span>
  );
}
