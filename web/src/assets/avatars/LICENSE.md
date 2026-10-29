# Illustrated avatars: licence and provenance

| Field                | Value                                                                 |
| -------------------- | --------------------------------------------------------------------- |
| Style                | DiceBear "Lorelei"                                                    |
| Style page           | https://www.dicebear.com/styles/lorelei/                              |
| Artwork              | "Lorelei" by Lisa Wischofsky, remixed by DiceBear                     |
| Artwork source       | https://www.figma.com/community/file/1198749693280469639              |
| Licence              | CC0 1.0 Universal, https://creativecommons.org/publicdomain/zero/1.0/ |
| Attribution required | No                                                                    |
| Retrieved            | 2026-10-29                                                            |
| Files                | 16 SVGs, one per avatar key (about 100 KB in total)                   |

The licence statement is also embedded in each SVG's `<metadata>` block (title Lorelei, creator
Lisa Wischofsky, source URL above, licence URL above). DiceBear's licence overview lists Lorelei
under CC0 1.0 (https://www.dicebear.com/licenses/); the DiceBear library and HTTP API are MIT.

## How the set was made (reproducible)

Each file was fetched once, offline, from the DiceBear HTTP API with the avatar key as the seed:

```
https://api.dicebear.com/9.x/lorelei/svg?seed=<key>
```

for the 16 keys, in this order: `maya`, `sam`, `ana`, `leo`, `priya`, `jules`, `kai`, `noor`,
`tess`, `omar`, `ivy`, `ravi`, `zoe`, `finn`, `lena`, `theo`. The result is saved as
`<key>.svg` in this folder. The first six are the demo personas' slugs.

The files were scanned before use: only `svg`, `g`, `path`, `rect` and `mask` elements plus the RDF
metadata, no script, event handlers, `foreignObject` or external references.

## How the app uses them

- No runtime call to DiceBear and no npm dependency; the SVGs are bundled static assets.
- `index.ts` maps each key to its bundled URL. The keys must equal `ILLUSTRATED_AVATAR_KEYS` in
  `src/trippilot/auth/avatars.py` (a test checks both lists).
- Render with `<img>` only, never with `dangerouslySetInnerHTML`.
