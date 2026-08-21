/**
 * 人物搜索：250ms 防抖 → searchCharacters(novelId, q) → 联想列表（最多 8 条）。
 * 结构/类名/文案逐字取自 design/novel-graph-workbench.html 的搜索段（唯一事实来源）：
 * .search/.search-box/.search-icon/.search-input/.search-clear + .suggest（.suggest-head/.suggest-row/.sr-name/.sr-hl/.sr-meta/.sr-arrow/.suggest-empty）。
 * 交互：Esc 关闭、点击外部关闭、选中后清空输入并调 onSelect。
 */
import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { searchCharacters } from "../api";
import type { CharacterCandidate } from "../types";
import { ArrowRightIcon, CloseIcon, SearchIcon } from "./icons";

interface Props {
  novelId: string;
  onSelect: (c: CharacterCandidate) => void;
}

const fmt = (n: number) => n.toLocaleString("en-US");
const MAX_RESULTS = 8;
const DEBOUNCE_MS = 250;

/** 命中高亮：indexOf 定位，与 workbench highlight() 一致 */
function highlight(name: string, q: string): ReactNode {
  const i = name.indexOf(q);
  if (i < 0) return name;
  return (
    <>
      {name.slice(0, i)}
      <span className="sr-hl">{name.slice(i, i + q.length)}</span>
      {name.slice(i + q.length)}
    </>
  );
}

export default function CharacterSearch({ novelId, onSelect }: Props) {
  const [q, setQ] = useState("");
  const [candidates, setCandidates] = useState<CharacterCandidate[]>([]);
  const [searched, setSearched] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const timer = useRef<number | undefined>(undefined);
  const latestQ = useRef("");

  // 切换小说时清空搜索
  useEffect(() => {
    setQ("");
    setCandidates([]);
    setSearched(false);
    latestQ.current = "";
  }, [novelId]);

  // 250ms 防抖搜索（丢弃过期响应）
  useEffect(() => {
    window.clearTimeout(timer.current);
    const query = q.trim();
    latestQ.current = query;
    if (!query) {
      setCandidates([]);
      setSearched(false);
      return;
    }
    timer.current = window.setTimeout(async () => {
      try {
        const list = await searchCharacters(novelId, query);
        if (latestQ.current !== query) return;
        setCandidates(list.slice(0, MAX_RESULTS));
        setSearched(true);
      } catch {
        if (latestQ.current !== query) return;
        setCandidates([]);
        setSearched(false);
      }
    }, DEBOUNCE_MS);
    return () => window.clearTimeout(timer.current);
  }, [q, novelId]);

  // 点击搜索框外部关闭联想
  useEffect(() => {
    function onDocClick(e: MouseEvent) {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) {
        setSearched(false);
      }
    }
    document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, []);

  const open = q.trim() !== "" && searched;

  function clear() {
    setQ("");
    setCandidates([]);
    setSearched(false);
    inputRef.current?.focus();
  }

  function select(c: CharacterCandidate) {
    setQ("");
    setCandidates([]);
    setSearched(false);
    onSelect(c);
  }

  return (
    <div className="search" ref={rootRef}>
      <div className="search-box">
        <SearchIcon className="search-icon" />
        <input
          ref={inputRef}
          className="search-input"
          placeholder="搜索人物，如 黛玉 / 凤姐"
          value={q}
          autoComplete="off"
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Escape") {
              setSearched(false);
              inputRef.current?.blur();
            }
          }}
        />
        {q !== "" && (
          <button type="button" className="search-clear" aria-label="清空" onClick={clear}>
            <CloseIcon size={12} />
          </button>
        )}
      </div>
      {open && (
        <div className="suggest">
          {candidates.length > 0 ? (
            <>
              <div className="suggest-head">联想结果 · {candidates.length} 位人物</div>
              {candidates.map((c) => (
                <button key={c.id} type="button" className="suggest-row" onClick={() => select(c)}>
                  <span className="sr-name">{highlight(c.name, q.trim())}</span>
                  <span className="sr-meta">
                    <span>提及</span>
                    <span>{fmt(c.mention_count)}</span>
                    <ArrowRightIcon className="sr-arrow" size={14} />
                  </span>
                </button>
              ))}
            </>
          ) : (
            <div className="suggest-empty">没有匹配的人物，试试 黛玉 / 凤姐 / 贾母</div>
          )}
        </div>
      )}
    </div>
  );
}
