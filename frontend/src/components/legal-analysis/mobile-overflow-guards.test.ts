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

test("案件报告根节点提供可继承的任意位置换行规则", () => {
  const reportSource = sourceBetween(
    caseReportSource,
    "export function CaseAnalysisReportResult",
    "function StageCard",
  );

  assert.match(
    reportSource,
    /<div className="[^"]*\bmin-w-0\b[^"]*\[overflow-wrap:anywhere\][^"]*">/,
  );
});

test("承载模型长文本的 flex 子项显式允许收缩", () => {
  const requiredGuards = [
    /<AlertTriangle[^>]*\/>\s*<div className="min-w-0">/,
    /<Info[^>]*\/>\s*<div className="min-w-0">/,
    /<Icon[^>]*\/>\s*<div className="min-w-0">/,
    /<span className="min-w-0">\{item\}<\/span>/,
  ];

  for (const guard of requiredGuards) {
    assert.match(caseReportSource, guard);
  }
});
