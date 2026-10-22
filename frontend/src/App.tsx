import { useState } from "react";
import DataCatalogPage from "./pages/DataCatalogPage";
import QueryPage from "./pages/QueryPage";
import UploadPage from "./pages/UploadPage";

type Tab = "upload" | "query" | "catalog";

export default function App() {
  const [tab, setTab] = useState<Tab>("upload");
  const [activeSessionId, setActiveSessionId] = useState<string>();

  return (
    <div className="app-shell">
      <header className="topbar">
        <div>
          <p className="eyebrow">曦源项目 · 异构数据治理</p>
          <h1>交互式智能分析平台</h1>
        </div>
        <nav className="tabs">
          <button className={tab === "upload" ? "tab active" : "tab"} onClick={() => setTab("upload")}>
            上传与问答
          </button>
          <button className={tab === "query" ? "tab active" : "tab"} onClick={() => setTab("query")}>
            智能查询
          </button>
          <button className={tab === "catalog" ? "tab active" : "tab"} onClick={() => setTab("catalog")}>
            数据目录
          </button>
        </nav>
      </header>

      <main>
        {tab === "upload" && (
          <UploadPage
            onComplete={(sessionId) => {
              setActiveSessionId(sessionId);
              setTab("query");
            }}
          />
        )}
        {tab === "query" && <QueryPage activeSessionId={activeSessionId} />}
        {tab === "catalog" && <DataCatalogPage />}
      </main>
    </div>
  );
}
