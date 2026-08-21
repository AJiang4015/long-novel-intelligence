/**
 * App —— 工作台壳 + 状态机（spec §3）：持有全部数据与状态，组件纯 UI。
 *
 * - phase: "empty" | "processing" | "graph"
 * - 上传抽屉 → POST 提交 → phase=processing → 1s 轮询 getJob
 *   → completed / completed_with_errors → getNovel → 恢复中心 → phase=graph + toast
 *   → failed → ErrorBanner（保留 job 展示错误），phase 回 "empty"
 * - 中心人物切换：setCenter + localStorage 持久化（wb-center:{novel_id}，同小说内恢复）
 *   → getGraph 真实加载（cancelled flag 防竞态，无假延迟）
 * - 边选中：selectedEdge 联动右侧 DetailsPanel
 * - 数字一律 en-US 千分位逗号（1,000，禁止空格）
 */
import { useEffect, useRef, useState } from "react";
import Topbar from "./components/Topbar";
import LeftSidebar from "./components/LeftSidebar";
import GraphPanel from "./components/GraphPanel";
import DetailsPanel from "./components/DetailsPanel";
import UploadDrawer from "./components/UploadDrawer";
import ExistingNovelPicker from "./components/ExistingNovelPicker";
import Toast from "./components/Toast";
import ErrorBanner from "./components/ErrorBanner";
import { getGraph, getJob, getNovel, listNovels } from "./api";
import type {
  CharacterCandidate,
  GraphEdge,
  GraphResponse,
  JobResponse,
  JobStatus,
  NovelListItem,
  NovelResponse,
} from "./types";

type Phase = "empty" | "processing" | "graph";

interface ToastState {
  msg: string;
  kind: "info" | "success";
}

/** 千分位（spec §5：en-US 恒定逗号，禁止空格） */
const fmt = (n: number) => n.toLocaleString("en-US");

/** localStorage 中心人物形状校验（恢复前防脏数据） */
function isCandidate(c: unknown): c is CharacterCandidate {
  if (typeof c !== "object" || c === null) return false;
  const o = c as Record<string, unknown>;
  return (
    typeof o.id === "string" &&
    typeof o.name === "string" &&
    typeof o.mention_count === "number"
  );
}

export default function App() {
  const [phase, setPhase] = useState<Phase>("empty");
  const [novel, setNovel] = useState<NovelResponse | null>(null);
  const [job, setJob] = useState<JobResponse | null>(null);
  const [center, setCenter] = useState<CharacterCandidate | null>(null);
  const [graph, setGraph] = useState<GraphResponse | null>(null);
  const [selectedEdge, setSelectedEdge] = useState<GraphEdge | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [existingNovels, setExistingNovels] = useState<NovelListItem[]>([]);
  const [graphLoading, setGraphLoading] = useState(false);
  const [toast, setToast] = useState<ToastState | null>(null);
  const toastTimer = useRef<number | undefined>(undefined);

  /** 顶栏状态：处理中显示实时 job 状态；graph 阶段（有小说）显示已完成 */
  const status: JobStatus | null =
    phase === "processing" ? (job?.status ?? null) : novel ? "completed" : null;

  /**
   * 启动探测：恢复已有小说（spec 三分支）——
   * 0 本 → 空态 + 自动弹上传抽屉；1 本 → 自动恢复；多本 → 打开选择器。
   * listNovels 失败 → 静默回退空态 + 抽屉，console.warn 保留诊断日志（Neo4j/API 排查）。
   */
  useEffect(() => {
    let cancelled = false;
    listNovels()
      .then((list) => {
        if (cancelled) return;
        if (list.length === 0) {
          setDrawerOpen(true);
        } else if (list.length === 1) {
          void loadNovel(list[0]);
        } else {
          setExistingNovels(list);
          setPickerOpen(true);
        }
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        console.warn("[novel-recovery] listNovels 失败，回退空态（检查后端/Neo4j 是否可用）：", err);
        setDrawerOpen(true);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  /**
   * 恢复已有小说：getNovel 填详情 → phase=graph → 复用 restoreCenter。
   * 无 wb-center:{novel_id} 时 center 保持 null → GraphPanel「选择人物」空态，不弹 UploadDrawer（约束 1）。
   */
  async function loadNovel(item: NovelListItem) {
    setPickerOpen(false);
    setDrawerOpen(false);
    setJob(null);
    setGraph(null);
    setSelectedEdge(null);
    try {
      const n = await getNovel(item.id);
      setNovel(n);
    } catch (err) {
      console.warn("[novel-recovery] getNovel 失败：", err);
      setNovel(null);
    }
    restoreCenter(item.id);
    setPhase("graph");
  }

  /** 卸载时清理 toast 计时器 */
  useEffect(() => () => window.clearTimeout(toastTimer.current), []);

  /** 轻提示：自动 2.6s 隐藏（workbench toast 时长）；重复触发重置计时 */
  function showToast(msg: string, kind: "info" | "success" = "success") {
    window.clearTimeout(toastTimer.current);
    setToast({ msg, kind });
    toastTimer.current = window.setTimeout(() => setToast(null), 2600);
  }

  /** 从 localStorage 恢复中心（key 带 novel_id 作用域，换小说不串） */
  function restoreCenter(novelId: string) {
    try {
      const raw = localStorage.getItem(`wb-center:${novelId}`);
      if (!raw) return;
      const parsed: unknown = JSON.parse(raw);
      if (isCandidate(parsed)) setCenter(parsed);
    } catch {
      /* 存储损坏/解析失败：忽略，回退到未选中心 */
    }
  }

  /** 上传成功：关抽屉、清空旧数据、setJob 初始对象、进入 processing */
  function handleUploaded(novelId: string, jobId: string) {
    setDrawerOpen(false);
    setNovel(null);
    setCenter(null);
    setGraph(null);
    setSelectedEdge(null);
    setJob({
      job_id: jobId,
      novel_id: novelId,
      status: "pending",
      progress: { done_chunks: 0, total_chunks: 0 },
      failed_blocks: [],
      stats: {},
    });
    setPhase("processing");
  }

  /**
   * processing 阶段 1s 轮询 getJob（沿用旧 Progress 写法：cancelled flag + 终态判断）。
   * 依赖 job?.job_id：同一上传期间 job_id 不变，轮询期间 effect 不重建。
   */
  useEffect(() => {
    if (phase !== "processing" || !job?.job_id) return;
    const jobId = job.job_id;
    let cancelled = false;

    const timer = window.setInterval(async () => {
      try {
        const j = await getJob(jobId);
        if (cancelled) return;
        setJob(j);

        if (j.status === "completed" || j.status === "completed_with_errors") {
          window.clearInterval(timer);
          try {
            const n = await getNovel(j.novel_id);
            if (cancelled) return;
            setNovel(n);
          } catch {
            /* getNovel 失败不阻塞进入 graph（中心/图仍可独立加载） */
          }
          if (cancelled) return;
          restoreCenter(j.novel_id);
          setPhase("graph");
          showToast(
            `分析完成 · 人物 ${fmt(j.stats?.persons ?? 0)} · 关系 ${fmt(j.stats?.relationships ?? 0)}`
          );
        } else if (j.status === "failed") {
          window.clearInterval(timer);
          setPhase("empty"); // 保留 job 供 ErrorBanner 展示错误
        }
      } catch {
        /* 轮询瞬时错误忽略，下一轮重试 */
      }
    }, 1000);

    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [phase, job?.job_id]);

  /**
   * 中心人物变化（graph 阶段）→ 真实时序加载子图：
   * setGraphLoading(true) → getGraph → setGraph / setSelectedEdge(null) → finally 关闭遮罩。
   */
  useEffect(() => {
    if (phase !== "graph" || !center) return;
    let cancelled = false;
    setGraphLoading(true);
    getGraph(center.id)
      .then((g) => {
        if (cancelled) return;
        setGraph(g);
        setSelectedEdge(null);
      })
      .catch(() => {
        if (cancelled) return;
        setGraph(null);
        setSelectedEdge(null);
      })
      .finally(() => {
        if (!cancelled) setGraphLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [phase, center]);

  /** 点击邻居节点 → 切换中心 + localStorage 持久化 + toast */
  function handleNodeClick(id: string) {
    const node = graph?.nodes.find((n) => n.id === id);
    if (!node || !novel) return;
    const candidate: CharacterCandidate = {
      id: node.id,
      name: node.name,
      mention_count: node.mention_count,
    };
    setCenter(candidate);
    try {
      localStorage.setItem(`wb-center:${novel.id}`, JSON.stringify(candidate));
    } catch {
      /* localStorage 不可用（隐私模式等）：仅跳过持久化 */
    }
    showToast(`已将「${node.name}」设为中心人物`, "info");
  }

  return (
    <>
      <Topbar
        novelTitle={novel?.title ?? null}
        status={status}
        onUploadClick={() => setDrawerOpen(true)}
      />
      {phase === "empty" && job?.status === "failed" && (
        <ErrorBanner title="分析失败" detail={job.error ?? undefined} />
      )}
      <div className="shell">
        <LeftSidebar
          novel={novel}
          job={job}
          phase={phase}
          center={center}
          graph={graph}
          onSelectCharacter={(c) => setCenter(c)}
        />
        <div className="center">
          <GraphPanel
            graph={graph}
            center={center}
            selectedEdge={selectedEdge}
            graphLoading={graphLoading}
            processing={phase === "processing"}
            job={job}
            novelTitle={novel?.title}
            onNodeClick={handleNodeClick}
            onEdgeClick={setSelectedEdge}
          />
        </div>
        <div className="right">
          <DetailsPanel
            graph={graph}
            selectedEdge={selectedEdge}
            onClose={() => setSelectedEdge(null)}
          />
        </div>
      </div>
      <UploadDrawer
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        onUploaded={handleUploaded}
      />
      <ExistingNovelPicker
        open={pickerOpen}
        novels={existingNovels}
        onClose={() => setPickerOpen(false)}
        onSelect={(item) => void loadNovel(item)}
      />
      <Toast message={toast?.msg ?? null} kind={toast?.kind ?? "success"} />
    </>
  );
}
