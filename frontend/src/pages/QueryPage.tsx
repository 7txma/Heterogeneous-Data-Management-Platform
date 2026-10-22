import { useState } from "react";
import { QueryResponse, queryData } from "../api/client";

type Props = {
  activeSessionId?: string;
};

const EXAMPLES = [
  "告诉我美国阿拉斯加州2004年的 NOx 排放量",
  "Alaska 2010 NOx emissions",
  "California 2020 年的 NOx 排放是多少",
];

export default function QueryPage({ activeSessionId }: Props) {
  const [question, setQuestion] = useState(EXAMPLES[0]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<QueryResponse | null>(null);

  async function handleQuery() {
    if (!question.trim()) return;
    setLoading(true);
    setError("");
    setResult(null);
    try {
      const resp = await queryData(question.trim(), activeSessionId);
      setResult(resp);
    } catch (err) {
      setError(err instanceof Error ? err.message : "查询失败");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="page">
      <section className="card hero-card">
        <h2>智能查询</h2>
        <p className="muted">
          用自然语言提问。系统会在已注册的多张子表中检索，并返回结果及来源（表名、字段、行号、证据片段）。
        </p>
        <label className="field">
          <span>您的问题</span>
          <textarea rows={3} value={question} onChange={(e) => setQuestion(e.target.value)} />
        </label>
        <div className="chip-row">
          {EXAMPLES.map((item) => (
            <button key={item} className="chip-btn" onClick={() => setQuestion(item)}>
              {item}
            </button>
          ))}
        </div>
        <button className="btn primary" disabled={loading} onClick={handleQuery}>
          {loading ? "检索中..." : "开始查询"}
        </button>
      </section>

      {error && <div className="alert error">{error}</div>}

      {result && (
        <section className="card">
          <h3>查询结果</h3>
          <div className="result-box">{result.answer}</div>
          {result.value !== null && result.value !== undefined && (
            <p className="highlight-value">数值：{String(result.value)} {result.unit ?? ""}</p>
          )}
          <p className="muted">推理：{result.reasoning}</p>
          {result.sql_equivalent && (
            <pre className="code-block">{result.sql_equivalent}</pre>
          )}

          <h4>来源追溯</h4>
          {result.sources.length === 0 ? (
            <p className="muted">暂无命中来源</p>
          ) : (
            <div className="source-list">
              {result.sources.map((source, idx) => (
                <div key={`${source.table_id}-${idx}`} className="source-item">
                  <div className="source-title">
                    {source.matched_region} · 字段 {source.column} · 第 {source.row_index + 1} 行
                  </div>
                  <div className="muted">值：{String(source.value)}</div>
                  <pre className="code-block small">{JSON.stringify(source.evidence, null, 2)}</pre>
                </div>
              ))}
            </div>
          )}
        </section>
      )}
    </div>
  );
}
