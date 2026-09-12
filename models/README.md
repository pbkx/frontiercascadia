# Local Fishial detector

Run once after dependency installation:

```bash
.venv/bin/python scripts/download_model.py
```

This downloads the pretrained **YOLO26 Fish Detector** linked under **Detection** in the official [Fishial project](https://github.com/fishial/fish-identification). The verified archive `detector_v26_n3.zip` contains an Ultralytics-compatible `model.pt`, installed as `models/fishial.pt`. No training, species classification, cloud inference, or API key is involved. Model weights stay out of Git.

Download URL: https://storage.googleapis.com/fishial-ml-resources/detector_v26_n3.zip

Verified model SHA-256: `5b786b334355fdb0c3faa9d375d70de24f3535ee6f11e9c3e26ec2e90810c03f`

The downloader verifies both archive and checkpoint hashes and supports `--archive /path/to/detector_v26_n3.zip` for installation from an offline copy. If upstream replaces the release, it stops with a setup message. You may obtain a compatible pretrained checkpoint directly from Fishial and set `FISHIAL_MODEL_PATH` yourself. A model must have a general `Fish`/`fish` detection class; COCO models and species classifiers are rejected.

The Fishial repository carries the MIT license, copyright 2021 Wye Foundation – Fishial.AI Project. Upstream code/license: https://github.com/fishial/fish-identification/blob/main/LICENSE. Model usage is subject to the upstream checkpoint terms and the Ultralytics AGPL-3.0 or enterprise license as applicable. SalmonSight does not claim authorship of or training credit for these weights.
