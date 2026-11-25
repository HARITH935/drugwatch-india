import { NextResponse } from "next/server";

import { BackendError, mintGuestToken } from "@/lib/backend";

// The first Route Handler in this project, because this is the first thing the BROWSER itself
// has to call directly rather than a Server Component fetching on its behalf: the embedded SDK's
// fetchGuestToken runs in client JS (it has to - Superset's iframe needs a fresh token every few
// minutes, long after the page finished rendering), so there is no Server Component render to do
// this from. BACKEND_URL still never reaches the browser - this just proxies, same as every
// server-side fetch elsewhere on the site.
export async function POST(_request: Request, { params }: { params: Promise<{ key: string }> }) {
  const { key } = await params;
  try {
    const token = await mintGuestToken(key);
    return NextResponse.json(token);
  } catch (error) {
    if (!(error instanceof BackendError)) throw error;
    // Spring's own status (404 for an unlisted key, 503 for Superset being down) carries over
    // unchanged - the embedded SDK only needs to know the call failed, not why.
    return NextResponse.json({ error: "unavailable" }, { status: error.status ?? 503 });
  }
}
