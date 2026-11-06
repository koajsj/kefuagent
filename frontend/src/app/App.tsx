import { useEffect, useRef, useState, lazy, Suspense } from "react";
import {
  HashRouter,
  NavLink,
  Navigate,
  Route,
  Routes,
  useParams,
  useLocation,
} from "react-router-dom";
import { Button, Input, Label, TextField } from "@heroui/react";
import {
  LayoutDashboard,
  MessagesSquare,
  BookOpen,
  Bot,
  Wrench,
  KeyRound,
  Activity,
  Users,
  Settings2,
  Building2,
  Globe,
  WandSparkles,
  PanelLeftClose,
  PanelLeftOpen,
  LogOut,
  ArrowUpRight,
  Bookmark,
} from "lucide-react";
import { adapter } from "../adapters";
import { collection } from "../adapters/collection";
import { sessionState } from "../adapters/storage";
import { Context } from "./context";
import type { Row, Session } from "../types";
import { ErrorNotice, Loading } from "../components/ui";
const AdminPage = lazy(() =>
  import("../features/admin").then((m) => ({ default: m.AdminPage })),
);
const ChatPage = lazy(() =>
  import("../features/chat/ChatPage").then((m) => ({ default: m.ChatPage })),
);
const VisitorPage = lazy(() =>
  import("../features/visitor/VisitorPage").then((m) => ({
    default: m.VisitorPage,
  })),
);
const navigation = [
  {
    path: "dashboard",
    name: "工作区概览",
    icon: LayoutDashboard,
    group: "工作空间",
  },
  { path: "chat", name: "客服会话", icon: MessagesSquare, group: "工作空间" },
  { path: "knowledge", name: "知识库", icon: BookOpen, group: "工作空间" },
  { path: "memory", name: "个人记忆", icon: Bookmark, group: "工作空间" },
  { path: "agents", name: "Agent", icon: Bot, group: "构建与接入" },
  { path: "tools", name: "工具与授权", icon: Wrench, group: "构建与接入" },
  {
    path: "publications",
    name: "发布与嵌入",
    icon: Globe,
    group: "构建与接入",
    admin: true,
  },
  {
    path: "credentials",
    name: "模型凭证",
    icon: KeyRound,
    group: "管理",
    admin: true,
  },
  {
    path: "activity",
    name: "用量与审计",
    icon: Activity,
    group: "管理",
    admin: true,
  },
  {
    path: "members",
    name: "企业成员",
    icon: Users,
    group: "管理",
    admin: true,
  },
  {
    path: "setup",
    name: "运行设置",
    icon: Settings2,
    group: "管理",
    admin: true,
  },
  {
    path: "onboarding",
    name: "首次使用",
    icon: WandSparkles,
    group: "管理",
    admin: true,
  },
  {
    path: "platform",
    name: "平台管理",
    icon: Building2,
    group: "管理",
    platform: true,
  },
];
function PublicRoute() {
  const { id = "" } = useParams();
  return <VisitorPage key={id} publicationId={id} />;
}
function Workspace() {
  const [session, setSession] = useState<Session | null>(null),
    [tenants, setTenants] = useState<Row[]>([]),
    [pending, setPending] = useState(true),
    [error, setError] = useState<unknown>(),
    [notice, setNotice] = useState(""),
    [collapsed, setCollapsed] = useState(false);
  const epoch = useRef(0),
    toast = useRef<ReturnType<typeof setTimeout>>(undefined),
    location = useLocation();
  function notify(text: string) {
    clearTimeout(toast.current);
    setNotice(text);
    toast.current = setTimeout(() => setNotice(""), 7000);
  }
  async function refreshSession(preferred?: string) {
    const ticket = ++epoch.current;
    setPending(true);
    setError(undefined);
    adapter.setTenant("");
    setSession(null);
    try {
      const user = await adapter.request<Row>("/auth/me");
      const choices = await collection<Row>(
        adapter.request.bind(adapter),
        "/tenants",
      );
      if (ticket !== epoch.current) return;
      const remembered =
        preferred ?? sessionState.get("support.tenant." + user.id) ?? "";
      const tenant =
        choices.find((t) => t.id === remembered && t.status === "active")?.id ||
        choices.find((t) => t.status === "active")?.id ||
        "";
      adapter.setTenant(tenant);
      let workspace: Row | null = null;
      if (tenant) {
        try {
          workspace = await adapter.request<Row>("/workspace");
        } catch (e: any) {
          if (e.status !== 403) throw e;
        }
      }
      if (ticket !== epoch.current) return;
      setTenants(choices);
      setSession({ user, tenant, role: workspace?.role || "", workspace });
      sessionState.set("support.tenant." + user.id, tenant);
    } catch (e: any) {
      if (
        ticket === epoch.current &&
        e?.name !== "StaleResponse" &&
        e?.name !== "AbortError"
      )
        setError(e);
    } finally {
      if (ticket === epoch.current) setPending(false);
    }
  }
  useEffect(() => {
    adapter.onUnauthorized(() => {
      epoch.current++;
      adapter.setTenant("");
      setSession(null);
      setPending(false);
      setError(new Error("登录已过期，请重新登录。"));
    });
    void refreshSession();
    return () => {
      epoch.current++;
      adapter.setTenant("");
      clearTimeout(toast.current);
    };
  }, []);
  if (pending)
    return (
      <main className="login-panel">
        <div className="brand">KefuAgent</div>
        <Loading />
      </main>
    );
  if (!session)
    return <Login error={error} signedIn={() => refreshSession()} />;
  const allowed = navigation.filter((item) =>
    item.platform
      ? session.user.is_platform_admin
      : item.admin
        ? session.role === "admin" ||
          (item.path === "onboarding" && session.user.is_platform_admin)
        : !!session.role,
  );
  const current = navigation.find((i) => "/" + i.path === location.pathname);
  const value = { ...session, api: adapter, notify, refreshSession };
  return (
    <Context.Provider value={value}>
      <div className="app-shell">
        <a
          className="skip-link"
          href="#main-content"
          onClick={(event) => {
            event.preventDefault();
            document.getElementById("main-content")?.focus();
          }}
        >
          跳到主要内容
        </a>
        <aside className={"sidebar" + (collapsed ? " collapsed" : "")}>
          <div className="sidebar-header">
            <NavLink
              to="/dashboard"
              className="brand"
              aria-label="KefuAgent 首页"
            >
              {collapsed ? "K" : "KefuAgent"}
            </NavLink>
            <Button
              size="sm"
              variant="ghost"
              isIconOnly
              aria-label={collapsed ? "展开导航" : "收起导航"}
              aria-expanded={!collapsed}
              onPress={() => setCollapsed(!collapsed)}
            >
              {collapsed ? (
                <PanelLeftOpen size={17} />
              ) : (
                <PanelLeftClose size={17} />
              )}
            </Button>
          </div>
          {["工作空间", "构建与接入", "管理"].map((group) => (
            <nav key={group} className="nav-section" aria-label={group}>
              {!collapsed && <h2>{group}</h2>}
              {allowed
                .filter((n) => n.group === group)
                .map((n) => (
                  <NavLink
                    key={n.path}
                    to={"/" + n.path}
                    title={n.name}
                    aria-label={n.name}
                    className={({ isActive }) =>
                      "nav-link" + (isActive ? " active" : "")
                    }
                  >
                    <n.icon size={18} aria-hidden />
                    {!collapsed && <span>{n.name}</span>}
                  </NavLink>
                ))}
            </nav>
          ))}
          <div className="sidebar-footer">
            {!collapsed && (
              <>
                <label htmlFor="workspace-select">企业工作区</label>
                <select
                  id="workspace-select"
                  className="workspace-select"
                  value={session.tenant}
                  onChange={(e) => void refreshSession(e.target.value)}
                >
                  <option value="">选择企业</option>
                  {tenants.map((t) => (
                    <option
                      key={t.id}
                      value={t.id}
                      disabled={t.status !== "active"}
                    >
                      {t.name}
                    </option>
                  ))}
                </select>
                <small>
                  {session.user.display_name} ·{" "}
                  {session.role === "admin"
                    ? "企业管理员"
                    : session.role
                      ? "成员"
                      : "无企业权限"}
                </small>
              </>
            )}
            <Button
              variant="ghost"
              aria-label="退出登录"
              onPress={async () => {
                try {
                  await adapter.request("/auth/logout", { method: "POST" });
                  sessionState.removePrefix("support.pending.");
                  setSession(null);
                  adapter.setTenant("");
                } catch (e) {
                  notify(e instanceof Error ? e.message : "退出未确认");
                }
              }}
            >
              <LogOut size={16} />
              {!collapsed && "退出登录"}
            </Button>
          </div>
        </aside>
        <div className="app-main">
          <header className="topbar">
            <span className="breadcrumbs">
              工作空间 <span aria-hidden> / </span> {current?.name || "客服"}
            </span>
            <div className="topbar-actions">
              <span className="mode-badge">
                {adapter.mode === "demo" ? "静态 DEMO" : "正式 API 模式"}
              </span>
            </div>
          </header>
          <main className="main-content" id="main-content" tabIndex={-1}>
            {adapter.mode === "demo" && (
              <div className="demo-banner">
                离线产品演示 ·
                所有资料均为虚构。操作保存在当前标签页，不连接后端、不调用模型。
                <a
                  href="#/chat/50000000-0000-4000-8000-000000000001"
                  target="_blank"
                  rel="noopener"
                >
                  {" "}
                  访客端预览 <ArrowUpRight size={13} />
                </a>
              </div>
            )}
            {adapter.mode === "api" &&
              session.workspace &&
              !session.workspace.external_models_enabled && (
                <p className="notice">
                  外部模型调用已关闭。可使用明确标记的离线演示；真实模型质量尚未验收。
                </p>
              )}
            <div key={session.tenant}>
              <Routes>
                {allowed.map((n) => (
                  <Route
                    key={n.path}
                    path={"/" + n.path}
                    element={
                      n.path === "chat" ? (
                        <ChatPage />
                      ) : (
                        <AdminPage key={n.path} page={n.path} />
                      )
                    }
                  />
                ))}
                <Route
                  path="*"
                  element={
                    allowed.length ? (
                      <Navigate
                        to={
                          "/" +
                          (allowed.find((n) => n.path === "dashboard")?.path ||
                            allowed[0].path)
                        }
                        replace
                      />
                    ) : (
                      <div className="empty-state">
                        没有有效企业成员关系，请联系企业管理员。平台身份不会绕过企业权限。
                      </div>
                    )
                  }
                />
              </Routes>
            </div>
          </main>
        </div>
      </div>
      {notice && (
        <div className="toast-region" aria-live="polite">
          <div className="toast">{notice}</div>
        </div>
      )}
    </Context.Provider>
  );
}
function Login({
  error,
  signedIn,
}: {
  error: unknown;
  signedIn: () => Promise<void>;
}) {
  const [busy, setBusy] = useState(false),
    [failure, setFailure] = useState<unknown>(error);
  if (adapter.mode === "demo")
    return (
      <main className="login-panel">
        <div className="brand">KefuAgent</div>
        <h1>离线产品演示</h1>
        <p>无需账号、后端或模型密钥，所有内容均为虚构。</p>
        <Button onPress={signedIn}>进入演示工作区</Button>
      </main>
    );
  return (
    <div className="login-page">
      <aside className="login-aside">
        <div className="brand">KefuAgent</div>
        <h1>
          让每一次服务，
          <br />
          都有清晰的答案。
        </h1>
        <p>知识、AI 与人工协作，在一个安静而高效的工作空间中连接。</p>
        <div className="mode-badge">独立部署 · 企业数据隔离</div>
      </aside>
      <main className="login-panel">
        <h2>欢迎回来</h2>
        <p className="page-description">登录你的客服工作空间</p>
        <form
          className="login-form"
          onSubmit={async (e) => {
            e.preventDefault();
            if (busy) return;
            const form = e.currentTarget,
              values = new FormData(form);
            setBusy(true);
            setFailure(undefined);
            try {
              await adapter.request("/web-session", {
                method: "POST",
                body: {
                  login: values.get("login"),
                  password: values.get("password"),
                },
              });
              (form.elements.namedItem("password") as HTMLInputElement).value =
                "";
              await signedIn();
            } catch (e) {
              setFailure(e);
            } finally {
              setBusy(false);
            }
          }}
        >
          <TextField name="login" isRequired>
            <Label>登录身份</Label>
            <Input autoComplete="username" placeholder="账号或邮箱" />
          </TextField>
          <TextField name="password" type="password" isRequired>
            <Label>密码</Label>
            <Input autoComplete="current-password" />
          </TextField>
          <ErrorNotice error={failure} />
          <Button type="submit" isPending={busy}>
            登录工作区
          </Button>
        </form>
        <p className="page-description">
          首次部署？请先通过 setup 和 create-admin CLI
          初始化管理员。这里没有公开的管理员注册入口。
        </p>
      </main>
    </div>
  );
}
function AppRoutes() {
  const path = window.location.pathname.match(/^\/chat\/([0-9a-f-]{36})\/?$/i);
  if (path) return <VisitorPage publicationId={path[1]} />;
  return (
    <HashRouter>
      <Routes>
        <Route path="/chat/:id" element={<PublicRoute />} />
        <Route path="*" element={<Workspace />} />
      </Routes>
    </HashRouter>
  );
}

export function App() {
  return (
    <Suspense
      fallback={
        <main className="login-panel">
          <Loading />
        </main>
      }
    >
      <AppRoutes />
    </Suspense>
  );
}
