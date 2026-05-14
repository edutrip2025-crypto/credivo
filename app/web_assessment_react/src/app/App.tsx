import { useState } from "react";
import { AuthPanel } from "../features/auth/AuthPanel";
import { ProviderAssessments } from "../features/provider/ProviderAssessments";
import { StudentAssessments } from "../features/student/StudentAssessments";
import { IssuedCandidatePanel } from "../features/issued/IssuedCandidatePanel";
import { useSessionStore } from "../lib/sessionStore";

type View = "provider" | "student" | "issued";

export function App() {
  const [view, setView] = useState<View>("provider");
  const role = useSessionStore((s) => s.role);

  return (
    <div className="shell">
      <header className="header">
        <div className="brand">
          <img src="/assessment/credivo_logo.png" alt="Credivo" />
          <div>
            <span>Credivo</span>
            <h1>Assessment Console</h1>
          </div>
        </div>
        <div className="tabs">
          <button onClick={() => setView("provider")} className={view === "provider" ? "active" : ""}>Provider</button>
          <button onClick={() => setView("student")} className={view === "student" ? "active" : ""}>Student</button>
          <button onClick={() => setView("issued")} className={view === "issued" ? "active" : ""}>Issued Candidate</button>
        </div>
      </header>
      <AuthPanel />
      {view === "provider" && (role === "provider" || role === "admin") && <ProviderAssessments />}
      {view === "student" && role === "student" && <StudentAssessments />}
      {view === "issued" && <IssuedCandidatePanel />}
      {view === "provider" && role !== "provider" && role !== "admin" && (
        <section className="card"><small>Login as provider/admin to use provider workflow.</small></section>
      )}
      {view === "student" && role !== "student" && (
        <section className="card"><small>Login as student to use student assessment workflow.</small></section>
      )}
    </div>
  );
}
