"""Build concise GitHub Release notes from CHANGELOG and merged PR authors."""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CHANGELOG = ROOT / "docs" / "CHANGELOG.md"
LOGGER = logging.getLogger(__name__)
KNOWN_AUTHOR_LOGINS = {
    "Alfred": "massif-01",
    "massif0601@gmail.com": "massif-01",
}


def _run_git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True, encoding="utf-8").strip()


def _section_for(version: str) -> str:
    text = CHANGELOG.read_text(encoding="utf-8")
    pattern = re.compile(rf"^## \[{re.escape(version)}\].*?$", re.MULTILINE)
    match = pattern.search(text)
    if not match:
        return ""
    next_match = re.search(r"^## \[", text[match.end() :], re.MULTILINE)
    end = match.end() + next_match.start() if next_match else len(text)
    return text[match.end() : end].strip()


def _highlights(section: str) -> list[str]:
    release_highlights = re.search(
        r"^### 发布亮点\s*(.*?)(?=^### |\Z)",
        section,
        re.MULTILINE | re.DOTALL,
    )
    source = release_highlights.group(1) if release_highlights else section
    bullets = []
    for line in source.splitlines():
        line = line.strip()
        if not line.startswith("- "):
            continue
        item = line[2:].strip()
        item = re.sub(r"^(feat|fix|docs|test|chore|ci|refactor):\s*", "", item, flags=re.I)
        bullets.append(item)
        if len(bullets) >= 6:
            break
    return bullets


def _previous_tag(tag: str) -> str:
    tags = _run_git("tag", "--sort=-v:refname").splitlines()
    semver_tags = [t for t in tags if re.fullmatch(r"v\d+\.\d+\.\d+", t)]
    for current, previous in zip(semver_tags, semver_tags[1:]):
        if current == tag:
            return previous
    return semver_tags[1] if len(semver_tags) > 1 else ""


def _commit_subjects(previous_tag: str, tag: str) -> list[str]:
    rev_range = f"{previous_tag}..{tag}" if previous_tag else tag
    output = _run_git("log", "--format=%s", rev_range)
    return [line for line in output.splitlines() if line.strip()]


def _commit_authors(previous_tag: str, tag: str) -> list[str]:
    rev_range = f"{previous_tag}..{tag}" if previous_tag else tag
    output = _run_git("log", "--format=%an <%ae>", rev_range)
    return [line for line in output.splitlines() if line.strip()]


def _github_login_from_pr(repo: str, token: str, pr_number: str) -> str | None:
    if not token:
        return None

    request = urllib.request.Request(
        f"https://api.github.com/repos/{repo}/pulls/{pr_number}",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "User-Agent": "daily-stock-analysis-release-notes",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        LOGGER.warning(
            "Release notes PR author lookup failed for PR #%s: exception_type=%s status=%s",
            pr_number,
            type(exc).__name__,
            exc.code,
        )
        return None
    except urllib.error.URLError as exc:
        LOGGER.warning(
            "Release notes PR author lookup failed for PR #%s: exception_type=%s",
            pr_number,
            type(exc).__name__,
        )
        return None
    except OSError as exc:
        LOGGER.warning(
            "Release notes PR author lookup failed for PR #%s: exception_type=%s",
            pr_number,
            type(exc).__name__,
        )
        return None
    except json.JSONDecodeError as exc:
        LOGGER.warning(
            "Release notes PR author lookup failed for PR #%s: exception_type=%s",
            pr_number,
            type(exc).__name__,
        )
        return None
    user = payload.get("user") or {}
    login = user.get("login")
    return str(login) if login else None


def _fallback_login(author: str) -> str | None:
    for key, login in KNOWN_AUTHOR_LOGINS.items():
        if key in author:
            return login
    noreply = re.search(r"\+([^@<>]+)@users\.noreply\.github\.com", author)
    if noreply:
        return noreply.group(1)
    name = author.split("<", 1)[0].strip()
    if name and " " not in name and "[" not in name and name.lower() not in {"github", "dependabot"}:
        return name
    return None


def _contributors(previous_tag: str, tag: str) -> list[str]:
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    token = os.environ.get("GITHUB_TOKEN", "")
    logins: list[str] = []

    for subject in _commit_subjects(previous_tag, tag):
        pr_numbers = re.findall(r"\(#(\d+)\)", subject)
        for pr_number in pr_numbers:
            login = _github_login_from_pr(repo, token, pr_number) if repo else None
            if login and login not in logins:
                logins.append(login)

    for author in _commit_authors(previous_tag, tag):
        login = _fallback_login(author)
        if login and login not in logins:
            logins.append(login)

    return sorted(f"@{login}" for login in logins if not login.endswith("[bot]"))


def build(tag: str) -> str:
    if not re.fullmatch(r"v\d+\.\d+\.\d+", tag):
        raise SystemExit(f"Unsupported release tag: {tag}")
    version = tag[1:]
    section = _section_for(version)
    previous_tag = _previous_tag(tag)
    highlights = _highlights(section)
    contributors = _contributors(previous_tag, tag)

    lines = [f"## {tag}", "", "### Highlights"]
    if highlights:
        lines.extend(f"- {item}" for item in highlights)
    else:
        lines.append("- See the changelog for release details.")

    lines.extend(["", "### Contributors"])
    if contributors:
        lines.append(", ".join(contributors))
    else:
        lines.append("Maintainers")

    compare_from = previous_tag or tag
    lines.extend(
        [
            "",
            "### Full changelog",
            f"https://github.com/ZhuLinsen/daily_stock_analysis/compare/{compare_from}...{tag}",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    tag = os.environ.get("RELEASE_TAG") or os.environ.get("GITHUB_REF_NAME") or ""
    body = build(tag)
    output = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/tmp/release_body.md")
    output.write_text(body, encoding="utf-8")


if __name__ == "__main__":
    main()
