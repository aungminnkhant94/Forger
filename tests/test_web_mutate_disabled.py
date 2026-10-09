"""Public Forger dashboard mutate routes must stay disabled."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_auth_edit_route_is_disabled():
    text = (ROOT / "web/app/api/auth/edit/route.ts").read_text(encoding="utf-8")
    assert "Remote edit is disabled" in text
    assert "NEXT_PUBLIC_EDIT_KEY" not in text
    assert "status: 403" in text


def test_bookmark_delete_route_is_disabled():
    text = (ROOT / "web/app/api/bookmarks/[id]/route.ts").read_text(encoding="utf-8")
    assert "Remote delete is disabled" in text
    assert "NEXT_PUBLIC_EDIT_KEY" not in text
    assert "BACKEND_DELETE_TOKEN" not in text
    assert "status: 403" in text


def test_auth_context_is_read_only():
    text = (ROOT / "web/components/AuthContext.tsx").read_text(encoding="utf-8")
    assert "isEditMode: false" in text
    assert "/api/auth/edit" not in text
