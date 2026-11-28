"""Regression coverage for OR-COR-45b3d3c1: preserve complete image-import symbols."""
from unittest.mock import patch

import pytest

from src.services.image_stock_extractor import _parse_codes_from_text, _parse_items_from_text


# ---------------------------------------------------------------------------
# ASX atomic preservation / invalid-token rejection / json_repair failure path
# ---------------------------------------------------------------------------


ASX_RAW = [("BHP.AX", "BHP.AX"), ("a2m.ax", "A2M.AX"), ("A200.AX", "A200.AX"), ("ABC123.AX", "ABC123.AX")]
INVALID_ASX = ["TOOLONG7.AX", "B-H.AX", "BHP.AX.US", "_BHP.AX", ".AX", "BHP.AXX"]


class TestAsxAtomicPreservation:
    """Valid ASX plain-text tokens must be preserved atomically by both parsers."""

    @pytest.mark.parametrize("raw,expected", ASX_RAW)
    def test_legacy_parser_preserves_asx_atomically(self, raw, expected):
        assert _parse_codes_from_text(raw) == [expected]

    @pytest.mark.parametrize("raw,expected", ASX_RAW)
    def test_items_parser_preserves_asx_atomically(self, raw, expected):
        assert [i[0] for i in _parse_items_from_text(raw)] == [expected]

    def test_mixed_order_and_dedup(self):
        text = "BHP.AX AAPL BRK.B 600519 00700 BHP.AX a2m.ax A200.AX ABC123.AX"
        assert _parse_codes_from_text(text) == [
            "BHP.AX", "AAPL", "BRK.B", "600519", "00700", "A2M.AX", "A200.AX", "ABC123.AX",
        ]
        assert [i[0] for i in _parse_items_from_text(text)] == [
            "BHP.AX", "AAPL", "BRK.B", "600519", "00700", "A2M.AX", "A200.AX", "ABC123.AX",
        ]


class TestInvalidAsxTokensNeverYieldBareFragments:
    """Invalid ASX-like tokens must not leak bare BHP, AX, H, etc."""

    @pytest.mark.parametrize("token", INVALID_ASX)
    def test_legacy_parser_rejects_invalid_asx(self, token):
        assert _parse_codes_from_text(token) == []

    @pytest.mark.parametrize("token", INVALID_ASX)
    def test_items_parser_rejects_invalid_asx(self, token):
        assert _parse_items_from_text(token) == []


class TestJsonRepairFailurePath:
    """When json_repair raises, malformed JSON must still recover complete ASX tokens via fallback."""

    def test_repair_json_valueerror_recovers_asx_tokens(self):
        malformed = '[{"code":"BHP.AX"},{"code":"A2M.AX"'
        with patch("json_repair.repair_json", side_effect=ValueError("bad json")):
            assert _parse_items_from_text(malformed) == [("BHP.AX", None, "medium"), ("A2M.AX", None, "medium")]
            assert _parse_codes_from_text(malformed) == ["BHP.AX", "A2M.AX"]

    def test_valid_json_array_still_works(self):
        """Compatibility: normal JSON object/array paths unaffected (.AX values)."""
        text = '[{"code":"BHP.AX","name":"BHP","confidence":"high"}]'
        assert _parse_items_from_text(text) == [("BHP.AX", "BHP", "high")]
        assert _parse_codes_from_text('["BHP.AX","A2M.AX"]') == ["BHP.AX", "A2M.AX"]


from src.services import image_stock_extractor as parsers


def test_parse_codes_and_items_parametrized():
    cases = [
        ("AAPL.", ["AAPL"]),
        ("BHP.AX.", ["BHP.AX"]),
        ("[BHP.AX], (a2m.ax)\nBRK.B", ["BHP.AX", "A2M.AX", "BRK.B"]),
        ("AAPL..", []),
        ("BHP..AX", []),
        (".BHP.AX", []),
        ("BHP.AX_", []),
        ("\u4e2d\u6587BHP.AX", []),
        ("BHP.AX\u4e2d\u6587", []),
    ]
    for raw, expected in cases:
        assert parsers._parse_codes_from_text(raw) == expected, raw
        items = parsers._parse_items_from_text(raw)
        assert [c for c, _, _ in items] == expected, raw


def test_parse_bad_sibling():
    raw = "_BAD AAPL 600519 TOOLONG7.AX BHP.AX.US"
    assert parsers._parse_codes_from_text(raw) == ["AAPL", "600519"]
    items = parsers._parse_items_from_text(raw)
    assert [c for c, _, _ in items] == ["AAPL", "600519"]


def test_parse_compatibility_text():
    raw = "600519.SH 000001.SZ 00700 BRK.B 600519.SS CODE NAME HIGH AAPL"
    assert parsers._parse_codes_from_text(raw) == ["600519", "000001", "00700", "BRK.B", "AAPL"]
    items = parsers._parse_items_from_text(raw)
    assert [c for c, _, _ in items] == ["600519", "000001", "00700", "BRK.B", "AAPL"]


def test_extract_stock_codes_from_image():
    from unittest.mock import MagicMock, patch
    from src.services import image_stock_extractor as p
    jpeg = b"\xff\xd8\xff" + b"\x00" * 20
    with patch.object(p, "_call_litellm_vision", return_value="BHP.AX A2M.AX") as mc, \
         patch.object(p, "_resolve_vision_model", return_value="test-model"), \
         patch.object(p, "_get_api_keys_for_model", return_value=[]), \
         patch.object(p, "get_config", return_value=MagicMock()):
        items, raw = p.extract_stock_codes_from_image(jpeg, "image/jpeg")
    assert items == [("BHP.AX", None, "medium"), ("A2M.AX", None, "medium")]
    assert raw == "BHP.AX A2M.AX"
    mc.assert_called_once()


# ---------------------------------------------------------------------------
# OR-COR-45b3d3c1 regression: raw fallback ASCII guard while retaining
# Unicode-aware maximal token consumption (ß, ﬃ, fullwidth, Arabic-Indic)
# ---------------------------------------------------------------------------


UNICODE_REJECT = ["ß", "ﬃ", "１２３４５", "ß.AX", "ﬃ.AX", "١٢٣٤٥"]


@pytest.mark.parametrize("token", UNICODE_REJECT)
def test_unicode_tokens_rejected_by_both_parsers(token):
    assert _parse_codes_from_text(token) == []
    assert _parse_items_from_text(token) == []


MIXED_VALID_INVALID = "BHP.AX A2M.AX A200.AX TOOLONG7.AX ß.AX １２３４５"
EXPECTED_THREE = ["BHP.AX", "A2M.AX", "A200.AX"]


def test_mixed_valid_invalid_text_yields_exact_three():
    assert _parse_codes_from_text(MIXED_VALID_INVALID) == EXPECTED_THREE
    assert [i[0] for i in _parse_items_from_text(MIXED_VALID_INVALID)] == EXPECTED_THREE


def test_repair_failure_malformed_code_only_json():
    malformed = '[{"code":"ß.AX"},{"code":"BHP.AX"}'
    with patch("json_repair.repair_json", side_effect=ValueError("bad json")):
        assert _parse_codes_from_text(malformed) == ["BHP.AX"]
        assert [i[0] for i in _parse_items_from_text(malformed)] == ["BHP.AX"]


def test_public_extraction_mixed_text_returns_three_au_items():
    from unittest.mock import MagicMock
    jpeg = b"\xff\xd8\xff" + b"\x00" * 20
    assert len(jpeg) == 23
    with patch.object(parsers, "_call_litellm_vision", return_value=MIXED_VALID_INVALID) as mc, \
         patch.object(parsers, "_resolve_vision_model", return_value="test-model"), \
         patch.object(parsers, "_get_api_keys_for_model", return_value=[]), \
         patch.object(parsers, "get_config", return_value=MagicMock()):
        items, raw = parsers.extract_stock_codes_from_image(jpeg, "image/jpeg")
    assert [i[0] for i in items] == EXPECTED_THREE
    assert raw == MIXED_VALID_INVALID
    mc.assert_called_once()
