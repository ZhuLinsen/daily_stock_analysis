# -*- coding: utf-8 -*-
"""Offline tests for AiBerkshireProvider.

Uses temporary git fixtures and in-memory inspectors. The default suite
does not read the live reference checkout and never touches a fork path.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from src.agent.providers.ai_berkshire import (
    ALLOWED_ORIGINS,
    AiBerkshireProvider,
    CheckoutLock,
    FilesystemThesisIndex,
    ThesisHit,
)
from src.schemas.research_contracts import (
    Horizon,
    ProviderError,
    ProviderErrorCode,
    ProviderRole,
    ResearchRequest,
    Stance,
)


class FakeInspector:
    def __init__(self, lock: CheckoutLock | Exception) -> None:
        self.lock = lock
        self.calls = 0

    def inspect(self, root: str) -> CheckoutLock:
        self.calls += 1
        if isinstance(self.lock, Exception):
            raise self.lock
        return self.lock


class FakeIndex:
    def __init__(self, hits: tuple[ThesisHit, ...] = ()) -> None:
        self.hits = hits
        self.queries: list[tuple[str, str]] = []

    def find(self, root: str, subject: str) -> tuple[ThesisHit, ...]:
        self.queries.append((root, subject))
        return self.hits


def make_request(**overrides) -> ResearchRequest:
    base = ResearchRequest(
        request_id="berk-req-001",
        run_id="berk-run-001",
        subject="TESTCO",
        market="us",
        as_of="2026-07-01",
        horizons=(Horizon.LONG,),
    )
    return replace(base, **overrides)


def _lock(root: str = "/tmp/berkshire-fixture") -> CheckoutLock:
    return CheckoutLock(
        root=root,
        head="abc123pinned",
        origin=ALLOWED_ORIGINS[0],
        clean=True,
    )


def _provider(
    *,
    lock: CheckoutLock | Exception | None = None,
    hits: tuple[ThesisHit, ...] = (),
    root: str = "/tmp/berkshire-fixture",
    pinned_sha: str = "abc123pinned",
) -> AiBerkshireProvider:
    return AiBerkshireProvider(
        root=root,
        pinned_sha=pinned_sha,
        inspector=FakeInspector(lock if lock is not None else _lock(root)),
        thesis_index=FakeIndex(hits),
    )


class TestCapabilities:
    def test_required_long_only(self) -> None:
        caps = _provider().capabilities()
        assert caps.role == ProviderRole.REQUIRED
        assert caps.supported_horizons == (Horizon.LONG,)
        assert caps.requires_network is False


class TestRevisionLock:
    def test_wrong_sha_fail_closed(self) -> None:
        provider = _provider(lock=replace(_lock(), head="deadbeef"))
        with pytest.raises(ProviderError) as exc:
            provider.validate(make_request())
        assert exc.value.code == ProviderErrorCode.REVISION_MISMATCH
        assert exc.value.fail_mode.value == "fail_closed"

    def test_dirty_tree_fail_closed(self) -> None:
        provider = _provider(lock=replace(_lock(), clean=False))
        result = provider.research(make_request())
        assert isinstance(result, ProviderError)
        assert result.code == ProviderErrorCode.REVISION_MISMATCH

    def test_wrong_origin_fail_closed(self) -> None:
        provider = _provider(lock=replace(_lock(), origin="https://example.invalid/other.git"))
        result = provider.research(make_request())
        assert isinstance(result, ProviderError)
        assert result.code == ProviderErrorCode.REVISION_MISMATCH

    def test_inspect_failure_is_unavailable(self) -> None:
        provider = _provider(lock=RuntimeError("missing git"))
        result = provider.research(make_request())
        assert isinstance(result, ProviderError)
        assert result.code == ProviderErrorCode.DEPENDENCY_UNAVAILABLE

    def test_forbidden_root_rejected_without_inspector(self) -> None:
        inspector = FakeInspector(_lock())
        provider = AiBerkshireProvider(
            root="/Volumes/future/projects/ai-berkshire-fork",
            pinned_sha="abc123pinned",
            inspector=inspector,
            thesis_index=FakeIndex(),
        )
        result = provider.research(make_request())
        assert isinstance(result, ProviderError)
        assert result.code == ProviderErrorCode.REVISION_MISMATCH
        assert inspector.calls == 0


class TestResearch:
    def test_missing_report_abstains(self) -> None:
        provider = _provider(hits=())
        opinion = provider.research(make_request())
        assert not isinstance(opinion, ProviderError)
        assert opinion.stance == Stance.ABSTAIN
        assert opinion.claims == ()

    def test_structured_stance_uses_file_hash(self) -> None:
        hit = ThesisHit(
            relative_path="TESTCO-long-thesis.md",
            content_hash="a" * 64,
            title="TESTCO long thesis",
            stance=Stance.BULLISH,
            size_bytes=128,
        )
        provider = _provider(hits=(hit,))
        opinion = provider.research(make_request())
        assert not isinstance(opinion, ProviderError)
        assert opinion.stance == Stance.BULLISH
        assert opinion.evidence_refs[0].content_hash == "a" * 64
        assert opinion.evidence_refs[0].source_uri == "berkshire://reports/TESTCO-long-thesis.md"
        assert "reports/TESTCO-long-thesis.md" in opinion.evidence_refs[0].locator

    def test_short_horizon_abstains(self) -> None:
        provider = _provider()
        opinion = provider.research(make_request(horizons=(Horizon.SHORT,)))
        assert not isinstance(opinion, ProviderError)
        assert opinion.stance == Stance.ABSTAIN

    def test_cancel(self) -> None:
        provider = _provider()
        assert provider.cancel("t1") is True
        result = provider.research(make_request())
        assert isinstance(result, ProviderError)
        assert result.code == ProviderErrorCode.CANCELLED


def _git(cwd: Path, *args: str) -> str:
    env = os.environ.copy()
    env.update(
        {
            "GIT_AUTHOR_NAME": "phase3-test",
            "GIT_AUTHOR_EMAIL": "phase3@example.invalid",
            "GIT_COMMITTER_NAME": "phase3-test",
            "GIT_COMMITTER_EMAIL": "phase3@example.invalid",
        }
    )
    result = subprocess.run(
        ["git", "-C", str(cwd), *args],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    return result.stdout.strip()


def _init_fixture(tmp_path: Path, *, dirty: bool = False) -> Path:
    root = tmp_path / "ai-berkshire-reference"
    reports = root / "reports"
    reports.mkdir(parents=True)
    (reports / "TESTCO-long-thesis.md").write_text(
        "# TESTCO long thesis\n\nstance: bullish\n\nSanitized fixture only.\n",
        encoding="utf-8",
    )
    _git(root, "init")
    _git(root, "remote", "add", "origin", ALLOWED_ORIGINS[0])
    _git(root, "add", "reports/TESTCO-long-thesis.md")
    _git(root, "commit", "-m", "fixture")
    if dirty:
        (reports / "dirty.txt").write_text("dirty", encoding="utf-8")
    return root


class TestFilesystemIndex:
    def test_real_git_lock_and_report(self, tmp_path: Path) -> None:
        root = _init_fixture(tmp_path)
        head = _git(root, "rev-parse", "HEAD")
        provider = AiBerkshireProvider(root=str(root), pinned_sha=head)
        opinion = provider.research(make_request())
        assert not isinstance(opinion, ProviderError)
        assert opinion.stance == Stance.BULLISH
        assert opinion.evidence_refs[0].content_hash
        assert "TESTCO-long-thesis.md" in opinion.evidence_refs[0].locator

    def test_symlink_escape_ignored(self, tmp_path: Path) -> None:
        root = _init_fixture(tmp_path)
        outside = tmp_path / "outside.md"
        outside.write_text("secret", encoding="utf-8")
        link = root / "reports" / "TESTCO-escape.md"
        link.symlink_to(outside)
        hits = FilesystemThesisIndex().find(str(root), "TESTCO")
        assert all("escape" not in hit.relative_path for hit in hits)
