import pytest

from src.llm.response_content import strip_leading_think_wrapper


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        (
            "<THINK>internal reasoning</THINK>\n{\"status\":\"ok\"}",
            '{"status":"ok"}',
        ),
        (
            '{"summary":"literal <think>text</think>"}',
            '{"summary":"literal <think>text</think>"}',
        ),
        (
            "prefix <think>internal reasoning</think>{\"status\":\"ok\"}",
            "prefix <think>internal reasoning</think>{\"status\":\"ok\"}",
        ),
        (
            "<think>unclosed reasoning{\"status\":\"ok\"}",
            "<think>unclosed reasoning{\"status\":\"ok\"}",
        ),
    ],
)
def test_strip_leading_think_wrapper_is_anchored_and_fail_closed(
    response: str,
    expected: str,
) -> None:
    assert strip_leading_think_wrapper(response) == expected
