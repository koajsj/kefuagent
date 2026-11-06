import { createContext, useContext } from "react";
import type { Adapter, Session } from "../types";
export type AppContext = Session & {
  api: Adapter;
  notify: (text: string) => void;
  refreshSession: (tenant?: string) => Promise<void>;
};
export const Context = createContext<AppContext | null>(null);
export function useApp() {
  const value = useContext(Context);
  if (!value) throw new Error("Workspace unavailable");
  return value;
}
