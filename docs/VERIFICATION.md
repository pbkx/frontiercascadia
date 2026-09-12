# Verification

Verified locally on September 12, 2026, on Apple silicon with Python 3.11, Node.js, Next.js, and the official Fishial checkpoint installed.

- `./scripts/setup.sh`: dependency installation and `.env` creation completed.
- `make check`: 37 backend tests passed; frontend lint, typecheck, and production build passed.
- `npm --prefix frontend run test:e2e`: both Chromium tests passed. They cover visible passage counting, reversals, trajectory filter selection, fish details, heatmaps, pause/resume, calibration, source chooser, and a narrow viewport.
- `npm --prefix frontend audit`: no reported dependency vulnerabilities after the patched PostCSS override.
- `./scripts/dev.sh --offline`: both localhost servers launched without downloads.
- Official Fishial archive and model SHA-256 verified; `models/fishial.pt` loaded with class `{0: 'Fish'}`. Local inference succeeded on Apple MPS and on CPU.
- With network socket connections disabled, the real checkpoint detected fish in an example-image crop from the Fishial repository and passed normalized detections to ByteTrack. A blank-frame smoke test is included in the automated suite.
- The actual `precompute_demo.py` and `validate.py` commands ran on a temporary video fixture containing upstream example imagery; the cache contained raw local detector outputs. Cached replay produced tracks with network socket connections blocked.
- Browser upload → calibration → local inference → frame display → tracking completed with no browser errors. At a 1440×900 viewport, the processed frame layer occupied 1440×900 and preserved the source's 640×360 aspect ratio via the same object-cover geometry as the Canvas overlay.
- Missing or unsuitable model tests verify an explicit setup message, no automatic COCO download, and no synthetic detections painted onto actual uploaded footage.

The temporary image/video fixtures are integration checks, not field footage, and are not bundled as an Issaquah demo. No model-accuracy, count-accuracy, biological, or engineering benchmark is claimed. Real field evaluation still requires an authorized clip, camera calibration, and human passage counts. The default bundled experience is an explicitly labeled illustrative simulation.

The in-app browser tool failed at initialization in this environment; UI verification used a separate local Chromium instance through Playwright.
