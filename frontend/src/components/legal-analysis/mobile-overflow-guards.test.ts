import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const workspaceSource = readFileSync(
  new URL("./legal-analysis-workspace.tsx", import.meta.url),
  "utf8",
);
const caseReportSource = readFileSync(
  new URL("./case-analysis-report-result.tsx", import.meta.url),
  "utf8",
);
const historySource = readFileSync(
  new URL("./analysis-history.tsx", import.meta.url),
  "utf8",
);

function sourceBetween(source: string, start: string, end: string): string {
  const startIndex = source.indexOf(start);
  const endIndex = source.indexOf(end, startIndex + start.length);
  assert.notEqual(startIndex, -1, `未找到源码起点：${start}`);
  assert.notEqual(endIndex, -1, `未找到源码终点：${end}`);
  return source.slice(startIndex, endIndex);
}

test("结果栏作为网格项可以在窄屏收缩", () => {
  const panelSource = sourceBetween(
    workspaceSource,
    "function AnalysisResultPanel",
    "function LoadingState",
  );

  assert.match(panelSource, /<aside className="[^"]*\bmin-w-0\b[^"]*">/);
});

test("案件下载卡片在窄屏可收缩并直接提供 PDF", () => {
  assert.match(
    caseReportSource,
    /<div className="[^"]*\bmin-w-0\b[^"]*\[overflow-wrap:anywhere\][^"]*">/,
  );
  assert.match(caseReportSource, /下载案件文书 PDF/);
  assert.doesNotMatch(caseReportSource, /CASE_STAGE_ORDER|StageCard|案件卷宗索引/);
});

test("案件历史直接下载而合同历史仍打开详情", () => {
  assert.match(historySource, /endpoint === "case-analyses"/);
  assert.match(historySource, /case-analyses\/\$\{encodeURIComponent\(id\)\}\/document/);
  assert.match(historySource, /下载文书/);
  assert.match(historySource, /onClick=\{\(\) => openItem\(item\)\}/);
});
