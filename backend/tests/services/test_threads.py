import uuid

from app.services.threads import ThreadTurn, previously_recommended, render_context


def _turn(**kw):
    return ThreadTurn(run_id=uuid.uuid4(), message="m", **kw)


def test_render_context_includes_explanations_only_for_recent_turns():
    old = _turn(recommended=[("Old Song", "Old Artist", "old why")])
    mid = _turn(recommended=[("Mid", "A", "mid why")])
    new = _turn(
        songs=["Made in Abyss Kevin Penkin"],
        guidance="slower",
        recommended=[("New", "B", "new why")],
    )
    text = render_context([old, mid, new])
    assert "Old Song — Old Artist" in text and "old why" not in text
    assert "new why" in text and "steering applied: slower" in text


def test_previously_recommended_flattens_all_turns():
    turns = [_turn(recommended=[("A", "x", "")]), _turn(recommended=[("B", "y", "")])]
    assert previously_recommended(turns) == ["A x", "B y"]
