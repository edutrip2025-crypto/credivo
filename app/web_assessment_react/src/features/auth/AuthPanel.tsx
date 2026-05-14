import { useForm } from "react-hook-form";
import { z } from "zod";
import { zodResolver } from "@hookform/resolvers/zod";
import { api } from "../../lib/api";
import { useSessionStore } from "../../lib/sessionStore";

const schema = z.object({
  email: z.string().email(),
  password: z.string().min(1),
});

type Form = z.infer<typeof schema>;

export function AuthPanel() {
  const { register, handleSubmit, formState } = useForm<Form>({ resolver: zodResolver(schema) });
  const setSession = useSessionStore((s) => s.setSession);
  const clear = useSessionStore((s) => s.clear);
  const role = useSessionStore((s) => s.role);

  const onSubmit = async (values: Form) => {
    const { data } = await api.post("/auth/login", values);
    setSession(data.access_token, data.role);
  };

  return (
    <section className="card">
      <h2>Authenticated Flows</h2>
      <form onSubmit={handleSubmit(onSubmit)} className="row">
        <input placeholder="Email" {...register("email")} />
        <input placeholder="Password" type="password" {...register("password")} />
        <button type="submit" disabled={formState.isSubmitting}>Login</button>
        <button type="button" onClick={clear}>Logout</button>
      </form>
      <small>Current role: {role ?? "none"}</small>
    </section>
  );
}
