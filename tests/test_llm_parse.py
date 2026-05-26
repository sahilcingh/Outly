from llm.drafter import _parse_json_response


def test_parse_json_direct() -> None:
    content = '{"subject":"Hi","body":"Hello","rationale":"Because."}'
    out = _parse_json_response(content)
    assert out and out["subject"] == "Hi"


def test_parse_json_from_code_fence() -> None:
    content = """Here you go:
```json
{"subject":"S","body":"B","rationale":"R"}
```"""
    out = _parse_json_response(content)
    assert out and out["body"] == "B"


def test_parse_json_from_embedded_object() -> None:
    content = 'Some preface {"subject":"S2","body":"B2","rationale":"R2"} trailing'
    out = _parse_json_response(content)
    assert out and out["rationale"] == "R2"

