"""The ScriptedPrompter used by command tests honors its queued answers and defaults."""

from finance_agent.cli.prompts import ScriptedPrompter


def test_scripted_prompter_returns_queued_then_defaults() -> None:
    p = ScriptedPrompter(
        text=["hello"], secret=["tok"], confirm=[False], select=["dining"],
        multiselect=[["a (#1)", "b (#2)"]],
    )
    assert p.text("name?", default="x") == "hello"
    assert p.text("again?", default="fallback") == "fallback"  # queue empty -> default
    assert p.secret("token?") == "tok"
    assert p.confirm("ok?", default=True) is False
    assert p.select("cat?", ["dining", "groceries"]) == "dining"
    assert p.multiselect("which?", ["a (#1)", "b (#2)", "c (#3)"]) == ["a (#1)", "b (#2)"]
    assert p.multiselect("which?", ["a"]) == []  # queue empty -> none
