from __future__ import annotations

import re

_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def strip_ansi(text: str) -> str:
    """Strip ANSI escape sequences from rendered CLI output.

    Rich decides whether to colourise based on the environment (FORCE_COLOR,
    CLICOLOR_FORCE, TTY_COMPATIBLE, isatty, ...) and that decision varies by
    where the suite runs (e.g. GitHub Actions sets TTY_COMPATIBLE, which a
    developer shell usually doesn't). When it does colourise, Rich can split a
    word like ``--profile`` across escape codes, so a literal substring check
    against rendered output is fragile regardless of which env vars happen to
    be set. Strip escapes first so assertions are colour-state independent.

    Note the character class is ``[A-Za-z]``, not just ``m`` — Rich emits more
    than plain SGR resets (e.g. cursor movement) using other final bytes.
    """
    return _ANSI.sub("", text)
