#!/usr/bin/env python3
"""One-time download of the official pretrained Fishial YOLO detector; no training."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
import zipfile
import requests

ROOT = Path(__file__).resolve().parents[1]
SOURCE = 'https://github.com/fishial/fish-identification'
URL = 'https://storage.googleapis.com/fishial-ml-resources/detector_v26_n3.zip'
ARCHIVE_SHA256 = '4f33cfdd724ffd26a5863774e157e8a43e590fdc183d854017a99b6dbf3a85ec'
MODEL_SHA256 = '5b786b334355fdb0c3faa9d375d70de24f3535ee6f11e9c3e26ec2e90810c03f'


def digest(path: Path) -> str:
    checksum = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            checksum.update(chunk)
    return checksum.hexdigest()


def install(output: Path, archive: Path | None = None):
    output = output.resolve()
    if output.is_file() and digest(output) == MODEL_SHA256:
        print(f'Official Fishial checkpoint already installed: {output}')
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='fishial-', dir=output.parent) as temporary:
        temporary = Path(temporary)
        if archive is None:
            archive = temporary / 'download.zip'
            print(f'Downloading pretrained Fishial detector (~115 MB) from {URL}', flush=True)
            with requests.get(URL, stream=True, timeout=(15, 60)) as response:
                response.raise_for_status()
                size = 0
                with archive.open('wb') as handle:
                    for chunk in response.iter_content(1024 * 1024):
                        size += len(chunk)
                        if size > 250 * 1024 * 1024:
                            raise ValueError('Unexpected archive size; download stopped.')
                        handle.write(chunk)
        if digest(archive) != ARCHIVE_SHA256:
            raise ValueError('Official archive checksum differs from the verified release. Check the Fishial repository for a changed release; the existing model was preserved.')
        with zipfile.ZipFile(archive) as bundle:
            # Only extract the fixed checkpoint member; never execute bundled scripts.
            with bundle.open('model.pt') as src, (temporary / 'fishial.pt').open('wb') as dst:
                shutil.copyfileobj(src, dst)
            metadata = json.loads(bundle.read('info.json'))
        model = temporary / 'fishial.pt'
        if digest(model) != MODEL_SHA256:
            raise ValueError('Checkpoint checksum mismatch.')
        model.replace(output)
        output.with_suffix('.source.json').write_text(json.dumps({'project': SOURCE, 'download': URL, 'sha256': MODEL_SHA256, 'upstream_metadata': metadata}, indent=2) + '\n')
    print(f'Installed local fish detector: {output}\nAll inference now runs offline. No API key or training is needed.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'models/fishial.pt')
    parser.add_argument('--archive', type=Path, help='Install from a previously downloaded official ZIP, fully offline')
    args = parser.parse_args()
    try:
        install(args.output, args.archive)
    except (OSError, ValueError, requests.RequestException, zipfile.BadZipFile, KeyError) as exc:
        parser.exit(1, f'Model setup failed: {exc}\nGet the Detection checkpoint from {SOURCE} and set FISHIAL_MODEL_PATH. No alternative weights were substituted.\n')


if __name__ == '__main__':
    main()
