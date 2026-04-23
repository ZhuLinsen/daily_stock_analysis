# -*- coding: utf-8 -*-
"""
===================================
Analysis Metadata Utility Unit Tests
===================================
"""

import pytest
from src.utils.analysis_metadata import SELECTION_SOURCES, SELECTION_SOURCE_PATTERN


class TestSelectionSourceConstants:
    """Test selection source constants"""

    def test_selection_sources_tuple(self):
        """Test that SELECTION_SOURCES is a tuple with expected values"""
        assert isinstance(SELECTION_SOURCES, tuple)
        assert len(SELECTION_SOURCES) == 4
        assert "manual" in SELECTION_SOURCES
        assert "autocomplete" in SELECTION_SOURCES
        assert "import" in SELECTION_SOURCES
        assert "image" in SELECTION_SOURCES

    def test_selection_sources_order(self):
        """Test that selection sources are in expected order"""
        assert SELECTION_SOURCES[0] == "manual"
        assert SELECTION_SOURCES[1] == "autocomplete"
        assert SELECTION_SOURCES[2] == "import"
        assert SELECTION_SOURCES[3] == "image"

    def test_selection_sources_unique(self):
        """Test that selection source values are unique"""
        assert len(SELECTION_SOURCES) == len(set(SELECTION_SOURCES))

    def test_selection_source_pattern_string(self):
        """Test that SELECTION_SOURCE_PATTERN is a string"""
        assert isinstance(SELECTION_SOURCE_PATTERN, str)

    def test_selection_source_pattern_regex(self):
        """Test that SELECTION_SOURCE_PATTERN is a valid regex"""
        import re
        # Should be able to compile as regex
        pattern = re.compile(SELECTION_SOURCE_PATTERN)
        assert pattern is not None

    def test_selection_source_pattern_valid_sources(self):
        """Test that regex pattern matches all valid selection sources"""
        import re
        pattern = re.compile(SELECTION_SOURCE_PATTERN)

        for source in SELECTION_SOURCES:
            assert pattern.fullmatch(source) is not None, f"Pattern should match {source}"

    def test_selection_source_pattern_invalid_sources(self):
        """Test that regex pattern rejects invalid selection sources"""
        import re
        pattern = re.compile(SELECTION_SOURCE_PATTERN)

        invalid_sources = [
            "",
            "invalid",
            "Manual",
            "AUTOCOMPLETE",
            "autocomplete ",
            " autocomplete",
            "manual|autocomplete",
            "image;upload",
            "upload",
            "scan",
            "voice",
        ]

        for invalid_source in invalid_sources:
            assert pattern.fullmatch(invalid_source) is None, f"Pattern should reject {invalid_source}"


class TestSelectionSourcePatternEdgeCases:
    """Test selection source pattern edge cases"""

    def test_pattern_partial_match(self):
        """Test that regex pattern does not do partial matching"""
        import re
        pattern = re.compile(SELECTION_SOURCE_PATTERN)

        # Partial matches should fail
        assert pattern.fullmatch("manual-extra") is None
        assert pattern.fullmatch("autocomplete_value") is None
        assert pattern.fullmatch("import_data") is None

    def test_pattern_case_sensitive(self):
        """Test that regex pattern is case-sensitive"""
        import re
        pattern = re.compile(SELECTION_SOURCE_PATTERN)

        # Uppercase forms should fail
        assert pattern.fullmatch("MANUAL") is None
        assert pattern.fullmatch("Autocomplete") is None
        assert pattern.fullmatch("Import") is None

    def test_pattern_whitespace(self):
        """Test that regex pattern rejects inputs with spaces"""
        import re
        pattern = re.compile(SELECTION_SOURCE_PATTERN)

        assert pattern.fullmatch(" manual") is None
        assert pattern.fullmatch("manual ") is None
        assert pattern.fullmatch("aut ocomplete") is None

    def test_pattern_special_characters(self):
        """Test that regex pattern rejects special characters"""
        import re
        pattern = re.compile(SELECTION_SOURCE_PATTERN)

        special_cases = [
            "manual!",
            "autocomplete.",
            "import@",
            "image#",
            "manual\n",
            "autocomplete\t",
        ]

        for special_case in special_cases:
            assert pattern.fullmatch(special_case) is None, f"Pattern should reject {special_case}"

    def test_pattern_unicode(self):
        """Test that regex pattern handles Unicode characters"""
        import re
        pattern = re.compile(SELECTION_SOURCE_PATTERN)

        # Chinese characters should fail
        assert pattern.fullmatch("手动输入") is None
        assert pattern.fullmatch("自动补全") is None
        assert pattern.fullmatch("图片识别") is None

        # Mixed characters should fail
        assert pattern.fullmatch("manual输入") is None
        assert pattern.fullmatch("autocomplete识别") is None


class TestSelectionSourceIntegration:
    """Test selection source integration in Pydantic models"""

    def test_pydantic_validation_valid_sources(self):
        """Test that Pydantic validates valid selection sources"""
        from pydantic import BaseModel, Field

        class TestModel(BaseModel):
            source: str = Field(pattern=SELECTION_SOURCE_PATTERN)

        # All valid selection sources should pass validation
        for valid_source in SELECTION_SOURCES:
            model = TestModel(source=valid_source)
            assert model.source == valid_source

    def test_pydantic_validation_invalid_sources(self):
        """Test that Pydantic rejects invalid selection sources"""
        from pydantic import BaseModel, Field, ValidationError

        class TestModel(BaseModel):
            source: str = Field(pattern=SELECTION_SOURCE_PATTERN)

        invalid_sources = ["invalid", "upload", "scan", ""]

        for invalid_source in invalid_sources:
            with pytest.raises(ValidationError):
                TestModel(source=invalid_source)

    def test_optional_selection_source(self):
        """Test optional selection source field"""
        from pydantic import BaseModel, Field
        from typing import Optional

        class TestModel(BaseModel):
            source: Optional[str] = Field(None, pattern=SELECTION_SOURCE_PATTERN)

        # None should pass
        model = TestModel()
        assert model.source is None

        # Valid values should pass
        model = TestModel(source="manual")
        assert model.source == "manual"

        # Invalid values should fail
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            TestModel(source="invalid")


class TestSelectionSourceBusinessLogic:
    """Test selection source business logic"""

    def test_all_sources_covered(self):
        """Test that all expected user input scenarios are covered"""
        # Manual input
        assert "manual" in SELECTION_SOURCES
        # Autocomplete selection
        assert "autocomplete" in SELECTION_SOURCES
        # Batch import
        assert "import" in SELECTION_SOURCES
        # Image recognition
        assert "image" in SELECTION_SOURCES

    def test_no_redundant_sources(self):
        """Test that there are no redundant or duplicate selection sources"""
        # Each selection source should represent a unique user interaction pattern
        unique_patterns = {
            "manual": "User directly inputs stock code",
            "autocomplete": "User selects from autocomplete list",
            "import": "User uses batch import function",
            "image": "User uses image recognition function",
        }

        assert len(SELECTION_SOURCES) == len(unique_patterns)

    def test_future_extensibility(self):
        """Test that pattern structure supports future extensions"""
        # Current pattern should use group structure for easy extension
        pattern_string = SELECTION_SOURCE_PATTERN

        # Pattern should contain groups and pipe operator
        assert "(" in pattern_string
        assert ")" in pattern_string
        assert "|" in pattern_string

    def test_pattern_match_performance(self):
        """Test regex pattern match performance"""
        import re
        import time

        pattern = re.compile(SELECTION_SOURCE_PATTERN)

        # Test performance with many valid matches
        start_time = time.time()
        for _ in range(10000):
            pattern.fullmatch("manual")
            pattern.fullmatch("autocomplete")
            pattern.fullmatch("import")
            pattern.fullmatch("image")
        end_time = time.time()

        # Should complete in reasonable time (< 1 second)
        assert end_time - start_time < 1.0

    def test_pattern_reject_performance(self):
        """Test regex pattern reject performance"""
        import re
        import time

        pattern = re.compile(SELECTION_SOURCE_PATTERN)

        # Test performance with many invalid matches
        start_time = time.time()
        for _ in range(10000):
            pattern.fullmatch("invalid_source_123")
        end_time = time.time()

        # Should complete in reasonable time (< 1 second)
        assert end_time - start_time < 1.0


class TestSelectionSourceDocumentation:
    """Test selection source documentation and usage"""

    def test_source_descriptions(self):
        """Test that each selection source has clear semantics"""
        descriptions = {
            "manual": "User manually inputs stock code",
            "autocomplete": "User selects stock through autocomplete component",
            "import": "User batch adds stocks through import function",
            "image": "User adds stocks through image recognition function",
        }

        for source in SELECTION_SOURCES:
            assert source in descriptions
            assert descriptions[source]  # Description is not empty

    def test_source_use_cases(self):
        """Test that each selection source corresponds to use cases"""
        use_cases = {
            "manual": [
                "User directly inputs 600519 in input box",
                "User directly inputs AAPL in input box",
                "User directly inputs 贵州茅台 in input box",
            ],
            "autocomplete": [
                "User inputs '茅台', selects '贵州茅台' from dropdown",
                "User inputs 'gzmt', selects '贵州茅台' from dropdown",
                "User inputs '6005', selects '600519.SH' from dropdown",
            ],
            "import": [
                "User batch imports stocks through Excel",
                "User batch imports stocks through CSV",
                "User imports from history records",
            ],
            "image": [
                "User uploads stock screenshot for recognition",
                "User uploads market image for recognition",
            ],
        }

        for source in SELECTION_SOURCES:
            assert source in use_cases
            assert len(use_cases[source]) > 0


class TestSelectionSourceValidationIntegration:
    """Test selection source integration in task queue"""

    def test_task_queue_validation(self):
        """Test that task queue validates selection sources"""
        from src.services.task_queue import AnalysisTaskQueue

        queue = AnalysisTaskQueue(max_workers=1)

        # Valid selection sources should pass
        for source in SELECTION_SOURCES:
            try:
                queue.validate_selection_source(source)
            except ValueError:
                pytest.fail(f"Valid selection source {source} was rejected")

    def test_task_queue_reject_invalid_source(self):
        """Test that task queue rejects invalid selection sources"""
        from src.services.task_queue import AnalysisTaskQueue

        queue = AnalysisTaskQueue(max_workers=1)

        invalid_sources = ["invalid", "upload", "scan", ""]

        for invalid_source in invalid_sources:
            with pytest.raises(ValueError, match="Invalid selection_source"):
                queue.validate_selection_source(invalid_source)

    def test_task_queue_none_source(self):
        """Test that task queue accepts None as selection source"""
        from src.services.task_queue import AnalysisTaskQueue

        queue = AnalysisTaskQueue(max_workers=1)

        # None should pass validation (backward compatibility)
        try:
            queue.validate_selection_source(None)
        except ValueError:
            pytest.fail("None should be a valid selection source (backward compatibility)")
