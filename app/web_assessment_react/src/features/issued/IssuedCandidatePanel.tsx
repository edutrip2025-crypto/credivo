import { useEffect, useMemo, useState } from "react";
import { api } from "../../lib/api";
import { useAssessmentTimer } from "../student/useAssessmentTimer";

type IssuedOption = { id: number; text: string };
type IssuedQuestion = { question_id: number; question_text: string; question_type: string; options: IssuedOption[] };
type IssuedExam = {
  issued_id: number;
  assessment_title: string;
  assessment_type: string;
  duration_minutes: number;
  timing_mode: "question" | "assessment";
  time_per_question_seconds: number | null;
  questions: IssuedQuestion[];
  status: string;
  score_pct?: number;
  passed?: boolean;
};

export function IssuedCandidatePanel() {
  const [token, setToken] = useState<string>("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [paper, setPaper] = useState<IssuedExam | null>(null);
  const [index, setIndex] = useState(0);
  const [answers, setAnswers] = useState<Record<number, number[]>>({});
  const [status, setStatus] = useState("");
  const [accessKey, setAccessKey] = useState("");

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const key = String(params.get("issued_key") || "").trim();
    if (key) setAccessKey(key);
  }, []);

  const issuedApi = async <T,>(method: "GET" | "POST", path: string, body?: unknown) => {
    const response = await api.request<T>({
      method,
      url: path,
      data: body,
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    return response.data;
  };

  const loadMe = async (newToken: string) => {
    setToken(newToken);
    const response = await api.request<IssuedExam>({
      method: "GET",
      url: "/exams/issued/me",
      headers: { Authorization: `Bearer ${newToken}` },
    });
    const me = response.data;
    if (me.status === "completed") {
      setPaper(null);
      setStatus(`Already completed. Score ${Number(me.score_pct || 0).toFixed(2)}%`);
      return;
    }
    setPaper(me);
    setIndex(0);
    setAnswers({});
    setStatus("");
  };

  const login = async () => {
    const auth = accessKey
      ? await api.post(`/exams/issued/key/${encodeURIComponent(accessKey)}/login`, { password })
      : await api.post("/exams/issued/login", { email, password });
    await loadMe(String(auth.data.token || ""));
  };

  const current = useMemo(() => (paper ? paper.questions[index] : null), [paper, index]);

  const submit = async () => {
    if (!paper) return;
    const response = await issuedApi<{ passed: boolean; score_pct: number; status: string }>("POST", "/exams/issued/submit", {
      answers: Object.fromEntries(Object.entries(answers).map(([qid, selected]) => [qid, selected])),
      submitted_data: {},
      proctoring_events: [],
      time_taken_seconds: 0,
    });
    setStatus(`${response.passed ? "PASS" : "FAIL"} | score ${Number(response.score_pct || 0).toFixed(2)}% | ${response.status}`);
  };

  const { timerDisplay } = useAssessmentTimer({
    timingMode: paper?.timing_mode || "assessment",
    durationMinutes: Number(paper?.duration_minutes || 30),
    timePerQuestionSeconds: Number(paper?.time_per_question_seconds || 30),
    questionIndex: index,
    enabled: Boolean(paper),
    onAssessmentTimeUp: () => { void submit(); },
    onQuestionTimeUp: () => {
      if (!paper) return;
      if (index < paper.questions.length - 1) setIndex((x) => x + 1);
      else void submit();
    },
  });

  return (
    <section className="card">
      <h2>Issued Candidate Assessment</h2>
      {!paper ? (
        <div className="row">
          {!accessKey && <input placeholder="Issued email" value={email} onChange={(e) => setEmail(e.target.value)} />}
          <input placeholder="Issued password" type="password" value={password} onChange={(e) => setPassword(e.target.value)} />
          <button onClick={login}>Login</button>
          {status && <small>{status}</small>}
        </div>
      ) : (
        <>
          <h3>{paper.assessment_title}</h3>
          <div>Question {index + 1}/{paper.questions.length} | Timer: {timerDisplay}</div>
          {current && (
            <div className="item">
              <strong>{current.question_text}</strong>
              {current.options.map((o) => (
                <label key={o.id} className="option">
                  <input
                    type={current.question_type === "mcq_multiple_correct" ? "checkbox" : "radio"}
                    name={`issued-${current.question_id}`}
                    checked={(answers[current.question_id] || []).includes(o.id)}
                    onChange={(e) => {
                      const prev = answers[current.question_id] || [];
                      const next = current.question_type === "mcq_multiple_correct"
                        ? (e.target.checked ? [...prev, o.id] : prev.filter((x) => x !== o.id))
                        : [o.id];
                      setAnswers((state) => ({ ...state, [current.question_id]: next }));
                    }}
                  />
                  {o.text}
                </label>
              ))}
            </div>
          )}
          <div className="row">
            <button disabled={index === 0} onClick={() => setIndex((x) => x - 1)}>Prev</button>
            {paper && index < paper.questions.length - 1 ? (
              <button onClick={() => setIndex((x) => x + 1)}>Next</button>
            ) : (
              <button onClick={() => void submit()}>Submit Issued Assessment</button>
            )}
          </div>
          {status && <div>{status}</div>}
        </>
      )}
    </section>
  );
}

