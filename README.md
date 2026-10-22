# 曦源 · 异构数据治理 Web 平台

面向开题报告第一阶段的可运行原型：支持混乱表格上传、多表识别、上传问答、智能查询与来源追溯。

## 功能

- **上传**：CSV / XLSX / XLS
- **多表识别**：按空行/空列切分 sheet 内多个子表
- **层级表头**：识别多层表头并展平为字段路径
- **上传问答**：上传后自动生成描述/口径/字段含义问题
- **智能查询**：自然语言检索（默认规则引擎，可选 LLM）
- **来源追溯**：返回答案、命中表、字段、行号与证据

## 目录结构

```
web/
  backend/     FastAPI + SQLite + pandas
  frontend/    React + Vite
  sample_data/ 示例混乱表格
```

## 启动方式

### 1. 后端

```powershell
cd web/backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

### 2. 前端

```powershell
cd web/frontend
npm install
npm run dev
```

浏览器访问：http://127.0.0.1:5173

API 文档：http://127.0.0.1:8000/docs

## 可选：启用 LLM 查询

在 `web/backend/.env` 中配置：

```env
OPENAI_API_KEY=your_key
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=gpt-4o-mini
```

## 示例流程

1. 上传 `sample_data/messy_emissions.xlsx`
2. 填写整体描述与问答
3. 进入「智能查询」，提问：`告诉我美国阿拉斯加州的 NOx 排放量`
4. 查看结果与来源追溯

## 查询能力说明（已增强）

- 识别问题中的**年份**（如 2004），并匹配宽表列名 `emissions2004`
- 识别州名全称 / 中文 / 缩写（Alaska / 阿拉斯加 / AK）
- 按 `Pollutant` 过滤 NOX 等指标；多部门明细行自动求和
- 多工作表：自动跳过 README 等说明页，分别解析数据 sheet

重新上传大表后请完成「上传问答」（可用「填充建议答案」）。

## 后续迭代计划

1. 合并单元格精确解析（openpyxl merged ranges）
2. 关系推理与跨表 join 建议
3. 交互式候选对象确认 UI
4. 更强的 NL2SQL / ReAct 查询链路
5. 实验评价体系与任务样例库
