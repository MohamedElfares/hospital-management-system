"""Helpers for assembling a tutorial page from the canonical template.

A page is the template's shell — head, styles, reader controls, scripts —
with a new sidebar, hero, steps and verification section in between. These
helpers render those blocks, and ``chunk`` copies code straight out of a
repository file so a panel can never drift from what was committed.

Writing a page means one short script that calls ``libraries``, ``step``
(or ``section`` when a step needs a terminal block instead of a code panel),
``verify_section`` and finally ``page``::

    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).parent))
    import page_builder as pb

    body = pb.libraries("Nothing new to install.", "Available already", [
        ("pytest", "Finds and runs the tests."),
    ])
    body += pb.step(
        "01",
        "One behaviour per test",
        ["Why this step exists, in one or two short paragraphs."],
        ["What the reader's code has to <b>accomplish</b>."],
        [("pytest.fixture", "<b>What it is.</b> Why this step needs it.")],
        [("backend/tests/test_logging.py", pb.chunk("backend/tests/test_logging.py",
                                                    "def test_", None))],
        ["A tick box aimed at a real mistake."],
    )
    verify = pb.verify_section(
        pb.paras(["Run it and read the output."])
        + pb.term("uv run pytest -q", [], ["20 passed in 1.00s"]),
        ["The command printed what this page shows."],
    )
    pb.write_page(
        slug="stage-09-example",
        html=pb.page(
            stage="09",
            title="Example stage",
            description="Stage 09 of the Hospital Management System build: an example.",
            h1="Example stage",
            lede="One sentence on what the stage achieves.",
            files=[("backend/app/example.py", "new")],
            nav=["First step"],
            body=body,
            verify=verify,
        ),
    )

Then validate the result before showing it to anyone::

    python .claude/skills/hms-tutorial/scripts/check_tutorial.py tutorial/stage-09-example.html

Rules this file exists to keep: code panels are copied, never retyped;
terminal blocks hold output that a command actually produced; and the
template's ``<style>`` and ``<script>`` are never touched, so every page in
the series looks the same.
"""

# Escapes code and command output so it survives inside HTML.
import html

# Locates the repository, the template and the output folder.
from pathlib import Path

# The repository root: this file is at .claude/skills/hms-tutorial/scripts/.
ROOT = Path(__file__).resolve().parents[4]

# The canonical template, which is also the worked example (stage 03).
TEMPLATE_PATH = ROOT / "docs" / "templates" / "tutorial-template.html"
TEMPLATE = TEMPLATE_PATH.read_text(encoding="utf-8")

# Everything above the sidebar (head, styles, reader controls) and everything
# from the end of the content (footer scripts) are reused unchanged.
HEAD = TEMPLATE[: TEMPLATE.index("\t\t<!-- BLOCK: sidebar contents")]
TAIL = TEMPLATE[TEMPLATE.index("\t\t\t\t</main>") :]

SVG_TASK = '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">\n\t\t\t\t\t\t\t\t\t<path d="M12 20h9M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4z" />\n\t\t\t\t\t\t\t\t</svg>'
SVG_HINT = '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">\n\t\t\t\t\t\t\t\t\t\t<path d="m9 18 6-6-6-6" />\n\t\t\t\t\t\t\t\t\t</svg>'
SVG_FILE = '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">\n\t\t\t\t\t\t\t\t\t\t<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />\n\t\t\t\t\t\t\t\t\t\t<path d="M14 2v6h6" />\n\t\t\t\t\t\t\t\t\t</svg>'
SVG_EYE = '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">\n\t\t\t\t\t\t\t\t\t\t\t<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7z" />\n\t\t\t\t\t\t\t\t\t\t\t<circle cx="12" cy="12" r="3" />\n\t\t\t\t\t\t\t\t\t\t</svg>'
SVG_BOOK = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">\n\t\t\t\t\t\t\t\t\t<path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20" />\n\t\t\t\t\t\t\t\t\t<path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z" />\n\t\t\t\t\t\t\t\t</svg>'
SVG_TERM = '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">\n\t\t\t\t\t\t\t\t\t<path d="m4 17 6-6-6-6M12 19h8" />\n\t\t\t\t\t\t\t\t</svg>'


def condense_docstrings(code: str) -> str:
    """Shorten each docstring to its summary and its structured sections.

    A panel is an excerpt, so a long docstring may be cut to its first line
    plus ``Attributes``, ``Returns``, ``Raises`` or ``Yields``; the validator
    ignores docstrings for exactly this reason. Code itself is never touched.

    Args:
        code: Python source taken from a repository file.

    Returns:
        The same source with each docstring reduced.
    """
    lines = code.split("\n")
    out: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        if stripped.startswith('"""') and stripped.count('"""') == 1:
            indent = line[: len(line) - len(line.lstrip())]
            block = [line]
            index += 1
            while index < len(lines):
                block.append(lines[index])
                if '"""' in lines[index]:
                    break
                index += 1
            summary, body = block[0], block[1:-1]
            kept: list[str] = []
            keeping = False
            for entry in body:
                header = entry.strip()
                if header in ("Attributes:", "Returns:", "Raises:", "Yields:"):
                    keeping = True
                    kept += ["", entry]
                    continue
                if (
                    header.endswith(":")
                    and entry.startswith(indent)
                    and not entry.startswith(indent + " ")
                ):
                    keeping = False
                if keeping:
                    if header == "" and kept and kept[-1] == "":
                        continue
                    kept.append(entry)
            while kept and kept[-1].strip() == "":
                kept.pop()
            out += [summary, *kept, indent + '"""'] if kept else [summary + '"""']
            index += 1
            continue
        out.append(line)
        index += 1
    return "\n".join(out)


def chunk(relative_path: str, start: str, end: str | None) -> str:
    """Copy part of a repository file, from one marker to another.

    Panels quote committed files, so this reads the file rather than taking
    code from a conversation. Markers are literal text: the first line of a
    function, a comment above a block, or ``None`` to read to the end.

    Args:
        relative_path: Path from the repository root, as the panel labels it.
        start: Text where the excerpt begins.
        end: Text where it stops, or ``None`` for the rest of the file.

    Returns:
        The excerpt, with docstrings condensed.
    """
    text = (ROOT / relative_path).read_text(encoding="utf-8").replace("\r\n", "\n")
    first = text.index(start)
    last = text.index(end, first) if end else len(text)
    return condense_docstrings(text[first:last].rstrip("\n"))


def panel(relative_path: str, code: str, language: str = "python") -> str:
    """Render a blurred code panel labelled with the file it quotes.

    The blur is the mechanism of the series, not decoration: the reader
    attempts the code first and clicks to compare.

    Args:
        relative_path: Path from the repository root; the validator checks
            the panel against this file.
        code: The excerpt, normally from ``chunk``.
        language: Highlight.js language. The template loads python, yaml,
            ini and bash.

    Returns:
        The panel's HTML.
    """
    return (
        '\t\t\t\t\t\t<div class="code is-masked">\n'
        '\t\t\t\t\t\t\t<div class="code__head">\n'
        '\t\t\t\t\t\t\t\t<span class="code__path">\n'
        f"\t\t\t\t\t\t\t\t\t{SVG_FILE}\n\t\t\t\t\t\t\t\t\t{relative_path}\n"
        "\t\t\t\t\t\t\t\t</span>\n"
        '\t\t\t\t\t\t\t\t<button class="code__copy" type="button">Copy</button>\n'
        "\t\t\t\t\t\t\t</div>\n"
        '\t\t\t\t\t\t\t<div class="code__body">\n'
        f'\t\t\t\t\t\t\t\t<pre><code class="language-{language}">{html.escape(code, quote=False)}</code></pre>\n'
        f'\t\t\t\t\t\t\t\t<button class="code__mask" type="button" aria-label="Reveal the code for {relative_path}">\n'
        "\t\t\t\t\t\t\t\t\t<span>\n"
        f"\t\t\t\t\t\t\t\t\t\t{SVG_EYE}\n\t\t\t\t\t\t\t\t\t\tWrite yours first — click to compare\n"
        "\t\t\t\t\t\t\t\t\t</span>\n"
        "\t\t\t\t\t\t\t\t</button>\n"
        "\t\t\t\t\t\t\t</div>\n"
        "\t\t\t\t\t\t</div>\n"
    )


def task(items: list[str]) -> str:
    """Render the numbered outcome list of a step.

    Args:
        items: Outcomes the reader's code must achieve, not keystrokes.

    Returns:
        The block's HTML.
    """
    entries = "".join(f"\t\t\t\t\t\t\t\t<li>{item}</li>\n" for item in items)
    return (
        '\t\t\t\t\t\t<div class="task">\n\t\t\t\t\t\t\t<div class="block-label">\n'
        f"\t\t\t\t\t\t\t\t{SVG_TASK}\n\t\t\t\t\t\t\t\tWhat your code has to do\n\t\t\t\t\t\t\t</div>\n"
        f"\t\t\t\t\t\t\t<ol>\n{entries}\t\t\t\t\t\t\t</ol>\n\t\t\t\t\t\t</div>\n"
    )


def hint(entries: list[tuple[str, str]], title: str = "Hint — the imports this step needs") -> str:
    """Render the folded hint list.

    Args:
        entries: ``(name, description)`` pairs; the description says what the
            name is and why this step needs it.
        title: Summary text, changed when a step hints at keys rather than
            imports.

    Returns:
        The block's HTML.
    """
    rows = "".join(
        f"\t\t\t\t\t\t\t\t<div>\n\t\t\t\t\t\t\t\t\t<dt>{name}</dt>\n"
        f"\t\t\t\t\t\t\t\t\t<dd>{description}</dd>\n\t\t\t\t\t\t\t\t</div>\n"
        for name, description in entries
    )
    return (
        '\t\t\t\t\t\t<details class="hint">\n\t\t\t\t\t\t\t<summary>\n\t\t\t\t\t\t\t\t<span class="block-label">\n'
        f"\t\t\t\t\t\t\t\t\t{SVG_HINT}\n\t\t\t\t\t\t\t\t\t{title}\n"
        "\t\t\t\t\t\t\t\t</span>\n\t\t\t\t\t\t\t</summary>\n"
        f'\t\t\t\t\t\t\t<dl class="import-list">\n{rows}\t\t\t\t\t\t\t</dl>\n\t\t\t\t\t\t</details>\n'
    )


def checks(items: list[str], label: str = "Check yours against it") -> str:
    """Render a tick-box list.

    Args:
        items: Statements in the first person, each aimed at a real mistake.
        label: Heading; the closing list uses "Before you commit".

    Returns:
        The block's HTML.
    """
    entries = "".join(
        f'\t\t\t\t\t\t\t\t<li><label><input type="checkbox" /><span>{item}</span></label></li>\n'
        for item in items
    )
    return (
        f'\t\t\t\t\t\t<div class="check">\n\t\t\t\t\t\t\t<div class="block-label">{label}</div>\n'
        f"\t\t\t\t\t\t\t<ul>\n{entries}\t\t\t\t\t\t\t</ul>\n\t\t\t\t\t\t</div>\n"
    )


def term(command: str, output: list[str], success: list[str], where: str = "backend/") -> str:
    """Render a terminal block holding a command and its real output.

    Args:
        command: What was typed, without a ``$``; the CSS adds the prompt.
            Empty when the block shows output alone.
        output: Lines as they were printed, in the order they appeared.
        success: Closing lines, styled to stand out.
        where: Label for the directory or terminal the command ran in.

    Returns:
        The block's HTML.
    """
    lines = "".join(
        f'<div class="term__out">{html.escape(line, quote=False)}</div>' for line in output
    )
    final = "".join(
        f'<div class="term__out--ok">{html.escape(line, quote=False)}</div>' for line in success
    )
    typed = f'<div class="term__cmd">{html.escape(command, quote=False)}</div>' if command else ""
    return (
        '\t\t\t\t\t\t<div class="term">\n\t\t\t\t\t\t\t<div class="term__head">\n'
        f"\t\t\t\t\t\t\t\t{SVG_TERM}\n\t\t\t\t\t\t\t\t{where}\n\t\t\t\t\t\t\t</div>\n"
        f'\t\t\t\t\t\t\t<div class="term__body">{typed}{lines}{final}</div>\n'
        "\t\t\t\t\t\t</div>\n"
    )


def paras(texts: list[str]) -> str:
    """Render prose paragraphs.

    Args:
        texts: Paragraphs, which may contain inline HTML.

    Returns:
        The paragraphs' HTML.
    """
    return "".join(f"\t\t\t\t\t\t<p>\n\t\t\t\t\t\t\t{text}\n\t\t\t\t\t\t</p>\n" for text in texts)


def note(text: str) -> str:
    """Render the spaced paragraph that follows a terminal block.

    Args:
        text: What the output means, including what it does not prove.

    Returns:
        The paragraph's HTML.
    """
    return f'\t\t\t\t\t\t<p style="margin-top: var(--sp-3)">\n\t\t\t\t\t\t\t{text}\n\t\t\t\t\t\t</p>\n'


def section(
    number: str,
    heading: str,
    prose: list[str],
    tasks: list[str],
    hints: list[tuple[str, str]] | None,
    blocks: str,
    check_items: list[str],
    hint_title: str = "Hint — the imports this step needs",
) -> str:
    """Render one numbered step from already-rendered blocks.

    Use this when a step shows a terminal block, several panels, or anything
    other than a single code panel; ``step`` is the shorthand for the common
    case.

    Args:
        number: Two digits; it becomes the section id ``step-NN``.
        heading: States the idea in plain words, not the API name.
        prose: One or two paragraphs on why the step exists.
        tasks: Outcomes for the reader's code.
        hints: Hint entries, or ``None`` for no hint block.
        blocks: Rendered HTML placed between the hint and the check list.
        check_items: Tick boxes.
        hint_title: Summary text of the hint block.

    Returns:
        The section's HTML.
    """
    parts = [
        f'\t\t\t\t\t<section class="section reveal" id="step-{number}">\n',
        f'\t\t\t\t\t\t<div class="section__kicker">Step {number}</div>\n',
        f"\t\t\t\t\t\t<h2>{heading}</h2>\n",
        paras(prose),
        "\n",
        task(tasks),
        "\n",
    ]
    if hints:
        parts += [hint(hints, hint_title), "\n"]
    parts += [blocks, "\n", checks(check_items), "\t\t\t\t\t</section>\n\n"]
    return "".join(parts)


def step(
    number: str,
    heading: str,
    prose: list[str],
    tasks: list[str],
    hints: list[tuple[str, str]] | None,
    panels: list[tuple[str, str]],
    check_items: list[str],
    hint_title: str = "Hint — the imports this step needs",
    language: str = "python",
) -> str:
    """Render a step whose blocks are code panels.

    Args:
        number: Two digits; it becomes the section id ``step-NN``.
        heading: States the idea in plain words.
        prose: One or two paragraphs on why the step exists.
        tasks: Outcomes for the reader's code.
        hints: Hint entries, or ``None``.
        panels: ``(relative_path, code)`` pairs, normally from ``chunk``.
        check_items: Tick boxes.
        hint_title: Summary text of the hint block.
        language: Highlight.js language for every panel in this step.

    Returns:
        The section's HTML.
    """
    blocks = "\n".join(panel(path, code, language) for path, code in panels)
    return section(number, heading, prose, tasks, hints, blocks, check_items, hint_title)


def libraries(intro: str, label: str, items: list[tuple[str, str]]) -> str:
    """Render the opening callout of what the reader already has.

    Args:
        intro: A paragraph saying what is new, if anything.
        label: Callout heading, such as "Installed in Stage 02".
        items: ``(name, description)`` pairs.

    Returns:
        The section's HTML.
    """
    entries = "".join(
        f"\t\t\t\t\t\t\t\t<li><b>{name}</b><span>{description}</span></li>\n"
        for name, description in items
    )
    return (
        "\t\t\t\t\t<!-- BLOCK: callout — packages already installed ------ -->\n"
        '\t\t\t\t\t<section class="section reveal" id="libraries">\n'
        '\t\t\t\t\t\t<div class="section__kicker">Before you start</div>\n'
        "\t\t\t\t\t\t<h2>What you already have</h2>\n"
        f"{paras([intro])}\n"
        '\t\t\t\t\t\t<aside class="callout">\n\t\t\t\t\t\t\t<div class="block-label">\n'
        f"\t\t\t\t\t\t\t\t{SVG_BOOK}\n\t\t\t\t\t\t\t\t{label}\n\t\t\t\t\t\t\t</div>\n\n"
        f'\t\t\t\t\t\t\t<ul class="callout__list">\n{entries}\t\t\t\t\t\t\t</ul>\n'
        "\t\t\t\t\t\t</aside>\n\t\t\t\t\t</section>\n\n"
    )


def verify_section(blocks: str, check_items: list[str]) -> str:
    """Render the closing "Check your work" section.

    Args:
        blocks: Rendered prose, terminal blocks and a closing ``note`` saying
            what the output does and does not prove.
        check_items: The "Before you commit" tick boxes.

    Returns:
        The section's HTML.
    """
    return (
        "\t\t\t\t\t<!-- BLOCK: verification, terminal output ---------------- -->\n"
        '\t\t\t\t\t<section class="section reveal" id="verify">\n'
        '\t\t\t\t\t\t<div class="section__kicker">Finish</div>\n'
        "\t\t\t\t\t\t<h2>Check your work</h2>\n"
        f"{blocks}\n"
        f"{checks(check_items, 'Before you commit')}"
        "\t\t\t\t\t</section>\n\n"
    )


def page(
    stage: str,
    title: str,
    description: str,
    h1: str,
    lede: str,
    files: list[tuple[str, str]],
    nav: list[str],
    body: str,
    verify: str,
    milestone: str = "Milestone 1.1 · Foundation",
) -> str:
    """Assemble a whole page around the template's shell.

    The stage number has to agree in the title, the badge, the sidebar and
    the footer; passing it once keeps them in step, and the validator checks
    the result.

    Args:
        stage: Two digits, such as ``"09"``.
        title: Browser title, without the series suffix.
        description: Meta description, mentioning the stage number.
        h1: Page heading.
        lede: One sentence under the heading.
        files: ``(path, "new" | "edit")`` pairs for the files-touched row.
        nav: Sidebar labels, one per step, in order.
        body: The callout and the steps.
        verify: The closing section, from ``verify_section``.
        milestone: Eyebrow text next to the stage badge.

    Returns:
        The complete page.
    """
    import re

    head = re.sub(
        r"<title>.*?</title>", f"<title>{title} — HMS Tutorial</title>", HEAD, count=1
    )
    head = re.sub(
        r'(name="description"\s*content=")[^"]*(")',
        lambda match: match.group(1) + description + match.group(2),
        head,
        count=1,
    )

    links = "".join(
        f'\t\t\t\t<a class="nav-link" href="#step-{index + 1:02d}">'
        f'<span class="nav-link__num">{index + 1:02d}</span>{label}</a>\n'
        for index, label in enumerate(nav)
    )
    sidebar = (
        "\t\t<!-- BLOCK: sidebar contents ------------------------------------ -->\n"
        '\t\t<nav class="sidebar" id="sidebar" aria-label="Stage contents">\n'
        '\t\t\t<div class="sidebar__brand">Hospital Management System</div>\n'
        f'\t\t\t<div class="sidebar__stage">{milestone.split(" · ")[0]} · Stage {stage}</div>\n\n'
        '\t\t\t<div class="nav-group">\n\t\t\t\t<div class="nav-group__label">Before you start</div>\n'
        '\t\t\t\t<a class="nav-link" href="#libraries">What you already have</a>\n\t\t\t</div>\n\n'
        '\t\t\t<div class="nav-group">\n\t\t\t\t<div class="nav-group__label">Build it</div>\n'
        f"{links}\t\t\t</div>\n\n"
        '\t\t\t<div class="nav-group">\n\t\t\t\t<div class="nav-group__label">Finish</div>\n'
        '\t\t\t\t<a class="nav-link" href="#verify">Check your work</a>\n\t\t\t</div>\n'
        "\t\t</nav>\n\n"
    )

    touched = "".join(f"\t\t\t\t\t\t<span>{path} <em>{kind}</em></span>\n" for path, kind in files)
    hero = (
        '\t\t<div class="shell">\n\t\t\t<div class="column">\n'
        "\t\t\t\t<!-- BLOCK: page header ---------------------------------- -->\n"
        '\t\t\t\t<header class="hero">\n\t\t\t\t\t<div class="hero__eyebrow">\n'
        f'\t\t\t\t\t\t<span class="stage-badge">Stage {stage}</span>\n'
        f"\t\t\t\t\t\t<span>{milestone}</span>\n\t\t\t\t\t</div>\n"
        f"\t\t\t\t\t<h1>{h1}</h1>\n"
        f'\t\t\t\t\t<p class="lede">\n\t\t\t\t\t\t{lede}\n\t\t\t\t\t</p>\n'
        f'\t\t\t\t\t<div class="hero__files">\n{touched}\t\t\t\t\t</div>\n'
        "\t\t\t\t</header>\n\n"
        '\t\t\t\t<main class="content" id="main">\n'
    )

    footer = (
        '\t\t\t\t\t<footer class="foot">\n'
        f'\t\t\t\t\t\t<span>Hospital Management System · {milestone.split(" · ")[0]} · Stage {stage}</span>\n'
        "\t\t\t\t\t\t<span>Written after the stage was built and verified.</span>\n"
        "\t\t\t\t\t</footer>\n"
    )

    return head + sidebar + hero + body + verify + footer + TAIL


def write_page(slug: str, html_text: str) -> Path:
    """Write a finished page into the tutorial folder.

    Args:
        slug: File name without the extension, such as ``stage-09-example``.
        html_text: The page, from ``page``.

    Returns:
        The path written, so a builder script can print it.
    """
    destination = ROOT / "tutorial" / f"{slug}.html"
    destination.write_text(html_text, encoding="utf-8", newline="\n")
    return destination
