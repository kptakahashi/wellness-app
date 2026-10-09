"""JSON schemas shared by every inference backend (Claude or rules)."""

from __future__ import annotations

CARD_KINDS = ["meal", "exercise", "stress", "mood", "sleep", "custom"]

DAY_INFERENCE_SCHEMA: dict = {
    "type": "object",
    "additionalProperties": False,
    "required": ["summary", "timeline", "cards"],
    "properties": {
        "summary": {
            "type": "string",
            "description": "その日を2〜3文で描く。事実のみ。指示や助言は書かない。",
        },
        "timeline": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["time", "label", "category", "confidence"],
                "properties": {
                    "time": {"type": "string", "description": "HH:MM"},
                    "end": {"type": "string"},
                    "label": {"type": "string", "description": "例: 昼食(カツカレー推定)"},
                    "category": {"type": "string", "enum": ["sleep", "meal", "exercise", "work", "move", "screen", "other"]},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    "source": {"type": "string"},
                },
            },
        },
        "cards": {
            "type": "array",
            "maxItems": 7,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["kind", "time", "question", "options", "proposed", "confidence", "evidence"],
                "properties": {
                    "kind": {"type": "string", "enum": CARD_KINDS},
                    "time": {"type": "string", "description": "HH:MM。該当なしは空文字"},
                    "question": {"type": "string", "description": "1文。Yes/Noか3択で答えられる形"},
                    "options": {"type": "array", "minItems": 2, "maxItems": 4, "items": {"type": "string"}},
                    "proposed": {"type": "string", "description": "optionsのうちAIが正しいと推定するもの"},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    "evidence": {"type": "string", "description": "推定の根拠を1文で"},
                },
            },
        },
    },
}

INSIGHT_SCHEMA: dict = {
    "type": "object",
    "additionalProperties": False,
    "required": ["insights"],
    "properties": {
        "insights": {
            "type": "array",
            "maxItems": 6,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["statement", "evidence", "confidence", "n_samples"],
                "properties": {
                    "statement": {"type": "string", "description": "事実と相関だけを1〜2文で。助言・命令は禁止"},
                    "evidence": {"type": "string", "description": "数値を含む根拠"},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    "n_samples": {"type": "integer"},
                },
            },
        }
    },
}
