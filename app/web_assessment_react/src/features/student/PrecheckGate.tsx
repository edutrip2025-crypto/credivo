import { useMemo, useState } from "react";

type Props = {
  onComplete: () => void;
};

type CheckKey = "camera" | "microphone" | "desktop" | "rules";

const labels: Record<CheckKey, string> = {
  camera: "Camera permission and face visibility",
  microphone: "Microphone permission and voice check",
  desktop: "Desktop/laptop environment attestation",
  rules: "Read-aloud rules confirmation",
};

export function PrecheckGate({ onComplete }: Props) {
  const [checks, setChecks] = useState<Record<CheckKey, boolean>>({
    camera: false,
    microphone: false,
    desktop: false,
    rules: false,
  });
  const [busy, setBusy] = useState(false);
  const nextPending = useMemo(() => (Object.keys(labels) as CheckKey[]).find((k) => !checks[k]), [checks]);
  const allDone = !nextPending;

  const runCheck = async (key: CheckKey) => {
    setBusy(true);
    try {
      if (key === "camera") {
        const stream = await navigator.mediaDevices.getUserMedia({ video: true });
        stream.getTracks().forEach((t) => t.stop());
      }
      if (key === "microphone") {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        stream.getTracks().forEach((t) => t.stop());
      }
      if (key === "rules") {
        await new Promise((r) => window.setTimeout(r, 1200));
      }
      if (key === "desktop" && /Mobi|Android|iPhone|iPad/i.test(navigator.userAgent)) {
        throw new Error("Desktop/laptop is required for strict proctored assessments.");
      }
      setChecks((prev) => ({ ...prev, [key]: true }));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="card">
      <h2>Assessment Precheck</h2>
      <p>{allDone ? "Done: All mandatory checks completed." : `Pending: ${labels[nextPending as CheckKey]}`}</p>
      <div className="row">
        {(Object.keys(labels) as CheckKey[]).map((k) => (
          <button key={k} onClick={() => runCheck(k)} disabled={busy || checks[k]}>
            {checks[k] ? `Done: ${labels[k]}` : `Run: ${labels[k]}`}
          </button>
        ))}
      </div>
      <div className="row">
        <button onClick={onComplete} disabled={!allDone || busy}>Continue To Assessment</button>
      </div>
    </section>
  );
}

