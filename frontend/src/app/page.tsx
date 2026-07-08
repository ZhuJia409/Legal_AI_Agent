import { BookOpen, Bot, Database, FileText } from "lucide-react";

const modules = [
  {
    title: "智能体编排",
    description: "LangChain、LangGraph、DeepAgents 已纳入后端技术栈配置。",
    icon: Bot,
  },
  {
    title: "法律 RAG",
    description: "默认 embedding 为 BAAI/bge-m3，reranker 为 Qwen/Qwen3-Reranker-4B。",
    icon: BookOpen,
  },
  {
    title: "多数据库",
    description: "MySQL、Milvus、Redis、MongoDB、MinIO 将通过本地 compose 管理。",
    icon: Database,
  },
  {
    title: "文档工作台",
    description: "上传、解析、引用来源展示和会话界面将在后续业务阶段实现。",
    icon: FileText,
  },
];

export default function Home() {
  return (
    <main className="min-h-screen bg-stone-50 text-zinc-950">
      <section className="mx-auto flex min-h-screen w-full max-w-6xl flex-col justify-center px-6 py-12">
        <div className="max-w-3xl">
          <p className="text-sm font-medium text-sky-700">Legal AI Agent</p>
          <h1 className="mt-3 text-4xl font-semibold tracking-normal text-zinc-950 md:text-6xl">
            法律智能体应用配置台
          </h1>
          <p className="mt-5 max-w-2xl text-base leading-7 text-zinc-600">
            当前阶段完成前端框架、后端框架、AI 应用框架和本地基础设施配置，
            后续可在此基础上继续实现法律问答、文档分析和案件材料整理工作流。
          </p>
        </div>

        <div className="mt-10 grid gap-4 md:grid-cols-2">
          {modules.map((item) => {
            const Icon = item.icon;
            return (
              <article
                className="rounded-lg border border-zinc-200 bg-white p-5 shadow-sm"
                key={item.title}
              >
                <div className="flex items-start gap-4">
                  <div className="rounded-md bg-sky-50 p-2 text-sky-700">
                    <Icon aria-hidden="true" className="h-5 w-5" />
                  </div>
                  <div>
                    <h2 className="text-base font-semibold text-zinc-950">{item.title}</h2>
                    <p className="mt-2 text-sm leading-6 text-zinc-600">{item.description}</p>
                  </div>
                </div>
              </article>
            );
          })}
        </div>
      </section>
    </main>
  );
}
