from typer.testing import CliRunner

from cardly_cli.__main__ import app

runner = CliRunner()
ENV = {"CARDLY_API_KEY": "k"}

EXPECTED_GROUPS = [
    "account",
    "api",
    "art",
    "configure",
    "contacts",
    "echo",
    "invitations",
    "lists",
    "orders",
    "ref",
    "webhooks",
    "users",
]


def test_help_lists_every_v0_1_group():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for group in EXPECTED_GROUPS:
        assert group in result.stdout, f"missing command group: {group}"


def test_every_group_help_renders():
    for group in EXPECTED_GROUPS:
        if group == "api":
            continue  # root-level command, not a group
        result = runner.invoke(app, [group, "--help"])
        assert result.exit_code == 0, f"{group} --help failed"


def test_v0_2_surface_is_present():
    result = runner.invoke(app, ["--help"])
    assert "users" in result.stdout
    assert "invitations" in result.stdout

    for cmd in (
        ["art", "upload", "--help"],
        ["art", "update", "--help"],
        ["art", "delete", "--help"],
    ):
        assert runner.invoke(app, cmd).exit_code == 0


def test_deliberate_absences_stay_absent():
    # Each of these reflects a fact about Cardly's API, not an oversight.
    # No contact-list update endpoint exists.
    assert runner.invoke(app, ["lists", "update", "L1"], env=ENV).exit_code != 0
    # No order cancel endpoint exists (portal-only).
    assert runner.invoke(app, ["orders", "cancel", "o1"], env=ENV).exit_code != 0


def test_unofficial_disclaimer_present():
    result = runner.invoke(app, ["--help"])
    assert "Unofficial" in result.stdout or "not affiliated" in result.stdout
