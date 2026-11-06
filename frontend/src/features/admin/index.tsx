import { UserMemory } from "./UserMemory";
import { Agents } from "./Agents";
import { Operations } from "./Operations";
import { Tools } from "./Tools";
import { Publications } from "./Publications";
import { Dashboard, Onboarding } from "./Overview";
import { KnowledgePage } from "../knowledge";
export function AdminPage({ page }: { page: string }) {
  if (page === "memory") return <UserMemory />;
  if (page === "agents") return <Agents />;
  if (page === "tools") return <Tools />;
  if (page === "publications") return <Publications />;
  if (page === "dashboard") return <Dashboard />;
  if (page === "onboarding") return <Onboarding />;
  if (page === "knowledge") return <KnowledgePage />;
  return <Operations page={page} />;
}
