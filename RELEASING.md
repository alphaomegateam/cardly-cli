# Releasing cardly-cli

Publishing uses **PyPI trusted publishing** (OIDC) — the same mechanism as
loxo-cli. No API token exists anywhere in this repo, in CI secrets, or on any
developer machine. That is the point: there is no long-lived credential to leak.

## One-time setup (required before the first release)

This step is deliberately web-only. PyPI has no API for it, because it is the
trust anchor: it is what proves to PyPI that this GitHub workflow may publish
under this name. Nothing else can create it.

1. Go to https://pypi.org/manage/account/publishing/
2. Under **Add a new pending publisher**, enter exactly:

   | Field                  | Value           |
   |------------------------|-----------------|
   | PyPI Project Name      | `cardly-cli`    |
   | Owner                  | `alphaomegateam`|
   | Repository name        | `cardly-cli`    |
   | Workflow name          | `publish.yml`   |
   | Environment name       | `pypi`          |

3. Save.

The `pypi` GitHub environment already exists (created to match loxo-cli's).
The name `cardly-cli` was unclaimed on PyPI as of 2026-07-15.

## Releasing

```bash
git tag -a v0.2.0 -m "cardly-cli 0.2.0"
git push origin v0.2.0
```

`.github/workflows/publish.yml` triggers on `v*` tags, builds with `uv build`,
and publishes via OIDC. **Do not push a release tag before the pending publisher
exists** — the workflow will fail closed rather than publish, and you would then
need a fresh tag.

## Verifying a release

```bash
uv tool install cardly-cli
cardly --version        # -> 0.2.0
cardly echo             # free connectivity + auth check; spends no credit
```

## Pre-release checklist

- [ ] `uv run pytest -q` green on a plain run
- [ ] `uv run ruff check src tests && uv run black --check src tests && uv run mypy` clean
- [ ] CI green on 3.11 / 3.12 / 3.13
- [ ] Version bumped in **both** `pyproject.toml` and `src/cardly_cli/__init__.py`
- [ ] `CHANGELOG.md` entry added
- [ ] `uv build` succeeds and the wheel runs from a clean venv:
      `uv venv /tmp/v && VIRTUAL_ENV=/tmp/v uv pip install dist/*.whl && /tmp/v/bin/cardly --version`
