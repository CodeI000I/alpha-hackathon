"""Validate report chart annotations and export offline PDF crops."""

import argparse
import csv
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import shutil
import tempfile

import pymupdf

ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
SHA_RE = re.compile(r"^[a-f0-9]{64}$")
KINDS = {"line", "bar", "pie", "scatter", "mixed"}
GENERATED = {"image", "image_sha256", "image_width", "image_height"}
CSV_FIELDS = ("chart_id", "series_id", "label", "value", "unit", "forecast")


def _need(condition, message):
    if not condition:
        raise ValueError(message)


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _finite(value):
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def validate_catalog(payload):
    _need(isinstance(payload, dict) and isinstance(payload.get("schema_version"), int) and not isinstance(payload["schema_version"], bool) and payload["schema_version"] == 1, "schema_version must be 1")
    documents, charts = payload.get("documents"), payload.get("charts")
    _need(isinstance(documents, list) and isinstance(charts, list), "documents and charts must be arrays")
    docs, filenames = {}, set()
    for doc in documents:
        _need(isinstance(doc, dict), "document must be an object")
        _need(_text(doc.get("id")) and ID_RE.fullmatch(doc["id"]), "unsafe document id")
        _need(doc["id"] not in docs, "duplicate document id")
        filename = doc.get("file")
        _need(_text(filename) and "/" not in filename and "\\" not in filename and Path(filename).name == filename and Path(filename).suffix.lower() == ".pdf", "unsafe PDF basename")
        _need(filename not in filenames, "duplicate PDF filename")
        filenames.add(filename)
        _need(isinstance(doc.get("sha256"), str) and SHA_RE.fullmatch(doc["sha256"]), "invalid document SHA-256")
        _need(isinstance(doc.get("pages"), int) and not isinstance(doc["pages"], bool) and doc["pages"] > 0, "document pages must be a positive integer")
        _need(_text(doc.get("title")), "document title is required")
        docs[doc["id"]] = doc["pages"]

    chart_ids = set()
    for chart in charts:
        _need(isinstance(chart, dict), "chart must be an object")
        chart_id = chart.get("id")
        _need(_text(chart_id) and ID_RE.fullmatch(chart_id), "unsafe chart id")
        _need(chart_id not in chart_ids, "duplicate chart id")
        chart_ids.add(chart_id)
        document_id = chart.get("document_id")
        _need(isinstance(document_id, str) and document_id in docs, f"unknown document for chart {chart_id}")
        page = chart.get("page")
        _need(isinstance(page, int) and not isinstance(page, bool) and 1 <= page <= docs[chart["document_id"]], f"invalid page for chart {chart_id}")
        kind = chart.get("kind")
        _need(_text(chart.get("title")) and isinstance(kind, str) and kind in KINDS, f"invalid title or kind for chart {chart_id}")
        crop = chart.get("crop")
        _need(isinstance(crop, list) and len(crop) == 4 and all(_finite(v) and 0 <= v <= 1 for v in crop) and crop[0] < crop[2] and crop[1] < crop[3], f"invalid crop for chart {chart_id}")
        status = chart.get("data_status")
        _need(isinstance(status, str) and status in {"labelled_values", "image_only"}, f"invalid data_status for chart {chart_id}")
        axis = chart.get("x_axis")
        axis_kind = axis.get("kind") if isinstance(axis, dict) else None
        _need(isinstance(axis, dict) and isinstance(axis.get("label"), str) and isinstance(axis_kind, str) and axis_kind in {"time", "category"}, f"invalid x_axis for chart {chart_id}")
        _need(isinstance(chart.get("note"), str), f"invalid note for chart {chart_id}")
        series_list = chart.get("series")
        _need(isinstance(series_list, list), f"series must be an array for chart {chart_id}")
        if status == "image_only":
            _need(not series_list, f"image_only chart {chart_id} must not have series")
        else:
            _need(bool(series_list), f"labelled_values chart {chart_id} requires series")
        series_ids = set()
        for series in series_list:
            _need(isinstance(series, dict), f"series must be an object in chart {chart_id}")
            series_id = series.get("id")
            _need(_text(series_id) and ID_RE.fullmatch(series_id) and series_id not in series_ids, f"unsafe or duplicate series id in chart {chart_id}")
            series_ids.add(series_id)
            _need(_text(series.get("label")) and isinstance(series.get("unit"), str), f"invalid series label or unit in chart {chart_id}")
            points = series.get("points")
            _need(isinstance(points, list) and points, f"series points required in chart {chart_id}")
            for point in points:
                _need(isinstance(point, dict) and _text(point.get("label")) and _finite(point.get("value")), f"invalid point in chart {chart_id}")
                _need("forecast" not in point or isinstance(point["forecast"], bool), f"invalid forecast flag in chart {chart_id}")
        for key in GENERATED:
            if key in chart and key == "image":
                _need(chart[key] == f"images/{chart_id}.jpg", f"unsafe image path for chart {chart_id}")
            elif key in chart and key == "image_sha256":
                _need(isinstance(chart[key], str) and SHA_RE.fullmatch(chart[key]), f"invalid image hash for chart {chart_id}")
            elif key in chart:
                _need(isinstance(chart[key], int) and not isinstance(chart[key], bool) and chart[key] > 0, f"invalid image dimensions for chart {chart_id}")
    return payload


def load_annotations(directory):
    files = sorted(Path(directory).glob("*.json"))
    _need(bool(files), f"no annotation JSON files in {directory}")
    documents, charts = [], []
    for path in files:
        payload = json.loads(path.read_text(encoding="utf-8"))
        _need(isinstance(payload, dict) and isinstance(payload.get("documents"), list) and isinstance(payload.get("charts"), list), f"invalid annotations file {path.name}")
        documents.extend(payload["documents"])
        charts.extend(payload["charts"])
    return validate_catalog({"schema_version": 1, "documents": documents, "charts": charts})


def _csv_bytes(catalog):
    out = io.StringIO(newline="")
    writer = csv.DictWriter(out, fieldnames=CSV_FIELDS, lineterminator="\n")
    writer.writeheader()
    for chart in catalog["charts"]:
        for series in chart["series"]:
            for point in series["points"]:
                writer.writerow({
                    "chart_id": chart["id"], "series_id": series["id"], "label": point["label"],
                    "value": str(point["value"]), "unit": series["unit"],
                    "forecast": str(point["forecast"]).lower() if "forecast" in point else "",
                })
    return out.getvalue().encode("utf-8")


def _base_catalog(catalog):
    return {
        "schema_version": 1,
        "documents": catalog["documents"],
        "charts": [{key: value for key, value in chart.items() if key not in GENERATED} for chart in catalog["charts"]],
    }


def _verify_sources(input_dir, catalog):
    root = Path(input_dir)
    sources = {}
    for document in catalog["documents"]:
        path = root / document["file"]
        _need(path.is_file(), f"missing source PDF: {document['file']}")
        data = path.read_bytes()
        _need(hashlib.sha256(data).hexdigest() == document["sha256"], f"SHA-256 mismatch: {document['file']}")
        with pymupdf.open(path) as pdf:
            _need(len(pdf) == document["pages"], f"page count mismatch: {document['file']}")
        sources[document["id"]] = path
    return sources


def _render(path, page_number, crop, destination):
    with pymupdf.open(path) as pdf:
        page = pdf[page_number - 1]
        rect = page.rect
        clip = pymupdf.Rect(
            rect.x0 + rect.width * crop[0], rect.y0 + rect.height * crop[1],
            rect.x0 + rect.width * crop[2], rect.y0 + rect.height * crop[3],
        ) & rect
        _need(not clip.is_empty and clip.width > 0 and clip.height > 0, "crop is outside PDF page")
        scale = min(1199 / clip.width, 1599 / clip.height)
        pix = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), clip=clip, alpha=False)
        pix.save(destination, jpg_quality=92)
        return pix.width, pix.height


def prepare(input_dir, output_dir, catalog):
    validate_catalog(catalog)
    sources = _verify_sources(input_dir, catalog)  # Preflight every PDF before touching the export.
    output = Path(output_dir)
    output.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=f".{output.name}.stage-", dir=output.parent))
    try:
        (stage / "images").mkdir()
        exported = json.loads(json.dumps(_base_catalog(catalog), ensure_ascii=False))
        for chart in exported["charts"]:
            doc_path = sources[chart["document_id"]]
            image_path = stage / "images" / f"{chart['id']}.jpg"
            width, height = _render(doc_path, chart["page"], chart["crop"], image_path)
            image = image_path.read_bytes()
            chart.update(image=f"images/{chart['id']}.jpg", image_sha256=hashlib.sha256(image).hexdigest(), image_width=width, image_height=height)
        (stage / "points.csv").write_bytes(_csv_bytes(catalog))
        (stage / "catalog.json").write_text(json.dumps(exported, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        output.mkdir(parents=True, exist_ok=True)
        (output / "images").mkdir(exist_ok=True)
        for image in sorted((stage / "images").iterdir()):
            os.replace(image, output / "images" / image.name)
        os.replace(stage / "points.csv", output / "points.csv")
        os.replace(stage / "catalog.json", output / "catalog.json")
    finally:
        shutil.rmtree(stage, ignore_errors=True)
    return output


def verify_export(output_dir, catalog):
    validate_catalog(catalog)
    output = Path(output_dir)
    exported = json.loads((output / "catalog.json").read_text(encoding="utf-8"))
    validate_catalog(exported)
    _need(_base_catalog(exported) == _base_catalog(catalog), "exported catalog differs from annotations")
    for chart in exported["charts"]:
        _need(chart.get("image") == f"images/{chart['id']}.jpg" and all(key in chart for key in ("image_sha256", "image_width", "image_height")), f"missing image metadata: {chart['id']}")
        path = output / chart["image"]
        _need(path.is_file(), f"missing image: {chart['id']}")
        data = path.read_bytes()
        _need(data.startswith(b"\xff\xd8"), f"invalid image JPEG: {chart['id']}")
        pix = pymupdf.Pixmap(data)
        width, height = pix.width, pix.height
        _need((width, height) == (chart["image_width"], chart["image_height"]) and width <= 1200 and height <= 1600, f"invalid image dimensions: {chart['id']}")
        _need(hashlib.sha256(data).hexdigest() == chart["image_sha256"], f"image hash mismatch: {chart['id']}")
    _need((output / "points.csv").read_bytes() == _csv_bytes(catalog), "points.csv differs from annotations")
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--annotations", type=Path, default=Path("eda/report_charts"))
    parser.add_argument("--output", type=Path, default=Path("frontend/public/report-charts"))
    parser.add_argument("--input", type=Path, help="directory containing the original PDFs")
    parser.add_argument("--check", action="store_true", help="verify the existing offline export without source PDFs")
    args = parser.parse_args()
    catalog = load_annotations(args.annotations)
    if args.check:
        verify_export(args.output, catalog)
    elif args.input:
        prepare(args.input, args.output, catalog)
    else:
        parser.error("--input is required unless --check is used")


if __name__ == "__main__":
    main()
