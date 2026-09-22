# Writing a Stage

How the words work. The design is settled (`DESIGN.md`); this is the part that decides whether
a page actually teaches.

## The shape of a step

```
kicker          STEP 03
heading         Timestamps from one clock — the database's
why-prose       1–2 short paragraphs: the problem this solves, and the consequence of
                getting it wrong
task            "What your code has to do" — outcomes, not keystrokes
hint            <details> with the imports this step needs and why
code            blurred until the reader clicks
check           tick boxes phrased in the first person
```

The reader meets the problem, tries it, then compares. Every block should be answering the
question the previous one raised.

## Headings and why-prose

Headings state the idea in plain words, not the API name. "Timestamps from one clock — the
database's" tells you the point; "Add the TimestampMixin" does not.

The prose explains why the step exists and what goes wrong without it. Two paragraphs at most —
if a third is needed, the step is really two steps.

> An app server whose clock drifts by a few seconds can otherwise produce a row that was
> updated before it was created.

Concrete consequences like that are what make a rule stick. Prefer them over restating the
requirement.

## Tasks: outcomes, not keystrokes

The task list says what the code must **accomplish**, so the reader has something to solve. It
names the API only when the point of the step is that specific API.

**Weak — a dictation:**

> 1. Import `DateTime` and `func` from `sqlalchemy`.
> 2. Add `server_default=func.now()` to both columns.
> 3. Add `onupdate=func.now()` to `updated_at`.

**Strong — a specification:**

> 1. Store both as **timezone-aware UTC instants**, so comparing them with
>    `datetime.now(UTC)` works instead of raising `TypeError`.
> 2. Take both values from **the database's clock**, not the application's — including the
>    value written on every update.
> 3. Set the creation time **once, on insert**; refresh the change time on **every update made
>    through the ORM**.

Guidelines that keep tasks in that register:

- 4–6 items. Fewer means the step is thin; more means it is two steps.
- Bold the requirement, not the function name.
- State the failure the requirement prevents when it isn't obvious.
- Last item is usually a way to prove it works — a command, an import, a small experiment.
- Mention project rules that apply here (Ruff's single-line imports, "Alembic owns the
  schema", "services own the transaction"), because they shape the answer.

## Hints: the imports, and why

Folded away in a `<details>`, so a reader who wants to struggle first can. Each entry is the
imported name, a bold phrase saying what it is, and a sentence on why this step needs it.

> **func** — *A builder for SQL function calls.* `func.now()` is not a Python value — it is
> SQL that the database evaluates, which is how both columns share one clock.

> **Iterator** — *The return type of a generator function.* `Iterator[Session]` says "this
> yields sessions"; `Session` alone would be a lie that type checkers accept.

Only list what is new in that step, and say so when a name was already imported earlier. This
mirrors the project's rule that every import gets a one-line comment — the hint text and the
comment in the committed file should say the same thing.

## Checks: the reader's own mistakes

After the code, 3–5 tick boxes written in the first person, each aimed at a real failure mode
rather than a restatement of the code.

> - I passed `uuid.uuid4` — the function — and not `uuid.uuid4()`, which would give every row
>   the same ID.
> - I used *either* a `with` block *or* `try`/`finally` — not both, which would close twice.
> - Searching the file for `target_metadata` finds exactly one assignment.

Where to find them: the review findings from when the stage was actually built. Bugs that
happened are better check items than bugs that could theoretically happen. At least one item
should be about understanding rather than syntax — "I can explain why the ID is generated in
Python rather than by the database".

## Code panels

- Copy from the repo file, verbatim, with the Read tool.
- Condense a long docstring to its summary paragraph plus `Attributes`/`Returns` if the panel
  would otherwise be mostly prose — but never rewrite the code itself.
- One file path per panel, and the path is the real one, from the repo root.
- A step usually has one panel. Two is fine when a file has two distinct parts.

## Terminal blocks

Real commands, real output. Run them; paste what came back. The `$` comes from CSS, so the
command line contains only the command. Use `--ok` on the line that proves success.

If output is long, keep the lines that matter and the success line. Never fabricate a version
number, a path, or a timing.

## Voice

- Second person, present tense: "you", "your code".
- Plain words over ceremony: "so", "because", "otherwise" — not "hence", "thus", "in order to".
- Name trade-offs instead of hiding them ("a raw SQL `UPDATE` bypasses `onupdate` entirely").
- No emoji, no exclamation marks, no "simply" or "just" — the reader is learning this for the
  first time and nothing here is simple.
- British or American spelling is fine as long as one page is consistent with the repo's docs.

## The closing section

"Check your work" pairs the verification commands with a short paragraph interpreting the
output — including what a passing result does *not* prove. Then a final "Before you commit"
check list covering:

- the commands printed what the page shows
- `uv run ruff check .` and `uv run ruff format --check .` pass
- docstrings and one-line import comments are in place
- the developer can explain every line without the page

That last item is the project's actual definition of done, so it belongs on every page.
