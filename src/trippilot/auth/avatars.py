"""The illustrated avatar set (D-45): the only keys an account may store as `avatar_key`.

The set is 16 DiceBear "Lorelei" illustrations (CC0 1.0), bundled as static SVGs in
`web/src/assets/avatars/` with `index.ts` mapping each key to its file. The six demo personas'
slugs come first (`demo/cast.py` uses them as their avatar keys), then ten more. A test checks
this set against `index.ts` and the files on disk, so the two lists cannot drift apart.
"""

from __future__ import annotations

ILLUSTRATED_AVATAR_KEYS: frozenset[str] = frozenset(
    {
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
    }
)
"""Allowed values of `accounts.avatar_key` when `avatar_kind` is 'illustrated'."""
