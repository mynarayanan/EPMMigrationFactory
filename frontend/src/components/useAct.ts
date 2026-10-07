import { useQueryClient } from "@tanstack/react-query";
import { useCallback } from "react";
import { ApiError } from "../api";
import { useNotify } from "../notify";

/** Run a mutation, refresh everything for the project, and surface gate/permission errors as toasts. */
export function useAct(pid: number) {
  const qc = useQueryClient();
  const notify = useNotify();
  return useCallback(async <R,>(fn: () => Promise<R>, okMsg?: string): Promise<R | undefined> => {
    try {
      const r = await fn();
      if (okMsg) notify("ok", okMsg);
      return r;
    } catch (e) {
      notify("error", e instanceof ApiError ? e.message : "Unexpected error");
    } finally {
      await qc.invalidateQueries({ queryKey: ["p", pid] });
    }
  }, [pid, qc, notify]);
}
