"""Helpers for persisting mixed-type dataframes safely."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pandas as pd

NA_TOKENS = {
    "",
    "na",
    "n/a",
    "nan",
    "null",
    "none",
    "-",
    "—",
    ".",
    "nd",
    "n.d.",
}


def clean_cell(value: Any) -> Any:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, str):
        text = value.strip()
        if text.lower() in NA_TOKENS:
            return None
        # numeric strings with commas
        compact = text.replace(",", "").replace(" ", "")
        if re.fullmatch(r"-?\d+(\.\d+)?([eE][+-]?\d+)?", compact):
            try:
                return float(compact) if "." in compact or "e" in compact.lower() else int(compact)
            except ValueError:
                return text
        return text
    return value


def prepare_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize NA-like values and coerce mixed columns for storage/query."""
    out = df.copy()
    out.columns = [str(c) for c in out.columns]
    for col in out.columns:
        out[col] = out[col].map(clean_cell)
        # If column is mostly numeric, cast to float
        non_null = out[col].dropna()
        if len(non_null) == 0:
            continue
        numeric_ratio = non_null.map(lambda v: isinstance(v, (int, float))).mean()
        if numeric_ratio >= 0.7:
            out[col] = pd.to_numeric(out[col], errors="coerce")
        else:
            # Keep as object/string-friendly to avoid parquet mixed-type crashes
            out[col] = out[col].map(lambda v: None if v is None else v)
    return out


def save_table_dataframe(df: pd.DataFrame, path: Path) -> str:
    """
    Save dataframe robustly. Prefer parquet; fall back to pickle if Arrow rejects mixed types.
    Returns the actual saved path string.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    cleaned = prepare_dataframe(df)

    parquet_path = path.with_suffix(".parquet")
    try:
        # Convert remaining object cols to string for Arrow safety
        safe = cleaned.copy()
        for col in safe.columns:
            if safe[col].dtype == object:
                safe[col] = safe[col].map(lambda v: None if v is None or (isinstance(v, float) and pd.isna(v)) else str(v))
        safe.to_parquet(parquet_path, index=False)
        return str(parquet_path)
    except Exception:
        pkl_path = path.with_suffix(".pkl")
        cleaned.to_pickle(pkl_path)
        return str(pkl_path)


def load_table_dataframe(path: str | Path) -> pd.DataFrame:
    path = Path(path)
    if not path.exists():
        # try alternate extension
        for alt in (path.with_suffix(".parquet"), path.with_suffix(".pkl")):
            if alt.exists():
                path = alt
                break
        else:
            raise FileNotFoundError(path)

    if path.suffix == ".pkl":
        df = pd.read_pickle(path)
    else:
        df = pd.read_parquet(path)

    return prepare_dataframe(df)
