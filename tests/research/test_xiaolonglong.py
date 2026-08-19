# -*- coding: utf-8 -*-
"""Offline tests for XiaolonglongProvider.

Fixtures are hand-written sanitized notes. Tests never read the live
private-knowledge tree and never crop original documents.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from src.agent.providers.xiaolonglong import StaticGrantStore, XiaolonglongProvider
from src.schemas.research_contracts import (
    Horizon,
    ProviderError,
    ProviderErrorCode,
    ProviderRole,
    ResearchRequest,
    Stance,
    to_json,
)


def make_request(**overrides) -> ResearchRequest:
    base = ResearchRequest(
        request_id="xll-req-001",
        run_id="xll-run-001",
        subject="TESTCO",
        market="cn",
        as_of="2026-07-01",
        horizons=(Horizon.MEDIUM,),
        authorization_context="grant-test",
    )
    return replace(base, **overrides)


def _provider(tmp_path: Path, grants: set[str] | None = None) -> XiaolonglongProvider:
    root = tmp_path / "xiaolonglong"
    root.mkdir()
    note = root / "notes"
    note.mkdir()
    (note / "sanitized-fixture.md").write_text(
        "# sanitized fixture\n\nsubjects: TESTCO\nstance: bullish\n\nHand-written test note.\n",
        encoding="utf-8",
    )
    store = StaticGrantStore(grants if grants is not None else {"grant-test"})
    provider = XiaolonglongProvider(root=str(root), grants=store)
    ids = provider.rebuild_index(as_of="2026-07-01")
    for opaque_id in ids:
        provider.grant_index_entry(opaque_id, "grant-test", as_of="2026-07-01")
    return provider


class TestCapabilities:
    def test_required_private_role(self, tmp_path: Path) -> None:
        caps = _provider(tmp_path).capabilities()
        assert caps.role == ProviderRole.REQUIRED
        assert caps.handles_private_data is True
        assert Horizon.SHORT not in caps.supported_horizons


class TestAuthorization:
    def test_missing_grant_fail_closed(self, tmp_path: Path) -> None:
        provider = _provider(tmp_path, grants=set())
        result = provider.research(make_request(authorization_context=""))
        assert isinstance(result, ProviderError)
        assert result.code == ProviderErrorCode.UNAUTHORIZED

    def test_self_declared_token_rejected(self, tmp_path: Path) -> None:
        provider = _provider(tmp_path, grants={"grant-test"})
        result = provider.research(make_request(authorization_context="authorized"))
        assert isinstance(result, ProviderError)
        assert result.code == ProviderErrorCode.UNAUTHORIZED

    def test_revoked_grant_fail_closed(self, tmp_path: Path) -> None:
        provider = _provider(tmp_path)
        assert isinstance(provider._grants, StaticGrantStore)
        provider._grants.revoke("grant-test")
        result = provider.research(make_request())
        assert isinstance(result, ProviderError)
        assert result.code == ProviderErrorCode.UNAUTHORIZED


class TestResearch:
    def test_opaque_evidence_only(self, tmp_path: Path) -> None:
        provider = _provider(tmp_path)
        opinion = provider.research(make_request())
        assert not isinstance(opinion, ProviderError)
        assert opinion.stance == Stance.BULLISH
        payload = to_json(opinion)
        assert "sanitized-fixture.md" not in payload
        assert "Hand-written test note" not in payload
        assert "private://" in payload
        ref = opinion.evidence_refs[0]
        assert ref.source_uri.startswith("private://")
        assert ref.locator.startswith("private://")
        assert ref.authorization == "granted"
        assert ref.content_hash
        assert ref.as_of == "2026-07-01"

    def test_revoked_entry_abstains(self, tmp_path: Path) -> None:
        provider = _provider(tmp_path)
        ids = [ref.source_uri.split("private://", 1)[-1] for ref in provider.research(make_request()).evidence_refs]
        assert ids
        provider.revoke_index_entry(ids[0])
        opinion = provider.research(make_request())
        assert not isinstance(opinion, ProviderError)
        assert opinion.stance == Stance.ABSTAIN

    def test_short_horizon_abstains(self, tmp_path: Path) -> None:
        provider = _provider(tmp_path)
        opinion = provider.research(make_request(horizons=(Horizon.SHORT,)))
        assert not isinstance(opinion, ProviderError)
        assert opinion.stance == Stance.ABSTAIN

    def test_cancel(self, tmp_path: Path) -> None:
        provider = _provider(tmp_path)
        assert provider.cancel("t1") is True
        result = provider.research(make_request())
        assert isinstance(result, ProviderError)
        assert result.code == ProviderErrorCode.CANCELLED

    def test_symlink_not_indexed(self, tmp_path: Path) -> None:
        root = tmp_path / "xiaolonglong"
        root.mkdir()
        outside = tmp_path / "outside.md"
        outside.write_text("secret-original\n", encoding="utf-8")
        (root / "escape.md").symlink_to(outside)
        provider = XiaolonglongProvider(root=str(root), grants=StaticGrantStore({"grant-test"}))
        ids = provider.rebuild_index()
        assert ids == ()

    def test_parent_path_rejected(self, tmp_path: Path) -> None:
        sneaky = tmp_path / "not-private" / ".." / "xiaolonglong"
        provider = XiaolonglongProvider(root=str(sneaky), grants=StaticGrantStore({"grant-test"}))
        result = provider.research(make_request())
        assert isinstance(result, ProviderError)
        assert result.code == ProviderErrorCode.DEPENDENCY_UNAVAILABLE
