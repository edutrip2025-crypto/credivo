import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { api } from "../../lib/api";
import { CodingEnv } from "../tools/CodingEnv";
import { ExcelSimulator } from "../tools/ExcelSimulator";

type Assessment = {
  exam_id: number;
  title: string;
  status: string;
  pass_score: number;
  assessment_type: string;
  timing_mode: "question" | "assessment";
  duration_minutes: number;
  time_per_question_seconds: number | null;
  questions_per_attempt: number;
  question_count: number;
};

type QuestionOption = { option_text: string; is_correct: boolean; position: number };

type QuestionRow = {
  question_id: number;
  question_text: string;
  question_type: string;
  marks: number;
  negative_marks: number;
  options: { option_id: number; option_text: string; is_correct: boolean; position: number }[];
};

export function ProviderAssessments() {
  const qc = useQueryClient();
  const [selectedExamId, setSelectedExamId] = useState<number | null>(null);
  const [issueExamId, setIssueExamId] = useState<number | null>(null);
  const [candidateName, setCandidateName] = useState("");
  const [candidateEmail, setCandidateEmail] = useState("");
  const [questionText, setQuestionText] = useState("");
  const [questionType, setQuestionType] = useState<"mcq_single_correct" | "mcq_multiple_correct">("mcq_single_correct");
  const [marks, setMarks] = useState(1);
  const [negativeMarks, setNegativeMarks] = useState(0);
  const [options, setOptions] = useState<QuestionOption[]>([
    { option_text: "", is_correct: true, position: 1 },
    { option_text: "", is_correct: false, position: 2 },
    { option_text: "", is_correct: false, position: 3 },
    { option_text: "", is_correct: false, position: 4 },
  ]);
  const [form, setForm] = useState({
    title: "",
    instructions: "",
    about: "",
    tools: "",
    topics: "",
    pass_score: 70,
    max_attempts: 3,
    questions_per_attempt: 25,
    timing_mode: "question" as "question" | "assessment",
    duration_minutes: 25,
    time_per_question_seconds: 25,
    negative_marking: false,
  });
  const [showTools, setShowTools] = useState(false);
  const [selectedTools, setSelectedTools] = useState<string[]>([]);
  const [activeTool, setActiveTool] = useState<string | null>(null);

  const TOOL_TYPES = [
    "Excel",
    "Coding Env",
    "Accounting Software Simulation",
    "Tax Software",
  ];

  const exams = useQuery({
    queryKey: ["provider-assessments"],
    queryFn: async () => (await api.get<Assessment[]>("/provider/workspace/assessments")).data,
  });

  const questions = useQuery({
    queryKey: ["provider-assessment-questions", selectedExamId],
    enabled: Boolean(selectedExamId),
    queryFn: async () => (await api.get<QuestionRow[]>(`/exams/${selectedExamId}/questions`)).data,
  });

  const issued = useQuery({
    queryKey: ["issued-by-me"],
    queryFn: async () => (await api.get("/exams/issued/by-me")).data,
  });

  const createAssessment = useMutation({
    mutationFn: async () => {
      const payload = {
        course_id: 0,
        title: form.title,
        assessment_type: "mcq",
        instructions: form.instructions,
        about: form.about,
        tools: [
          ...new Set(
            [
              ...selectedTools,
              ...form.tools.split(/\r?\n|,/).map((x) => x.trim()).filter(Boolean),
            ].filter(Boolean),
          ),
        ],
        topics: form.topics.split(/\r?\n|,/).map((x) => x.trim()).filter(Boolean),
        duration_minutes: Number(form.duration_minutes),
        timing_mode: form.timing_mode,
        time_per_question_seconds: form.timing_mode === "question" ? Number(form.time_per_question_seconds) : null,
        questions_per_attempt: Number(form.questions_per_attempt),
        pass_score: Number(form.pass_score),
        negative_marking: Boolean(form.negative_marking),
        shuffle_questions: false,
        shuffle_options: false,
        max_attempts: Number(form.max_attempts),
        certificate_enabled: true,
      };
      return (await api.post("/exams", payload)).data;
    },
    onSuccess: async (data) => {
      setSelectedExamId(Number(data.id));
      await qc.invalidateQueries({ queryKey: ["provider-assessments"] });
    },
  });

  const addQuestion = useMutation({
    mutationFn: async () => {
      if (!selectedExamId) throw new Error("Select assessment first.");
      const normalized = options
        .map((o, i) => ({ ...o, position: i + 1, option_text: String(o.option_text || "").trim() }))
        .filter((o) => o.option_text);
      const payload = {
        question_text: questionText,
        question_type: questionType,
        marks: Number(marks),
        negative_marks: Number(negativeMarks),
        options: normalized,
      };
      return (await api.post(`/exams/${selectedExamId}/questions`, payload)).data;
    },
    onSuccess: async () => {
      setQuestionText("");
      setOptions([
        { option_text: "", is_correct: true, position: 1 },
        { option_text: "", is_correct: false, position: 2 },
        { option_text: "", is_correct: false, position: 3 },
        { option_text: "", is_correct: false, position: 4 },
      ]);
      await qc.invalidateQueries({ queryKey: ["provider-assessment-questions", selectedExamId] });
      await qc.invalidateQueries({ queryKey: ["provider-assessments"] });
    },
  });

  const publish = useMutation({
    mutationFn: async () => {
      if (!selectedExamId) throw new Error("Select assessment first.");
      return (await api.post(`/exams/${selectedExamId}/publish`)).data;
    },
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: ["provider-assessments"] });
    },
  });

  const issue = useMutation({
    mutationFn: async () => {
      if (!issueExamId) throw new Error("Select exam to issue.");
      return (
        await api.post(`/exams/${issueExamId}/issue`, {
          candidate_name: candidateName,
          candidate_email: candidateEmail,
        })
      ).data;
    },
    onSuccess: async () => {
      setCandidateName("");
      setCandidateEmail("");
      await qc.invalidateQueries({ queryKey: ["issued-by-me"] });
      await qc.invalidateQueries({ queryKey: ["provider-assessments"] });
    },
  });

  const selectedExam = useMemo(
    () => (exams.data || []).find((x) => x.exam_id === selectedExamId) || null,
    [exams.data, selectedExamId],
  );

  return (
    <section className="card">
      <h2>Provider: Complete Assessment Workflow</h2>
      <div className="item" style={{ marginBottom: 10 }}>
        <h3 style={{ margin: 0 }}>Workspace</h3>
        <div className="item" style={{ marginTop: 8 }}>
          <strong>Custom</strong>
          <div className="row" style={{ marginTop: 8 }}>
            <button type="button" onClick={() => setShowTools((v) => !v)}>Tools</button>
            <small>Open tools directly for dev testing (independent of assessment creation).</small>
          </div>
        </div>
      </div>
      {showTools && (
        <div className="item">
          <strong>Tools Lab</strong>
          {TOOL_TYPES.map((tool) => {
            const active = selectedTools.includes(tool);
            return (
              <label key={tool} className="row" style={{ marginTop: 6 }}>
                <input
                  type="checkbox"
                  checked={active}
                  onChange={(e) => {
                    setSelectedTools((prev) =>
                      e.target.checked ? [...prev, tool] : prev.filter((x) => x !== tool),
                    );
                  }}
                />
                {tool}
                <button
                  type="button"
                  style={{ marginLeft: 8 }}
                  onClick={() => setActiveTool(tool)}
                >
                  Open
                </button>
              </label>
            );
          })}
          <small>Enabled for assessment payload: {selectedTools.length ? selectedTools.join(", ") : "None"}</small>
        </div>
      )}
      {activeTool === "Excel" && <ExcelSimulator />}
      {activeTool === "Coding Env" && <CodingEnv />}
      {activeTool === "Accounting Software Simulation" && (
        <div className="item"><strong>Accounting Software Simulation</strong><div>Queued next. I will build ledger/journal simulator in the next step.</div></div>
      )}
      {activeTool === "Tax Software" && (
        <div className="item"><strong>Tax Software</strong><div>Queued next. I will build form/rules simulator in the next step.</div></div>
      )}

      <h3>1) Create Assessment</h3>
      <div className="row">
        <input placeholder="Title" value={form.title} onChange={(e) => setForm((p) => ({ ...p, title: e.target.value }))} />
        <input placeholder="Instructions" value={form.instructions} onChange={(e) => setForm((p) => ({ ...p, instructions: e.target.value }))} />
        <input placeholder="About" value={form.about} onChange={(e) => setForm((p) => ({ ...p, about: e.target.value }))} />
        <input placeholder="Additional tools (comma/newline)" value={form.tools} onChange={(e) => setForm((p) => ({ ...p, tools: e.target.value }))} />
        <input placeholder="Topics (comma/newline)" value={form.topics} onChange={(e) => setForm((p) => ({ ...p, topics: e.target.value }))} />
        <input type="number" placeholder="Pass score" value={form.pass_score} onChange={(e) => setForm((p) => ({ ...p, pass_score: Number(e.target.value) }))} />
        <input type="number" placeholder="Max attempts" value={form.max_attempts} onChange={(e) => setForm((p) => ({ ...p, max_attempts: Number(e.target.value) }))} />
        <select value={form.timing_mode} onChange={(e) => setForm((p) => ({ ...p, timing_mode: e.target.value as "question" | "assessment" }))}>
          <option value="question">Time per question</option>
          <option value="assessment">Time per assessment</option>
        </select>
        <input type="number" placeholder="Duration minutes" value={form.duration_minutes} onChange={(e) => setForm((p) => ({ ...p, duration_minutes: Number(e.target.value) }))} />
        <input type="number" placeholder="Time per question seconds" value={form.time_per_question_seconds} onChange={(e) => setForm((p) => ({ ...p, time_per_question_seconds: Number(e.target.value) }))} />
        <input type="number" placeholder="Questions per attempt" value={form.questions_per_attempt} onChange={(e) => setForm((p) => ({ ...p, questions_per_attempt: Number(e.target.value) }))} />
        <label>
          <input
            type="checkbox"
            checked={form.negative_marking}
            onChange={(e) => setForm((p) => ({ ...p, negative_marking: e.target.checked }))}
          />
          Negative marking
        </label>
        <button onClick={() => createAssessment.mutate()} disabled={createAssessment.isPending}>Create</button>
      </div>

      <h3>2) Select & Build Questions</h3>
      <div className="row">
        <select value={selectedExamId ?? ""} onChange={(e) => setSelectedExamId(Number(e.target.value))}>
          <option value="">Select assessment</option>
          {(exams.data || []).map((x) => (
            <option key={x.exam_id} value={x.exam_id}>
              {x.title} ({x.status}) Q:{x.question_count}
            </option>
          ))}
        </select>
        {selectedExam && <small>Selected: {selectedExam.title} | {selectedExam.status}</small>}
      </div>
      {selectedExam && selectedExam.status !== "published" && (
        <div className="item">
          <input placeholder="Question text" value={questionText} onChange={(e) => setQuestionText(e.target.value)} />
          <div className="row">
            <select value={questionType} onChange={(e) => setQuestionType(e.target.value as "mcq_single_correct" | "mcq_multiple_correct")}>
              <option value="mcq_single_correct">Single correct</option>
              <option value="mcq_multiple_correct">Multiple correct</option>
            </select>
            <input type="number" value={marks} onChange={(e) => setMarks(Number(e.target.value))} />
            <input type="number" value={negativeMarks} onChange={(e) => setNegativeMarks(Number(e.target.value))} />
          </div>
          {options.map((o, idx) => (
            <div key={idx} className="row">
              <input
                placeholder={`Option ${idx + 1}`}
                value={o.option_text}
                onChange={(e) =>
                  setOptions((prev) => prev.map((x, i) => (i === idx ? { ...x, option_text: e.target.value } : x)))
                }
              />
              <label>
                <input
                  type={questionType === "mcq_single_correct" ? "radio" : "checkbox"}
                  checked={o.is_correct}
                  name="correct-option"
                  onChange={(e) =>
                    setOptions((prev) =>
                      prev.map((x, i) => {
                        if (questionType === "mcq_single_correct") return { ...x, is_correct: i === idx };
                        if (i === idx) return { ...x, is_correct: e.target.checked };
                        return x;
                      }),
                    )
                  }
                />
                Correct
              </label>
            </div>
          ))}
          <button onClick={() => addQuestion.mutate()} disabled={addQuestion.isPending}>Add Question</button>
          <button onClick={() => publish.mutate()} disabled={publish.isPending}>Publish Assessment</button>
        </div>
      )}
      {(questions.data || []).map((q) => (
        <article key={q.question_id} className="item">
          <strong>{q.question_text}</strong> <small>{q.question_type} | marks {q.marks}</small>
        </article>
      ))}

      <h3>3) Issue Assessment</h3>
      <div className="row">
        <select value={issueExamId ?? ""} onChange={(e) => setIssueExamId(Number(e.target.value))}>
          <option value="">Select published assessment</option>
          {(exams.data || []).filter((x) => x.status === "published").map((x) => (
            <option key={x.exam_id} value={x.exam_id}>{x.title}</option>
          ))}
        </select>
        <input placeholder="Candidate name" value={candidateName} onChange={(e) => setCandidateName(e.target.value)} />
        <input placeholder="Candidate email" value={candidateEmail} onChange={(e) => setCandidateEmail(e.target.value)} />
        <button onClick={() => issue.mutate()} disabled={issue.isPending}>Send Invite</button>
      </div>

      <h3>4) Issued Status & Results</h3>
      {(issued.data || []).map((row: { internal_id: string; candidate_email: string; assessment_title: string; status: string; score_pct: number | null; passed: boolean | null }) => (
        <div key={`${row.internal_id}-${row.candidate_email}`} className="item">
          <strong>{row.internal_id}</strong> | {row.assessment_title} | {row.candidate_email} | {row.status}
          {row.score_pct != null && <> | {Number(row.score_pct).toFixed(2)}% | {row.passed ? "PASS" : "FAIL"}</>}
        </div>
      ))}
    </section>
  );
}
