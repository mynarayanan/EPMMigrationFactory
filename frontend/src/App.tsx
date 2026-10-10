import { BrowserRouter, Link, Navigate, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AuthProvider, useAuth } from "./auth";
import { NotifyProvider } from "./notify";
import Login from "./pages/Login";
import Projects from "./pages/Projects";
import ProjectPage from "./pages/ProjectPage";
import NewProject from "./pages/NewProject";

function Shell() {
  const { me, loading, logout } = useAuth();
  if (loading) return <main><p className="muted">Loading…</p></main>;
  if (!me) return <Login />;
  return (
    <>
      <header className="topbar">
        <Link to="/" className="brand" style={{ textDecoration: "none" }}>EPM <b>Migration</b> Workbench</Link>
        <div className="who"><span>{me.username}</span>{me.roles.map((r) => <span key={r} className="role">{r}</span>)}
          <button className="btn ghost small" onClick={logout}>Sign out</button></div>
      </header>
      <main>
        <Routes><Route path="/" element={<Projects />} /><Route path="/projects/new" element={<NewProject />} /><Route path="/projects/:id" element={<ProjectPage />} /><Route path="*" element={<Navigate to="/" />} /></Routes>
      </main>
    </>
  );
}

export default function App({ client }: { client?: QueryClient }) {
  const qc = client ?? new QueryClient({ defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false, staleTime: 0 } } });
  return (
    <QueryClientProvider client={qc}>
      <NotifyProvider><AuthProvider><BrowserRouter><Shell /></BrowserRouter></AuthProvider></NotifyProvider>
    </QueryClientProvider>
  );
}
