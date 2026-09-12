"use client";

import { useEffect } from "react";

export default function AnalyticsRedirect() {
  useEffect(() => {
    const query = new URLSearchParams(window.location.search);
    const session = query.get("session") || window.localStorage.getItem("salmonsight-session");
    window.location.replace(`/${session ? `?session=${encodeURIComponent(session)}&analytics=1` : "?analytics=1"}`);
  }, []);

  return <main className="analytics-redirect">Opening Analytics…</main>;
}
