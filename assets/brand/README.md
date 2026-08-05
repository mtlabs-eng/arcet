# arcet brand assets

## The mark

A continuous route enters from outside, passes between two boundaries, and
ends at a single copper terminal. That is the tool in one shape: a permission
is not a fact on its own, it is the end of a path, and arcet's job is to show
the path.

## Files

| File | Use |
|---|---|
| `arcet-logo.svg` | Mark and wordmark. The default. |
| `arcet-mark.svg` | Mark only, where the name is already present. |
| `arcet-logo-dark.svg` | For dark backgrounds. Ivory, with the copper terminal kept. |
| `arcet-logo-mono.svg` | Single colour via `currentColor`. Only works when the SVG is **inlined** — referenced through `<img>` it falls back to black. Use the dark file for that. |
| `favicon.svg` | Mark on a square canvas. |
| `favicon-16.svg` | Reduced mark for 16 px. See below. |
| `favicon.ico` | 16, 32 and 48 px. The 16 px entry uses the reduced mark. |
| `arcet-mark-32.png`, `-64.png`, `-128.png` | Raster mark, transparent background. |
| `social-preview.png` | 1280×640, for the repository's social preview card. |
| `launch-card.png` | 1200×1200, square, for social posts. |
| `launch-card.svg` | The same card with the terminal text as editable `<text>`. |

The terminal panel in `launch-card` is **not typed by hand**. It is captured
verbatim from `resolve()` and `render_table()` running against a fixture-backed
source, the same way the tests drive them, with fictitious identities and
subscription ids throughout. If the renderer changes, regenerating the card
changes it — which is the point. Composing it surfaced a real wrapping defect
in the warning headline at narrow widths, now fixed and covered by a test.

**One thing on the card is not literal output.** The subscription scope is
shown abbreviated — `/subscriptions/00000000…44444444` — where arcet prints it
in full, every time. At a size that stays legible in a phone feed a
51-character id crowds out the chain, which is the thing the card exists to
show. It is written down here because a project that spends this much effort
separating "tested" from "verified" should not quietly edit its own screenshot.

The SVG is the source and the PNG is rasterised from it: the generator reads
the SVG back and draws its elements, so the two cannot drift apart. Rendering
through cairosvg was tried first and abandoned — on macOS it cannot resolve
JetBrains Mono and silently substitutes a proportional face, which moves every
column.

The SVG keeps the text as `<text>` elements so it can be edited, and names
JetBrains Mono with a monospace fallback; the PNG is the one to post.

`social-preview.png` has to be uploaded by hand — GitHub exposes no API for
it. Settings → General → Social preview. It is versioned here so the card can
be rebuilt without redesigning it.

## Colour

| Role | Hex |
|---|---|
| Charcoal — mark and wordmark | `#1B2329` |
| Copper — the terminal, and nothing else | `#C1723B` |
| Warm ivory — background in the reference | `#FBF2E6` |

Copper marks the end of the route. It is the one thing on the page that says
*this is the answer*, so it is never used for anything else — not for accents,
not for links, not for a second element in the same mark.

## Legibility

Checked by rendering and inspecting, not assumed:

| Size | Full mark |
|---|---|
| 48 px | Clean, every element reads |
| 32 px | Good |
| 24 px | Holds; inner detail begins to merge |
| **16 px** | **Fails** — route, inner boundary and outer wall merge into a grey blob |

`favicon-16.svg` exists because of that last row. It keeps the boundary, one
entering line and the copper terminal, and drops the rest. The meaning
survives at a size where the detail cannot.

## Typography

The wordmark is [Plus Jakarta Sans](https://github.com/tokotype/PlusJakartaSans)
Bold (weight 700), chosen by measuring five open-licensed grotesques against
the approved reference and taking the closest fit on letter widths, x-height
and stroke weight.

The glyphs are embedded as outlines, not as text — the SVGs need no font
installed and render identically everywhere. Plus Jakarta Sans is licensed
under the SIL Open Font License 1.1, which permits this.

## Clear space and minimum size

Leave clear space equal to the height of the copper terminal on every side.
Do not place the lockup smaller than 120 px wide; below that use the mark
alone, and below 24 px use the reduced mark.

## Do not

- Recolour the mark, or use copper for anything but the terminal.
- Add gradients, shadows, glow or 3D.
- Stretch, rotate, or change the spacing between mark and wordmark.
- Place the charcoal mark on a dark background — use `arcet-logo-mono.svg`.
- Redraw the route. Its shape is the argument.

## Regenerating

The assets are generated from measured geometry and real glyph outlines rather
than drawn by hand. The source reference is `design/brand-reference.png`;
the geometry was derived by scanning it for stroke weight, the octagon's
centre, half-width, half-height and chamfer, and the copper terminal's radius.

The generator is not committed — it needs `fonttools`, `cairosvg` and a copy of
Plus Jakarta Sans, none of which are project dependencies. These files are the
artefact; treat them as source.
