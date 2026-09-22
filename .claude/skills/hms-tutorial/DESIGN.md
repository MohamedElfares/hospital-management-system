# Tutorial Page Design System

The visual contract every tutorial page in this project shares. Read this before changing any
CSS; the values themselves live as custom properties at the top of the template, so a change
made there flows through the whole page.

## Contents

1. Principles
2. Colour
3. Typography and the text-size control
4. Space and shape
5. Motion
6. Component anatomy
7. Responsive behaviour
8. Accessibility floor
9. Decisions already settled

---

## 1. Principles

- **Whitespace and type carry the design.** There is no decorative layer: no gradients, no
  illustrations, no colour-coded boxes competing for attention.
- **Hairlines are the only ornament.** `1px solid var(--rule)` separates things; nothing is
  ever thicker.
- **The accent is rare.** It marks exactly four kinds of thing: the stage badge, the active
  nav item, the progress bar, and block labels. If a fifth use appears, something else should
  give the accent up.
- **Rounding means "this is a UI object".** Code panels, terminals, callouts and controls get
  a radius; prose, rules and lists never do.
- **The code panel always separates itself from the page.** Pages ship dark, and the panel
  goes one shade darker than the canvas; in the light theme the canvas turns ivory while the
  panel stays dark. Either way the eye can tell reading from typing at a glance.

## 2. Colour

Proportions follow 70 / 20 / 10: canvas, surfaces, accent.

| Token | Dark (default) | Light (opt-in) | Used for |
|---|---|---|---|
| `--bg` | `#161512` | `#faf8f4` | Page canvas |
| `--surface` | `#1e1d19` | `#ffffff` | Callout, hint, check cards |
| `--surface-sunken` | `#1a1916` | `#f6f2ea` | Inline code, hover fills |
| `--rule` | `#2e2c27` | `#e6e0d5` | Hairlines |
| `--rule-strong` | `#46423a` | `#cfc7b7` | Tick-box border |
| `--ink` | `#ece7dc` | `#1b1a17` | Headings, emphasis |
| `--ink-mid` | `#bab3a6` | `#57534b` | Body prose |
| `--ink-soft` | `#948d81` | `#6f6a60` | Labels, kickers, metadata |
| `--accent` | `#6fc3b5` | `#0f766e` | Links, badges, active states |
| `--accent-ink` | `#14201e` | `#ffffff` | Marks drawn *on* the accent |
| `--accent-wash` / `--accent-line` | teal at 12% / 42% | teal at 9% / 35% | Badge fill, callout edge |
| `--code-bg` | `#100f0d` | `#1b1a17` | Code and terminal body |
| `--code-head` | `#1a1916` | `#232220` | Panel header |
| `--code-rule` | `#2b2924` | `#302e2a` | Panel borders |
| `--code-ink` / `--code-dim` | `#ece7dc` / `#9a9388` | `#ece7dc` / `#979085` | Code text / paths, output |

Seven syntax tokens (`--syn-comment`, `--syn-keyword`, `--syn-string`, `--syn-number`,
`--syn-func`, `--syn-class`, `--syn-meta`) are shared by both themes — they were picked on a
dark surface to begin with. They are mapped onto highlight.js classes in the stylesheet, so
the CDN theme is never loaded and colours stay in the token system.

**Theme mechanics.** Dark is what these pages ship with, unconditionally: `:root` carries the
dark palette and `:root[data-theme="light"]` is the reader's opt-in from the toggle. The
operating system's preference is deliberately not consulted, so a page opens the same way on
every machine and screenshots stay consistent. An inline script in `<head>` applies a stored
choice before first paint, so there is no flash.

Any new colour token needs a light counterpart, or that element keeps its dark value on a
light page — the validator treats a missing one as an error. Syntax tokens are the documented
exception, since the code panel is dark in both themes.

Teal comes from the "health" row of the bento accent guidance; it is the project's colour, not
a per-page choice. Don't vary it between stages.

## 3. Typography and the text-size control

Three families: **Fraunces** (headings), **DM Sans** (prose, UI), **JetBrains Mono** (code,
paths, step numbers, kickers).

| Token | Base | Role |
|---|---|---|
| `--size-label` | 11px | Tracked uppercase labels and kickers |
| `--size-small` | 13px | Captions, nav, check text |
| `--size-code` | 13px | Code and terminal |
| `--size-task` | 15px | Task and check lists |
| `--size-body` | 17px | Prose |
| `--size-lede` | 19px | Hero intro |
| `--size-brand` | ~17px | Sidebar brand |
| `--size-h3` / `--size-h2` / `--size-h1` | `clamp()` | Headings |

Headings are serif at **weight 400** — contrast comes from size, never from bold. Labels are
always small tracked uppercase sans; the serif never does UI work. Prose is capped at
`--measure` (68ch).

**The multiplier.** Every size token is `calc(base × var(--type-scale))`, and the control steps
that one variable through `0.9 / 1 / 1.1 / 1.25 / 1.4`. That is why each class keeps its own
size instead of everything flattening to one — any new size token must follow the same
`calc()` pattern or it will stop responding to the control. Chrome (the control pill itself)
deliberately does not scale.

## 4. Space and shape

8px base: `--sp-1` `0.5rem` → `--sp-12` `6rem`. Sections are `--sp-8` apart, the hero opens at
`--sp-12`, blocks inside a step are `--sp-3` apart.

Radius: `--radius-panel` 10px (code, terminal, callout, hint, check), `--radius-control` 6px
(buttons), `--radius-check` 4px (tick box), `--radius-pill` (badges, controls, mask button).
Everything else is square.

Shadows: only two, both from `--shadow-panel` — the mobile controls and the off-canvas
sidebar. Cards never lift.

## 5. Motion

One scroll reveal: 12px fade-up, `--dur-reveal` (0.55s) on `--ease-out`, fired once per
section by an IntersectionObserver. UI transitions use `--dur-ui` (0.18s). No spring easings,
no hover lift, no staggering — a page being read should hold still.

`prefers-reduced-motion: reduce` flattens every duration and disables the reveal. Anything new
must keep working under it.

## 6. Component anatomy

```
.hero            .hero__eyebrow > .stage-badge · milestone
                 h1 · .lede · .hero__files (path + em tag)

.section         .section__kicker (STEP 01) → h2 → prose
  .task          .block-label + <ol> with mono counters
  .hint          <details> → summary(.block-label) → .import-list (dt/dd pairs)
  .code          .code__head (.code__path + .code__copy)
                 .code__body (pre > code.language-python + .code__mask button)
  .check         .block-label + <ul> of <label><input type="checkbox"><span>

.term            .term__head (cwd) + .term__body (.term__cmd / .term__out / --ok)
.callout         .block-label + .callout__list (b + span)
.controls        two text-size buttons + divider + theme button
```

Rules worth keeping:

- The mask is a real `<button>` with an `aria-label`, and once revealed it is removed from the
  tab order (`visibility: hidden`), so a keyboard user doesn't hit invisible controls.
- Tick boxes are native `<input type="checkbox">` inside a `<label>`: the whole row is
  clickable and keyboard support is free. No JavaScript is involved.
- The copy button copies the panel's text and swaps its own label for 1.6s.
- `.block-label` is shared by task, hint, callout and check so the labels stay identical.

## 7. Responsive behaviour

One stacked column at every width — the reader explicitly rejected a split layout, because
instructions and code belong in reading order.

- **> 1080px:** fixed sidebar, content column `--content-max` (820px), centred.
- **≤ 1080px:** sidebar becomes off-canvas behind the "Contents" button, with a scrim and
  Escape to close; hero gains top padding so the fixed buttons don't collide.
- **≤ 640px:** body and code sizes step down (still through the multiplier), panel padding
  tightens, the import list and packages list stack to one column.

## 8. Accessibility floor

- Text contrast ≥ 4.5:1 in **both** themes, including muted labels. The validator prints the
  ratios; if a new colour lands below, darken or lighten it rather than shipping it.
- Visible focus everywhere: a 2px accent outline with 3px offset.
- Semantic structure: one `h1`, sections with `h2`, `<details>` for folded content, real
  buttons and checkboxes, a skip link, and `aria-label`s on icon-only controls.
- Icons are inline SVG with `aria-hidden="true"`, 1.5px stroke, `currentColor`. No emoji, no
  icon fonts.
- Print: navigation, controls and masks are hidden, code unblurs, and panels avoid page breaks.

## 9. Decisions already settled

Recorded so they aren't relitigated on the next page:

| Question | Decision | Why |
|---|---|---|
| Default theme | Dark, always; light is an opt-in that persists | One predictable opening state on every machine, and it matches where the reader is coding |
| Radius: 0, 12px or 20px? | 10px on UI objects only | Square panels read as unfinished; large radii read as marketing |
| Pure white or off-white? | Warm ivory `#faf8f4` | Long reading sessions beside a dark code panel |
| Body font | DM Sans | Satisfies "no Inter" and keeps the serif for headings |
| Motion | One fade-up, nothing else | Movement while reading is noise |
| Mac-style window dots on panels | Dropped | The file path already identifies the panel |
| Split (two-column) steps | Rejected | Instructions and code belong in reading order |
| Syntax theme | Ours, mapped onto highlight.js classes | Keeps colour in the token system; page still readable if the CDN is blocked |

External dependencies are deliberately limited to Google Fonts and highlight.js from cdnjs.
Everything else — layout, theme, controls, checkboxes — is vanilla and self-contained.
