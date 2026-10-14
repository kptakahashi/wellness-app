from app.inference.engine import _drop_unwanted


def test_drop_unwanted_removes_sleep_and_place_identity_questions():
    cards = [
        {"kind": "meal", "question": "12:25 大戸屋 1,150円、定食でしたか?"},
        {"kind": "sleep", "question": "昨夜は何時に寝ましたか?"},
        {"kind": "custom", "question": "よく眠れましたか?"},
        {"kind": "custom", "question": "19:00〜 ご自宅でしたか?"},
        {"kind": "mood", "question": "今日全体の調子は?"},
    ]
    kept = [c["kind"] for c in _drop_unwanted(cards)]
    assert kept == ["meal", "mood"]
