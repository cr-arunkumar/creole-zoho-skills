import importlib.util
import pathlib
import sqlite3
import sys

SKILLS = pathlib.Path(__file__).resolve().parents[1] / "skills"
DIRS = {"lint_task": SKILLS / "creole-studios-zoho" / "scripts", "store": SKILLS / "zoho-projects-core" / "scripts"}


def load(name):
    spec = importlib.util.spec_from_file_location(name, DIRS[name] / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


lt = load("lint_task")
store = load("store")

GOOD_DESC = ("Implement PostgreSQL Row Level Security for the reports schema: create role policies for "
             "analyst and admin, add helper functions for tenant lookup, write the migration script, "
             "and verify with pgTAP tests. Done when every policy denies cross-tenant reads.")
GOOD_COMMENT = ("Added 20261030_zoho_rls.sql with role policies and helper functions "
                "current_tenant() and is_admin(); applied it on staging and confirmed 8 passing pgTAP test cases "
                "including cross-tenant read denial.")


def t(**kw):
    base = dict(title="Implement RLS policies for reports schema [4.0 hrs]", description=GOOD_DESC,
                comment=GOOD_COMMENT, planned_minutes=240, logged_minutes=240, status="In QA Review")
    base.update(kw)
    return lt.lint(base)


def test_ex1_ideal_scores_high_no_errors():
    r = t()
    assert not r.errors and r.score >= 9.8


def test_ex4_in_progress_status_gate():
    r = t(status="In Progress")
    assert r.score == 9.0  # ideal work minus the flat 1.0 status-gate deduction
    assert any("In QA Review" in e for e in r.errors)


def test_ex5_checklist_copy_capped():
    r = t(comment="1. Setup DB - Done, 2. Update API - Done, 3. Testing - Done")
    assert r.score <= 5.2 and any("checklist" in e for e in r.errors)


def test_ex6_partial_delivery_capped_at_5():
    r = t(comment="Completed UI layout. API integration and unit testing are pending for tomorrow.",
          planned_minutes=300, logged_minutes=300)
    assert r.score <= 5.0


def test_ex6_blocker_documented_not_capped():
    r = t(comment="Completed UI layout; API integration blocked waiting on credentials from the client, "
                  "tested layout on mobile with 6 viewport cases.", planned_minutes=300, logged_minutes=300)
    assert not any("pending" in e for e in r.errors)


def test_ex7_overdue_beyond_buffer():
    r = t(planned_minutes=120, logged_minutes=210, title="Implement RLS policies for reports schema [2.0 hrs]")
    assert r.score <= 5.5 and any("over" in e for e in r.errors)


def test_grace_buffer_allows_5_minutes():
    r = t(planned_minutes=240, logged_minutes=245)
    assert not any("over" in e for e in r.errors)


def test_ex8_single_word_comment():
    r = t(comment="Done")
    assert r.score <= 4.0 and r.errors


def test_ex9_short_description_rushed_in_progress():
    r = t(description="Do php upgrade and testing.", comment="Upgraded php.", planned_minutes=240,
          logged_minutes=75, status="In Progress")
    assert r.score <= 4.0 and any("description" in e for e in r.errors)


def test_ex10_zero_hours_or_blank_description():
    assert t(logged_minutes=0).score == 0.0
    assert t(description="").score == 0.0


def test_empty_title_flagged():
    assert any("title is empty" in e for e in t(title="").errors)


def test_title_missing_hours_tag_warns_and_mismatch_warns():
    assert any("hours tag" in w for w in t(title="Implement RLS policies for reports").warnings)
    assert any("!= planned" in w for w in t(title="Implement RLS policies for reports [2.0 hrs]").warnings)


def test_draft_mode_skips_comment_and_status_gates():
    r = lt.lint(dict(title="Implement RLS policies [4.0 hrs]", description=GOOD_DESC, planned_minutes=240, final=False))
    assert not r.errors


def test_store_roundtrip(tmp_path):
    con = store.connect(tmp_path / "s.db")
    store.save_draft(con, {"project": "Research & Training 2025", "task_list": "Task List 2026",
                           "parent": "Asha: 14 hours", "owner": "Asha", "title": "x"})
    store.save_draft(con, {"org": "Creole Studios", "project": "Research & Training 2025", "task_list": "Task List 2026",
                           "parent": "Asha: 14 hours", "owner": "Asha", "title": "y"})
    store.save_draft(con, {"org": "Other Org", "project": "Other", "task_list": "L", "parent": "P", "owner": "O"})
    assert store.last_context(con)["project"] == "Other"
    assert store.last_context(con, org="Creole Studios")["owner"] == "Asha"
    assert store.last_context(con, org="Nobody") is None
    assert len(store.history(con, 5)) == 3
    assert isinstance(con, sqlite3.Connection)
