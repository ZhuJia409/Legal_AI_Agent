import {
  AlertTriangle,
  CalendarClock,
  FileText,
  Info,
  ListOrdered,
  MessageSquareText,
  Route,
  Scale,
  Search,
  ShieldAlert,
  UsersRound,
  Download,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

import { CASE_STAGE_ORDER } from "@/lib/legal-analysis-types";
import type {
  CaseAnalysisResponse,
  CaseFinding,
  CaseSourceRef,
  CaseStageCode,
  CaseStageResult,
  RiskDimension,
  RiskLevel,
  StageStatus,
  StrategyMode,
} from "@/lib/legal-analysis-types";
import { cn } from "@/lib/utils";

type StageMeta = {
  index: string;
  label: string;
  icon: LucideIcon;
};

const STAGE_META: Record<CaseStageCode, StageMeta> = {
  intake_screening: { index: "01", label: "接案初筛", icon: UsersRound },
  fact_reconstruction: { index: "02", label: "事实重构", icon: ListOrdered },
  evidence_review: { index: "03", label: "证据审查", icon: Search },
  legal_classification: { index: "04", label: "法律定性", icon: Scale },
  deep_analysis: { index: "05", label: "争点分析", icon: MessageSquareText },
  risk_assessment: { index: "06", label: "风险评估", icon: ShieldAlert },
  strategy_options: { index: "07", label: "策略方案", icon: Route },
  document_draft: { index: "08", label: "报告草稿", icon: FileText },
  deadline_management: { index: "09", label: "期限管理", icon: CalendarClock },
};

const STATUS_LABELS: Record<StageStatus, string> = {
  succeeded: "已完成",
  needs_input: "待补材料",
  failed: "未完成",
  skipped: "已跳过",
};

const STATUS_STYLES: Record<StageStatus, string> = {
  succeeded: "border-emerald-200 bg-emerald-50 text-emerald-800",
  needs_input: "border-amber-200 bg-amber-50 text-amber-800",
  failed: "border-rose-200 bg-rose-50 text-rose-800",
  skipped: "border-zinc-200 bg-zinc-100 text-zinc-600",
};

const RISK_LABELS: Record<RiskLevel, string> = {
  unknown: "风险待确认",
  low: "低风险",
  medium: "中风险",
  high: "高风险",
};

const RISK_STYLES: Record<RiskLevel, string> = {
  unknown: "border-zinc-200 bg-zinc-100 text-zinc-700",
  low: "border-emerald-200 bg-emerald-50 text-emerald-800",
  medium: "border-amber-200 bg-amber-50 text-amber-800",
  high: "border-rose-200 bg-rose-50 text-rose-800",
};

const RISK_DIMENSION_LABELS: Record<RiskDimension, string> = {
  internal: "己方短板",
  opponent: "对方抗辩",
  execution_cost: "执行与成本",
};

const STRATEGY_MODES = ["aggressive", "balanced", "conservative"] as const;

const STRATEGY_LABELS: Record<StrategyMode, string> = {
  aggressive: "积极方案",
  balanced: "稳健方案",
  conservative: "保守方案",
};

export function CaseAnalysisReportResult({ result }: { result: CaseAnalysisResponse }) {
  const stageMap = new Map(result.stages.map((stage) => [stage.stage, stage]));
  const failedStageLabels = result.report.failed_stages.map(
    (stage) => STAGE_META[stage].label,
  );

  return (
    <div className="mt-6 min-w-0 space-y-4 [overflow-wrap:anywhere]">
      {result.draft_document ? (
        <a
          className="inline-flex h-10 items-center gap-2 rounded-md bg-[#214a4b] px-4 text-sm font-semibold text-white hover:bg-[#183c3d]"
          href={result.draft_document.download_path}
        >
          <Download aria-hidden="true" className="h-4 w-4" />
          下载文书草稿 DOCX
        </a>
      ) : null}
      {result.status === "partial" ? (
        <div className="rounded-lg border border-amber-200 bg-amber-50 p-4 text-amber-950">
          <div className="flex items-start gap-3">
            <AlertTriangle aria-hidden="true" className="mt-0.5 h-5 w-5 shrink-0" />
            <div className="min-w-0">
              <p className="text-sm font-semibold">当前为部分案件分析</p>
              <p className="mt-1 text-xs leading-5">
                {failedStageLabels.length > 0
                  ? `未完整完成：${failedStageLabels.join("、")}。请补充材料并交由律师复核。`
                  : "部分阶段仍需补充材料，结论不可直接作为诉讼或谈判决策。"}
              </p>
            </div>
          </div>
        </div>
      ) : null}

      <section className="relative overflow-hidden rounded-xl border border-[#b9d8cc] bg-[#f4faf6] p-5 pl-6">
        <div aria-hidden="true" className="absolute inset-y-0 left-0 w-1 bg-[#214a4b]" />
        <div className="flex flex-wrap items-center gap-2">
          <span
            className={cn(
              "rounded-md border px-2.5 py-1 text-xs font-semibold",
              result.status === "complete"
                ? "border-emerald-200 bg-white text-emerald-800"
                : "border-amber-200 bg-white text-amber-800",
            )}
          >
            {result.status === "complete" ? "完整报告" : "部分报告"}
          </span>
          <RiskBadge level={result.risk_level} />
        </div>
        <h3 className="mt-4 text-lg font-semibold tracking-tight text-zinc-950">案件分析总览</h3>
        <p className="mt-2 text-sm leading-6 text-zinc-700">
          {result.report.executive_summary || result.summary}
        </p>
        <p className="mt-3 break-all text-[11px] leading-5 text-zinc-500">
          分析编号：{result.analysis_id}
        </p>
      </section>

      <OverviewList title="关键发现" items={result.report.key_findings} emptyText="暂无关键发现。" />
      <OverviewList
        title="建议动作"
        items={result.report.recommended_actions}
        emptyText="暂无可执行建议。"
      />
      <OverviewList
        title="报告限制"
        items={result.report.limitations}
        emptyText="未返回额外限制说明，仍须由律师核验完整材料。"
        tone="warning"
      />

      <nav aria-label="案件卷宗索引" className="rounded-xl border border-zinc-200 bg-white p-3">
        <div className="mb-3 flex items-center justify-between gap-3">
          <div className="min-w-0">
            <p className="text-xs font-semibold uppercase tracking-[0.16em] text-[#214a4b]">
              Case docket
            </p>
            <h3 className="mt-1 text-sm font-semibold text-zinc-950">案件卷宗索引</h3>
          </div>
          <span className="text-xs text-zinc-500">点击跳转</span>
        </div>
        <div className="grid grid-cols-3 gap-2">
          {CASE_STAGE_ORDER.map((stageCode) => {
            const stage = stageMap.get(stageCode);
            const meta = STAGE_META[stageCode];
            const Icon = meta.icon;
            return (
              <a
                className="group min-w-0 rounded-lg border border-zinc-200 bg-[#fafbf9] p-2.5 transition-colors hover:border-[#8fb7aa] hover:bg-[#f2f8f4] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#214a4b]/35"
                href={`#case-stage-${stageCode}`}
                key={stageCode}
              >
                <div className="flex items-center justify-between gap-1">
                  <span className="font-mono text-[10px] font-semibold text-zinc-400">
                    {meta.index}
                  </span>
                  <Icon aria-hidden="true" className="h-3.5 w-3.5 text-[#214a4b]" />
                </div>
                <p className="mt-2 truncate text-xs font-semibold text-zinc-800">{meta.label}</p>
                <p
                  className={cn(
                    "mt-1 truncate text-[10px] font-medium",
                    stage ? statusTextColor(stage.status) : "text-rose-700",
                  )}
                >
                  {stage ? STATUS_LABELS[stage.status] : "未返回"}
                </p>
              </a>
            );
          })}
        </div>
      </nav>

      <div className="space-y-4">
        {CASE_STAGE_ORDER.map((stageCode) => {
          const stage = stageMap.get(stageCode);
          return stage ? (
            <StageCard key={stageCode} stage={stage}>
              {renderStageContent(stage)}
            </StageCard>
          ) : (
            <MissingStageCard key={stageCode} stageCode={stageCode} />
          );
        })}
      </div>

      <div className="rounded-lg border border-zinc-200 bg-[#f7f8f6] p-4">
        <div className="flex items-start gap-2">
          <Info aria-hidden="true" className="mt-0.5 h-4 w-4 shrink-0 text-[#214a4b]" />
          <div className="min-w-0">
            <p className="text-xs font-semibold text-zinc-700">专业复核提示</p>
            <p className="mt-1 text-xs leading-5 text-zinc-500">{result.disclaimer}</p>
          </div>
        </div>
      </div>
    </div>
  );
}

function StageCard({ children, stage }: { children: ReactNode; stage: CaseStageResult }) {
  const meta = STAGE_META[stage.stage];
  const Icon = meta.icon;

  return (
    <section
      className="scroll-mt-4 overflow-hidden rounded-xl border border-zinc-200 bg-white"
      id={`case-stage-${stage.stage}`}
    >
      <div className="border-l-4 border-[#214a4b] p-4">
        <div className="flex items-start justify-between gap-3">
          <div className="flex min-w-0 items-start gap-3">
            <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-[#edf4ef] text-[#214a4b]">
              <Icon aria-hidden="true" className="h-4 w-4" />
            </div>
            <div className="min-w-0">
              <p className="font-mono text-[10px] font-semibold tracking-[0.12em] text-zinc-400">
                STAGE {meta.index}
              </p>
              <h3 className="mt-1 text-sm font-semibold text-zinc-950">{meta.label}</h3>
            </div>
          </div>
          <StatusBadge status={stage.status} />
        </div>

        <p className="mt-4 text-sm leading-6 text-zinc-700">{stage.summary}</p>

        {stage.error ? (
          <div className="mt-3 rounded-lg border border-rose-200 bg-rose-50 p-3 text-rose-900">
            <p className="text-xs font-semibold">阶段错误 · {stage.error.code}</p>
            <p className="mt-1 text-xs leading-5">{stage.error.message}</p>
          </div>
        ) : null}

        {stage.missing_information.length > 0 ? (
          <TextList
            className="mt-4"
            emptyText="暂无缺失信息。"
            items={stage.missing_information}
            title="仍需补充"
            tone="warning"
          />
        ) : stage.status === "needs_input" ? (
          <p className="mt-4 rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs leading-5 text-amber-900">
            该阶段标记为待补材料，但未返回具体清单，请由律师人工核对。
          </p>
        ) : null}

        <div className="mt-5">{children}</div>

        <div className="mt-5 flex items-start gap-2 border-t border-zinc-100 pt-3 text-[11px] leading-5 text-zinc-500">
          <Scale aria-hidden="true" className="mt-0.5 h-3.5 w-3.5 shrink-0 text-[#214a4b]" />
          <p className="min-w-0">
            {stage.requires_human_review
              ? "本阶段结果必须由法律专业人士结合完整材料复核。"
              : "请人工确认本阶段是否需要进一步复核。"}
          </p>
        </div>
      </div>
    </section>
  );
}

function MissingStageCard({ stageCode }: { stageCode: CaseStageCode }) {
  const meta = STAGE_META[stageCode];
  const Icon = meta.icon;

  return (
    <section
      className="scroll-mt-4 rounded-xl border border-dashed border-rose-300 bg-rose-50/60 p-4"
      id={`case-stage-${stageCode}`}
    >
      <div className="flex items-start gap-3">
        <Icon aria-hidden="true" className="mt-0.5 h-5 w-5 shrink-0 text-rose-700" />
        <div className="min-w-0">
          <p className="text-xs font-semibold text-rose-900">
            {meta.index} · {meta.label}
          </p>
          <p className="mt-1 text-xs leading-5 text-rose-800">
            服务未返回该阶段结果，当前报告不完整，请重新分析或联系管理员。
          </p>
        </div>
      </div>
    </section>
  );
}

function renderStageContent(stage: CaseStageResult): ReactNode {
  switch (stage.stage) {
    case "intake_screening":
      return (
        <div className="space-y-4">
          <InfoRow label="案件路由" value={stage.case_route || "尚未确认案件路由"} />
          <CardCollection title="当事人" emptyText="未识别到当事人。">
            {stage.parties.map((party, index) => (
              <ContentCard key={`${party.name}-${party.role}-${index}`} title={party.name} eyebrow={party.role}>
                <CaseReferenceDetails refs={party.source_refs} />
              </ContentCard>
            ))}
          </CardCollection>
          <CardCollection title="表面诉求" emptyText="未识别到明确诉求。">
            {stage.claims.map((claim, index) => (
              <ContentCard
                key={`${claim.claimant}-${index}`}
                title={claim.request}
                eyebrow={`主张方：${claim.claimant}`}
              >
                <CaseReferenceDetails refs={claim.source_refs} />
              </ContentCard>
            ))}
          </CardCollection>
          <FindingCollection title="紧急红线" items={stage.red_flags} emptyText="暂无紧急红线。" />
        </div>
      );
    case "fact_reconstruction":
      return (
        <div className="space-y-4">
          <Timeline events={stage.timeline} />
          <FindingCollection title="关键事实" items={stage.key_facts} emptyText="暂无关键事实。" />
          <FindingCollection title="事实冲突" items={stage.conflicts} emptyText="暂无已识别冲突。" />
        </div>
      );
    case "evidence_review":
      return (
        <div className="space-y-4">
          <FindingCollection
            title="证据线索"
            items={stage.evidence_clues}
            emptyText="暂无证据线索。"
          />
          <FindingCollection title="证据缺口" items={stage.gaps} emptyText="暂无证据缺口。" />
          <TextList
            emptyText="暂无补强动作。"
            items={stage.reinforcement_plan}
            title="证据补强计划"
          />
        </div>
      );
    case "legal_classification":
      return (
        <div className="space-y-4">
          <CardCollection title="法律关系" emptyText="暂无法律关系判断。">
            {stage.legal_relations.map((relation, index) => (
              <ContentCard key={`${relation.name}-${index}`} title={relation.name}>
                <p className="text-xs leading-5 text-zinc-600">{relation.description}</p>
                <CaseReferenceDetails refs={relation.source_refs} />
              </ContentCard>
            ))}
          </CardCollection>
          <CardCollection title="候选案由" emptyText="暂无候选案由。">
            {stage.candidate_causes.map((cause, index) => (
              <ContentCard key={`${cause.name}-${index}`} title={cause.name}>
                <p className="text-xs leading-5 text-zinc-600">{cause.reason}</p>
                <CaseReferenceDetails refs={cause.source_refs} />
              </ContentCard>
            ))}
          </CardCollection>
          <TextList
            emptyText="暂无程序问题。"
            items={stage.procedure_questions}
            title="程序问题"
          />
        </div>
      );
    case "deep_analysis":
      return (
        <CardCollection title="核心争议焦点" emptyText="未形成可用争点分析。">
          {stage.issues.map((issue) => (
            <ContentCard key={issue.issue_id} title={issue.title} eyebrow={issue.issue_id}>
              <p className="text-xs leading-5 text-zinc-700">{issue.analysis}</p>
              <TextList emptyText="暂无双方立场。" items={issue.positions} title="双方立场" />
              <TextList
                emptyText="暂无不确定性。"
                items={issue.uncertainties}
                title="不确定性"
                tone="warning"
              />
              <TextList
                emptyText="暂无额外待补信息。"
                items={issue.missing_information}
                title="待补信息"
                tone="warning"
              />
              <CaseReferenceDetails refs={issue.source_refs} />
            </ContentCard>
          ))}
        </CardCollection>
      );
    case "risk_assessment":
      return (
        <div className="space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-zinc-200 bg-[#fafbf9] p-3">
            <span className="text-xs font-semibold text-zinc-700">综合风险</span>
            <RiskBadge level={stage.overall_risk_level} />
          </div>
          <CardCollection title="风险与抗辩" emptyText="暂无成功返回的风险分支。">
            {stage.risks.map((risk, index) => (
              <ContentCard
                key={`${risk.dimension}-${risk.title}-${index}`}
                title={risk.title}
                eyebrow={RISK_DIMENSION_LABELS[risk.dimension]}
                trailing={<RiskBadge level={risk.risk_level} />}
              >
                <p className="text-xs leading-5 text-zinc-700">{risk.detail}</p>
                <div className="mt-3 rounded-md bg-[#eef5f1] p-3">
                  <p className="text-[11px] font-semibold text-[#214a4b]">缓释动作</p>
                  <p className="mt-1 text-xs leading-5 text-zinc-700">{risk.mitigation}</p>
                </div>
                <CaseReferenceDetails refs={risk.source_refs} />
              </ContentCard>
            ))}
          </CardCollection>
        </div>
      );
    case "strategy_options":
      return (
        <div className="space-y-3">
          {STRATEGY_MODES.map((mode) => {
            const strategy = stage.strategies.find((item) => item.mode === mode);
            return strategy ? (
              <ContentCard key={mode} title={STRATEGY_LABELS[mode]} eyebrow={strategy.objective}>
                <p className="text-xs leading-5 text-zinc-700">{strategy.summary}</p>
                <TextList emptyText="暂无步骤。" items={strategy.steps} title="执行步骤" />
                <TextList
                  emptyText="暂无前置条件。"
                  items={strategy.prerequisites}
                  title="前置条件"
                />
                <TextList emptyText="暂无策略风险。" items={strategy.risks} title="策略风险" />
                <TextList
                  emptyText="暂无待补信息。"
                  items={strategy.missing_information}
                  title="待补信息"
                  tone="warning"
                />
              </ContentCard>
            ) : (
              <div
                className="rounded-lg border border-dashed border-zinc-300 bg-zinc-50 p-3"
                key={mode}
              >
                <p className="text-xs font-semibold text-zinc-700">{STRATEGY_LABELS[mode]}</p>
                <p className="mt-1 text-xs leading-5 text-zinc-500">该策略分支未返回结果。</p>
              </div>
            );
          })}
        </div>
      );
    case "document_draft":
      return (
        <div className="space-y-4">
          <InfoRow label="草稿标题" value={stage.draft_title || "未生成草稿标题"} />
          <TextList
            emptyText="暂无报告章节。"
            items={stage.draft_sections}
            title="草稿章节"
            numbered
          />
          <TextList
            emptyText="暂无质量检查项。"
            items={stage.quality_checks}
            title="质量检查"
          />
        </div>
      );
    case "deadline_management":
      return (
        <CardCollection title="期限与限制" emptyText="暂无可计算期限。">
          {stage.deadlines.map((deadline, index) => (
            <ContentCard key={`${deadline.name}-${index}`} title={deadline.name}>
              <div className="grid gap-2 sm:grid-cols-2">
                <InfoRow label="触发日期" value={deadline.trigger_date || "待确认"} />
                <InfoRow label="截止日期" value={deadline.deadline || "暂不可计算"} />
              </div>
              <p className="mt-3 rounded-md border border-amber-200 bg-amber-50 p-3 text-xs leading-5 text-amber-900">
                {deadline.uncertainty}
              </p>
              <CaseReferenceDetails refs={deadline.source_refs} />
            </ContentCard>
          ))}
        </CardCollection>
      );
  }
}

function StatusBadge({ status }: { status: StageStatus }) {
  return (
    <span
      className={cn(
        "shrink-0 rounded-md border px-2 py-1 text-[10px] font-semibold",
        STATUS_STYLES[status],
      )}
    >
      {STATUS_LABELS[status]}
    </span>
  );
}

function RiskBadge({ level }: { level: RiskLevel }) {
  return (
    <span
      className={cn(
        "inline-flex rounded-md border px-2.5 py-1 text-xs font-semibold",
        RISK_STYLES[level],
      )}
    >
      {RISK_LABELS[level]}
    </span>
  );
}

function statusTextColor(status: StageStatus): string {
  if (status === "succeeded") return "text-emerald-700";
  if (status === "needs_input") return "text-amber-700";
  if (status === "failed") return "text-rose-700";
  return "text-zinc-500";
}

function OverviewList({
  emptyText,
  items,
  title,
  tone = "default",
}: {
  emptyText: string;
  items: string[];
  title: string;
  tone?: "default" | "warning";
}) {
  return (
    <section
      className={cn(
        "rounded-xl border p-4",
        tone === "warning"
          ? "border-amber-200 bg-amber-50/60"
          : "border-zinc-200 bg-white",
      )}
    >
      <h3 className="text-sm font-semibold text-zinc-900">{title}</h3>
      <TextItems emptyText={emptyText} items={items} numbered={false} tone={tone} />
    </section>
  );
}

function TextList({
  className,
  emptyText,
  items,
  numbered = false,
  title,
  tone = "default",
}: {
  className?: string;
  emptyText: string;
  items: string[];
  numbered?: boolean;
  title: string;
  tone?: "default" | "warning";
}) {
  return (
    <section className={className}>
      <h4 className="text-xs font-semibold text-zinc-800">{title}</h4>
      <TextItems emptyText={emptyText} items={items} numbered={numbered} tone={tone} />
    </section>
  );
}

function TextItems({
  emptyText,
  items,
  numbered,
  tone,
}: {
  emptyText: string;
  items: string[];
  numbered: boolean;
  tone: "default" | "warning";
}) {
  return items.length > 0 ? (
    <ol className="mt-2 space-y-2">
      {items.map((item, index) => (
        <li className="flex gap-2 text-xs leading-5 text-zinc-600" key={`${item}-${index}`}>
          <span
            className={cn(
              "mt-0.5 shrink-0 font-mono text-[10px] font-semibold",
              tone === "warning" ? "text-amber-700" : "text-[#214a4b]",
            )}
          >
            {numbered ? String(index + 1).padStart(2, "0") : "•"}
          </span>
          <span className="min-w-0">{item}</span>
        </li>
      ))}
    </ol>
  ) : (
    <p className="mt-2 text-xs leading-5 text-zinc-500">{emptyText}</p>
  );
}

function CardCollection({
  children,
  emptyText,
  title,
}: {
  children: ReactNode;
  emptyText: string;
  title: string;
}) {
  const hasChildren = Array.isArray(children) ? children.length > 0 : Boolean(children);

  return (
    <section>
      <h4 className="text-xs font-semibold text-zinc-800">{title}</h4>
      {hasChildren ? (
        <div className="mt-2 space-y-3">{children}</div>
      ) : (
        <p className="mt-2 text-xs leading-5 text-zinc-500">{emptyText}</p>
      )}
    </section>
  );
}

function FindingCollection({
  emptyText,
  items,
  title,
}: {
  emptyText: string;
  items: CaseFinding[];
  title: string;
}) {
  return (
    <CardCollection emptyText={emptyText} title={title}>
      {items.map((item, index) => (
        <ContentCard key={`${item.title}-${index}`} title={item.title}>
          <p className="text-xs leading-5 text-zinc-600">{item.detail}</p>
          <CaseReferenceDetails refs={item.source_refs} />
        </ContentCard>
      ))}
    </CardCollection>
  );
}

function ContentCard({
  children,
  eyebrow,
  title,
  trailing,
}: {
  children: ReactNode;
  eyebrow?: string;
  title: string;
  trailing?: ReactNode;
}) {
  return (
    <article className="rounded-lg border border-zinc-200 bg-[#fafbf9] p-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          {eyebrow ? (
            <p className="break-words text-[10px] font-semibold uppercase tracking-wide text-[#4d746b]">
              {eyebrow}
            </p>
          ) : null}
          <p className={cn("break-words text-xs font-semibold text-zinc-900", eyebrow ? "mt-1" : "")}>
            {title}
          </p>
        </div>
        {trailing ? <div className="shrink-0">{trailing}</div> : null}
      </div>
      <div className="mt-3">{children}</div>
    </article>
  );
}

function InfoRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-zinc-200 bg-[#fafbf9] p-3">
      <p className="text-[10px] font-semibold uppercase tracking-wide text-zinc-500">{label}</p>
      <p className="mt-1 break-words text-xs leading-5 text-zinc-800">{value}</p>
    </div>
  );
}

function Timeline({ events }: { events: Extract<CaseStageResult, { stage: "fact_reconstruction" }>["timeline"] }) {
  return (
    <section>
      <h4 className="text-xs font-semibold text-zinc-800">事实时间线</h4>
      {events.length > 0 ? (
        <ol className="mt-3 space-y-3 border-l border-[#b9d8cc] pl-4">
          {events.map((event, index) => (
            <li className="relative" key={`${event.date}-${event.event}-${index}`}>
              <span
                aria-hidden="true"
                className="absolute -left-[1.31rem] top-1.5 h-2 w-2 rounded-full bg-[#214a4b] ring-4 ring-white"
              />
              <p className="text-[10px] font-semibold text-[#4d746b]">{event.date}</p>
              <p className="mt-1 text-xs leading-5 text-zinc-700">{event.event}</p>
              <p className="mt-1 text-[11px] text-zinc-500">
                {event.parties.length > 0 ? `相关方：${event.parties.join("、")}` : "相关方待确认"}
              </p>
              <CaseReferenceDetails refs={event.source_refs} />
            </li>
          ))}
        </ol>
      ) : (
        <p className="mt-2 text-xs leading-5 text-zinc-500">暂无可用时间线。</p>
      )}
    </section>
  );
}

function CaseReferenceDetails({ refs }: { refs: CaseSourceRef[] }) {
  return refs.length > 0 ? (
    <div className="mt-3 space-y-2">
      {refs.map((ref, index) => (
        <details
          className="rounded-md border border-zinc-200 bg-white px-3 py-2"
          key={`${ref.paragraph_id}-${index}`}
        >
          <summary className="cursor-pointer text-[11px] font-medium leading-5 text-[#315f5a] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#214a4b]/30">
            证据引用 · {formatParagraphRef(ref.paragraph_id)}
          </summary>
          <p className="mt-2 whitespace-pre-wrap break-words border-t border-zinc-100 pt-2 text-xs leading-5 text-zinc-600">
            {ref.quote}
          </p>
        </details>
      ))}
    </div>
  ) : (
    <p className="mt-3 text-[11px] leading-5 text-zinc-400">该项未绑定材料引用。</p>
  );
}

function formatParagraphRef(paragraphId: string): string {
  const number = Number(paragraphId.replace(/^p0*/i, ""));
  if (!Number.isFinite(number) || number <= 0) return paragraphId;
  return `第${number}段`;
}
