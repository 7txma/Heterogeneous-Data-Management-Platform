from __future__ import annotations

import uuid
from starlette.concurrency import run_in_threadpool
from pathlib import Path
from typing import Any

import pandas as pd
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.database import get_db
from app.models import DataTable, QARecord, UploadSession
from app.services.query_engine import run_query
from app.services.storage import load_table_dataframe, save_table_dataframe
from app.services.table_parser import generate_upload_questions, parse_uploaded_file

router = APIRouter()


class QAAnswerItem(BaseModel):
    question_id: str
    question: str
    answer: str
    table_id: str | None = None
    question_type: str = "general"


class SubmitQAPayload(BaseModel):
    answers: list[QAAnswerItem]


class QueryPayload(BaseModel):
    question: str
    session_id: str | None = None
    use_llm: bool = False


def _table_to_dict(row: DataTable, include_df: bool = False) -> dict[str, Any]:
    data = {
        "id": row.id,
        "session_id": row.session_id,
        "name": row.name,
        "sheet_name": row.sheet_name,
        "region": row.region,
        "row_start": row.row_start,
        "row_end": row.row_end,
        "col_start": row.col_start,
        "col_end": row.col_end,
        "header_rows": row.header_rows,
        "columns": row.columns,
        "hierarchy": row.hierarchy,
        "sample_rows": row.sample_rows,
        "row_count": row.row_count,
        "user_description": row.user_description,
        "metadata": row.metadata_json or {},
        "metadata_json": row.metadata_json or {},
    }
    if include_df and row.parquet_path:
        try:
            data["dataframe"] = load_table_dataframe(row.parquet_path)
        except Exception:
            data["dataframe"] = None
    return data


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "app": settings.app_name}


@router.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    description: str = Form(""),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    if not file.filename:
        raise HTTPException(status_code=400, detail="未选择文件")

    suffix = Path(file.filename).suffix.lower()
    if suffix not in {".csv", ".xlsx", ".xls"}:
        raise HTTPException(status_code=400, detail="仅支持 CSV / XLSX / XLS")

    if not description.strip():
        raise HTTPException(status_code=422, detail="请先描述数据来源、主题和用途")
    content = await file.read()
    session_id = str(uuid.uuid4())
    upload_path = settings.upload_dir / f"{session_id}{suffix}"
    upload_path.write_bytes(content)

    try:
        regions = await run_in_threadpool(parse_uploaded_file, content, file.filename)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"文件解析失败: {exc}") from exc

    if not regions:
        raise HTTPException(status_code=400, detail="未识别到有效表格区域")

    try:
        session = UploadSession(
            id=session_id,
            filename=file.filename,
            original_description=description,
            status="awaiting_qa",
        )
        db.add(session)

        table_payloads: list[dict[str, Any]] = []
        for region in regions:
            table_id = region.id
            saved_path = ""
            if region.dataframe is not None:
                saved_path = save_table_dataframe(
                    region.dataframe,
                    settings.tables_dir / table_id,
                )

            row = DataTable(
                id=table_id,
                session_id=session_id,
                name=region.name,
                sheet_name=region.sheet_name,
                region=f"R{region.row_start}-R{region.row_end}_C{region.col_start}-C{region.col_end}",
                row_start=region.row_start,
                row_end=region.row_end,
                col_start=region.col_start,
                col_end=region.col_end,
                header_rows=region.header_rows,
                columns=region.columns,
                hierarchy=region.hierarchy,
                sample_rows=region.sample_rows,
                row_count=region.row_count,
                parquet_path=saved_path,
                metadata_json=region.metadata,
            )
            db.add(row)
            table_payloads.append(
                {
                    "id": table_id,
                    "name": region.name,
                    "sheet_name": region.sheet_name,
                    "row_count": region.row_count,
                    "columns": region.columns,
                    "hierarchy": region.hierarchy,
                    "sample_rows": region.sample_rows,
                    "region": row.region,
                    "pollutant_hint": region.metadata.get("pollutant_hint"),
                    "year_columns": region.metadata.get("year_columns"),
                }
            )

        questions = generate_upload_questions(regions, description)
        await db.commit()
    except Exception as exc:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"保存数据失败: {type(exc).__name__}: {exc}") from exc

    return {
        "session_id": session_id,
        "filename": file.filename,
        "description": description,
        "status": "awaiting_qa",
        "detected_tables": table_payloads,
        "table_count": len(table_payloads),
        "questions": questions,
    }


@router.get("/sessions")
async def list_sessions(db: AsyncSession = Depends(get_db)) -> list[dict[str, Any]]:
    result = await db.execute(
        select(UploadSession).options(selectinload(UploadSession.tables)).order_by(UploadSession.created_at.desc())
    )
    sessions = result.scalars().all()
    return [
        {
            "id": s.id,
            "filename": s.filename,
            "description": s.original_description,
            "status": s.status,
            "table_count": len(s.tables),
            "created_at": s.created_at.isoformat(),
        }
        for s in sessions
    ]


@router.get("/sessions/{session_id}")
async def get_session(session_id: str, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    result = await db.execute(
        select(UploadSession)
        .where(UploadSession.id == session_id)
        .options(selectinload(UploadSession.tables), selectinload(UploadSession.qa_records))
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")

    questions = []
    if session.status == "awaiting_qa":
        from app.services.table_parser import TableRegion

        pseudo_regions = [
            TableRegion(
                id=t.id,
                name=t.name,
                sheet_name=t.sheet_name,
                row_start=t.row_start,
                row_end=t.row_end,
                col_start=t.col_start,
                col_end=t.col_end,
                header_rows=t.header_rows,
                columns=t.columns,
                hierarchy=t.hierarchy,
                sample_rows=t.sample_rows,
                row_count=t.row_count,
                metadata=t.metadata_json or {},
            )
            for t in session.tables
        ]
        questions = generate_upload_questions(pseudo_regions, session.original_description)

    return {
        "id": session.id,
        "filename": session.filename,
        "description": session.original_description,
        "status": session.status,
        "tables": [_table_to_dict(t) for t in session.tables],
        "qa_records": [
            {
                "question": q.question,
                "answer": q.answer,
                "table_id": q.table_id,
                "question_type": q.question_type,
            }
            for q in session.qa_records
        ],
        "questions": questions,
    }


@router.post("/sessions/{session_id}/qa")
async def submit_qa(
    session_id: str,
    payload: SubmitQAPayload,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    result = await db.execute(
        select(UploadSession)
        .where(UploadSession.id == session_id)
        .options(selectinload(UploadSession.tables))
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")

    if not payload.answers or any(not a.answer.strip() for a in payload.answers):
        raise HTTPException(status_code=422, detail="请完成问答后再提交")
    owned_ids = {t.id for t in session.tables}
    if any(a.table_id and a.table_id not in owned_ids for a in payload.answers):
        raise HTTPException(status_code=422, detail="问答包含不属于此上传的表格")
    table_desc: dict[str, str] = {}
    for item in payload.answers:
        db.add(
            QARecord(
                session_id=session_id,
                table_id=item.table_id,
                question=item.question,
                answer=item.answer,
                question_type=item.question_type,
            )
        )
        if item.table_id and item.answer.strip():
            table_desc.setdefault(item.table_id, "")
            table_desc[item.table_id] += f"{item.question}: {item.answer}\n"

    for table in session.tables:
        if table.id in table_desc:
            table.user_description = table_desc[table.id].strip()

    session.status = "ready"
    await db.commit()
    return {"session_id": session_id, "status": "ready", "saved_answers": len(payload.answers)}


@router.get("/tables")
async def list_tables(db: AsyncSession = Depends(get_db)) -> list[dict[str, Any]]:
    result = await db.execute(select(DataTable).order_by(DataTable.name))
    rows = result.scalars().all()
    return [_table_to_dict(r) for r in rows]


@router.post("/query")
async def query_data(payload: QueryPayload, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    stmt = select(DataTable)
    if payload.session_id:
        stmt = stmt.where(DataTable.session_id == payload.session_id)
    result = await db.execute(stmt)
    rows = result.scalars().all()
    if not rows:
        raise HTTPException(status_code=404, detail="没有可用于查询的数据表")

    tables = [_table_to_dict(r, include_df=True) for r in rows]

    qa_context: list[dict[str, str]] = []
    if payload.session_id:
        qa_result = await db.execute(select(QARecord).where(QARecord.session_id == payload.session_id))
        qa_context = [
            {"question": q.question, "answer": q.answer} for q in qa_result.scalars().all() if q.answer
        ]

    query_result = await run_query(
        payload.question,
        tables,
        qa_context=qa_context,
        use_llm=payload.use_llm,
    )

    return {
        "question": payload.question,
        "answer": query_result.answer,
        "value": query_result.value,
        "unit": query_result.unit,
        "reasoning": query_result.reasoning,
        "sql_equivalent": query_result.sql_equivalent,
        "sources": [
            {
                "table_id": h.table_id,
                "table_name": h.table_name,
                "sheet_name": h.sheet_name,
                "column": h.column,
                "row_index": h.row_index,
                "value": h.value,
                "matched_region": h.matched_region,
                "evidence": h.evidence,
            }
            for h in query_result.hits
        ],
    }
