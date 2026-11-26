#!/usr/bin/env python3
"""Sync signed APKs and Fastlane/F-Droid metadata from tracked GitHub Releases into repo/ and metadata/.

Fail-closed security:
- Only downloads non-draft, non-prerelease GitHub Releases.
- Verifies every downloaded APK against the release's SHA256SUMS file before keeping it.
- Prunes old APKs beyond each app's `keepReleases` window.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPO_DIR = ROOT / "repo"
META_DIR = ROOT / "metadata"


def gh_json(*args: str) -> object:
    proc = subprocess.run(
        ["gh", *args],
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
    )
    return json.loads(proc.stdout)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def download_file(url: str, dest: Path) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "kyc-rip-fdroid-sync/1.0"})
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if token and url.startswith("https://api.github.com/"):
        req.add_header("Authorization", f"Bearer {token}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    with urllib.request.urlopen(req, timeout=180) as resp, tmp.open("wb") as out:
        shutil.copyfileobj(resp, out)
    tmp.replace(dest)


def parse_sha256sums(text: str) -> dict[str, str]:
    sums: dict[str, str] = {}
    for line in text.splitlines():
        m = re.fullmatch(r"([0-9a-f]{64})\s+\*?(\S+)", line.strip())
        if m:
            sums[m.group(2)] = m.group(1)
    return sums


def sync_metadata_tree(repo_slug: str, ref: str, remote_dir: str, local_dir: Path) -> None:
    """Recursively download a metadata/<appId> directory from a GitHub tag."""
    try:
        entries = gh_json("api", f"repos/{repo_slug}/contents/{remote_dir}?ref={ref}")
    except subprocess.CalledProcessError as e:
        print(f"  [warn] metadata path {remote_dir}@{ref} unavailable: {e.stderr.strip()}", file=sys.stderr)
        return
    if not isinstance(entries, list):
        return
    local_dir.mkdir(parents=True, exist_ok=True)
    for item in entries:
        itype = item.get("type")
        name = item.get("name", "")
        if not name or "/" in name or name in (".", ".."):
            continue
        if itype == "dir":
            sync_metadata_tree(repo_slug, ref, f"{remote_dir}/{name}", local_dir / name)
        elif itype == "file":
            dl_url = item.get("download_url")
            if dl_url:
                download_file(dl_url, local_dir / name)


def yaml_escape(s: str) -> str:
    return json.dumps(s, ensure_ascii=False)


def write_app_yaml(app: dict) -> None:
    app_id = app["appId"]
    lines = [
        "Categories:",
        *[f"  - {c}" for c in app.get("categories", ["Internet"])],
        f"License: {app['license']}",
        f"AuthorName: {yaml_escape(app.get('authorName', 'kyc.rip'))}",
        f"WebSite: {app['webSite']}",
        f"SourceCode: {app['sourceCode']}",
        f"IssueTracker: {app['issueTracker']}",
    ]
    if app.get("changelog"):
        lines.append(f"Changelog: {app['changelog']}")
    if app.get("donate"):
        lines.append(f"Donate: {app['donate']}")
    if app.get("antiFeatures"):
        lines.append("AntiFeatures:")
        for af in app["antiFeatures"]:
            lines.append(f"  {af}: {{}}")
    lines.append(f"AutoName: {yaml_escape(app['name'])}")
    META_DIR.mkdir(parents=True, exist_ok=True)
    (META_DIR / f"{app_id}.yml").write_text("\n".join(lines) + "\n", encoding="utf-8")


def sync_app(app: dict) -> None:
    app_id = app["appId"]
    repo_slug = app["repo"]
    apk_re = re.compile(app["apkPattern"])
    keep = max(1, int(app.get("keepReleases", 3)))

    print(f"==> Syncing {app_id} from {repo_slug} (keep={keep})")
    releases = gh_json("api", f"repos/{repo_slug}/releases?per_page=15")
    if not isinstance(releases, list):
        raise RuntimeError(f"Unexpected releases payload for {repo_slug}")

    selected: list[tuple[str, dict, dict | None]] = []
    for rel in releases:
        if rel.get("draft") or rel.get("prerelease"):
            continue
        assets = rel.get("assets") or []
        apk_asset = next((a for a in assets if apk_re.fullmatch(a.get("name", ""))), None)
        if not apk_asset:
            continue
        sums_asset = next((a for a in assets if a.get("name") == "SHA256SUMS"), None)
        selected.append((rel["tag_name"], apk_asset, sums_asset))
        if len(selected) >= keep:
            break

    if not selected:
        raise RuntimeError(f"No matching APK releases found for {app_id} in {repo_slug}")

    REPO_DIR.mkdir(parents=True, exist_ok=True)
    kept_filenames: set[str] = set()

    for tag, apk_asset, sums_asset in selected:
        filename = apk_asset["name"]
        kept_filenames.add(filename)
        dest = REPO_DIR / filename

        expected_sha: str | None = None
        if sums_asset:
            sums_tmp = ROOT / "tmp" / f"{app_id}-{tag}-SHA256SUMS"
            download_file(sums_asset["browser_download_url"], sums_tmp)
            sums = parse_sha256sums(sums_tmp.read_text(encoding="utf-8"))
            expected_sha = sums.get(filename)
            if not expected_sha:
                raise RuntimeError(f"SHA256SUMS for {repo_slug}@{tag} missing entry for {filename}")

        if dest.is_file() and expected_sha and sha256_file(dest) == expected_sha:
            print(f"  [ok] {filename} already verified in repo/")
            continue

        print(f"  [dl] {filename} ({tag})")
        download_file(apk_asset["browser_download_url"], dest)
        actual_sha = sha256_file(dest)
        if expected_sha and actual_sha != expected_sha:
            dest.unlink(missing_ok=True)
            raise RuntimeError(f"SHA-256 mismatch for {filename}: expected {expected_sha}, got {actual_sha}")
        print(f"  [verified] {filename} sha256={actual_sha[:16]}…")

    # Prune stale APKs belonging to this app outside the latest `keep` releases.
    for existing in REPO_DIR.glob("*.apk"):
        if apk_re.fullmatch(existing.name) and existing.name not in kept_filenames:
            print(f"  [prune] removing old APK {existing.name}")
            existing.unlink()
            existing.with_suffix(".apk.asc").unlink(missing_ok=True)

    # Sync Fastlane/F-Droid metadata from the newest release tag.
    latest_tag = selected[0][0]
    remote_meta = app.get("metadataDir")
    local_meta = META_DIR / app_id
    if local_meta.exists():
        shutil.rmtree(local_meta)
    if remote_meta:
        sync_metadata_tree(repo_slug, latest_tag, remote_meta, local_meta)
    write_app_yaml(app)


def main() -> None:
    cfg = json.loads((ROOT / "apps.json").read_text(encoding="utf-8"))
    for app in cfg["apps"]:
        sync_app(app)


if __name__ == "__main__":
    main()
