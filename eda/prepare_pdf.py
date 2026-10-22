"""Локальное распознавание PDF и аудит страниц."""

import argparse
import csv
import hashlib
import io
import json
import os
import subprocess
import tempfile
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import pymupdf


def extract_page(task):
    path, number, tessdata = task
    with pymupdf.open(path) as doc:
        page = doc[number]
        native = page.get_text(sort=True)
        images = page.get_image_info()
        rect = page.rect
        coverage = max(
            (pymupdf.Rect(i["bbox"]).get_area() / rect.get_area() for i in images), default=0
        )
        pix = page.get_pixmap(dpi=180, alpha=False)
        page_hash = hashlib.sha256(pix.samples).hexdigest()
        with tempfile.TemporaryDirectory() as directory:
            png = Path(directory) / "page.png"
            pix.save(png)
            command = ["tesseract", str(png), "stdout", "-l", "rus+eng", "--psm", "3"]
            if tessdata:
                command.extend(["--tessdata-dir", tessdata])
            command.extend(["-c", "tessedit_create_tsv=1"])
            result = subprocess.run(
                command,
                check=True,
                capture_output=True,
                text=True,
                timeout=180,
                env={**os.environ, "OMP_THREAD_LIMIT": "1"},
            )
        if not result.stdout.startswith("level\tpage_num\t"):
            raise ValueError("Tesseract did not return TSV")
        # Кавычки входят в распознанный текст и не задают формат TSV.
        words = [
            r
            for r in csv.DictReader(
                io.StringIO(result.stdout), delimiter="\t", quoting=csv.QUOTE_NONE
            )
            if r["level"] == "5" and r["text"].strip()
        ]
        if any("\t" in w["text"] or "\n" in w["text"] for w in words):
            raise ValueError("Invalid text field in Tesseract TSV")
        groups = {}
        for word in words:
            key = tuple(word[k] for k in ("block_num", "par_num", "line_num"))
            groups.setdefault(key, []).append(word)
        lines = []
        for group in groups.values():
            lines.append(
                dict(
                    text=" ".join(w["text"] for w in group),
                    confidence=sum(float(w["conf"]) for w in group) / len(group),
                    left=min(int(w["left"]) for w in group),
                    top=min(int(w["top"]) for w in group),
                    right=max(int(w["left"]) + int(w["width"]) for w in group),
                    bottom=max(int(w["top"]) + int(w["height"]) for w in group),
                )
            )
        confidence = [float(w["conf"]) for w in words]
        return dict(
            document=Path(path).name,
            page=number + 1,
            native_chars=len(native.strip()),
            image_count=len(images),
            image_coverage=min(coverage, 1.0),
            width_pt=rect.width,
            height_pt=rect.height,
            render_sha256=page_hash,
            ocr_words=len(words),
            ocr_confidence=sum(confidence) / len(confidence) if confidence else None,
            low_confidence_share=(
                sum(c < 60 for c in confidence) / len(confidence) if confidence else None
            ),
            text="\n".join(line["text"] for line in lines),
            lines=lines,
        )


def prepare(pdf_dir, output, tessdata=None, workers=3):
    paths = sorted(Path(pdf_dir).glob("*.pdf"))
    if not paths:
        raise FileNotFoundError(f"No PDF files in {pdf_dir}")
    documents, tasks = [], []
    for path in paths:
        with pymupdf.open(path) as doc:
            documents.append(
                dict(
                    document=path.name,
                    sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                    size_bytes=path.stat().st_size,
                    pages=len(doc),
                    metadata=doc.metadata,
                )
            )
            tasks.extend(
                (str(path), page, str(tessdata) if tessdata else None)
                for page in range(len(doc))
            )
    pages = []
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for row in pool.map(extract_page, tasks):
            pages.append(row)
            print(f"{len(pages)}/{len(tasks)}: {row['document']} p.{row['page']}", flush=True)
    payload = dict(
        engine=subprocess.check_output(["tesseract", "--version"], text=True).splitlines()[0],
        dpi=180,
        languages="rus+eng",
        psm=3,
        documents=documents,
        pages=pages,
    )
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=Path("data/reports"))
    parser.add_argument("--output", type=Path, default=Path("data/pdf_ocr.json"))
    parser.add_argument("--tessdata", type=Path)
    parser.add_argument("--workers", type=int, default=3, choices=range(1, 9))
    args = parser.parse_args()
    prepare(args.input, args.output, args.tessdata, args.workers)
