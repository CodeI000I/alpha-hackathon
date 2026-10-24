"""Explicitly prepare local analytics assets; importing this module downloads nothing.

Examples::

    python -m orchestrator.analytics.prepare_assets --ocr
    python -m orchestrator.analytics.prepare_assets --model --ocr

OCR assets come from the official Tesseract tessdata_fast repository and are
SHA-256 pinned. The sentence-transformer snapshot is pinned to one HF commit.
"""

import argparse
import hashlib
import os
from pathlib import Path
import tempfile
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[2]
MODEL_ID = 'sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2'
MODEL_REVISION = 'e8f8c211226b894fcb81acc59f3b34ba3efd5f42'
MODEL_DIR = ROOT / 'orchestrator' / 'data' / 'embedding-model'
MODEL_FILES = [
    'config.json', 'config_sentence_transformers.json', 'modules.json', 'model.safetensors',
    'sentence_bert_config.json', 'sentencepiece.bpe.model', 'special_tokens_map.json',
    'tokenizer.json', 'tokenizer_config.json', 'unigram.json', '1_Pooling/config.json',
]
TESSDATA_DIR = ROOT / 'orchestrator' / 'data' / 'tessdata'
OCR_ASSETS = {
    'eng': (
        'https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/main/eng.traineddata',
        '7d4322bd2a7749724879683fc3912cb542f19906c83bcc1a52132556427170b2',
    ),
    'rus': (
        'https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/main/rus.traineddata',
        'e16e5e036cce1d9ec2b00063cf8b54472625b9e14d893a169e2b0dedeb4df225',
    ),
}
MAX_TRAINEDDATA_BYTES = 10 * 1024 * 1024


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix='.asset-', delete=False) as handle:
        temp_path = Path(handle.name)
        try:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
            os.replace(temp_path, path)
        except BaseException:
            temp_path.unlink(missing_ok=True)
            raise


def prepare_ocr() -> Path:
    for language, (url, expected_hash) in OCR_ASSETS.items():
        destination = TESSDATA_DIR / f'{language}.traineddata'
        if destination.is_file() and hashlib.sha256(destination.read_bytes()).hexdigest() == expected_hash:
            print(f'{language}: already present and verified')
            continue
        request = Request(url, headers={'User-Agent': 'analytics-local-assets/1.0'})
        with urlopen(request, timeout=60) as response:
            content = response.read(MAX_TRAINEDDATA_BYTES + 1)
        if not content or len(content) > MAX_TRAINEDDATA_BYTES:
            raise RuntimeError(f'Unexpected size for {language} traineddata')
        if hashlib.sha256(content).hexdigest() != expected_hash:
            raise RuntimeError(f'Official {language} traineddata checksum changed; refusing to install')
        _atomic_write(destination, content)
        print(f'{language}: installed and verified ({len(content)} bytes)')
    print(f'Set TESSDATA_PREFIX={TESSDATA_DIR} for local OCR.')
    return TESSDATA_DIR


def prepare_model() -> Path:
    try:
        from huggingface_hub import snapshot_download
    except ImportError as exc:
        raise RuntimeError('Install the project environment to prepare the local sentence model') from exc
    snapshot_download(repo_id=MODEL_ID, revision=MODEL_REVISION, local_dir=MODEL_DIR,
                      allow_patterns=MODEL_FILES)
    print(f'Installed {MODEL_ID}@{MODEL_REVISION} at {MODEL_DIR}')
    return MODEL_DIR


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', action='store_true', help='download the pinned local sentence model')
    parser.add_argument('--ocr', action='store_true', help='download official pinned English and Russian OCR data')
    args = parser.parse_args(argv)
    if not (args.model or args.ocr):
        parser.error('select at least one of --model or --ocr')
    if args.model:
        prepare_model()
    if args.ocr:
        prepare_ocr()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
