/*
 * Illustrated avatar set (D-45, UI-SPEC "Avatar set and licence").
 *
 * Style:     DiceBear "Lorelei" (https://www.dicebear.com/styles/lorelei/)
 * Artwork:   Lorelei by Lisa Wischofsky, remixed by DiceBear
 *            (https://www.figma.com/community/file/1198749693280469639)
 * Licence:   CC0 1.0 Universal (public domain dedication), no attribution required
 * Retrieved: 2026-10-29, one SVG per key, generated once offline with the DiceBear HTTP API
 *            (see LICENSE.md in this folder for the exact URL pattern); the files are static
 *            assets, there is no runtime call to DiceBear.
 *
 * Maps avatar key -> bundled asset URL. The keys are exactly the values of
 * `ILLUSTRATED_AVATAR_KEYS` in src/trippilot/auth/avatars.py, in UI-SPEC order: the first six are
 * the demo personas' slugs, then ten more. Render with <img> only, never as inline markup.
 */
import ana from './ana.svg';
import finn from './finn.svg';
import ivy from './ivy.svg';
import jules from './jules.svg';
import kai from './kai.svg';
import lena from './lena.svg';
import leo from './leo.svg';
import maya from './maya.svg';
import noor from './noor.svg';
import omar from './omar.svg';
import priya from './priya.svg';
import ravi from './ravi.svg';
import sam from './sam.svg';
import tess from './tess.svg';
import theo from './theo.svg';
import zoe from './zoe.svg';

export const AVATAR_KEYS = [
  'maya',
  'sam',
  'ana',
  'leo',
  'priya',
  'jules',
  'kai',
  'noor',
  'tess',
  'omar',
  'ivy',
  'ravi',
  'zoe',
  'finn',
  'lena',
  'theo',
] as const;

export type AvatarKey = (typeof AVATAR_KEYS)[number];

export const AVATAR_URLS: Readonly<Record<AvatarKey, string>> = {
  maya,
  sam,
  ana,
  leo,
  priya,
  jules,
  kai,
  noor,
  tess,
  omar,
  ivy,
  ravi,
  zoe,
  finn,
  lena,
  theo,
};

/** Return the bundled image URL for a saved key, or undefined when the key is not in the set. */
export function avatarUrl(key: string | null | undefined): string | undefined {
  if (key === null || key === undefined) {
    return undefined;
  }
  return (AVATAR_KEYS as readonly string[]).includes(key)
    ? AVATAR_URLS[key as AvatarKey]
    : undefined;
}
