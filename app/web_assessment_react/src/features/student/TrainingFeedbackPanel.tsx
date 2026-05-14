import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../../lib/api";

type Props = {
  attemptId: number;
  latest?: {
    training_feedback_status?: string;
    training_feedback_comment?: string;
    training_feedback_count?: number;
  } | null;
};

export function TrainingFeedbackPanel({ attemptId, latest }: Props) {
  const [choice, setChoice] = useState<"correct" | "incorrect" | "">(
    latest?.training_feedback_status === "correct" || latest?.training_feedback_status === "incorrect"
      ? (latest.training_feedback_status as "correct" | "incorrect")
      : "",
  );
  const [comment, setComment] = useState(latest?.training_feedback_comment ?? "");

  const save = useMutation({
    mutationFn: async () =>
      (
        await api.post(`/student/attempts/${attemptId}/proctor-training-feedback`, {
          training_result: choice,
          comment,
        })
      ).data,
  });

  return (
    <section className="card">
      <h3>Proctor Training Feedback</h3>
      <div className="row">
        <button className={choice === "correct" ? "active" : ""} onClick={() => setChoice("correct")}>Pass (model correct)</button>
        <button className={choice === "incorrect" ? "active" : ""} onClick={() => setChoice("incorrect")}>Fail (model wrong)</button>
      </div>
      <textarea
        placeholder="Optional feedback comment"
        value={comment}
        onChange={(e) => setComment(e.target.value)}
        rows={3}
        style={{ width: "100%", marginTop: 8 }}
      />
      <div className="row" style={{ marginTop: 8 }}>
        <button onClick={() => save.mutate()} disabled={!choice || save.isPending}>Save Feedback</button>
        {save.data?.training_feedback_status && (
          <small>
            Saved: {save.data.training_feedback_status} ({Number(save.data.training_feedback_count || 1)} total)
          </small>
        )}
      </div>
    </section>
  );
}

