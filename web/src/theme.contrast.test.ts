import indexCss from './index.css?raw';

/**
 * WCAG AA contrast over the token pairs named in 01-UI-SPEC.md "Contrast pairs" (D-46).
 * The test reads the `:root` custom properties of index.css as text, so the palette can change
 * in that one block and this test tells you at once which pair stopped being readable.
 * If a pair fails, adjust the token in index.css, never this test.
 *
 * Known failing combination, deliberately NOT listed: primary text on --muted is 4.47:1.
 */

function rootTokens(): Map<string, string> {
  const css = indexCss.replace(/\/\*[\s\S]*?\*\//g, '');
  const root = /:root\s*\{([^}]*)\}/.exec(css);
  const tokens = new Map<string, string>();
  if (root?.[1] === undefined) {
    return tokens;
  }
  for (const declaration of root[1].matchAll(
    /--([a-z0-9-]+)\s*:\s*([^;]+);/g,
  )) {
    const name = declaration[1];
    const value = declaration[2];
    if (name !== undefined && value !== undefined) {
      tokens.set(name, value.trim());
    }
  }
  return tokens;
}

/** sRGB hex (#rgb or #rrggbb) to 0-255 channels. Other colour formats are not used by the tokens. */
function parseHex(token: string, value: string): [number, number, number] {
  const match = /^#([0-9a-f]{3}|[0-9a-f]{6})$/i.exec(value);
  if (match?.[1] === undefined) {
    throw new Error(`--${token} is "${value}", expected a hex colour`);
  }
  const hex =
    match[1].length === 3
      ? [...match[1]].map((digit) => digit + digit).join('')
      : match[1];
  return [
    Number.parseInt(hex.slice(0, 2), 16),
    Number.parseInt(hex.slice(2, 4), 16),
    Number.parseInt(hex.slice(4, 6), 16),
  ];
}

function channelLuminance(channel: number): number {
  const scaled = channel / 255;
  return scaled <= 0.03928 ? scaled / 12.92 : ((scaled + 0.055) / 1.055) ** 2.4;
}

function luminance(token: string, value: string): number {
  const [red, green, blue] = parseHex(token, value);
  return (
    0.2126 * channelLuminance(red) +
    0.7152 * channelLuminance(green) +
    0.0722 * channelLuminance(blue)
  );
}

function contrastRatio(
  tokens: Map<string, string>,
  foreground: string,
  background: string,
): number {
  const fg = tokens.get(foreground);
  const bg = tokens.get(background);
  if (fg === undefined) {
    throw new Error(`--${foreground} is not defined in the :root block`);
  }
  if (bg === undefined) {
    throw new Error(`--${background} is not defined in the :root block`);
  }
  const first = luminance(foreground, fg);
  const second = luminance(background, bg);
  const lighter = Math.max(first, second);
  const darker = Math.min(first, second);
  return (lighter + 0.05) / (darker + 0.05);
}

type Pair = readonly [name: string, fg: string, bg: string, min: number];

const TEXT = 4.5;
const GRAPHIC = 3;

const PAIRS: readonly Pair[] = [
  ['foreground on background', 'foreground', 'background', TEXT],
  ['foreground on card', 'foreground', 'card', TEXT],
  ['foreground on muted', 'foreground', 'muted', TEXT],
  ['foreground on accent', 'foreground', 'accent', TEXT],
  ['muted-foreground on background', 'muted-foreground', 'background', TEXT],
  ['muted-foreground on card', 'muted-foreground', 'card', TEXT],
  ['muted-foreground on muted', 'muted-foreground', 'muted', TEXT],
  ['muted-foreground on accent', 'muted-foreground', 'accent', TEXT],
  ['primary-foreground on primary', 'primary-foreground', 'primary', TEXT],
  [
    'primary-foreground on primary-hover',
    'primary-foreground',
    'primary-hover',
    TEXT,
  ],
  ['primary text on background', 'primary', 'background', TEXT],
  ['primary text on card', 'primary', 'card', TEXT],
  ['money text on background', 'money', 'background', TEXT],
  ['money text on card', 'money', 'card', TEXT],
  ['money text on money-surface', 'money', 'money-surface', TEXT],
  ['foreground on money-surface', 'foreground', 'money-surface', TEXT],
  ['money-foreground on money', 'money-foreground', 'money', TEXT],
  ['destructive text on card', 'destructive', 'card', TEXT],
  ['destructive text on background', 'destructive', 'background', TEXT],
  ['destructive text on money-surface', 'destructive', 'money-surface', TEXT],
  [
    'destructive-foreground on destructive',
    'destructive-foreground',
    'destructive',
    TEXT,
  ],
  [
    'banner text on banner',
    'sandbox-banner-foreground',
    'sandbox-banner',
    TEXT,
  ],
  ...[1, 2, 3, 4, 5, 6, 7, 8].map(
    (index): Pair => [
      `avatar-${index} initials`,
      'avatar-foreground',
      `avatar-${index}`,
      TEXT,
    ],
  ),
  ['ring on background', 'ring', 'background', GRAPHIC],
  ['input border on background', 'input', 'background', GRAPHIC],
  ['input border on card', 'input', 'card', GRAPHIC],
  ['logo icon on logo tile', 'primary-foreground', 'primary', GRAPHIC],
];

describe('theme contrast (WCAG AA, UI-SPEC pairs)', () => {
  const tokens = rootTokens();

  it.each(PAIRS)('%s meets its minimum ratio', (name, fg, bg, min) => {
    const ratio = contrastRatio(tokens, fg, bg);
    expect(
      ratio,
      `${name}: --${fg} on --${bg} is ${ratio.toFixed(2)}:1, needs ${min}:1`,
    ).toBeGreaterThanOrEqual(min);
  });

  it('covers every pair named in the UI-SPEC table', () => {
    expect(PAIRS).toHaveLength(34);
  });
});

describe('theme tokens', () => {
  const tokens = rootTokens();

  it.each([
    'background',
    'foreground',
    'card',
    'card-foreground',
    'popover',
    'popover-foreground',
    'primary',
    'primary-foreground',
    'primary-hover',
    'secondary',
    'secondary-foreground',
    'muted',
    'muted-foreground',
    'accent',
    'accent-foreground',
    'border',
    'input',
    'ring',
    'destructive',
    'destructive-foreground',
    'money',
    'money-foreground',
    'money-surface',
    'sandbox-banner',
    'sandbox-banner-foreground',
    'avatar-foreground',
    'avatar-1',
    'avatar-2',
    'avatar-3',
    'avatar-4',
    'avatar-5',
    'avatar-6',
    'avatar-7',
    'avatar-8',
    'radius',
  ])('defines --%s in the :root block', (name) => {
    expect(tokens.has(name), `--${name} is missing from :root`).toBe(true);
  });

  it('is light mode only: no dark block or dark variant in index.css', () => {
    const css = indexCss;
    expect(css).not.toMatch(/\.dark\b/);
    expect(css).not.toMatch(/@custom-variant\s+dark/);
  });

  it('declares the self-hosted font family and the 28px display size', () => {
    const css = indexCss;
    expect(css).toContain("'Plus Jakarta Sans Variable'");
    expect(css).toMatch(/--text-display:\s*1\.75rem/);
  });
});
