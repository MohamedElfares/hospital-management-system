---
name: hms-tutorial
description: Build, extend, or fix the HTML tutorial pages for the Hospital Management System — one self-contained page per completed stage, with numbered steps, outcome-style tasks, folded import hints, blurred code panels the reader reveals to compare against their own attempt, terminal blocks, and tick-box checklists. Use this skill whenever the user asks for a tutorial, walkthrough, guide, lesson, explainer page, or "write up" of a stage, milestone, or feature they have just finished in this project, and whenever they ask to change the look, layout, colours, or components of an existing tutorial page. Always load this before writing any tutorial HTML — never start from a blank file, never restyle from scratch, and never re-derive the design from the bento/clean/minimal-serif skills.
---

# HMS Tutorial Pages

One page per completed stage of the build. The reader is the developer who is about to
write that stage themselves: they read *why*, attempt the code, then reveal the panel and
compare. That is the whole point of the format — the page is an exercise, not a transcript.

Because of that, everything on the page has to be true of this repository. A step that
describes code the repo doesn't have, or a terminal block with invented output, breaks the
one promise the format makes.

## Before writing anything

1. **Confirm the stage is finished and verified.** These pages are written after the work is
   committed, not as a plan. If the user asks for a tutorial about something unbuilt, say so
   and offer to write it once the stage is done.
2. **Read the real files** with the Read tool and copy code from them. Never reconstruct code
   from memory or from this conversation — files drift, and a wrong line in a tutorial is
   worse than no tutorial.
3. **Re-run the verification commands** and paste their actual output into the terminal
   blocks. If a command can't be run right now, leave the block out rather than invent a
   result.
4. **Check `docs/PROJECT_PLAN.md`** (§18 for the milestone, plus the relevant design section)
   so the page's vocabulary matches the plan.

## Offering a page, and waiting

These pages are written at one moment: when a stage is genuinely done — acceptance criteria
met, linters and tests passing, work committed. At that moment, offer one in a single line,
for example *"Want me to write the tutorial page for this stage?"*, and then wait.

Never generate one unasked, never write one for unfinished work, and don't pitch it twice for
the same stage — if the answer was no, note it and move on. The offer is a convenience, not a
nudge; the stage is finished either way.

## Where things live

| Path | What it is |
|---|---|
| `docs/templates/tutorial-template.html` | The canonical template **and** the worked example (Stage 03, database layer). Copy it to start a new page. |
| `tutorial/stage-NN-<slug>.html` | Where finished tutorials go, at the repository root, numbered in build order. `tutorial/README.md` explains the folder to a reader. |
| `DESIGN.md` (this skill) | Tokens, palette, type scale, component anatomy. Read it before touching any CSS. |
| `CONTENT.md` (this skill) | How to write the prose, tasks, hints and checks. Read it before writing the copy. |
| `scripts/page_builder.py` (this skill) | Helpers that render the blocks and assemble a page around the template. `chunk` copies code out of a repository file so a panel cannot drift. |
| `scripts/check_tutorial.py` (this skill) | Validator. Run it before showing a page to the user. |

Build a page with `scripts/page_builder.py` rather than editing HTML by hand: a short script
calls `libraries`, `step` (or `section` when a step shows a terminal block), `verify_section`
and `page`, and its module docstring carries a worked example. Panels come from
`chunk("backend/app/…", start, end)`, which reads the committed file, so a panel can only
quote what the repository actually contains.

Copy the template, then replace the content inside `<main>` and the sidebar. Leave `<style>`
and `<script>` alone unless the user asks for a design or behaviour change — that is what
keeps every page in the series identical in look and feel.

## Page contract

The blocks appear in this order. Not every stage needs every block, but the order never
changes, because the reader learns the rhythm once and then knows where to look.

| Block | Class | Purpose |
|---|---|---|
| Reading progress | `.progress` | Fixed 2px bar |
| Contents | `.sidebar` | Stage nav, scroll-spied; off-canvas below 1080px |
| Reader controls | `.controls` | Text size (5 steps) and theme toggle |
| Page header | `.hero` | Stage badge, milestone, title, one-line lede, files-touched row |
| Packages callout | `.callout` | What is already installed and what it is for |
| Step | `.section` | Kicker → `h2` → why-prose → `.task` → `.hint` → `.code` → `.check` |
| Terminal | `.term` | A command and its real output |
| Check list | `.check` | Tick boxes the reader ticks off |
| Footer | `.foot` | Stage line |

A step is one idea. Six steps is comfortable; past eight, the stage probably wants splitting
into two pages.

## Filling the template

- **Stage number appears in four places:** `<title>`, the `.stage-badge`, `.sidebar__stage`,
  and the footer. The meta description mentions it too. Keep them in step.
- **Sidebar links must match section ids exactly** — the scroll-spy and the validator both
  depend on it. Use `step-01`, `step-02`, … and `verify` for the closing section.
- **Every code panel keeps `class="code is-masked"`.** The blur is the mechanism, not
  decoration: it lets the reader attempt the code first. Panels also need the real file path
  in `.code__path` and a working copy button.
- **Code is verbatim** from the repo file named in the path. Long docstrings may be condensed
  to their summary paragraph plus `Attributes`/`Returns`, since the page is an excerpt — but
  never edit the code itself to make it read better.
- **Terminal blocks** use `.term__cmd` for the command (the `$` is added by CSS — don't type
  it) and `.term__out` / `.term__out--ok` for output.
- **Close with a "Before you commit" check list** covering the commands, linting, docstrings,
  and the project's rule that the developer can explain every line.

## Adding a new kind of block

The current set covers explanation, instruction, hints, code, commands and verification.
When a stage genuinely needs something else — a diagram, a before/after comparison, a decision
table — ask the user first, then:

1. Build it from existing tokens; never hardcode a colour, size, radius or duration.
2. Give it a block comment in the stylesheet like the others.
3. Add it to the table above and to `DESIGN.md`.
4. Check it in both themes and at 140% text size before showing it.

## Verify before showing the user

```bash
python .claude/skills/hms-tutorial/scripts/check_tutorial.py tutorial/stage-NN-slug.html
```

It checks balanced markup, that every `var(--token)` is defined, light/dark parity, contrast
ratios in both themes, sidebar↔section id agreement, that code panels are masked and labelled,
that every check box is inside a label, that the stage number is consistent — and, most
importantly, that each code panel matches the repo file it claims to quote.

Fix what it reports, then tell the user what was checked. Open the page in a browser if you
can; the validator sees structure, not layout.

## Scope

This skill is the blend of the bento, clean and minimal-serif styles that the project already
settled on — don't load those skills for tutorial work and don't re-litigate their conflicts.
`DESIGN.md` records which decision won and why.
