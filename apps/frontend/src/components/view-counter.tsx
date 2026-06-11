"use client";

import { useEffect } from "react";

export function ViewCounter({ slug }: { slug: string }) {
  useEffect(() => {
    const key = `shkandal:viewed:${slug}`;
    if (sessionStorage.getItem(key)) return;
    sessionStorage.setItem(key, "1");
    const backend = process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://localhost:8000";
    void fetch(`${backend}/api/cases/${encodeURIComponent(slug)}/views`, { method: "POST" });
  }, [slug]);
  return null;
}
