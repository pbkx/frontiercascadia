# Demo footage

No Issaquah recording is bundled. The default illustrated habitat is **SIMULATED DATA**, not a field measurement.

Place a clip you have permission to use at `data/demo/issaquah.mp4` or `data/demo/salmon_demo.mp4`. MP4 with H.264 is recommended. The app discovers it when opening a new session. With `models/fishial.pt` installed, it can run actual inference entirely locally.

For smoother stage playback, cache the actual Fishial detections first:

```bash
.venv/bin/python scripts/precompute_demo.py \
  --video data/demo/issaquah.mp4 \
  --output data/demo/issaquah_detections.json \
  --sample-fps 10
```

This command also runs offline after the initial model download. The cache stores raw normalized fish boxes, confidence, source frame indices/timestamps, the detector identity/hash, and the video SHA-256. It does not store completed trajectories or behavior results. Replay runs ByteTrack and the behavior engine locally and is labeled **PREPROCESSED DEMO**.

Discovery prefers `DEFAULT_DEMO_VIDEO_PATH`, then `issaquah.mp4`, then `salmon_demo.mp4`. A matching `<video_stem>_detections.json` is preferred over `DEMO_DETECTIONS_PATH`. A cache for a different clip is rejected. Replacing a clip requires recomputing its cache. Clip and JSON files are ignored by Git.
