# Tutorials

One self-contained HTML page per completed stage of the build. Open any file in a browser —
there is no build step, no server, and no dependency beyond Google Fonts and highlight.js.

Each page is written **after** its stage is finished and verified, so every line of code on it
is copied from the committed files and every terminal block shows output that was actually
produced.

## How to read one

Work top to bottom. For each step: read why it exists, do what the task describes, open the
hint if you want the imports, then click the blurred panel to compare your version with the
one in the repository, and tick off the checks.

The controls at the top right change the text size and switch between the dark default and a
light theme. Both choices are remembered in your browser.

## Naming

`stage-NN-<slug>.html`, for example `stage-03-database-layer.html`, numbered in build order.

## How they are made

The template and the worked example live in `docs/templates/tutorial-template.html`. The
`hms-tutorial` skill in `.claude/skills/` holds the design system, the writing guide, and a
validator that checks a finished page before it is committed:

```bash
python .claude/skills/hms-tutorial/scripts/check_tutorial.py tutorial/stage-NN-slug.html
```

## Why an early page can differ from today's code

Each page teaches the code as it was when its stage was finished, and later stages change
some of the same files: Stage 06, for example, adds a connection timeout to the session
module that Stage 03 introduced. An early page therefore shows the earlier version on
purpose, so each change is taught in the stage that makes it.

To keep those pages verifiable, every page records the commit it was written from in
`<meta name="hms-source-commit">`, and the validator compares its code panels with that
commit rather than with today's files. Pages 01–07 quote commits from the Milestone 1.1
branch (pull request #10), which a fresh clone doesn't include; fetch them once before
validating those pages:

```bash
git fetch origin refs/pull/10/head:refs/remotes/origin/pull/10
```
