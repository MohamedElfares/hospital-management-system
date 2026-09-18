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
