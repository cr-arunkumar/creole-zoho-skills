import pytest

from zoho_skills import gate


def test_write_detection_defaults_to_safe():
    assert not gate.is_write_tool("get_portals") and not gate.is_write_tool("list_tasks")
    for w in ("create_a_task", "update_a_task", "delete_issue", "log_time", "mystery_tool"):
        assert gate.is_write_tool(w)


def test_token_roundtrip_single_use():
    g = gate.Gate()
    args = {"name": "x", "b": [1, 2]}
    t = g.issue("create_a_task", args)
    assert g.verify("create_a_task", {**args, "confirm_token": t}, t) == (True, "ok")
    ok, why = g.verify("create_a_task", args, t)
    assert not ok and "already used" in why


def test_tamper_detected():
    g = gate.Gate()
    t = g.issue("create_a_task", {"name": "x"})
    assert not g.verify("create_a_task", {"name": "y"}, t)[0]
    assert not g.verify("update_a_task", {"name": "x"}, t)[0]
    assert not g.verify("create_a_task", {"name": "x"}, "garbage")[0]
    assert not gate.Gate().verify("create_a_task", {"name": "x"}, t)[0]  # other process key


def test_expiry():
    now = [1000.0]
    g = gate.Gate(ttl=300, now=lambda: now[0])
    t = g.issue("create_a_task", {"a": 1})
    now[0] += 301
    ok, why = g.verify("create_a_task", {"a": 1}, t)
    assert not ok and "expired" in why
