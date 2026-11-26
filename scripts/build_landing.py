#!/usr/bin/env python3
"""Build a self-contained static landing page (`public/index.html`) for https://fdroid.kyc.rip/
with inline SVG QR code, 1-tap fdroidrepos:// deep link, SHA-256 fingerprint, and live app cards
parsed from `repo/index-v2.json`.
"""
from __future__ import annotations

import argparse
import html
import io
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def format_fp(hex_fp: str) -> str:
    clean = "".join(c for c in hex_fp.upper() if c in "0123456789ABCDEF")
    if len(clean) != 64:
        raise SystemExit(f"Expected 64-hex SHA-256 fingerprint, got {len(clean)} chars")
    return " ".join(clean[i : i + 2] for i in range(0, 64, 2))


def make_qr_svg(data: str) -> str:
    try:
        import qrcode
        import qrcode.image.svg

        qr = qrcode.QRCode(border=2, box_size=6)
        qr.add_data(data)
        qr.make(fit=True)
        img = qr.make_image(image_factory=qrcode.image.svg.SvgPathImage)
        buf = io.BytesIO()
        img.save(buf)
        svg = buf.getvalue().decode("utf-8")
        # Strip XML declaration so SVG embeds cleanly inline in HTML5.
        if svg.startswith("<?xml"):
            svg = svg.split("?>", 1)[1].lstrip()
        return svg
    except ImportError:
        return '<div class="qr-fallback">Install python3-qrcode in CI to render QR</div>'


def localized(val: object) -> str:
    if isinstance(val, str):
        return val
    if isinstance(val, dict):
        return str(val.get("en-US") or val.get("en") or next(iter(val.values()), ""))
    return ""


def load_apps_from_index(index_path: Path) -> list[dict]:
    if not index_path.is_file():
        return []
    data = json.loads(index_path.read_text(encoding="utf-8"))
    packages = data.get("packages") or {}
    out: list[dict] = []
    for app_id, pkg in sorted(packages.items()):
        meta = pkg.get("metadata") or {}
        versions = pkg.get("versions") or {}
        newest = None
        for v in versions.values():
            vc = int((v.get("manifest") or {}).get("versionCode") or 0)
            if newest is None or vc > newest[0]:
                newest = (vc, v)
        if not newest:
            continue
        v = newest[1]
        manifest = v.get("manifest") or {}
        file_info = v.get("file") or {}
        file_name = str(file_info.get("name") or "").lstrip("/")
        size_mb = round(int(file_info.get("size") or 0) / (1024 * 1024), 1)
        icon_meta = meta.get("icon") or {}
        icon_name = ""
        if isinstance(icon_meta, dict):
            first = icon_meta.get("en-US") or next(iter(icon_meta.values()), None)
            if isinstance(first, dict) and first.get("name"):
                icon_name = str(first["name"]).lstrip("/")
        out.append(
            {
                "appId": app_id,
                "name": localized(meta.get("name")) or app_id,
                "summary": localized(meta.get("summary")),
                "versionName": str(manifest.get("versionName") or ""),
                "versionCode": str(manifest.get("versionCode") or ""),
                "apkUrl": f"/repo/{file_name}" if file_name else "",
                "apkSha": str(file_info.get("sha256") or ""),
                "sizeMb": size_mb,
                "iconUrl": f"/repo/{icon_name}" if icon_name else "",
                "webSite": str(meta.get("webSite") or ""),
                "sourceCode": str(meta.get("sourceCode") or ""),
            }
        )
    return out


def render_html(repo_url: str, fingerprint: str, apps: list[dict]) -> str:
    clean_fp = "".join(c for c in fingerprint.upper() if c in "0123456789ABCDEF")
    pretty_fp = format_fp(clean_fp)
    https_uri = f"{repo_url}?fingerprint={clean_fp}"
    fdroid_uri = https_uri.replace("https://", "fdroidrepos://", 1)
    qr_svg = make_qr_svg(https_uri)

    cards_html: list[str] = []
    for a in apps:
        icon = (
            f'<img class="app-icon" src="{html.escape(a["iconUrl"])}" alt="" width="48" height="48">'
            if a["iconUrl"]
            else '<div class="app-icon placeholder">ɱ</div>'
        )
        sha_short = f'{a["apkSha"][:8]}…{a["apkSha"][-8:]}' if len(a["apkSha"]) == 64 else ""
        links = []
        if a["apkUrl"]:
            links.append(f'<a class="btn-sm primary" href="{html.escape(a["apkUrl"])}">Direct APK ({a["sizeMb"]} MB)</a>')
        if a["webSite"]:
            links.append(f'<a class="btn-sm" href="{html.escape(a["webSite"])}">Website</a>')
        if a["sourceCode"]:
            links.append(f'<a class="btn-sm" href="{html.escape(a["sourceCode"])}">Source</a>')
        cards_html.append(
            f"""<article class="app-card">
  <div class="app-head">
    {icon}
    <div>
      <h3>{html.escape(a["name"])} <span class="ver">v{html.escape(a["versionName"])}</span></h3>
      <p class="muted mono">{html.escape(a["appId"])}{f' · SHA-256 {html.escape(sha_short)}' if sha_short else ''}</p>
    </div>
  </div>
  <p class="summary">{html.escape(a["summary"])}</p>
  <div class="app-links">{''.join(links)}</div>
</article>"""
        )

    apps_block = "\n".join(cards_html) or '<p class="muted">Apps will appear here after the first CI sync.</p>'

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>kyc.rip F-Droid Repository</title>
<meta name="description" content="Official F-Droid repository for kyc.rip privacy & Monero Android apps (XMRadar, Ripley Vault, and more).">
<style>
  :root {{
    --bg: #0c0d11; --card: #15171f; --border: #262936; --fg: #eceef4;
    --muted: #98a0b3; --accent: #8b5cf6; --xmr: #f26822; --ok: #22c55e;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; font: 15px/1.55 system-ui, -apple-system, sans-serif;
    background: var(--bg); color: var(--fg);
  }}
  main {{ max-width: 820px; margin: 0 auto; padding: 36px 20px 64px; }}
  header {{ display: flex; flex-direction: column; gap: 8px; margin-bottom: 24px; }}
  .kicker {{ font-size: 11px; letter-spacing: 0.12em; text-transform: uppercase; color: var(--xmr); font-weight: 700; }}
  h1 {{ margin: 0; font-size: 28px; letter-spacing: -0.02em; }}
  h2 {{ margin: 32px 0 14px; font-size: 18px; }}
  p {{ margin: 0; }}
  .muted {{ color: var(--muted); }}
  .mono {{ font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px; }}
  .hero-card {{
    display: grid; grid-template-columns: 1fr auto; gap: 24px; align-items: center;
    background: var(--card); border: 1px solid var(--border); border-radius: 16px; padding: 22px;
  }}
  @media (max-width: 640px) {{ .hero-card {{ grid-template-columns: 1fr; }} }}
  .qr-box {{
    background: #ffffff; padding: 12px; border-radius: 12px; width: 176px; height: 176px;
    display: grid; place-items: center; justify-self: center;
  }}
  .qr-box svg {{ width: 100%; height: 100%; display: block; }}
  .cta-row {{ display: flex; flex-wrap: wrap; gap: 10px; margin: 16px 0; }}
  .btn {{
    display: inline-flex; align-items: center; gap: 8px; padding: 10px 16px;
    border-radius: 10px; text-decoration: none; font-weight: 700; font-size: 14px;
    background: var(--accent); color: #fff;
  }}
  .btn.secondary {{ background: transparent; border: 1px solid var(--border); color: var(--fg); }}
  .kv {{ display: flex; flex-direction: column; gap: 8px; margin-top: 10px; }}
  .kv code {{
    display: block; padding: 8px 10px; border-radius: 8px; background: #0b0c10;
    border: 1px solid var(--border); word-break: break-all; color: #dbe2f0;
  }}
  .apps {{ display: grid; gap: 14px; }}
  .app-card {{
    background: var(--card); border: 1px solid var(--border); border-radius: 14px; padding: 18px;
    display: flex; flex-direction: column; gap: 12px;
  }}
  .app-head {{ display: flex; gap: 14px; align-items: center; }}
  .app-icon {{ width: 48px; height: 48px; border-radius: 12px; object-fit: cover; flex: none; }}
  .app-icon.placeholder {{
    display: grid; place-items: center; background: var(--accent); color: #fff; font-weight: 800; font-size: 22px;
  }}
  .app-head h3 {{ margin: 0 0 2px; font-size: 17px; }}
  .ver {{
    font-size: 12px; font-weight: 600; color: var(--ok); background: rgba(34,197,94,.12);
    padding: 2px 7px; border-radius: 999px; margin-left: 6px;
  }}
  .summary {{ color: #d5dae6; font-size: 14px; }}
  .app-links {{ display: flex; flex-wrap: wrap; gap: 8px; }}
  .btn-sm {{
    display: inline-flex; align-items: center; padding: 7px 12px; border-radius: 8px;
    font-size: 13px; font-weight: 600; text-decoration: none;
    border: 1px solid var(--border); color: var(--fg);
  }}
  .btn-sm.primary {{ background: var(--xmr); border-color: var(--xmr); color: #fff; }}
  footer {{ margin-top: 40px; font-size: 13px; color: var(--muted); display: flex; justify-content: space-between; flex-wrap: wrap; gap: 8px; }}
  footer a {{ color: var(--muted); }}
</style>
</head>
<body>
<main>
  <header>
    <span class="kicker">kyc.rip · Official F-Droid Repository</span>
    <h1>fdroid.kyc.rip</h1>
    <p class="muted">Signed Android APKs for kyc.rip privacy &amp; Monero apps — built in public CI from open-source repos, zero Google Play Services, zero Firebase, zero trackers.</p>
  </header>

  <section class="hero-card">
    <div>
      <p>Add once in <strong>F-Droid</strong>, <strong>Droid-ify</strong>, or <strong>Neo Store</strong> to get automatic signed updates for all kyc.rip apps.</p>
      <div class="cta-row">
        <a class="btn" href="{html.escape(fdroid_uri)}">Add to F-Droid</a>
        <a class="btn secondary" href="https://github.com/KYC-rip/fdroid-repo">Repo Source</a>
      </div>
      <div class="kv">
        <span class="muted mono">Repository URL</span>
        <code class="mono">{html.escape(repo_url)}</code>
        <span class="muted mono">SHA-256 Signing Fingerprint</span>
        <code class="mono">{html.escape(pretty_fp)}</code>
      </div>
    </div>
    <div class="qr-box" aria-label="QR code for fdroid.kyc.rip/repo">{qr_svg}</div>
  </section>

  <h2>Apps in this repository</h2>
  <section class="apps">
    {apps_block}
  </section>

  <footer>
    <span>Hosted on Cloudflare R2 · Signed with fdroidserver</span>
    <span><a href="https://kyc.rip">kyc.rip</a> · <a href="https://xmradar.app">xmradar.app</a> · <a href="https://github.com/KYC-rip">GitHub</a></span>
  </footer>
</main>
</body>
</html>
"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fingerprint", required=True, help="64-hex SHA-256 signing certificate fingerprint")
    ap.add_argument("--repo-url", default="https://fdroid.kyc.rip/repo")
    ap.add_argument("--index", default=str(ROOT / "repo" / "index-v2.json"))
    ap.add_argument("--out", default=str(ROOT / "public" / "index.html"))
    args = ap.parse_args()

    apps = load_apps_from_index(Path(args.index))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_html(args.repo_url, args.fingerprint, apps), encoding="utf-8")
    print(f"Built {out} ({len(apps)} app(s))")


if __name__ == "__main__":
    main()
