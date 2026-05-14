import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../../lib/api";

const ROWS = 12;
const COLS = 8;

function colLabel(col: number): string {
  return String.fromCharCode("A".charCodeAt(0) + col);
}

function parseRef(ref: string): { row: number; col: number } | null {
  const m = /^([A-Z]+)(\d+)$/.exec(ref.trim().toUpperCase());
  if (!m) return null;
  const letters = m[1];
  const row = Number(m[2]) - 1;
  let col = 0;
  for (let i = 0; i < letters.length; i += 1) col = col * 26 + (letters.charCodeAt(i) - 64);
  col -= 1;
  if (row < 0 || col < 0) return null;
  return { row, col };
}

function keyFor(row: number, col: number): string {
  return `${colLabel(col)}${row + 1}`;
}

export function ExcelSimulator() {
  const [cells, setCells] = useState<Record<string, string>>({});
  const graphStatus = useQuery({
    queryKey: ["excel-graph-status"],
    queryFn: async () => (await api.get("/tools/excel/graph/status")).data,
    retry: false,
  });

  const getRaw = (row: number, col: number): string => cells[keyFor(row, col)] ?? "";

  const values = useMemo(() => {
    const memo: Record<string, string | number> = {};

    const resolve = (ref: string, stack: Set<string>): string | number => {
      if (memo[ref] !== undefined) return memo[ref];
      if (stack.has(ref)) return "#CYCLE!";
      stack.add(ref);
      const raw = (cells[ref] ?? "").trim();
      if (!raw.startsWith("=")) {
        const asNum = Number(raw);
        memo[ref] = raw !== "" && Number.isFinite(asNum) ? asNum : raw;
        stack.delete(ref);
        return memo[ref];
      }

      const body = raw.slice(1).trim();
      const sumMatch = /^SUM\((.+)\)$/i.exec(body);
      if (sumMatch) {
        const arg = sumMatch[1].trim();
        const range = /^([A-Z]+\d+):([A-Z]+\d+)$/i.exec(arg);
        let total = 0;
        if (range) {
          const a = parseRef(range[1]);
          const b = parseRef(range[2]);
          if (a && b) {
            const r1 = Math.min(a.row, b.row);
            const r2 = Math.max(a.row, b.row);
            const c1 = Math.min(a.col, b.col);
            const c2 = Math.max(a.col, b.col);
            for (let r = r1; r <= r2; r += 1) {
              for (let c = c1; c <= c2; c += 1) {
                const v = resolve(keyFor(r, c), stack);
                const n = Number(v);
                if (Number.isFinite(n)) total += n;
              }
            }
            memo[ref] = total;
            stack.delete(ref);
            return total;
          }
        }
      }

      const vlookupMatch = /^VLOOKUP\(([^,]+),([^,]+),([^,]+),([^)]+)\)$/i.exec(body);
      if (vlookupMatch) {
        const lookupToken = vlookupMatch[1].trim();
        const rangeToken = vlookupMatch[2].trim();
        const colIndexToken = vlookupMatch[3].trim();
        const exactToken = vlookupMatch[4].trim().toUpperCase();
        const lookupValue = lookupToken.replace(/^"|"$/g, "");
        const range = /^([A-Z]+\d+):([A-Z]+\d+)$/i.exec(rangeToken);
        const colIndex = Number(colIndexToken);
        const exact = exactToken === "FALSE" || exactToken === "0";
        if (range && Number.isFinite(colIndex) && colIndex >= 1 && exact) {
          const a = parseRef(range[1]);
          const b = parseRef(range[2]);
          if (a && b) {
            const r1 = Math.min(a.row, b.row);
            const r2 = Math.max(a.row, b.row);
            const c1 = Math.min(a.col, b.col);
            const targetCol = c1 + (Math.floor(colIndex) - 1);
            for (let r = r1; r <= r2; r += 1) {
              const first = String(resolve(keyFor(r, c1), stack));
              if (first === lookupValue) {
                const out = resolve(keyFor(r, targetCol), stack);
                memo[ref] = out;
                stack.delete(ref);
                return out;
              }
            }
            memo[ref] = "#N/A";
            stack.delete(ref);
            return "#N/A";
          }
        }
      }

      const replaced = body.replace(/\b([A-Z]+\d+)\b/g, (_m, r) => {
        const v = resolve(String(r).toUpperCase(), stack);
        const n = Number(v);
        return Number.isFinite(n) ? String(n) : "0";
      });
      if (!/^[\d+\-*/().\s]+$/.test(replaced)) {
        memo[ref] = "#ERR";
        stack.delete(ref);
        return "#ERR";
      }
      try {
        // eslint-disable-next-line no-new-func
        const val = Function(`"use strict"; return (${replaced});`)();
        memo[ref] = Number.isFinite(Number(val)) ? Number(val) : "#ERR";
      } catch {
        memo[ref] = "#ERR";
      }
      stack.delete(ref);
      return memo[ref];
    };

    Object.keys(cells).forEach((ref) => resolve(ref, new Set()));
    return memo;
  }, [cells]);

  return (
    <div className="item">
      <strong>Excel Simulator (Dev)</strong>
      <small>
        Microsoft Graph Excel: {graphStatus.data?.configured ? "configured" : "not configured"}
        {Array.isArray(graphStatus.data?.missing) && graphStatus.data.missing.length ? ` (${graphStatus.data.missing.join(", ")})` : ""}
      </small>
      <small>Supports values, arithmetic refs (`=A1+B1`), `SUM(A1:A5)`, `VLOOKUP(\"k\",A1:B5,2,FALSE)`.</small>
      <div style={{ overflowX: "auto", marginTop: 8 }}>
        <table style={{ borderCollapse: "collapse", minWidth: 760 }}>
          <thead>
            <tr>
              <th style={{ border: "1px solid #dbe4f0", padding: 6, background: "#f5f8ff" }}>#</th>
              {Array.from({ length: COLS }).map((_, c) => (
                <th key={c} style={{ border: "1px solid #dbe4f0", padding: 6, background: "#f5f8ff" }}>{colLabel(c)}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {Array.from({ length: ROWS }).map((_, r) => (
              <tr key={r}>
                <td style={{ border: "1px solid #dbe4f0", padding: 6, background: "#f5f8ff" }}>{r + 1}</td>
                {Array.from({ length: COLS }).map((_, c) => {
                  const ref = keyFor(r, c);
                  return (
                    <td key={ref} style={{ border: "1px solid #dbe4f0", padding: 4 }}>
                      <input
                        value={getRaw(r, c)}
                        onChange={(e) => setCells((prev) => ({ ...prev, [ref]: e.target.value }))}
                        placeholder={String(values[ref] ?? "")}
                        style={{ width: 90 }}
                      />
                      <div style={{ fontSize: 11, color: "#4b5563", marginTop: 2 }}>{String(values[ref] ?? "")}</div>
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
