import { useMemo, useState } from "react";
import { DetectedTable, UploadQuestion, UploadResponse, submitQA, uploadFile } from "../api/client";

type Props = {
  onComplete: (sessionId: string) => void;
};

export default function UploadPage({ onComplete }: Props) {
  const [file, setFile] = useState<File | null>(null);
  const [description, setDescription] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [uploadResult, setUploadResult] = useState<UploadResponse | null>(null);
  const [answers, setAnswers] = useState<Record<string, string>>({});

  const generalQuestions = useMemo(
    () => uploadResult?.questions.filter((q) => q.question_type === "general") ?? [],
    [uploadResult],
  );
  const tableQuestions = useMemo(
    () => uploadResult?.questions.filter((q) => q.question_type === "table") ?? [],
    [uploadResult],
  );

  const requiredMissing = useMemo(() => {
    if (!uploadResult) return 0;
    return uploadResult.questions.filter((q) => q.required && !answers[q.id]?.trim()).length;
  }, [uploadResult, answers]);

  async function handleUpload() {
    if (!file) {
      setError("请先选择文件");
      return;
    }
    setLoading(true);
    setError("");
    try {
      const result = await uploadFile(file, description);
      setUploadResult(result);
      const initial: Record<string, string> = {};
      for (const q of result.questions) {
        initial[q.id] = q.prefill ?? "";
      }
      setAnswers(initial);
      if (!result.questions.length) {
        setError("上传成功但未生成问答，请刷新后重试");
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "上传失败");
    } finally {
      setLoading(false);
    }
  }

  function applyPrefills() {
    if (!uploadResult) return;
    setAnswers((prev) => {
      const next = { ...prev };
      for (const q of uploadResult.questions) {
        if (q.prefill && !next[q.id]?.trim()) {
          next[q.id] = q.prefill;
        }
      }
      return next;
    });
  }

  async function handleSubmitQA() {
    if (!uploadResult) return;
    if (requiredMissing > 0) {
      setError(`还有 ${requiredMissing} 个必填问题未回答（可用“填充建议答案”快速填写）`);
      return;
    }
    setLoading(true);
    setError("");
    try {
      await submitQA(
        uploadResult.session_id,
        uploadResult.questions.map((q) => ({
          question_id: q.id,
          question: q.question,
          answer: answers[q.id] ?? "",
          table_id: q.table_id,
          question_type: q.question_type,
        })),
      );
      onComplete(uploadResult.session_id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "提交失败");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="page">
      <section className="card hero-card">
        <h2>上传异构表格</h2>
        <p className="muted">
          支持混乱 Excel / CSV，以及多工作表工作簿（会自动跳过 README 等说明页）。系统会识别多表区域、宽表年份列（如
          emissions2004），并在上传后引导问答。
        </p>
        <div className="form-grid">
          <label className="field">
            <span>数据文件</span>
            <input type="file" accept=".csv,.xlsx,.xls" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
          </label>
          <label className="field">
            <span>数据整体描述</span>
            <textarea
              rows={4}
              placeholder="例如：美国各州分行业污染物排放（千吨），年份在 emissionsYYYY 列中"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
          </label>
        </div>
        <button className="btn primary" disabled={loading || !file} onClick={handleUpload}>
          {loading ? "解析中（大文件可能需数十秒）..." : "上传并识别表格结构"}
        </button>
      </section>

      {error && <div className="alert error">{error}</div>}

      {uploadResult && (
        <>
          <section className="card">
            <div className="card-header">
              <h3>识别结果</h3>
              <span className="badge">{uploadResult.table_count} 个子表</span>
            </div>
            <p className="muted">文件：{uploadResult.filename} · 会话 {uploadResult.session_id.slice(0, 8)}…</p>
            <div className="table-grid">
              {uploadResult.detected_tables.map((table) => (
                <TablePreview key={table.id} table={table} />
              ))}
            </div>
          </section>

          <section className="card" id="upload-qa">
            <div className="card-header">
              <h3>上传问答（必做）</h3>
              <span className="badge warn">{requiredMissing} 项待填</span>
            </div>
            <p className="muted">
              大表也会生成问答。请至少完成必填项；系统已根据表头给出建议答案，可一键填充后修改。
            </p>
            <div className="chip-row" style={{ marginBottom: 16 }}>
              <button type="button" className="chip-btn" onClick={applyPrefills}>
                填充建议答案
              </button>
            </div>

            <h4>整体问题</h4>
            <div className="qa-list">
              {generalQuestions.map((q) => (
                <QuestionItem
                  key={q.id}
                  question={q}
                  value={answers[q.id] ?? ""}
                  onChange={(value) => setAnswers((prev) => ({ ...prev, [q.id]: value }))}
                />
              ))}
            </div>

            {tableQuestions.length > 0 && (
              <>
                <h4>子表问题</h4>
                <div className="qa-list">
                  {tableQuestions.map((q) => (
                    <QuestionItem
                      key={q.id}
                      question={q}
                      value={answers[q.id] ?? ""}
                      onChange={(value) => setAnswers((prev) => ({ ...prev, [q.id]: value }))}
                    />
                  ))}
                </div>
              </>
            )}

            <button className="btn primary" disabled={loading} onClick={handleSubmitQA}>
              {loading ? "提交中..." : "完成问答并注册数据"}
            </button>
          </section>
        </>
      )}
    </div>
  );
}

function TablePreview({ table }: { table: DetectedTable }) {
  const yearCols = table.columns.filter((c) => /\d{4}/.test(c.name)).length;
  return (
    <div className="mini-card">
      <h4>{table.name}</h4>
      <p className="muted">工作表：{table.sheet_name}</p>
      <p className="muted">区域：{table.region}</p>
      <p className="muted">
        行数：{table.row_count}
        {yearCols > 0 ? ` · 含 ${yearCols} 个年份相关列` : ""}
      </p>
      <p className="muted">层级表头：{table.hierarchy.levels} 层</p>
      <div className="chip-row">
        {table.columns.slice(0, 8).map((c) => (
          <span key={c.name} className="chip">
            {c.name}
          </span>
        ))}
      </div>
    </div>
  );
}

function QuestionItem({
  question,
  value,
  onChange,
}: {
  question: UploadQuestion;
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <label className="qa-item">
      <div className="qa-title">
        {question.required && <span className="required">*</span>}
        {question.question}
      </div>
      <textarea rows={3} value={value} onChange={(e) => onChange(e.target.value)} />
    </label>
  );
}
