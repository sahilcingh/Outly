import sqlite3

import storage.drafts as drafts


def test_init_db_creates_new_tables(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "drafts.db"
    monkeypatch.setattr(drafts, "DB_PATH", db_path)
    drafts.init_db()

    with sqlite3.connect(db_path) as conn:
        tables = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }

    assert "drafts" in tables
    assert "company_profiles" in tables
    assert "outreach_touches" in tables


def test_save_and_list_outreach_touches(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "drafts.db"
    monkeypatch.setattr(drafts, "DB_PATH", db_path)

    drafts.save_company_profile(
        "Acme",
        "https://acme.example/about",
        {"one_liner": "Acme makes widgets", "signals": ["hiring"]},
    )
    drafts.save_outreach_touch(
        company_name="Acme",
        company_url="https://acme.example/about",
        touch_index=1,
        channel="email",
        subject="Quick idea for Acme",
        body="Body text",
        rationale="Because of X",
    )

    touches = drafts.list_outreach_touches(company_url="https://acme.example/about")
    assert len(touches) == 1
    assert touches[0].touch_index == 1
    assert touches[0].channel == "email"

