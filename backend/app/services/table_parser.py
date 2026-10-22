"""Messy spreadsheet parsing: multi-table / multi-sheet detection and hierarchy extraction."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from typing import Any

import pandas as pd

from app.services.storage import prepare_dataframe


DOC_SHEET_NAMES = {
    "readme",
    "read me",
    "notes",
    "note",
    "说明",
    "文档",
    "changelog",
    "version",
    "about",
    "metadata",
}


@dataclass
class TableRegion:
    id: str
    name: str
    sheet_name: str
    row_start: int
    row_end: int
    col_start: int
    col_end: int
    header_rows: list[int] = field(default_factory=list)
    columns: list[dict[str, Any]] = field(default_factory=list)
    hierarchy: dict[str, Any] = field(default_factory=dict)
    sample_rows: list[dict[str, Any]] = field(default_factory=list)
    row_count: int = 0
    dataframe: pd.DataFrame | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


def _is_empty_row(row: pd.Series) -> bool:
    return row.isna().all() or (row.astype(str).str.strip() == "").all()


def _is_empty_col(series: pd.Series) -> bool:
    return series.isna().all() or (series.astype(str).str.strip() == "").all()


def _row_density(row: pd.Series) -> float:
    values = row.dropna().astype(str).str.strip()
    values = values[values != ""]
    return len(values) / max(len(row), 1)


def _non_empty_count(row: pd.Series) -> int:
    values = row.dropna().astype(str).str.strip()
    return int((values != "").sum())


def _is_doc_sheet(sheet_name: str, raw: pd.DataFrame) -> bool:
    name = sheet_name.strip().lower()
    if name in DOC_SHEET_NAMES or name.startswith("readme"):
        return True
    if raw.empty:
        return True
    # Mostly long text paragraphs, few columns → documentation
    if raw.shape[1] <= 3 and raw.shape[0] >= 3:
        sample = raw.head(15).astype(str).fillna("")
        long_cells = 0
        total = 0
        for v in sample.to_numpy().ravel():
            text = str(v).strip()
            if not text or text.lower() == "nan":
                continue
            total += 1
            if len(text) > 80:
                long_cells += 1
        if total and long_cells / total >= 0.45:
            return True
    return False


def _find_header_rows(block: pd.DataFrame, max_scan: int = 12) -> list[int]:
    """Find real header rows, skipping title banners like 'Emissions in thousands of tons'."""
    if block.empty:
        return [0]

    scan = min(max_scan, len(block))
    # Title rows: very sparse (1-2 cells) or density < 0.25
    start = 0
    while start < scan and (
        _non_empty_count(block.iloc[start]) <= 2 or _row_density(block.iloc[start]) < 0.25
    ):
        # but don't skip if this looks like a compact header of a tiny table
        if _non_empty_count(block.iloc[start]) >= 2 and block.shape[1] <= 4:
            break
        start += 1
        if start >= scan:
            start = 0
            break

    header_rows: list[int] = []
    for i in range(start, scan):
        row = block.iloc[i]
        non_empty = row.dropna().astype(str).str.strip()
        non_empty = non_empty[non_empty != ""]
        if len(non_empty) == 0:
            if header_rows:
                break
            continue
        numeric_ratio = sum(
            bool(re.match(r"^-?\d+(\.\d+)?$", str(v).replace(",", ""))) for v in non_empty
        ) / len(non_empty)
        # A data row is mostly numeric; header is mostly labels
        if numeric_ratio < 0.55:
            header_rows.append(i)
            # Single strong header row is enough when next row is data-like
            if i + 1 < len(block):
                nxt = block.iloc[i + 1].dropna().astype(str).str.strip()
                nxt = nxt[nxt != ""]
                if len(nxt):
                    nxt_num = sum(
                        bool(re.match(r"^-?\d+(\.\d+)?$", str(v).replace(",", ""))) for v in nxt
                    ) / len(nxt)
                    if nxt_num >= 0.4 and len(header_rows) >= 1:
                        break
        else:
            break

    return header_rows or [start]


def _build_hierarchy(header_block: pd.DataFrame) -> dict[str, Any]:
    if header_block.empty:
        return {"levels": 0, "columns": []}

    filled = header_block.copy().astype(object)
    for col in filled.columns:
        last = None
        for idx in filled.index:
            val = filled.at[idx, col]
            text = _normalize_header_label(val) if pd.notna(val) else ""
            text = text if text and text.lower() != "nan" else None
            if text:
                last = text
                filled.at[idx, col] = text
            elif last:
                filled.at[idx, col] = last

    levels = len(filled)
    columns: list[dict[str, Any]] = []
    for col_idx, col in enumerate(filled.columns):
        path = []
        for row_idx in filled.index:
            val = filled.at[row_idx, col]
            if pd.notna(val) and str(val).strip() and str(val).strip().lower() != "nan":
                path.append(str(val).strip())
        # Prefer leaf (last) for display when path is multi-level title pollution
        path = [_normalize_header_label(p) for p in path if _normalize_header_label(p)]
        leaf = path[-1] if path else f"col_{col_idx}"
        display = leaf if levels == 1 else (" / ".join(path) if path else leaf)
        columns.append(
            {
                "index": col_idx,
                "path": path,
                "leaf": leaf,
                "display_name": display,
            }
        )
    return {"levels": levels, "columns": columns}


def _flatten_columns(header_rows: list[int], block: pd.DataFrame) -> tuple[list[str], dict[str, Any]]:
    if not header_rows:
        return [f"col_{i}" for i in range(block.shape[1])], {"levels": 0, "columns": []}

    header_block = block.iloc[header_rows].reset_index(drop=True)
    hierarchy = _build_hierarchy(header_block)
    names: list[str] = []
    used: dict[str, int] = {}
    for item in hierarchy["columns"]:
        # Prefer leaf name for wide emission tables (emissions2004)
        name = item["leaf"] if re.search(r"(19|20)\d{2}", item["leaf"]) else item["display_name"]
        if name in used:
            used[name] += 1
            name = f"{name}_{used[name]}"
        else:
            used[name] = 0
        names.append(name)
        item["display_name"] = name
    return names, hierarchy


def _normalize_header_label(value: Any) -> str:
    """Normalize Excel headers like 2004.0 / '1970' into stable labels."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if float(value).is_integer():
            iv = int(value)
            if 1900 <= iv <= 2100:
                return str(iv)
        return str(value).rstrip("0").rstrip(".") if isinstance(value, float) else str(value)
    text = str(value).strip()
    if re.fullmatch(r"(19|20)\d{2}\.0+", text):
        return text.split(".", 1)[0]
    return text


def _extract_year_columns(columns: list[str]) -> list[int]:
    years = []
    for c in columns:
        m = re.search(r"(19|20)\d{2}", str(c))
        if m:
            years.append(int(m.group(0)))
    return sorted(set(years))


def _split_block_into_tables(block: pd.DataFrame, sheet_name: str, base_name: str) -> list[TableRegion]:
    if block.empty:
        return []

    empty_cols = [_is_empty_col(block.iloc[:, c]) for c in range(block.shape[1])]
    segments: list[tuple[int, int]] = []
    start = None
    for idx, is_empty in enumerate(empty_cols):
        if not is_empty and start is None:
            start = idx
        elif is_empty and start is not None:
            segments.append((start, idx - 1))
            start = None
    if start is not None:
        segments.append((start, block.shape[1] - 1))
    if not segments:
        segments = [(0, block.shape[1] - 1)]

    regions: list[TableRegion] = []
    for seg_idx, (c0, c1) in enumerate(segments):
        sub = block.iloc[:, c0 : c1 + 1].copy()
        sub = sub.dropna(how="all").dropna(axis=1, how="all")
        if sub.empty or sub.shape[0] < 2:
            continue

        header_rows = _find_header_rows(sub)
        col_names, hierarchy = _flatten_columns(header_rows, sub)
        data_start = max(header_rows) + 1 if header_rows else 1
        data = sub.iloc[data_start:].copy()
        data.columns = col_names[: data.shape[1]]
        data = data.dropna(how="all")
        if data.empty:
            continue

        data = prepare_dataframe(data.reset_index(drop=True))
        sample = data.head(5).fillna("").astype(str).to_dict(orient="records")
        columns = [
            {
                "name": name,
                "path": hierarchy["columns"][i]["path"] if i < len(hierarchy["columns"]) else [name],
                "dtype": str(data[name].dtype),
                "year": (re.search(r"(19|20)\d{2}", name).group(0) if re.search(r"(19|20)\d{2}", name) else None),
            }
            for i, name in enumerate(data.columns)
        ]
        year_cols = _extract_year_columns([c["name"] for c in columns])
        region_name = base_name if len(segments) == 1 else f"{base_name}_part{seg_idx + 1}"

        try:
            row_start = int(sub.index[0])
            row_end = int(sub.index[-1])
        except Exception:
            row_start, row_end = 0, sub.shape[0]

        regions.append(
            TableRegion(
                id=str(uuid.uuid4()),
                name=region_name,
                sheet_name=sheet_name,
                row_start=row_start,
                row_end=row_end,
                col_start=c0,
                col_end=c1,
                header_rows=header_rows,
                columns=columns,
                hierarchy=hierarchy,
                sample_rows=sample,
                row_count=len(data),
                dataframe=data,
                metadata={
                    "source_rows": [int(i) + 1 for i in sub.iloc[data_start:].dropna(how="all").index],
                    "source_columns": [int(i) + 1 for i in sub.columns],
                    "density": float(_row_density(sub.iloc[header_rows[0]])),
                    "year_columns": year_cols,
                    "wide_year_format": len(year_cols) >= 2,
                    "title_skipped": header_rows[0] > 0,
                    "pollutant_hint": _pollutant_from_sheet(sheet_name),
                    "quality_score": _region_quality_score(len(data), year_cols, columns),
                },
            )
        )
    return regions


def _pollutant_from_sheet(sheet_name: str) -> str | None:
    name = sheet_name.strip().lower().replace(" ", "").replace("_", "").replace("-", "")
    mapping = {
        "co": "co",
        "carbonmonoxide": "co",
        "nox": "nox",
        "so2": "so2",
        "voc": "voc",
        "nh3": "nh3",
        "pm10": "pm10",
        "pm10primary": "pm10",
        "pm25": "pm25",
        "pm25primary": "pm25",
        "pm2.5": "pm25",
        "blackcarbon": "bc",
        "organiccarbon": "oc",
    }
    return mapping.get(name)


def _region_quality_score(row_count: int, year_cols: list[int], columns: list[dict[str, Any]]) -> float:
    """Prefer real data blocks over footnote/notes fragments."""
    score = float(row_count)
    if len(year_cols) >= 5:
        score += 50 + len(year_cols)
        # consecutive years are a strong signal
        span = max(year_cols) - min(year_cols) if year_cols else 0
        if span >= 10:
            score += 30
    elif len(year_cols) >= 2:
        score += 10
    else:
        score -= 20
    # Footnote-like: few rows but many bogus far-future years
    if row_count <= 5 and any(y > 2030 or y < 1950 for y in year_cols):
        score -= 80
    # Need at least one label-like first column
    if columns:
        first = str(columns[0]["name"]).lower()
        if any(k in first for k in ["source", "category", "sector", "state", "industry", "来源", "行业"]):
            score += 20
    return score


def _split_sheet(raw: pd.DataFrame, sheet_name: str) -> list[TableRegion]:
    if raw.empty:
        return []

    empty_rows = raw.replace(r"^\s*$", pd.NA, regex=True).isna().all(axis=1).tolist()
    blocks: list[pd.DataFrame] = []
    start = None
    for idx, is_empty in enumerate(empty_rows):
        if not is_empty and start is None:
            start = idx
        elif is_empty and start is not None:
            # Only split on 2+ consecutive empty rows for large sheets to avoid over-splitting
            blocks.append(raw.iloc[start:idx].copy())
            start = None
    if start is not None:
        blocks.append(raw.iloc[start:].copy())

    # A blank spacer before numeric records continues the preceding table.
    merged = []
    for block in blocks:
        first = block.iloc[0].dropna().tolist()
        numeric = sum(isinstance(v, (int, float)) for v in first)
        if merged and numeric >= max(1, len(first) * 0.5):
            merged[-1] = pd.concat([merged[-1], block])
        else:
            merged.append(block)
    blocks = merged

    regions: list[TableRegion] = []
    for block_idx, block in enumerate(blocks):
        block = block.dropna(how="all")
        if block.empty:
            continue
        base_name = sheet_name if len(blocks) == 1 else f"{sheet_name}_block{block_idx + 1}"
        regions.extend(_split_block_into_tables(block, sheet_name, base_name))
    return regions


def parse_uploaded_file(content: bytes, filename: str) -> list[TableRegion]:
    """Parse CSV/XLS/XLSX and return detected table regions across sheets."""
    suffix = Path(filename).suffix.lower()
    regions: list[TableRegion] = []
    skipped_sheets: list[str] = []

    if suffix == ".csv":
        for encoding in ("utf-8-sig", "utf-8", "gbk", "latin-1"):
            try:
                raw = pd.read_csv(BytesIO(content), header=None, encoding=encoding)
                break
            except UnicodeDecodeError:
                continue
        else:
            raw = pd.read_csv(BytesIO(content), header=None)
        regions.extend(_split_sheet(raw, Path(filename).stem))
    elif suffix in {".xlsx", ".xls"}:
        excel = pd.ExcelFile(BytesIO(content))
        for sheet in excel.sheet_names:
            raw = pd.read_excel(excel, sheet_name=sheet, header=None)
            if _is_doc_sheet(sheet, raw):
                skipped_sheets.append(sheet)
                continue
            if raw.empty or (raw.shape[0] * raw.shape[1] == 0):
                skipped_sheets.append(sheet)
                continue
            sheet_regions = _split_sheet(raw, sheet)
            regions.extend(sheet_regions)
    else:
        raise ValueError(f"不支持的文件格式: {suffix}")

    for idx, region in enumerate(regions):
        if region.name == region.sheet_name and len(regions) > 1:
            region.name = f"{region.sheet_name}_table{idx + 1}"
        region.metadata["skipped_sheets"] = skipped_sheets

    return regions


def _filter_regions(regions: list[TableRegion]) -> list[TableRegion]:
    if not regions:
        return regions

    by_sheet: dict[str, list[TableRegion]] = {}
    for r in regions:
        by_sheet.setdefault(r.sheet_name, []).append(r)

    kept: list[TableRegion] = []
    for sheet, items in by_sheet.items():
        ranked = sorted(items, key=lambda r: r.metadata.get("quality_score", 0), reverse=True)
        best_score = ranked[0].metadata.get("quality_score", 0)
        # Keep top region and any near-equal high-quality blocks (side-by-side tables)
        for r in ranked:
            score = r.metadata.get("quality_score", 0)
            years = r.metadata.get("year_columns") or []
            if r is ranked[0]:
                kept.append(r)
                continue
            if score >= best_score * 0.85 and len(years) >= 5 and r.row_count >= 5:
                kept.append(r)
            # also keep explicitly separate side-by-side parts with good years
            elif "_part" in r.name and len(years) >= 5 and r.row_count >= 5:
                kept.append(r)
    return kept or regions


def generate_upload_questions(regions: list[TableRegion], user_description: str) -> list[dict[str, Any]]:
    """Generate Q&A prompts after upload. Keep manageable even for large/multi-sheet files."""
    questions: list[dict[str, Any]] = [
        {
            "id": "dataset_purpose",
            "table_id": None,
            "question_type": "general",
            "question": "请简要说明这批数据的来源、主题和主要用途是什么？",
            "required": True,
            "prefill": user_description,
        },
        {
            "id": "time_range",
            "table_id": None,
            "question_type": "general",
            "question": "这些数据覆盖的时间范围或统计年份是什么？（例如 2002-2022）",
            "required": True,
            "prefill": _suggest_year_range(regions),
        },
        {
            "id": "geo_granularity",
            "table_id": None,
            "question_type": "general",
            "question": "数据的地理/组织粒度是什么？（例如：美国州级、部门/行业明细）",
            "required": True,
            "prefill": "美国州级 + 行业/部门明细" if any(_looks_like_state_table(r) for r in regions) else "",
        },
        {
            "id": "statistical_caliber",
            "table_id": None,
            "question_type": "general",
            "question": "是否存在需要特别注意的统计口径、单位或不可直接比较的情况？（如千吨、NEI 口径）",
            "required": False,
            "prefill": "单位可能为千吨（thousands of tons）" if any("emission" in str(r.columns).lower() for r in regions) else "",
        },
        {
            "id": "wide_year_confirm",
            "table_id": None,
            "question_type": "general",
            "question": "年份是否以宽表列名形式出现（如 emissions2004）？若是，请确认查询时应按列名取年份。",
            "required": False,
            "prefill": "是，年份在列名中（emissionsYYYY）" if any(r.metadata.get("wide_year_format") for r in regions) else "",
        },
    ]

    # Limit table-specific questions to avoid overwhelming users on large uploads
    ranked = sorted(regions, key=lambda r: r.row_count, reverse=True)
    for region in ranked[:5]:
        col_preview = ", ".join(c["name"] for c in region.columns[:10])
        years = region.metadata.get("year_columns") or []
        year_hint = f"，检测到年份列：{years[0]}-{years[-1]}" if len(years) >= 2 else ""
        questions.append(
            {
                "id": f"{region.id}_meaning",
                "table_id": region.id,
                "question_type": "table",
                "question": (
                    f"系统识别到子表「{region.name}」（工作表: {region.sheet_name}，"
                    f"约 {region.row_count} 行{year_hint}）。请描述这张表的含义。"
                ),
                "required": True,
                "context": {"columns": col_preview, "sheet": region.sheet_name},
            }
        )
        questions.append(
            {
                "id": f"{region.id}_key_columns",
                "table_id": region.id,
                "question_type": "table",
                "question": (
                    f"在子表「{region.name}」中，哪些字段代表地区/对象？哪些代表污染物？"
                    f"数值字段如何对应年份？"
                ),
                "required": True,
                "context": {"columns": col_preview},
                "prefill": _suggest_key_columns(region),
            }
        )

    if len(regions) > 5:
        questions.append(
            {
                "id": "extra_tables_note",
                "table_id": None,
                "question_type": "general",
                "question": f"另外还识别到 {len(regions) - 5} 张子表未逐一提问。请补充它们是否与主表同类、有何差异。",
                "required": False,
            }
        )

    skipped = regions[0].metadata.get("skipped_sheets") if regions else []
    if skipped:
        questions.append(
            {
                "id": "skipped_sheets",
                "table_id": None,
                "question_type": "general",
                "question": f"系统跳过了可能为说明文档的工作表：{', '.join(skipped)}。这些表是否包含关键约束信息？",
                "required": False,
                "prefill": "README 等为说明文档，可不参与数值查询",
            }
        )

    return questions


def _suggest_year_range(regions: list[TableRegion]) -> str:
    years: list[int] = []
    for r in regions:
        years.extend(r.metadata.get("year_columns") or [])
    years = sorted(set(years))
    if len(years) >= 2:
        return f"{years[0]}-{years[-1]}"
    if len(years) == 1:
        return str(years[0])
    return ""


def _looks_like_state_table(region: TableRegion) -> bool:
    names = " ".join(c["name"].lower() for c in region.columns)
    return "state" in names or "州" in names


def _suggest_key_columns(region: TableRegion) -> str:
    names = [c["name"] for c in region.columns]
    lower = {n.lower(): n for n in names}
    parts = []
    for key in ["state", "region", "州"]:
        hit = next((lower[k] for k in lower if key in k and "fips" not in k), None)
        if hit:
            parts.append(f"地区字段：{hit}")
            break
    for key in ["pollutant", "污染物"]:
        hit = next((lower[k] for k in lower if key in k), None)
        if hit:
            parts.append(f"污染物字段：{hit}")
            break
    years = region.metadata.get("year_columns") or []
    if years:
        parts.append(f"年份在宽表列名中：emissions{years[0]} … emissions{years[-1]}")
    return "；".join(parts)
