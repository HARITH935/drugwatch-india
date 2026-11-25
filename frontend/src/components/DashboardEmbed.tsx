"use client";

import { embedDashboard, type EmbeddedDashboard } from "@superset-ui/embedded-sdk";
import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/Button";

// The only client-side JavaScript this site writes itself: embedding an iframe is something
// only the browser can do, and the guest token it needs expires every 5 minutes
// (GuestTokenService.TOKEN_LIFETIME_SECONDS) long after any server render has finished. The SDK
// refreshes that token on its own schedule - this component only has to hand it a function that
// fetches a fresh one, never a timer of its own.

const LABELS: Record<string, string> = {
  states: "By state",
  "manufacturer-reporting": "Manufacturer reporting",
  "spurious-reports": "Spurious reports",
  "drug-classes": "Drug classes",
};

function labelFor(key: string): string {
  return LABELS[key] ?? key;
}

async function fetchToken(key: string): Promise<{ token: string; dashboardId: string }> {
  const response = await fetch(`/api/dashboards/${encodeURIComponent(key)}/guest-token`, {
    method: "POST",
  });
  if (!response.ok) throw new Error(`guest token request failed: ${response.status}`);
  return response.json();
}

export function DashboardEmbed({ keys }: { keys: string[] }) {
  const [active, setActive] = useState(keys[0]);
  const [error, setError] = useState(false);
  const mountRef = useRef<HTMLDivElement>(null);
  const embeddedRef = useRef<EmbeddedDashboard | null>(null);

  useEffect(() => {
    // Next.js inlines NEXT_PUBLIC_* at build time by replacing this exact expression - the `??`
    // fallback is still evaluated at runtime in the browser, same pattern backend.ts's own
    // DEFAULT_BACKEND_URL uses for the server-side variable.
    const supersetDomain = process.env.NEXT_PUBLIC_SUPERSET_URL ?? "http://localhost:8088";
    const mount = mountRef.current;
    if (!mount) return;

    let cancelled = false;
    setError(false);

    (async () => {
      let dashboardId: string;
      try {
        dashboardId = (await fetchToken(active)).dashboardId;
      } catch {
        if (!cancelled) setError(true);
        return;
      }
      if (cancelled) return;

      let embedded;
      try {
        embedded = await embedDashboard({
          id: dashboardId,
          supersetDomain,
          mountPoint: mount,
          fetchGuestToken: async () => (await fetchToken(active)).token,
          dashboardUiConfig: { hideTitle: true },
        });
      } catch {
        if (!cancelled) setError(true);
        return;
      }

      if (cancelled) {
        embedded.unmount();
      } else {
        embeddedRef.current = embedded;
      }
    })();

    return () => {
      cancelled = true;
      embeddedRef.current?.unmount();
      embeddedRef.current = null;
    };
  }, [active]);

  return (
    <div className="space-y-4">
      <div role="tablist" aria-label="Choose a dashboard" className="flex flex-wrap gap-2">
        {keys.map((key) => (
          <Button
            key={key}
            type="button"
            role="tab"
            aria-selected={key === active}
            variant={key === active ? "primary" : "secondary"}
            size="sm"
            onClick={() => setActive(key)}
          >
            {labelFor(key)}
          </Button>
        ))}
      </div>

      {error ? (
        <p role="status">This dashboard is unavailable right now. Please try again soon.</p>
      ) : (
        <div
          ref={mountRef}
          role="tabpanel"
          className="h-[720px] w-full overflow-hidden rounded-(--radius-lg) border border-border"
        />
      )}
    </div>
  );
}
