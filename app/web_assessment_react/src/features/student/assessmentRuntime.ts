export type TimingMode = "question" | "assessment";

export type TimerState = {
  remainingAssessmentSec: number;
  questionRemainingByIndex: Record<number, number>;
  questionTimedOutByIndex: Record<number, boolean>;
};

export function formatClock(totalSeconds: number): string {
  const sec = Math.max(0, Math.floor(totalSeconds));
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

export function createInitialTimerState(durationMinutes: number): TimerState {
  return {
    remainingAssessmentSec: Math.max(1, Math.floor(durationMinutes * 60)),
    questionRemainingByIndex: {},
    questionTimedOutByIndex: {},
  };
}

export function ensureQuestionSeconds(state: TimerState, index: number, perQuestionSec: number): number {
  if (!Number.isFinite(state.questionRemainingByIndex[index])) {
    state.questionRemainingByIndex[index] = Math.max(1, Math.floor(perQuestionSec));
  }
  return state.questionRemainingByIndex[index];
}

