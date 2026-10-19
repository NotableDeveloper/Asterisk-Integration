#!/usr/bin/env python3
"""Download official models atomically, reject unsafe archives, record SHA256."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import tarfile
import tempfile
import urllib.request

BASE = 'https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/'
MODELS = [
    'sherpa-onnx-streaming-zipformer-korean-2024-06-16',
    'sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17',
]

def download(url, target):
    print(f'Downloading {url}', flush=True)
    partial = target.with_suffix(target.suffix + '.part')
    try:
        with urllib.request.urlopen(url, timeout=120) as response, partial.open('wb') as out:
            shutil.copyfileobj(response, out)
        partial.replace(target)
    finally:
        partial.unlink(missing_ok=True)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--directory', type=Path, default=Path(__file__).resolve().parents[1] / 'models')
    parser.add_argument('--verify', action='store_true', help='Verify downloaded files against the local manifest without network access')
    args = parser.parse_args()
    root = args.directory.resolve()
    root.mkdir(parents=True, exist_ok=True)
    if args.verify:
        manifest = json.loads((root / 'manifest.json').read_text())
        for name, expected in manifest.items():
            path = (root / name).resolve()
            if not path.is_relative_to(root):
                raise ValueError(f'Unsafe manifest path: {name}')
            with path.open('rb') as stream:
                actual = hashlib.file_digest(stream, 'sha256').hexdigest()
            if actual != expected['sha256'] or path.stat().st_size != expected['bytes']:
                raise ValueError(f'Model integrity mismatch: {name}')
        print(f'Verified {len(manifest)} files against local manifest')
        return
    for name in MODELS:
        if (root / name).exists():
            expected = ['tokens.txt', 'encoder-epoch-99-avg-1.int8.onnx',
                        'decoder-epoch-99-avg-1.int8.onnx', 'joiner-epoch-99-avg-1.int8.onnx'] if 'zipformer' in name else ['tokens.txt', 'model.int8.onnx', 'test_wavs/ko.wav']
            if not all((root / name / f).is_file() and (root / name / f).stat().st_size for f in expected):
                raise ValueError(f'Incomplete model directory: {root / name}. Move it aside and rerun.')
            continue
        with tempfile.TemporaryDirectory(dir=root) as temp:
            temp = Path(temp)
            archive = temp / (name + '.tar.bz2')
            download(BASE + archive.name, archive)
            with tarfile.open(archive) as tar:
                for member in tar.getmembers():
                    dest = (temp / member.name).resolve()
                    if not dest.is_relative_to(temp) or not (member.isfile() or member.isdir()):
                        raise ValueError(f'Unsafe archive entry: {member.name}')
                tar.extractall(temp, filter='data')
            (temp / name).replace(root / name)
    vad = root / 'silero_vad.onnx'
    if not vad.exists():
        download(BASE + vad.name, vad)
    manifest = {}
    for path in sorted(root.rglob('*')):
        if path.is_file() and path.suffix in {'.onnx', '.txt', '.wav'}:
            with path.open('rb') as stream:
                digest = hashlib.file_digest(stream, 'sha256').hexdigest()
            manifest[str(path.relative_to(root))] = {'bytes': path.stat().st_size, 'sha256': digest}
    (root / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print('Models ready. Local integrity manifest: ' + str(root / 'manifest.json'))

if __name__ == '__main__':
    main()
