import { useEffect, useRef, useState } from "react";
import { searchCharacters } from "../api";
import type { CharacterCandidate } from "../types";

interface Props {
  novelId: string;
  onSelect: (c: CharacterCandidate) => void;
}

export default function CharacterSearch({ novelId, onSelect }: Props) {
  const [q, setQ] = useState("");
  const [candidates, setCandidates] = useState<CharacterCandidate[]>([]);
  const [open, setOpen] = useState(false);
  const timer = useRef<number | undefined>(undefined);

  useEffect(() => {
    window.clearTimeout(timer.current);
    if (!q.trim()) {
      setCandidates([]);
      return;
    }
    timer.current = window.setTimeout(async () => {
      try {
        const list = await searchCharacters(novelId, q.trim());
        setCandidates(list);
        setOpen(true);
      } catch {
        setCandidates([]);
      }
    }, 300);
    return () => window.clearTimeout(timer.current);
  }, [q, novelId]);

  return (
    <div style={{ marginBottom: 12 }}>
      <input
        style={{ width: 320, padding: 8, fontSize: 14 }}
        placeholder="输入人物名…"
        value={q}
        onChange={(e) => setQ(e.target.value)}
      />
      {open && candidates.length > 0 && (
        <ul style={{ listStyle: "none", margin: 0, padding: 0, border: "1px solid #ccc", maxWidth: 320 }}>
          {candidates.map((c) => (
            <li
              key={c.id}
              style={{ padding: 8, cursor: "pointer" }}
              onClick={() => {
                setOpen(false);
                onSelect(c);
              }}
            >
              {c.name}（出现 {c.mention_count} 块）
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
