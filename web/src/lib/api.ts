import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(path, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
  });
  if (!r.ok) {
    let msg = r.statusText;
    try {
      const j = await r.json();
      msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail ?? j);
    } catch {
      /* not JSON */
    }
    throw new ApiError(r.status, msg);
  }
  return r.json() as Promise<T>;
}

export const post = <T,>(path: string, body?: unknown) =>
  api<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });

/** GET that treats 404 as "nothing yet" (null) rather than an error. */
export function useDoc<T>(key: string[], path: string) {
  return useQuery<T | null>({
    queryKey: key,
    queryFn: async () => {
      try {
        return await api<T>(path);
      } catch (e) {
        if (e instanceof ApiError && e.status === 404) return null;
        throw e;
      }
    },
  });
}

export interface Job {
  id: string;
  kind: string;
  label: string;
  status: "queued" | "running" | "done" | "error";
  message: string;
}

/** Start a background job and poll it; refresh the given queries when it finishes. */
export function useJob(startPath: string, invalidate: string[][], body?: () => unknown) {
  const qc = useQueryClient();
  const [job, setJob] = useState<Job | null>(null);
  const start = useMutation({
    mutationFn: () => post<Job>(startPath, body ? body() : undefined),
    onSuccess: setJob,
  });
  useEffect(() => {
    if (!job || job.status === "done" || job.status === "error") return;
    const t = setInterval(async () => {
      const j = await api<Job>(`/api/jobs/${job.id}`);
      setJob(j);
      if (j.status === "done") invalidate.forEach((k) => qc.invalidateQueries({ queryKey: k }));
    }, 1500);
    return () => clearInterval(t);
  }, [job, qc, invalidate]);
  const busy = start.isPending || job?.status === "queued" || job?.status === "running";
  return { run: () => start.mutate(), busy, job, error: start.error as Error | null };
}
