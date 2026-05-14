import Editor from "@monaco-editor/react";
import { useMemo, useState } from "react";
import { api } from "../../lib/api";

type CodingFile = {
  id: string;
  name: string;
  language: "javascript" | "python" | "typescript" | "sql";
  value: string;
};

const STARTER_FILES: CodingFile[] = [
  {
    id: "main-js",
    name: "main.js",
    language: "javascript",
    value: [
      "function reconcileLedger(entries) {",
      "  return entries.reduce((total, entry) => total + entry.debit - entry.credit, 0);",
      "}",
      "",
      "const entries = [",
      "  { debit: 1200, credit: 0 },",
      "  { debit: 0, credit: 450 },",
      "  { debit: 300, credit: 0 },",
      "];",
      "",
      "console.log('Ledger balance:', reconcileLedger(entries));",
    ].join("\n"),
  },
  {
    id: "tests-js",
    name: "tests.js",
    language: "javascript",
    value: [
      "function assertEqual(actual, expected, label) {",
      "  if (actual !== expected) throw new Error(`${label}: expected ${expected}, got ${actual}`);",
      "  console.log(`PASS: ${label}`);",
      "}",
      "",
      "assertEqual(2 + 2, 4, 'basic arithmetic');",
    ].join("\n"),
  },
  {
    id: "notes-py",
    name: "analysis.py",
    language: "python",
    value: [
      "def normalize_invoice(amount):",
      "    return round(float(amount), 2)",
      "",
      "print('Normalized:', normalize_invoice('1299.456'))",
    ].join("\n"),
  },
];

const LANGUAGE_LABELS: Record<CodingFile["language"], string> = {
  javascript: "JavaScript",
  typescript: "TypeScript",
  python: "Python",
  sql: "SQL",
};

function cloneStarterFiles(): CodingFile[] {
  return STARTER_FILES.map((file) => ({ ...file }));
}

function serializeWorkerValue(value: unknown): string {
  if (typeof value === "string") return value;
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

async function runCode(language: "javascript" | "python", code: string): Promise<string[]> {
  const { data } = await api.post<{
    stdout: string;
    stderr: string;
    timed_out: boolean;
    exit_code: number | null;
  }>("/tools/coding/run", { language, code });

  const lines = [
    ...(data.stdout ? data.stdout.split(/\r?\n/) : []),
    ...(data.stderr ? data.stderr.split(/\r?\n/) : []),
  ].filter(Boolean);

  if (data.timed_out) return lines.length ? lines : ["Execution timed out after 3 seconds."];
  return lines.length ? lines : [`Process exited with code ${data.exit_code ?? "unknown"}.`];
}

export function CodingEnv() {
  const [files, setFiles] = useState<CodingFile[]>(() => cloneStarterFiles());
  const [activeFileId, setActiveFileId] = useState(STARTER_FILES[0].id);
  const [output, setOutput] = useState<string[]>(["Ready. Open a JavaScript file and click Run."]);
  const [isRunning, setIsRunning] = useState(false);

  const activeFile = useMemo(
    () => files.find((file) => file.id === activeFileId) ?? files[0],
    [activeFileId, files],
  );

  const canRun = activeFile?.language === "javascript" || activeFile?.language === "python";

  const updateActiveFile = (patch: Partial<CodingFile>) => {
    setFiles((current) =>
      current.map((file) => (file.id === activeFile.id ? { ...file, ...patch } : file)),
    );
  };

  const createFile = () => {
    const rawName = window.prompt("File name", "main.py")?.trim();
    if (!rawName) return;
    const extension = rawName.split(".").pop()?.toLowerCase();
    const language: CodingFile["language"] =
      extension === "py" ? "python" : extension === "ts" ? "typescript" : extension === "sql" ? "sql" : "javascript";
    const nextFile: CodingFile = {
      id: `scratch-${Date.now()}`,
      name: rawName,
      language,
      value: language === "python" ? "print('New Python file')" : "console.log('New coding task file');",
    };
    setFiles((current) => [...current, nextFile]);
    setActiveFileId(nextFile.id);
  };

  const renameActiveFile = () => {
    const rawName = window.prompt("Rename file", activeFile.name)?.trim();
    if (!rawName) return;
    updateActiveFile({ name: rawName });
  };

  const deleteActiveFile = () => {
    if (files.length <= 1) {
      setOutput(["Keep at least one file in the workspace."]);
      return;
    }
    setFiles((current) => current.filter((file) => file.id !== activeFile.id));
    setActiveFileId(files.find((file) => file.id !== activeFile.id)?.id ?? files[0].id);
  };

  const resetWorkspace = () => {
    const resetFiles = cloneStarterFiles();
    setFiles(resetFiles);
    setActiveFileId(resetFiles[0].id);
    setOutput(["Workspace reset to starter files."]);
  };

  const runActiveFile = async () => {
    if (!activeFile) return;
    if (!canRun) {
      setOutput([
        `${LANGUAGE_LABELS[activeFile.language]} execution needs a backend sandbox executor.`,
        "Current runner supports JavaScript and Python.",
      ]);
      return;
    }

    setIsRunning(true);
    setOutput([`Running ${activeFile.name}...`]);
    try {
      const runnableLanguage = activeFile.language === "python" ? "python" : "javascript";
      const result = await runCode(runnableLanguage, activeFile.value);
      setOutput(result.map(serializeWorkerValue));
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setOutput([`Runner request failed: ${message}`]);
    }
    setIsRunning(false);
  };

  if (!activeFile) return null;

  return (
    <div className="item coding-env coding-env-fullscreen">
      <div className="tool-header">
        <div>
          <strong>Coding Env</strong>
          <small>Dedicated assessment IDE with JavaScript and Python execution.</small>
        </div>
        <div className="row">
          <button type="button" onClick={createFile}>New File</button>
          <button type="button" onClick={renameActiveFile}>Rename</button>
          <button type="button" onClick={deleteActiveFile}>Delete</button>
          <button type="button" onClick={resetWorkspace}>Reset</button>
          <button type="button" onClick={runActiveFile} disabled={isRunning}>
            {isRunning ? "Running..." : "Run"}
          </button>
        </div>
      </div>

      <div className="coding-layout">
        <aside className="coding-sidebar">
          <strong>Files</strong>
          {files.map((file) => (
            <button
              className={file.id === activeFile.id ? "file-tab active" : "file-tab"}
              key={file.id}
              type="button"
              onClick={() => setActiveFileId(file.id)}
            >
              <span>{file.name}</span>
              <small>{LANGUAGE_LABELS[file.language]}</small>
            </button>
          ))}
        </aside>

        <section className="coding-main">
          <div className="row coding-toolbar">
            <strong>{activeFile.name}</strong>
            <select
              aria-label="Language"
              value={activeFile.language}
              onChange={(event) =>
                updateActiveFile({ language: event.target.value as CodingFile["language"] })
              }
            >
              {Object.entries(LANGUAGE_LABELS).map(([value, label]) => (
                <option key={value} value={value}>{label}</option>
              ))}
            </select>
            <small>{canRun ? "Backend runner active" : "Edit-only until backend runner is connected"}</small>
          </div>

          <div className="editor-frame">
            <Editor
              height="430px"
              language={activeFile.language}
              onChange={(value) => updateActiveFile({ value: value ?? "" })}
              options={{
                automaticLayout: true,
                fontSize: 14,
                minimap: { enabled: false },
                scrollBeyondLastLine: false,
                tabSize: 2,
                wordWrap: "on",
              }}
              theme="vs-dark"
              value={activeFile.value}
            />
          </div>

          <div className="console-panel">
            <strong>Console</strong>
            <pre>{output.join("\n")}</pre>
          </div>
        </section>
      </div>
    </div>
  );
}
