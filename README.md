# kyc.rip F-Droid Repository (`https://fdroid.kyc.rip/repo`)

Official self-hosted F-Droid repository for **kyc.rip** privacy & Monero Android apps (starting with **XMRadar**, and ready for **Ripley Vault** and future `rip.kyc.*` apps).

## Architecture

- **Single source of truth:** [`apps.json`](apps.json) lists every tracked GitHub repository, APK filename regex, F-Droid metadata path, license, categories, and AntiFeatures.
- **Verified APK sync:** [`scripts/sync_apps.py`](scripts/sync_apps.py) pulls signed APKs from GitHub Releases and verifies every APK against the release's `SHA256SUMS` before indexing.
- **Signed F-Droid index:** [`.github/workflows/publish.yml`](.github/workflows/publish.yml) runs `fdroidserver` (`fdroid update`) with a dedicated repo signing key (separate from each app's APK signing key) and uploads `repo/` + [`index.html`](scripts/build_landing.py) to Cloudflare R2 (`kyc-rip-fdroid`).
- **Edge delivery:** [`worker/`](worker/) is a tiny Cloudflare Worker streaming `kyc-rip-fdroid` at `https://fdroid.kyc.rip` with full HTTP `Range` support, immutable caching for APKs, and 5-minute caching for `index-v2.json`.

## Adding a new `rip.kyc.*` app

1. Make sure the app's GitHub Releases attach its signed `.apk` and a `SHA256SUMS` file, and keep F-Droid Fastlane metadata under `metadata/<appId>/en-US/`.
2. Add an entry to [`apps.json`](apps.json) and push to `main`.
3. Trigger **Publish F-Droid Repository** (or wait for the next 6-hour scheduled run).

## Required GitHub `release` environment secrets

| Secret | Description |
|---|---|
| `FDROID_KEYSTORE_BASE64` | Base64-encoded JKS/PKCS12 keystore used to sign the F-Droid index (back up offline; never rotate!) |
| `FDROID_KEYSTORE_PASS` | Keystore password |
| `FDROID_KEY_ALIAS` | Key alias inside the keystore (e.g. `fdroid-kyc-rip`) |
| `FDROID_KEY_PASS` | Key password |
| `R2_ENDPOINT` | `https://<ACCOUNT_ID>.r2.cloudflarestorage.com` |
| `R2_BUCKET` | `kyc-rip-fdroid` |
| `R2_ACCESS_KEY_ID` | Scoped Cloudflare R2 API token access key ID (Object Read & Write on `kyc-rip-fdroid`) |
| `R2_SECRET_ACCESS_KEY` | Scoped Cloudflare R2 API token secret access key |
