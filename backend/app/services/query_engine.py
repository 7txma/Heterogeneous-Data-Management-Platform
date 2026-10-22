"""Natural language query over registered messy tables with source attribution."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

import httpx
import pandas as pd

from app.config import settings


@dataclass
class QueryHit:
    table_id: str
    table_name: str
    sheet_name: str
    column: str
    value: Any
    row_index: int
    matched_region: str
    evidence: dict[str, Any]
    score: float = 0.0
    year: int | None = None
    aggregation: str | None = None


@dataclass
class QueryResult:
    answer: str
    value: Any | None
    unit: str | None
    hits: list[QueryHit]
    reasoning: str
    sql_equivalent: str | None = None


# Full US state aliases: full name / Chinese / abbreviation
US_STATE_ALIASES: dict[str, list[str]] = {
    "alabama": ["alabama", "阿拉巴马", "al"],
    "alaska": ["alaska", "阿拉斯加州", "阿拉斯加", "ak"],
    "arizona": ["arizona", "亚利桑那", "az"],
    "arkansas": ["arkansas", "阿肯色", "ar"],
    "california": ["california", "加利福尼亚", "加州", "ca"],
    "colorado": ["colorado", "科罗拉多", "co"],
    "connecticut": ["connecticut", "康涅狄格", "ct"],
    "delaware": ["delaware", "特拉华", "de"],
    "florida": ["florida", "佛罗里达", "fl"],
    "georgia": ["georgia", "佐治亚", "乔治亚", "ga"],
    "hawaii": ["hawaii", "夏威夷", "hi"],
    "idaho": ["idaho", "爱达荷", "id"],
    "illinois": ["illinois", "伊利诺伊", "il"],
    "indiana": ["indiana", "印第安纳", "in"],
    "iowa": ["iowa", "爱荷华", "ia"],
    "kansas": ["kansas", "堪萨斯", "ks"],
    "kentucky": ["kentucky", "肯塔基", "ky"],
    "louisiana": ["louisiana", "路易斯安那", "la"],
    "maine": ["maine", "缅因", "me"],
    "maryland": ["maryland", "马里兰", "md"],
    "massachusetts": ["massachusetts", "马萨诸塞", "麻省", "ma"],
    "michigan": ["michigan", "密歇根", "mi"],
    "minnesota": ["minnesota", "明尼苏达", "mn"],
    "mississippi": ["mississippi", "密西西比", "ms"],
    "missouri": ["missouri", "密苏里", "mo"],
    "montana": ["montana", "蒙大拿", "mt"],
    "nebraska": ["nebraska", "内布拉斯加", "ne"],
    "nevada": ["nevada", "内华达", "nv"],
    "new hampshire": ["new hampshire", "新罕布什尔", "nh"],
    "new jersey": ["new jersey", "新泽西", "nj"],
    "new mexico": ["new mexico", "新墨西哥", "nm"],
    "new york": ["new york", "纽约", "ny"],
    "north carolina": ["north carolina", "北卡罗来纳", "nc"],
    "north dakota": ["north dakota", "北达科他", "nd"],
    "ohio": ["ohio", "俄亥俄", "oh"],
    "oklahoma": ["oklahoma", "俄克拉荷马", "ok"],
    "oregon": ["oregon", "俄勒冈", "or"],
    "pennsylvania": ["pennsylvania", "宾夕法尼亚", "pa"],
    "rhode island": ["rhode island", "罗得岛", "ri"],
    "south carolina": ["south carolina", "南卡罗来纳", "sc"],
    "south dakota": ["south dakota", "南达科他", "sd"],
    "tennessee": ["tennessee", "田纳西", "tn"],
    "texas": ["texas", "德克萨斯", "德州", "tx"],
    "utah": ["utah", "犹他", "ut"],
    "vermont": ["vermont", "佛蒙特", "vt"],
    "virginia": ["virginia", "弗吉尼亚", "va"],
    "washington": ["washington", "华盛顿州", "wa"],
    "west virginia": ["west virginia", "西弗吉尼亚", "wv"],
    "wisconsin": ["wisconsin", "威斯康星", "wi"],
    "wyoming": ["wyoming", "怀俄明", "wy"],
    "district of columbia": ["district of columbia", "华盛顿特区", "dc"],
}

STATE_ABBR_TO_CANONICAL = {
    a.upper(): canon
    for canon, aliases in US_STATE_ALIASES.items()
    for a in aliases
    if len(a) == 2 and a.isalpha()
}


def _normalize(text: str) -> str:
    return re.sub(r"\s+", "", str(text).lower())


def _extract_metric(question: str) -> str | None:
    q = question.lower()
    mapping = [
        ("nox", ["nox", "noₓ", "氮氧化物", "nitrogen oxide"]),
        ("so2", ["so2", "so₂", "二氧化硫"]),
        ("co2", ["co2", "co₂", "二氧化碳"]),
        ("co", ["一氧化碳", " carbon monoxide", " pollutant co", "污染物co"]),
        ("pm25", ["pm2.5", "pm25", "细颗粒物"]),
        ("pm10", ["pm10", "可吸入颗粒物"]),
        ("voc", ["voc", "挥发性有机"]),
        ("nh3", ["nh3", "氨"]),
    ]
    # special: bare "co" is ambiguous; require clearer signals
    for metric, keys in mapping:
        for key in keys:
            if key in q:
                if metric == "co" and ("nox" in q or "co2" in q or "voc" in q):
                    continue
                return metric
    if re.search(r"(?<![a-z])co(?![a-z0-9])", q) and "nox" not in q:
        return "co"
    return None


def _extract_year(question: str) -> int | None:
    # Prefer 19xx / 20xx near 年 or alone
    patterns = [
        r"(19|20)\d{2}\s*年",
        r"年[份度]?\s*(19|20)\d{2}",
        r"(?<!\d)((?:19|20)\d{2})(?!\d)",
    ]
    for pat in patterns:
        m = re.search(pat, question)
        if not m:
            continue
        digits = re.search(r"(19|20)\d{2}", m.group(0))
        if digits:
            year = int(digits.group(0))
            if 1900 <= year <= 2100:
                return year
    return None


def _extract_location(question: str) -> tuple[str | None, list[str]]:
    q_norm = _normalize(question)
    q_raw = question.lower()

    # Prefer longer aliases first to avoid short abbr false positives in Chinese text
    ranked: list[tuple[str, str]] = []
    for canonical, aliases in US_STATE_ALIASES.items():
        for alias in aliases:
            ranked.append((canonical, alias))
    ranked.sort(key=lambda x: len(x[1]), reverse=True)

    for canonical, alias in ranked:
        a = _normalize(alias)
        if len(alias) == 2 and alias.isalpha():
            # abbreviation: word boundary style
            if re.search(rf"(?<![a-z]){re.escape(alias.lower())}(?![a-z])", q_raw):
                return canonical, US_STATE_ALIASES[canonical]
        elif a and a in q_norm:
            return canonical, US_STATE_ALIASES[canonical]
    return None, []


def _year_from_column(col_name: str) -> int | None:
    text = str(col_name)
    m = re.search(r"(19|20)\d{2}", text)
    if not m:
        return None
    year = int(m.group(0))
    return year if 1900 <= year <= 2100 else None


def _is_year_column(col_name: str) -> bool:
    name = _normalize(col_name)
    if name in {"year", "年份", "年度", "yr"}:
        return True
    return bool(re.fullmatch(r"(year|yr|年份|年度)?(19|20)\d{2}", name))


def _is_emission_value_column(col_name: str) -> bool:
    name = _normalize(col_name)
    year = _year_from_column(col_name)
    keys = ["emission", "排放", "amount", "value", "total", "qty", "quantity"]
    if any(k in name for k in keys):
        return True
    # bare year columns like 2004 / 2004.0 used as values in wide tables
    if year is not None:
        if re.fullmatch(r"(19|20)\d{2}(?:\.0+)?", name):
            return True
        if re.fullmatch(rf"(emissions?|year|yr)?{year}(?:\.0+)?", name):
            return True
    return False


def _column_matches_metric(col_name: str, metric: str | None) -> bool:
    if not metric:
        return False
    name = _normalize(col_name)
    if metric == "nox":
        return "nox" in name or "氮氧化物" in name or "nitrogenoxide" in name
    if metric == "so2":
        return "so2" in name or "二氧化硫" in name
    if metric == "co2":
        return "co2" in name or "二氧化碳" in name
    if metric == "co":
        return name in {"co", "一氧化碳"} or "carbonmonoxide" in name or name.endswith("/co")
    if metric == "pm25":
        return "pm2.5" in name or "pm25" in name
    if metric == "pm10":
        return "pm10" in name
    return metric in name


def _column_matches_location(col_name: str) -> bool:
    name = _normalize(col_name)
    keys = ["state", "region", "area", "location", "geo", "州", "地区", "区域", "province", "省市"]
    # avoid matching "statement" etc. lightly
    return any(k in name for k in keys) and "fips" not in name


def _column_matches_pollutant(col_name: str) -> bool:
    name = _normalize(col_name)
    return any(k in name for k in ["pollutant", "污染物", "species", "化学物"])


def _pollutant_from_name(name: str) -> str | None:
    text = _normalize(name).replace("_", "").replace("-", "")
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
        "blackcarbon": "bc",
        "organiccarbon": "oc",
    }
    for key, metric in mapping.items():
        if key in text:
            return metric
    return None


def _cell_matches_location(cell: Any, canonical: str | None, aliases: list[str]) -> bool:
    if cell is None or (isinstance(cell, float) and pd.isna(cell)):
        return False
    text = str(cell).strip()
    if not text:
        return False
    upper = text.upper()
    if len(text) == 2 and upper in STATE_ABBR_TO_CANONICAL:
        return STATE_ABBR_TO_CANONICAL[upper] == canonical
    norm = _normalize(text)
    return any(_normalize(a) == norm or _normalize(a) in norm for a in aliases if len(a) > 2) or any(
        _normalize(a) == norm for a in aliases
    )


def _cell_matches_metric(cell: Any, metric: str | None) -> bool:
    if not metric:
        return True
    text = _normalize(str(cell))
    if metric == "nox":
        return text in {"nox", "noₓ"} or "nitrogenoxide" in text or "氮氧化物" in text
    if metric == "co":
        return text in {"co", "一氧化碳"} or "carbonmonoxide" in text
    return metric in text


def _to_number(value: Any) -> float | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value).strip().replace(",", "").replace(" ", "")
    if not text or text.lower() in {"nan", "none", "-", "—"}:
        return None
    m = re.search(r"-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?", text)
    return float(m.group()) if m else None


def _pick_value_columns(df: pd.DataFrame, year: int | None, metric: str | None) -> list[str]:
    cols = [str(c) for c in df.columns]
    year_cols = [c for c in cols if _year_from_column(c) is not None and _is_emission_value_column(c)]
    metric_named = [c for c in cols if _column_matches_metric(c, metric)]

    if year is not None:
        exact = [c for c in cols if _year_from_column(c) == year and (_is_emission_value_column(c) or c in metric_named)]
        if exact:
            return exact
        # long format: Year column + metric/value column
        return []

    if metric_named:
        return metric_named
    if year_cols:
        return year_cols
    return [c for c in cols if _is_emission_value_column(c)]


def _filter_mask(
    df: pd.DataFrame,
    location: str | None,
    aliases: list[str],
    metric: str | None,
    year: int | None,
) -> pd.Series:
    mask = pd.Series(True, index=df.index)

    loc_cols = [c for c in df.columns if _column_matches_location(str(c))]
    if location and loc_cols:
        loc_ok = pd.Series(False, index=df.index)
        for lc in loc_cols:
            loc_ok = loc_ok | df[lc].map(lambda v: _cell_matches_location(v, location, aliases))
        mask &= loc_ok

    pol_cols = [c for c in df.columns if _column_matches_pollutant(str(c))]
    if metric and pol_cols:
        pol_ok = pd.Series(False, index=df.index)
        for pc in pol_cols:
            pol_ok = pol_ok | df[pc].map(lambda v: _cell_matches_metric(v, metric))
        mask &= pol_ok

    year_cols = [c for c in df.columns if _is_year_column(str(c)) and _year_from_column(str(c)) is None]
    # columns literally named Year / 年份
    year_cols = [c for c in df.columns if _normalize(str(c)) in {"year", "年份", "年度", "yr"}]
    if year is not None and year_cols:
        y_ok = pd.Series(False, index=df.index)
        for yc in year_cols:
            y_ok = y_ok | df[yc].map(lambda v: _to_number(v) == float(year) or str(v).strip() == str(year))
        mask &= y_ok

    return mask


def query_tables_rule_based(
    question: str,
    tables: list[dict[str, Any]],
    qa_context: list[dict[str, str]] | None = None,
) -> QueryResult:
    metric = _extract_metric(question)
    year = _extract_year(question)
    location, aliases = _extract_location(question)
    hits: list[QueryHit] = []
    notes: list[str] = []

    notes.append(f"解析意图：地区={location or '未指定'}，指标={metric or '未指定'}，年份={year or '未指定'}")

    for table in tables:
        df: pd.DataFrame = table["dataframe"]
        if df is None or df.empty:
            continue
        table_id = table["id"]
        table_name = table["name"]
        sheet_name = table.get("sheet_name", "")
        meta = table.get("metadata") or table.get("metadata_json") or {}
        pollutant_hint = (meta.get("pollutant_hint") if isinstance(meta, dict) else None) or _pollutant_from_name(
            sheet_name
        )

        # Skip obvious documentation tables
        if str(sheet_name).lower() in {"readme", "read me", "notes", "说明"}:
            continue

        # If sheets are split by pollutant (CO/NOX/SO2...), skip unrelated sheets
        if metric and pollutant_hint and pollutant_hint != metric:
            # allow BC/OC only when asked
            continue

        if location and not any(_column_matches_location(str(c)) for c in df.columns):
            continue

        value_cols = _pick_value_columns(df, year, metric)
        long_year_cols = [c for c in df.columns if _normalize(str(c)) in {"year", "年份", "年度", "yr"}]

        # Wide format with year in column names
        if year is not None and not value_cols and not long_year_cols:
            notes.append(f"表 {table_name} 未找到年份列 {year}")
            continue

        if year is not None and not value_cols and long_year_cols:
            # long format: filter year rows, pick metric/emission columns
            value_cols = [
                c
                for c in df.columns
                if _column_matches_metric(str(c), metric) or _is_emission_value_column(str(c))
            ]
            value_cols = [c for c in value_cols if c not in long_year_cols]

        if not value_cols:
            # fallback: any emission-like columns
            value_cols = [c for c in df.columns if _is_emission_value_column(str(c))]
            if year is not None:
                value_cols = [c for c in value_cols if _year_from_column(str(c)) == year]
            if not value_cols:
                continue

        mask = _filter_mask(df, location, aliases, metric, year if long_year_cols else None)
        filtered = df[mask]
        if filtered.empty:
            continue

        for vcol in value_cols:
            col_year = _year_from_column(str(vcol))
            if year is not None and col_year is not None and col_year != year:
                continue

            nums = filtered[vcol].map(_to_number).dropna()
            if nums.empty:
                continue

            # Multiple sector rows for same state/pollutant/year → aggregate
            if len(nums) > 1:
                total = float(nums.sum())
                first_idx = int(nums.index[0])
                evidence_row = filtered.loc[first_idx]
                evidence = {
                    str(k): json.loads(evidence_row.to_json()).get(str(k))
                    for k in list(df.columns)[:8]
                }
                evidence["matched_rows"] = int(len(nums))
                evidence["aggregation"] = "sum"
                if year:
                    evidence["year"] = year
                score = 10.0
                if location:
                    score += 5
                if metric:
                    score += 5
                if year and (col_year == year or year in notes):
                    score += 8
                hits.append(
                    QueryHit(
                        table_id=table_id,
                        table_name=table_name,
                        sheet_name=sheet_name,
                        column=str(vcol),
                        value=round(total, 4),
                        row_index=first_idx,
                        matched_region=f"{sheet_name} / {table_name}",
                        evidence=evidence,
                        score=score,
                        year=year or col_year,
                        aggregation=f"sum of {len(nums)} rows",
                    )
                )
            else:
                idx = int(nums.index[0])
                evidence_row = filtered.loc[idx]
                evidence = {str(k): json.loads(evidence_row.to_json()).get(str(k)) for k in list(df.columns)[:8]}
                if year:
                    evidence["year"] = year
                score = 8.0
                if location:
                    score += 5
                if metric:
                    score += 5
                if year and col_year == year:
                    score += 8
                hits.append(
                    QueryHit(
                        table_id=table_id,
                        table_name=table_name,
                        sheet_name=sheet_name,
                        column=str(vcol),
                        value=float(nums.iloc[0]),
                        row_index=idx,
                        matched_region=f"{sheet_name} / {table_name}",
                        evidence=evidence,
                        score=score,
                        year=year or col_year,
                        aggregation=None,
                    )
                )

    if not hits:
        return QueryResult(
            answer=(
                "未在已注册的数据表中找到与问题匹配的明确结果。"
                f"（已识别：地区={location or '无'}，指标={metric or '无'}，年份={year or '无'}）"
                "请确认已上传相关数据，并完成上传问答。"
            ),
            value=None,
            unit=None,
            hits=[],
            reasoning="；".join(notes) + "。规则检索未命中。",
        )

    hits.sort(key=lambda h: h.score, reverse=True)
    best = hits[0]
    loc_label = location or "目标对象"
    metric_label = (metric or "指标").upper()
    year_part = f"{best.year} 年" if best.year else ""
    agg_part = f"（已对 {best.aggregation} 汇总）" if best.aggregation else ""
    answer = (
        f"{loc_label} {year_part}的 {metric_label} 相关数值约为 {best.value}{agg_part}。"
        f"该结果来自子表「{best.table_name}」（工作表 {best.sheet_name}），"
        f"字段「{best.column}」，对应第 {best.row_index + 1} 行附近数据。"
    )
    reasoning = "；".join(notes)
    reasoning += "。按「地区 + 污染物 + 年份列」过滤后选取最高匹配；宽表年份取自列名（如 emissions2004）。"
    if best.aggregation:
        reasoning += f" 因存在多部门/多行业明细，对匹配行求和：{best.aggregation}。"
    if qa_context:
        reasoning += f" 同时参考了 {len(qa_context)} 条用户上传问答。"

    where_bits = []
    if location:
        where_bits.append(f"State MATCHES '{location}'")
    if metric:
        where_bits.append(f"Pollutant = '{metric.upper()}'")
    if best.year:
        where_bits.append(f"year_or_column = {best.year}")
    where_sql = " AND ".join(where_bits) if where_bits else "TRUE"
    agg = "SUM" if best.aggregation else ""
    sql = f"SELECT {agg}(`{best.column}`) FROM `{best.table_name}` WHERE {where_sql}".strip()

    unit = None
    joined = _normalize(" ".join(str(x) for x in [best.table_name, best.sheet_name, best.column]))
    if "kton" in joined or "thousand" in joined or "emissions" in joined:
        unit = "千吨（表内单位）"

    return QueryResult(
        answer=answer,
        value=best.value,
        unit=unit,
        hits=hits[:8],
        reasoning=reasoning,
        sql_equivalent=sql,
    )


async def query_tables_llm(
    question: str,
    tables: list[dict[str, Any]],
    qa_context: list[dict[str, str]] | None = None,
) -> QueryResult:
    if not settings.openai_api_key:
        return query_tables_rule_based(question, tables, qa_context)

    catalog = []
    for t in tables:
        catalog.append(
            {
                "table_id": t["id"],
                "name": t["name"],
                "sheet_name": t.get("sheet_name"),
                "columns": [c["name"] for c in t.get("columns", [])][:40],
                "sample_rows": t.get("sample_rows", [])[:3],
                "description": t.get("user_description", ""),
            }
        )

    system = (
        "你是异构环境治理数据分析助手。根据给定表目录和用户问答，"
        "选择最相关表和字段回答用户问题，并给出可追溯来源。"
        "注意：年份可能藏在列名中（如 emissions2004）。"
        "返回纯 JSON: {answer, value, unit, table_id, table_name, column, row_index, year, reasoning}."
    )
    user_payload = {
        "question": question,
        "parsed_hint": {
            "location": _extract_location(question)[0],
            "metric": _extract_metric(question),
            "year": _extract_year(question),
        },
        "tables": catalog,
        "qa_context": qa_context or [],
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            f"{settings.openai_base_url or 'https://api.openai.com/v1'}/chat/completions",
            headers={"Authorization": f"Bearer {settings.openai_api_key}"},
            json={
                "model": settings.openai_model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
                ],
                "temperature": 0.1,
            },
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
        content = content.strip()
        if content.startswith("```"):
            content = re.sub(r"^```(?:json)?\s*", "", content)
            content = re.sub(r"\s*```$", "", content)
        data = json.loads(content)

    hit = None
    for t in tables:
        if t["id"] == data.get("table_id"):
            hit = QueryHit(
                table_id=t["id"],
                table_name=data.get("table_name", t["name"]),
                sheet_name=t.get("sheet_name", ""),
                column=data.get("column", ""),
                value=data.get("value"),
                row_index=int(data.get("row_index", 0)),
                matched_region=f"{t.get('sheet_name', '')} / {t['name']}",
                evidence={"llm": True, "year": data.get("year")},
                year=data.get("year"),
            )
            break

    return QueryResult(
        answer=data.get("answer", ""),
        value=data.get("value"),
        unit=data.get("unit"),
        hits=[hit] if hit else [],
        reasoning=data.get("reasoning", "LLM 推理"),
    )


async def run_query(
    question: str,
    tables: list[dict[str, Any]],
    qa_context: list[dict[str, str]] | None = None,
    use_llm: bool = False,
) -> QueryResult:
    # Always prefer rule engine for structured wide tables; LLM is optional overlay
    rule_result = query_tables_rule_based(question, tables, qa_context)
    if use_llm and settings.openai_api_key and rule_result.value is None:
        try:
            return await query_tables_llm(question, tables, qa_context)
        except Exception:
            return rule_result
    return rule_result
