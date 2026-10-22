from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class UploadSession(Base):
    __tablename__ = "upload_sessions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    filename: Mapped[str] = mapped_column(String(512))
    original_description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(32), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    tables: Mapped[list["DataTable"]] = relationship(back_populates="session")
    qa_records: Mapped[list["QARecord"]] = relationship(back_populates="session")


class DataTable(Base):
    __tablename__ = "data_tables"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("upload_sessions.id"))
    name: Mapped[str] = mapped_column(String(256))
    sheet_name: Mapped[str] = mapped_column(String(256), default="")
    region: Mapped[str] = mapped_column(String(64), default="")
    row_start: Mapped[int] = mapped_column(default=0)
    row_end: Mapped[int] = mapped_column(default=0)
    col_start: Mapped[int] = mapped_column(default=0)
    col_end: Mapped[int] = mapped_column(default=0)
    header_rows: Mapped[list] = mapped_column(JSON, default=list)
    columns: Mapped[list] = mapped_column(JSON, default=list)
    hierarchy: Mapped[dict] = mapped_column(JSON, default=dict)
    sample_rows: Mapped[list] = mapped_column(JSON, default=list)
    row_count: Mapped[int] = mapped_column(default=0)
    parquet_path: Mapped[str] = mapped_column(String(512), default="")
    user_description: Mapped[str] = mapped_column(Text, default="")
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)

    session: Mapped["UploadSession"] = relationship(back_populates="tables")


class QARecord(Base):
    __tablename__ = "qa_records"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("upload_sessions.id"))
    table_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    question: Mapped[str] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text, default="")
    question_type: Mapped[str] = mapped_column(String(64), default="general")

    session: Mapped["UploadSession"] = relationship(back_populates="qa_records")
