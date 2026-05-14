import { create } from "zustand";

type Role = "provider" | "student" | "admin" | null;

type SessionState = {
  token: string | null;
  role: Role;
  setSession: (token: string, role: Role) => void;
  clear: () => void;
};

export const useSessionStore = create<SessionState>((set) => ({
  token: null,
  role: null,
  setSession: (token, role) => set({ token, role }),
  clear: () => set({ token: null, role: null }),
}));
