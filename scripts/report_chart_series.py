"""Build portable per-series JSON and SVG exports from the offline chart catalog."""

import html
import json
import math
import re


_ID = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_SHA = re.compile(r"^[a-f0-9]{64}$")
_MODES = {"line", "bar", "scatter", "stacked", "band"}


def _need(ok, message):
    if not ok:
        raise ValueError(message)


def _finite(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _sig(value):
    rounded = float(format(value, ".3g"))
    return 0.0 if rounded == 0 else rounded


def _validate_profile(chart):
    profile = chart.get("digitization")
    if profile is None:
        return None, {}
    _need(isinstance(profile, dict), f"invalid digitization profile for {chart['id']}")
    _need(profile.get("image_sha256") == chart.get("image_sha256") and isinstance(profile.get("image_sha256"), str) and _SHA.fullmatch(profile["image_sha256"]), f"stale digitization image hash for {chart['id']}")
    width, height = chart.get("image_width"), chart.get("image_height")
    _need(isinstance(width, int) and not isinstance(width, bool) and width > 0 and isinstance(height, int) and not isinstance(height, bool) and height > 0, f"missing image dimensions for {chart['id']}")
    plot = profile.get("plot")
    _need(isinstance(plot, list) and len(plot) == 4 and all(_finite(v) for v in plot), f"invalid plot bounds for {chart['id']}")
    left, top, right, bottom = plot
    _need(0 <= left < right <= width and 0 <= top < bottom <= height, f"plot is outside image for {chart['id']}")
    ticks = profile.get("x_ticks")
    _need(isinstance(ticks, list) and ticks, f"x_ticks required for {chart['id']}")
    last = -1
    for tick in ticks:
        _need(isinstance(tick, dict) and _finite(tick.get("position")) and 0 <= tick["position"] <= 1 and _text(tick.get("label")), f"invalid x tick for {chart['id']}")
        _need(tick["position"] > last, f"x_ticks must be ordered for {chart['id']}")
        last = tick["position"]
    entries = profile.get("series")
    _need(isinstance(entries, list), f"digitized series required for {chart['id']}")
    known = {item["id"] for item in chart.get("series", []) + chart.get("unavailable_series", [])}
    mapping = {}
    for entry in entries:
        _need(isinstance(entry, dict) and _text(entry.get("id")) and _ID.fullmatch(entry["id"]), f"invalid digitized series id for {chart['id']}")
        _need(entry["id"] in known and entry["id"] not in mapping, f"unknown or duplicate digitized series {entry['id']}")
        mapping[entry["id"]] = entry
        if "forecast_from" in entry:
            _need(_finite(entry["forecast_from"]) and 0 <= entry["forecast_from"] <= 1, f"invalid forecast threshold: {entry['id']}")
        if entry.get("mode") == "unreadable":
            _need(_text(entry.get("note")), f"unreadable series requires note: {entry['id']}")
            continue
        _need(entry.get("mode") in _MODES, f"invalid digitization mode: {entry['id']}")
        axis = entry.get("y_axis")
        _need(isinstance(axis, dict) and _finite(axis.get("min")) and _finite(axis.get("max")) and axis["min"] < axis["max"], f"invalid y axis: {entry['id']}")
        _need(_finite(axis["max"] - axis["min"]), f"y axis span is not finite: {entry['id']}")
        _need(_finite(entry.get("estimated_error")) and entry["estimated_error"] > 0 and _text(entry.get("note")), f"invalid digitization accuracy: {entry['id']}")
        anchors = entry.get("anchors")
        _need(isinstance(anchors, list) and anchors, f"anchors required: {entry['id']}")
        prior_x = -1
        for anchor in anchors:
            size = 3 if entry["mode"] in {"stacked", "band"} else 2
            _need(isinstance(anchor, list) and len(anchor) == size and all(_finite(v) and 0 <= v <= 1 for v in anchor), f"invalid anchor: {entry['id']}")
            _need(anchor[0] >= prior_x, f"anchors must be x-ordered: {entry['id']}")
            _need(anchor[1] <= anchor[2] if size == 3 else True, f"invalid band anchor: {entry['id']}")
            if entry["mode"] == "stacked":
                zero_y = axis["max"] / (axis["max"] - axis["min"])
                _need(not anchor[1] < zero_y < anchor[2], f"stacked segment crosses zero: {entry['id']}")
            prior_x = anchor[0]
    return profile, mapping


def _digitized_points(entry):
    if entry is None or entry["mode"] == "unreadable":
        return []
    low, high = entry["y_axis"]["min"], entry["y_axis"]["max"]
    decimals = max(0, 1 - math.floor(math.log10(entry["estimated_error"])))
    result = []
    for anchor in entry["anchors"]:
        x = anchor[0]
        if len(anchor) == 3:
            top_value = high - anchor[1] * (high - low)
            bottom_value = high - anchor[2] * (high - low)
            if entry["mode"] == "stacked":
                zero_y = high / (high - low)
                sign = -1 if (anchor[1] + anchor[2]) / 2 > zero_y else 1
                result.append({"x": x, "value": round(sign * (anchor[2] - anchor[1]) * (high - low), decimals)})
            else:
                result.append({"x": x, "value_low": round(bottom_value, decimals), "value_high": round(top_value, decimals)})
        else:
            value = high - anchor[1] * (high - low)
            result.append({"x": x, "value": round(value, decimals)})
        if "forecast_from" in entry:
            result[-1]["forecast"] = x >= entry["forecast_from"]
    return result


def _svg(title, label, unit, x_axis, note, points, approximate, error, forecast_points, mode, profile_entry=None):
    esc = lambda value: html.escape(str(value), quote=True)
    title_text = ("Приблизительная оцифровка — " if approximate else "") + title + " — " + label
    styles = '<style>text{font-family:Arial,sans-serif;fill:#24363a}.title{font-size:18px;font-weight:600}.label,.value,.axis{font-size:12px}.grid{stroke:#d9e0e1;stroke-width:1}.approx{font-size:12px;fill:#2874b8}.forecast{fill:#d87918}</style>'
    wrapped = []
    line = ""
    for word in title_text.split():
        if line and len(line) + len(word) + 1 > 72:
            wrapped.append(line)
            line = word
        else:
            line = (line + " " + word).strip()
    if line:
        wrapped.append(line)
    visible_title = wrapped[:2]

    if approximate:
        width, height = 960, 500
        x0, x1, y0, y1 = 82, 930, 112, 390
        entry = profile_entry
        anchors = entry["anchors"]
        axis_min, axis_max = entry["y_axis"]["min"], entry["y_axis"]["max"]
        display_min, display_max = (min(0, axis_min), max(0, axis_max)) if mode in {"bar", "stacked"} else (axis_min, axis_max)
        if display_min == display_max:
            display_min, display_max = axis_min, axis_max
        def px_x(value): return x0 + value * (x1 - x0)
        def value_y(value): return y0 + (display_max - value) / (display_max - display_min) * (y1 - y0)
        body = [f'<title>{esc(title_text)}</title>', f'<desc>{esc(note or "Значения из отчёта")}</desc>']
        body.extend(f'<text x="24" y="{25 + i * 22}" class="title">{esc(t)}</text>' for i, t in enumerate(visible_title))
        body.append(f'<text x="{x0}" y="84" class="axis">{esc(label)} · {esc(unit)}</text>')
        for i in range(5):
            value = display_max - i * (display_max - display_min) / 4
            y = value_y(value)
            body.extend([f'<line x1="{x0}" y1="{y:.1f}" x2="{x1}" y2="{y:.1f}" class="grid"/>',
                         f'<text x="{x0-10}" y="{y+4:.1f}" text-anchor="end" class="label">{esc(_sig(value))}</text>'])
        if mode in {"line", "scatter", "band"}:
            if mode == "band":
                upper = " ".join(("M" if i == 0 else "L") + f"{px_x(p['x']):.1f},{value_y(p['value_high']):.1f}" for i, p in enumerate(points))
                lower = " ".join(f"L{px_x(p['x']):.1f},{value_y(p['value_low']):.1f}" for p in reversed(points))
                body.append(f'<path d="{upper} {lower} Z" fill="#2874b8" opacity=".28" stroke="#2874b8"/>')
            if mode == "line":
                for first, second in zip(points, points[1:]):
                    color = "#d87918" if second.get("forecast") else "#2874b8"
                    body.append(f'<line x1="{px_x(first["x"]):.1f}" y1="{value_y(first["value"]):.1f}" x2="{px_x(second["x"]):.1f}" y2="{value_y(second["value"]):.1f}" stroke="{color}" stroke-width="3"/>')
            for point in points:
                forecast = bool(point.get("forecast"))
                color = "#d87918" if forecast else "#2874b8"
                value = point["value_high"] if mode == "band" else point["value"]
                body.append(f'<circle cx="{px_x(point["x"]):.1f}" cy="{value_y(value):.1f}" r="4" fill="{color}"/>')
            if entry.get("forecast_from") is not None:
                body.append(f'<text x="{x1-60}" y="84" class="axis forecast">■ Прогноз</text>')
        else:
            spacing = min((b[0] - a[0] for a, b in zip(anchors, anchors[1:]) if b[0] > a[0]), default=0.08) * (x1 - x0)
            bar_width = max(4, min(28, spacing * .55))
            zero_y = value_y(0)
            for anchor, point in zip(anchors, points):
                forecast = bool(point.get("forecast"))
                color = "#d87918" if forecast else "#2874b8"
                y_value = value_y(point["value"])
                top, bottom = min(zero_y, y_value), max(zero_y, y_value)
                body.append(f'<rect class="approx-bar" x="{px_x(anchor[0])-bar_width/2:.1f}" y="{top:.1f}" width="{bar_width:.1f}" height="{max(0,bottom-top):.1f}" fill="{color}"/>')
            if entry.get("forecast_from") is not None:
                body.append(f'<text x="{x1-60}" y="84" class="axis forecast">■ Прогноз</text>')
        ticks = entry.get("_x_ticks", [])
        def label_box(tick):
            label_width = max(1, len(tick["label"])) * 7
            left = max(8, min(px_x(tick["position"]) - label_width / 2, width - label_width - 8))
            return left, left + label_width
        last_right = -math.inf
        final_left = label_box(ticks[-1])[0] if ticks else width
        for i, tick in enumerate(ticks):
            x = px_x(tick["position"])
            label_left, label_right = label_box(tick)
            # Keep the endpoint labels and omit crowded intermediate labels only.
            if 0 < i < len(ticks) - 1 and (label_left < last_right + 12 or label_right > final_left - 12):
                continue
            body.append(f'<line x1="{x:.1f}" y1="{y1}" x2="{x:.1f}" y2="{y1+5}" class="grid"/>')
            body.append(f'<text x="{label_left:.1f}" y="{y1+22}" class="label">{esc(tick["label"])}</text>')
            last_right = label_right
        body.extend([f'<text x="{(x0+x1)/2:.1f}" y="{y1+46}" text-anchor="middle" class="axis">{esc(x_axis.get("label", ""))}</text>',
                     f'<text x="24" y="{height-14}" class="approx">Оценка погрешности ±{esc(error)} {esc(unit)}; опорные точки</text>'])
        return (f'<svg xmlns="http://www.w3.org/2000/svg" role="img" viewBox="0 0 {width} {height}" preserveAspectRatio="xMidYMid meet">' + styles + "".join(body) + "</svg>").encode("utf-8")

    longest = max((len(str(p.get("x", ""))) for p in points), default=0)
    longest_value = max((len(str(p.get("value_high", p.get("value", p.get("value_low", ""))))) for p in points), default=0)
    left, plot_width, value_width = max(290, longest * 8 + 24), 640, max(110, longest_value * 8 + 20)
    right, top = left + plot_width, 88
    width, height = right + value_width + 20, max(210, top + 48 * len(points) + 52)
    values = [p.get("value", p.get("value_high", p.get("value_low", 0))) for p in points]
    lo, hi = min([0.0, *values]), max([0.0, *values])
    if lo == hi: lo, hi = lo - 1, hi + 1
    span = hi - lo
    baseline = left + (0 - lo) / span * plot_width
    body = [f'<title>{esc(title_text)}</title>', f'<desc>{esc(note or "Значения из отчёта")}</desc>']
    body.extend(f'<text x="24" y="{25 + i * 22}" class="title">{esc(t)}</text>' for i, t in enumerate(visible_title))
    body.extend([f'<text x="{left}" y="66" class="axis">Сравнение подписанных значений · {esc(unit)}</text>',
                 f'<line x1="{baseline:.1f}" y1="{top-8}" x2="{baseline:.1f}" y2="{height-40}" class="grid"/>'])
    if any(forecast_points): body.append(f'<text x="{right-85}" y="66" class="axis forecast">■ Прогноз</text>')
    for i, point in enumerate(points):
        y = top + i * 48
        x = left + (point.get("value", 0) - lo) / span * plot_width
        start, end = min(baseline, x), max(baseline, x)
        forecast = bool(forecast_points[i]) if i < len(forecast_points) else False
        color = "#d87918" if forecast else "#3b6268"
        body.append(f'<text x="{left-12}" y="{y+5}" text-anchor="end" class="label">{esc(point["x"])}</text>')
        if "value_low" in point:
            body.append((f'<rect x="{start:.1f}" y="{y-10}" width="{end-start:.1f}" height="20" rx="4" fill="{color}" opacity=".25"/>' if end > start else "") + f'<text x="{right+8}" y="{y+5}" class="value">{esc(point["value_low"])}–{esc(point["value_high"])}</text>')
        else:
            body.append((f'<rect x="{start:.1f}" y="{y-10}" width="{end-start:.1f}" height="20" rx="4" fill="{color}"/>' if end > start else "") + f'<text x="{right+8}" y="{y+5}" class="value">{esc(point.get("value", ""))}</text>')
    if approximate: body.append(f'<text x="24" y="{height-12}" class="approx">Оценка погрешности ±{esc(error)} {esc(unit)}; опорные точки</text>')
    return (f'<svg xmlns="http://www.w3.org/2000/svg" role="img" viewBox="0 0 {width} {height}" preserveAspectRatio="xMidYMid meet">' + styles + "".join(body) + "</svg>").encode("utf-8")


def build_series_exports(catalog):
    """Return safe relative paths mapped to UTF-8 JSON/SVG bytes."""
    _need(isinstance(catalog, dict) and catalog.get("schema_version") == 1, "catalog schema_version must be 1")
    documents = catalog.get("documents")
    charts = catalog.get("charts")
    _need(isinstance(documents, list) and isinstance(charts, list), "catalog requires documents and charts")
    docs = {doc.get("id"): doc for doc in documents if isinstance(doc, dict) and isinstance(doc.get("id"), str) and _ID.fullmatch(doc["id"])}
    _need(len(docs) == len(documents), "invalid or duplicate document id")
    exports, items, chart_ids = {}, [], set()
    for chart in charts:
        _need(isinstance(chart, dict) and isinstance(chart.get("id"), str) and _ID.fullmatch(chart["id"]), "invalid chart id")
        cid = chart["id"]
        _need(cid not in chart_ids, f"duplicate chart id: {cid}")
        chart_ids.add(cid)
        document = docs.get(chart.get("document_id"))
        _need(document is not None, f"unknown document for chart {cid}")
        _need(_text(chart.get("title")) and isinstance(chart.get("page"), int) and not isinstance(chart.get("page"), bool) and chart["page"] > 0, f"invalid chart source metadata for {cid}")
        _need(isinstance(chart.get("crop"), list) and len(chart["crop"]) == 4 and all(_finite(v) for v in chart["crop"]), f"invalid chart crop for {cid}")
        _need(isinstance(chart.get("x_axis"), dict), f"invalid x axis for {cid}")
        image_hash = chart.get("image_sha256")
        _need(isinstance(chart.get("image"), str) and chart["image"] == f"images/{cid}.jpg" and isinstance(image_hash, str) and _SHA.fullmatch(image_hash), f"unsafe or missing image metadata for {cid}")
        exact = chart.get("series", [])
        unavailable = chart.get("unavailable_series", [])
        _need(isinstance(exact, list) and isinstance(unavailable, list), f"invalid series list for {cid}")
        all_series, seen = [], set()
        for series, status in [(s, "labelled_values") for s in exact] + [(s, "unavailable") for s in unavailable]:
            _need(isinstance(series, dict) and isinstance(series.get("id"), str) and _ID.fullmatch(series["id"]), f"invalid series id for {cid}")
            sid = series["id"]
            _need(sid not in seen and _text(series.get("label")) and isinstance(series.get("unit"), str), f"invalid or duplicate series {sid}")
            seen.add(sid)
            points = series.get("points", [])
            if status == "labelled_values":
                _need(isinstance(points, list) and points, f"empty exact series {sid}")
                for point in points:
                    _need(isinstance(point, dict) and _text(point.get("label")) and _finite(point.get("value")) and ("forecast" not in point or isinstance(point["forecast"], bool)), f"invalid exact point in {sid}")
                point_values = [point["value"] for point in points]
                _need(_finite(max(point_values) - min(point_values)), f"exact series span is not finite: {sid}")
            all_series.append((series, status))
        profile, profiles = _validate_profile(chart)
        for sid in profiles:
            _need(sid in seen, f"unknown digitized series {sid}")
        for series, initial_status in all_series:
            sid = series["id"]
            profile_entry = profiles.get(sid)
            approximate = profile_entry is not None and profile_entry.get("mode") != "unreadable"
            status = "digitized" if approximate else initial_status
            exact_points = series.get("points", []) if initial_status == "labelled_values" else []
            ticks = profile.get("x_ticks", []) if profile else []
            points = _digitized_points(profile_entry) if approximate else [
                {"x": p["label"], "value": p["value"], "source_index": i, **({"forecast": p["forecast"]} if "forecast" in p else {})}
                for i, p in enumerate(exact_points)
            ]
            file_base = f"series/{cid}--{sid}"
            json_file = f"{file_base}.json"
            svg_file = f"{file_base}.svg" if points else None
            source = {"document": document, "chart_title": chart["title"], "page": chart["page"], "crop": chart["crop"], "image": chart["image"], "image_sha256": chart["image_sha256"]}
            saved_profile = {**profile, "series": [profile_entry]} if profile_entry is not None else None
            record = {
                "schema_version": 1, "id": f"{cid}--{sid}", "chart_id": cid, "series_id": sid,
                "label": series["label"], "unit": series["unit"], "data_status": status,
                "source": source, "x_axis": chart["x_axis"], "note": chart.get("note", ""),
                "exact_points": exact_points, "digitization": saved_profile,
                "points": points, "json_file": json_file, "svg_file": svg_file,
            }
            exports[json_file] = (json.dumps(record, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")
            if svg_file:
                forecasts = [bool(point.get("forecast")) for point in exact_points] if not approximate else []
                svg_profile = {**profile_entry, "_x_ticks": ticks} if approximate else None
                exports[svg_file] = _svg(chart["title"], series["label"], series["unit"], chart["x_axis"], profile_entry.get("note") if approximate else chart.get("note", ""), points, approximate, profile_entry["estimated_error"] if approximate else None, forecasts, profile_entry.get("mode") if approximate else "bar", svg_profile)
            items.append({"id": record["id"], "chart_id": cid, "series_id": sid, "label": series["label"], "unit": series["unit"], "data_status": status, "json_file": json_file, "svg_file": svg_file})
    exports["series-index.json"] = (json.dumps({"schema_version": 1, "items": items}, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    return exports
