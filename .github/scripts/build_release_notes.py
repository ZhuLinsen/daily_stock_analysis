"""Publish notes from merged PRs and archive a published release on demand."""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import subprocess
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
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True, encoding="utf-8")


def _section_match(text: str, version: str) -> re.Match[str] | None:
    return re.search(
        rf"^## \[{re.escape(version)}\][^\n]*\n(.*?)(?=^## \[|^\[Unreleased\]:|\Z)",
        text,
        re.MULTILINE | re.DOTALL,
    )


def _section_for(text: str, version: str) -> str:
    match = _section_match(text, version)
    return match.group(1).strip() if match else ""


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


def _version(tag: str) -> tuple[int, ...]:
    if not re.fullmatch(r"v\d+\.\d+\.\d+", tag):
        raise ValueError(f"Unsupported release tag: {tag}")
    return tuple(map(int, tag[1:].split(".")))


def _previous_tag(tag: str) -> str:
    version = _version(tag)
    for candidate in _run_git("tag", "--merged", tag, "--sort=-v:refname").splitlines():
        if re.fullmatch(r"v\d+\.\d+\.\d+", candidate) and _version(candidate) < version:
            return candidate
    return ""


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
    previous_tag = _previous_tag(tag)
    # GitHub applies the categories and exclusions configured in .github/release.yml.
    args = [
        "gh", "api", "--method", "POST", "repos/{owner}/{repo}/releases/generate-notes",
        "-f", f"tag_name={tag}", "--jq", ".body",
    ]
    if previous_tag:
        args.extend(["-f", f"previous_tag_name={previous_tag}"])
    notes = subprocess.check_output(args, cwd=ROOT, encoding="utf-8").strip()
    if not notes:
        raise ValueError(f"GitHub returned empty release notes for {tag}")

    section = _section_for(CHANGELOG.read_text(encoding="utf-8"), tag[1:])
    highlights = _highlights(section)
    contributors = _contributors(previous_tag, tag)

    lines = [f"## {tag}", ""]
    if highlights:
        lines.append("### Highlights")
        lines.extend(f"- {item}" for item in highlights)
        lines.append("")

    lines.append(notes)
    lines.extend(["", "### Contributors"])
    if contributors:
        lines.append(", ".join(contributors))
    else:
        lines.append("Maintainers")

    return "\n".join(lines) + "\n"


def archive_release(tag: str) -> None:
    version = _version(tag)
    text = CHANGELOG.read_text(encoding="utf-8")
    headers = list(re.finditer(r"^## \[(\d+\.\d+\.\d+)\].*$", text, re.MULTILINE))
    if any(match.group(1) == tag[1:] for match in headers):
        print(f"{tag} is already archived")
        return

    args = ["gh", "release", "view", tag, "--json", "body,publishedAt,isDraft,url"]
    release = json.loads(subprocess.check_output(args, cwd=ROOT, encoding="utf-8"))
    body = (release["body"] or "").replace("\r\n", "\n").strip()
    if release["isDraft"] or not release["publishedAt"] or not body:
        raise ValueError(f"{tag} needs published release notes before it can be archived")
    date = release["publishedAt"][:10]
    body = body.removeprefix(f"## {tag}\n").lstrip()
    entry = f"## [{tag[1:]}] - {date}\n\n{body}\n\n"
    references = re.search(r"^\[Unreleased\]: .+$", text, re.MULTILINE)
    end_of_versions = references.start() if references else len(text)
    insert_at = next((header.start() for header in headers if _version("v" + header.group(1)) < version), end_of_versions)
    before = text[:insert_at]
    newest = not headers or insert_at == headers[0].start()
    pending = _section_match(before, "Unreleased")
    if pending:
        # The previous tag can still contain entries waiting for its own archive.
        pending_lines = pending.group(1).splitlines()
        carried = _released_pending_entries(tag, pending_lines)
        if carried:
            kept = "\n".join(line for line in pending_lines if line not in carried).strip("\n")
            before = before[:pending.start(1)] + (f"\n{kept}\n\n" if kept else "\n") + before[pending.end(1):]
            entry += "### 补充说明\n\n" + "\n".join(carried) + "\n\n"
    after = text[insert_at:]
    if references:
        pending_link = references.group()
        if newest:
            repo_url = release["url"].rsplit("/releases/tag/", 1)[0]
            pending_link = f"[Unreleased]: {repo_url}/compare/{tag}...HEAD"
        after = after.replace(references.group(), f"{pending_link}\n[{tag[1:]}]: {release['url']}", 1)
    CHANGELOG.write_text(before.rstrip("\n") + "\n\n" + entry + after, encoding="utf-8")
    print(f"Archived {tag} in {CHANGELOG}")


def _released_pending_entries(tag: str, pending_lines: list[str]) -> list[str]:
    bullets = [line for line in pending_lines if line.startswith("- ")]
    if not bullets:
        return []

    previous_tag = _previous_tag(tag)
    at_tag = _tag_pending_entries(tag)
    at_previous = _tag_pending_entries(previous_tag) if previous_tag else set()
    released_lines = at_tag - at_previous
    return [line for line in bullets if line in released_lines]


def _tag_pending_entries(tag: str) -> set[str]:
    section = _section_match(_run_git("show", f"{tag}:docs/CHANGELOG.md"), "Unreleased")
    return {line for line in section.group(1).splitlines() if line.startswith("- ")} if section else set()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("output", nargs="?", type=Path, help="write the tag's release body to this file")
    mode.add_argument("--archive", metavar="TAG", help="copy a published release into docs/CHANGELOG.md")
    args = parser.parse_args()
    if args.archive:
        archive_release(args.archive)
        return
    tag = os.environ.get("RELEASE_TAG") or os.environ.get("GITHUB_REF_NAME") or ""
    body = build(tag)
    output = args.output or Path("/tmp/release_body.md")
    output.write_text(body, encoding="utf-8")


if __name__ == "__main__":
    main()
