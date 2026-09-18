"""Validate an HMS tutorial page before it is shown to anyone.

The tutorial pages are single self-contained HTML files with no build step, so
nothing else checks them: a stray tag, a token that was renamed in one theme
only, or a code panel that has drifted from the file it claims to quote would
all ship silently. This script is the substitute for that missing toolchain.

It reports errors (things that are wrong) and warnings (things worth a look),
and exits non-zero when there is at least one error, so it can be wired into a
command chain later.

Usage:
    python check_tutorial.py tutorial/stage-03-database-layer.html
    python check_tutorial.py <page.html> --repo-root .
"""

# Command-line arguments for the page path and the repository root.
import argparse

# Regular expressions for pulling token blocks, panels and ids out of the page.
import re

# Exit code, so a failed check can stop a chain of commands.
import sys

# Forgiving HTML tokenizer used to confirm that every element is closed.
from html.parser import HTMLParser

# Filesystem paths that behave the same on Windows and Linux.
from pathlib import Path

# Elements that never have a closing tag, including the SVG shapes used inline.
VOID_ELEMENTS = {
    "area", "base", "br", "circle", "col", "embed", "hr", "img", "input",
    "line", "link", "meta", "param", "path", "polygon", "polyline", "rect",
    "source", "stop", "track", "use", "wbr",
}

# Foreground/background token pairs that carry text, checked in both themes.
CONTRAST_PAIRS = [
    ("--ink", "--bg"),
    ("--ink-mid", "--bg"),
    ("--ink-soft", "--bg"),
    ("--accent", "--bg"),
    ("--ink", "--surface"),
    ("--ink-mid", "--surface"),
    ("--accent-ink", "--accent"),
    ("--code-ink", "--code-bg"),
    ("--code-dim", "--code-bg"),
    ("--syn-comment", "--code-bg"),
]

# WCAG AA for body text. Anything below this is an error, not a preference.
MIN_CONTRAST = 4.5


class Report:
    """Collected findings for one page.

    Attributes:
        errors: Problems that make the page wrong.
        warnings: Things worth checking by eye.
        notes: Confirmations, printed so the run says what it actually verified.
    """

    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.notes: list[str] = []

    def error(self, message: str) -> None:
        """Record a problem that must be fixed.

        Args:
            message: One line describing what is wrong.
        """
        self.errors.append(message)

    def warn(self, message: str) -> None:
        """Record something suspicious that may still be intentional.

        Args:
            message: One line describing what to look at.
        """
        self.warnings.append(message)

    def note(self, message: str) -> None:
        """Record a check that passed, for the summary.

        Args:
            message: One line describing what was verified.
        """
        self.notes.append(message)


class TagBalance(HTMLParser):
    """Confirms every non-void element is closed in the right order.

    A single unclosed ``div`` in a step will silently swallow the rest of the
    page in some browsers, so this runs before anything else.

    Attributes:
        stack: Elements opened and not yet closed.
        problems: Mismatches found while parsing.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[tuple[str, tuple[int, int]]] = []
        self.problems: list[str] = []

    def handle_starttag(self, tag: str, attrs: list) -> None:  # noqa: D102 - parser hook
        if tag not in VOID_ELEMENTS:
            self.stack.append((tag, self.getpos()))

    def handle_endtag(self, tag: str) -> None:  # noqa: D102 - parser hook
        if tag in VOID_ELEMENTS:
            return
        if not self.stack:
            self.problems.append(f"stray </{tag}> at line {self.getpos()[0]}")
            return
        opened, position = self.stack.pop()
        if opened != tag:
            self.problems.append(
                f"expected </{opened}> (opened line {position[0]}) "
                f"but found </{tag}> at line {self.getpos()[0]}"
            )


def relative_luminance(colour: str) -> float:
    """Return the WCAG relative luminance of a ``#rrggbb`` colour.

    Args:
        colour: Hex colour string, with or without the leading ``#``.

    Returns:
        Luminance between 0 (black) and 1 (white).
    """
    value = colour.strip().lstrip("#")
    channels = [int(value[i : i + 2], 16) / 255 for i in (0, 2, 4)]
    linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast_ratio(foreground: str, background: str) -> float:
    """Return the contrast ratio between two hex colours.

    Args:
        foreground: Text colour.
        background: Surface the text sits on.

    Returns:
        Ratio from 1 (identical) to 21 (black on white), rounded to two places.
    """
    light, dark = sorted((relative_luminance(foreground), relative_luminance(background)))
    return round((dark + 0.05) / (light + 0.05), 2)


def parse_block(source: str, pattern: str) -> dict[str, str]:
    """Pull ``--token: value;`` pairs out of the first block matching a pattern.

    Args:
        source: The whole page.
        pattern: Regular expression whose first group is the block body.

    Returns:
        Mapping of token name to declared value; empty when the block is absent.
    """
    match = re.search(pattern, source, re.S)
    if not match:
        return {}
    return dict(re.findall(r"(--[a-z0-9-]+)\s*:\s*([^;]+);", match.group(1)))


def strip_docstrings(code: str) -> list[str]:
    """Drop triple-quoted blocks so only executable lines are compared.

    Tutorial panels may condense a long docstring for space, which is allowed;
    the code around it is not. Removing docstrings from both sides lets the
    comparison be strict about the part that matters.

    Args:
        code: Python source.

    Returns:
        Non-blank lines outside any triple-quoted string.
    """
    lines: list[str] = []
    inside = False
    for raw in code.split("\n"):
        line = raw.rstrip()
        markers = line.count('"""')
        if not inside:
            if markers == 1:
                inside = True
                continue
            if markers >= 2:
                continue
            if line.strip():
                lines.append(line)
        elif markers >= 1:
            inside = False
    return lines


def check_markup(source: str, report: Report) -> None:
    """Confirm the page's elements are balanced.

    Args:
        source: The whole page.
        report: Collector for findings.
    """
    parser = TagBalance()
    parser.feed(source)
    for problem in parser.problems:
        report.error(f"markup: {problem}")
    for tag, position in parser.stack:
        report.error(f"markup: <{tag}> opened at line {position[0]} is never closed")
    if not parser.problems and not parser.stack:
        report.note("markup is balanced")


def check_tokens(source: str, report: Report) -> dict[str, dict[str, str]]:
    """Check that tokens are defined, used, and mirrored in the light theme.

    These pages ship dark: ``:root`` carries the dark palette and
    ``:root[data-theme="light"]`` is the reader's opt-in. Every colour defined
    in the default therefore needs a light counterpart, or that element will
    keep its dark value on a light page.

    Args:
        source: The whole page.
        report: Collector for findings.

    Returns:
        The ``default`` and ``light`` token tables, for the contrast check.
    """
    default = parse_block(source, r"\n\t*:root \{(.*?)\n\t*\}")
    light = parse_block(source, r':root\[data-theme="light"\] \{(.*?)\n\t*\}')

    if not default:
        report.error("tokens: no :root block found")
        return {}

    used = set(re.findall(r"var\((--[a-z0-9-]+)", source))
    defined = set(default) | set(light)
    for token in sorted(used - defined):
        report.error(f"tokens: {token} is used but never defined")
    for token in sorted(defined - used - {"--type-scale"}):
        report.warn(f"tokens: {token} is defined but never used")

    if "dark" not in default.get("color-scheme", "") and "color-scheme: dark" not in source:
        report.warn("theme: the default :root does not declare color-scheme: dark")
    if re.search(r"@media \(prefers-color-scheme[^)]*\)\s*\{\s*:root", source):
        report.warn(
            "theme: a prefers-color-scheme block still targets :root, so the page will "
            "follow the operating system instead of always opening dark"
        )

    if not light:
        report.error('theme: no :root[data-theme="light"] block, so the toggle has nothing '
                     "to switch to")
    else:
        report.note(f"light theme overrides {len(light)} tokens")
        # Syntax colours are deliberately shared: the code panel stays dark in
        # both themes, so they need no light counterpart.
        missing = [
            token
            for token, value in default.items()
            if value.strip().startswith(("#", "rgba"))
            and token not in light
            and not token.startswith("--syn")
        ]
        if missing:
            report.error(
                "theme: these colours keep their dark value on a light page: "
                f"{', '.join(sorted(missing))}"
            )

    unscaled = [
        token
        for token in default
        if (token.startswith("--size-") or token == "--check-size")
        and "var(--type-scale)" not in default[token]
    ]
    if unscaled:
        report.error(
            "tokens: these sizes ignore the text-size control, so they will stay put "
            f"while everything else grows: {', '.join(unscaled)}"
        )
    elif any(token.startswith("--size-") for token in default):
        report.note("every type token scales with --type-scale")

    return {"default": default, "light": light}


def check_contrast(tables: dict[str, dict[str, str]], report: Report) -> None:
    """Check text/background pairs against WCAG AA in both themes.

    Args:
        tables: Light and dark token tables.
        report: Collector for findings.
    """
    for theme in ("dark (default)", "light"):
        palette = dict(tables.get("default", {}))
        if theme == "light":
            palette.update(tables.get("light", {}))
        if not palette:
            continue
        worst = None
        for foreground, background in CONTRAST_PAIRS:
            fg, bg = palette.get(foreground, ""), palette.get(background, "")
            if not fg.strip().startswith("#") or not bg.strip().startswith("#"):
                continue
            ratio = contrast_ratio(fg, bg)
            if ratio < MIN_CONTRAST:
                report.error(
                    f"contrast ({theme}): {foreground} on {background} is {ratio}:1, "
                    f"below {MIN_CONTRAST}:1"
                )
            if worst is None or ratio < worst[0]:
                worst = (ratio, foreground, background)
        if worst:
            report.note(
                f"contrast ({theme}): lowest pair is {worst[1]} on {worst[2]} at {worst[0]}:1"
            )


def check_navigation(source: str, report: Report) -> None:
    """Confirm sidebar links and section ids agree.

    Args:
        source: The whole page.
        report: Collector for findings.
    """
    links = re.findall(r'class="nav-link"[^>]*href="#([^"]+)"', source)
    links += re.findall(r'href="#([^"]+)"[^>]*class="nav-link"', source)
    sections = re.findall(r'<section[^>]*id="([^"]+)"', source)

    for target in links:
        if target not in sections:
            report.error(f"nav: link to #{target} has no matching section")
    for section in sections:
        if section not in links:
            report.warn(f"nav: section #{section} is not in the sidebar")
    if links and not set(links) - set(sections):
        report.note(f"{len(links)} sidebar links all resolve to sections")


def check_panels(source: str, repo_root: Path, report: Report) -> None:
    """Check code panels: masking, labels, and fidelity to the repo files.

    Args:
        source: The whole page.
        repo_root: Directory the panel paths are relative to.
        report: Collector for findings.
    """
    panels = re.findall(r'<div class="code([^"]*)">(.*?)\n\t*</div>\s*\n\t*<div class="check"',
                        source, re.S)
    blocks = re.findall(r'<div class="code(?P<mods>[^"]*)">(?P<body>.*?)</pre>', source, re.S)
    if not blocks:
        report.warn("panels: no code panels found")
        return

    checked = 0
    for mods, body in blocks:
        path_match = re.search(r'class="code__path">(.*?)</span>', body, re.S)
        label = re.sub(r"<[^>]+>", "", path_match.group(1)).strip() if path_match else ""
        name = label or "<unlabelled panel>"

        if "is-masked" not in mods:
            report.error(f"panels: {name} is not blurred (class should be 'code is-masked')")
        if not label:
            report.error("panels: a panel has no file path in its header")
        if "code__copy" not in body:
            report.error(f"panels: {name} has no copy button")

        code_match = re.search(r'<pre><code class="language-([a-z]+)">(.*)$', body, re.S)
        if not code_match or not label:
            continue
        language = code_match.group(1)

        source_file = repo_root / label
        if not source_file.exists():
            report.warn(f"panels: {label} does not exist under {repo_root}")
            continue

        shown = code_match.group(2).split("</code>")[0]
        for entity, char in (("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"), ("&quot;", '"')):
            shown = shown.replace(entity, char)
        actual = source_file.read_text(encoding="utf-8").replace("\r\n", "\n")

        # Docstrings may be condensed in a panel, so they are dropped from both
        # sides before comparing. Other languages are compared line for line.
        prepare = strip_docstrings if language == "python" else (
            lambda text: [line.rstrip() for line in text.split("\n") if line.strip()]
        )
        actual_lines = set(prepare(actual))
        drifted = [line for line in prepare(shown) if line not in actual_lines]
        if drifted:
            report.error(
                f"panels: {label} shows {len(drifted)} line(s) that are not in the file, "
                f"starting with: {drifted[0].strip()!r}"
            )
        else:
            checked += 1

    if checked:
        report.note(f"{checked} code panel(s) match the repo files they quote")
    if panels:
        report.note(f"{len(panels)} panel(s) are followed by a check list")


def check_interaction(source: str, report: Report) -> None:
    """Check the reader-facing controls that have no framework behind them.

    Args:
        source: The whole page.
        report: Collector for findings.
    """
    boxes = source.count('type="checkbox"')
    labelled = len(re.findall(r"<label><input type=\"checkbox\"[^>]*/?>\s*<span>", source))
    if boxes != labelled:
        report.error(
            f"checks: {boxes - labelled} of {boxes} tick boxes are not wrapped in a "
            "<label> with a <span>, so their row is not clickable"
        )
    elif boxes:
        report.note(f"{boxes} tick boxes are all inside labels")

    for control, label in (
        ("themeToggle", "theme toggle"),
        ("typeUp", "text-size increase"),
        ("typeDown", "text-size decrease"),
        ("progressFill", "progress bar"),
        ("navToggle", "contents button"),
    ):
        if f'id="{control}"' not in source:
            report.error(f"controls: the {label} (#{control}) is missing")
    if "hms-tutorial-theme" not in source:
        report.warn("controls: the theme choice is not persisted")

    # Only the places where the page names itself; prose may mention other
    # stages ("installed in Stage 02") perfectly legitimately.
    self_labels = [
        r'<meta\s+name="description"[^>]*?Stage (\d{2})',
        r'class="stage-badge">\s*Stage (\d{2})',
        r'class="sidebar__stage">[^<]*?Stage (\d{2})',
        r'class="foot">\s*<span>[^<]*?Stage (\d{2})',
    ]
    stages = {
        match.group(1)
        for pattern in self_labels
        for match in [re.search(pattern, source, re.S)]
        if match
    }
    if len(stages) > 1:
        report.error(f"header: the page calls itself more than one stage: {sorted(stages)}")
    elif stages:
        report.note(f"stage number is consistently {sorted(stages)[0]} in every header")
    else:
        report.warn("header: no stage number found in the badge, sidebar or footer")


def main() -> int:
    """Run every check against one page and print the findings.

    Returns:
        ``0`` when no errors were found, otherwise ``1``.
    """
    parser = argparse.ArgumentParser(description="Validate an HMS tutorial page.")
    parser.add_argument("page", type=Path, help="the tutorial HTML file to check")
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path.cwd(),
        help="directory the code panel paths are relative to (default: current directory)",
    )
    args = parser.parse_args()

    if not args.page.exists():
        print(f"error: {args.page} does not exist")
        return 1

    source = args.page.read_text(encoding="utf-8")
    report = Report()

    check_markup(source, report)
    tables = check_tokens(source, report)
    check_contrast(tables, report)
    check_navigation(source, report)
    check_panels(source, args.repo_root, report)
    check_interaction(source, report)

    print(f"\n{args.page}  ({len(source.splitlines())} lines)\n")
    for note in report.notes:
        print(f"  ok       {note}")
    for warning in report.warnings:
        print(f"  warning  {warning}")
    for error in report.errors:
        print(f"  ERROR    {error}")

    print(
        f"\n{len(report.errors)} error(s), {len(report.warnings)} warning(s), "
        f"{len(report.notes)} check(s) passed\n"
    )
    return 1 if report.errors else 0


if __name__ == "__main__":
    sys.exit(main())
