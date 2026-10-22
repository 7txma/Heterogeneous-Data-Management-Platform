import { useEffect, useState } from "react";
import { DetectedTable, listSessions, listTables } from "../api/client";

export default function DataCatalogPage() {
  const [tables, setTables] = useState<DetectedTable[]>([]);
  const [sessions, setSessions] = useState<
    { id: string; filename: string; description: string; status: string; table_count: number; created_at: string }[]
  >([]);
  const [error, setError] = useState("");

  useEffect(() => {
    Promise.all([listTables(), listSessions()])
      .then(([tableRows, sessionRows]) => {
        setTables(tableRows);
        setSessions(sessionRows);
      })
      .catch((err) => setError(err instanceof Error ? err.message : "加载失败"));
  }, []);

  return (
    <div className="page">
      <section className="card">
        <h2>数据目录</h2>
        <p className="muted">查看已注册的数据会话与子表元数据。</p>
        {error && <div className="alert error">{error}</div>}

        <h3>上传会话</h3>
        <div className="table-list">
          {sessions.length === 0 ? (
            <p className="muted">暂无会话</p>
          ) : (
            sessions.map((s) => (
              <div key={s.id} className="list-row">
                <div>
                  <strong>{s.filename}</strong>
                  <div className="muted">{s.description || "无描述"}</div>
                </div>
                <div className="row-meta">
                  <span className="badge">{s.status}</span>
                  <span>{s.table_count} 表</span>
                </div>
              </div>
            ))
          )}
        </div>

        <h3>已识别子表</h3>
        <div className="table-grid">
          {tables.length === 0 ? (
            <p className="muted">暂无子表，请先上传数据</p>
          ) : (
            tables.map((table) => (
              <div key={table.id} className="mini-card">
                <h4>{table.name}</h4>
                <p className="muted">{table.sheet_name}</p>
                <p className="muted">{table.row_count} 行 · 层级 {table.hierarchy.levels}</p>
                <div className="chip-row">
                  {table.columns.slice(0, 8).map((c) => (
                    <span className="chip" key={c.name}>
                      {c.name}
                    </span>
                  ))}
                </div>
              </div>
            ))
          )}
        </div>
      </section>
    </div>
  );
}
