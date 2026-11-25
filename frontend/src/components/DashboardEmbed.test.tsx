import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { DashboardEmbed } from "./DashboardEmbed";

const embedDashboard = vi.fn();
const unmount = vi.fn();

// The SDK itself needs a real browser (it inserts an iframe and talks to Superset directly), so
// it's mocked here - what this file actually verifies is OUR code: which id and callback we
// hand it, and what we render while waiting or on failure.
vi.mock("@superset-ui/embedded-sdk", () => ({
  embedDashboard: (...args: unknown[]) => embedDashboard(...args),
}));

function jsonResponse(body: unknown, ok = true, status = 200) {
  return Promise.resolve({ ok, status, json: () => Promise.resolve(body) } as Response);
}

describe("DashboardEmbed", () => {
  beforeEach(() => {
    embedDashboard.mockReset().mockResolvedValue({ unmount });
    unmount.mockReset();
    vi.stubGlobal(
      "fetch",
      vi.fn(() =>
        jsonResponse({
          dashboard: "states",
          dashboardId: "uuid-states",
          token: "tok-1",
          expiresInSeconds: 300,
        }),
      ),
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("embeds the first dashboard on mount, using the id its own guest-token request returned", async () => {
    render(<DashboardEmbed keys={["states", "drug-classes"]} />);

    await waitFor(() => expect(embedDashboard).toHaveBeenCalledTimes(1));
    expect(embedDashboard.mock.calls[0][0].id).toBe("uuid-states");
    expect(fetch).toHaveBeenCalledWith("/api/dashboards/states/guest-token", { method: "POST" });
  });

  it("switching tabs unmounts the old embed before mounting the new one", async () => {
    render(<DashboardEmbed keys={["states", "drug-classes"]} />);
    await waitFor(() => expect(embedDashboard).toHaveBeenCalledTimes(1));

    fireEvent.click(screen.getByRole("tab", { name: "Drug classes" }));

    await waitFor(() => expect(unmount).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(embedDashboard).toHaveBeenCalledTimes(2));
    expect(fetch).toHaveBeenLastCalledWith("/api/dashboards/drug-classes/guest-token", {
      method: "POST",
    });
  });

  it("the SDK's own refresh callback resolves to a token string, not the whole response", async () => {
    render(<DashboardEmbed keys={["states"]} />);
    await waitFor(() => expect(embedDashboard).toHaveBeenCalledTimes(1));

    const refreshed = await embedDashboard.mock.calls[0][0].fetchGuestToken();

    expect(refreshed).toBe("tok-1");
  });

  it("shows a calm message, not a crash, when the guest-token request fails", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => jsonResponse({}, false, 503)),
    );
    render(<DashboardEmbed keys={["states"]} />);

    await waitFor(() =>
      expect(
        screen.getByText("This dashboard is unavailable right now. Please try again soon."),
      ).toBeInTheDocument(),
    );
    expect(embedDashboard).not.toHaveBeenCalled();
  });

  it("shows a calm message, not a crash, when embedDashboard() itself rejects", async () => {
    // Found by actually running it: the guest-token fetch had its own try/catch, but the SDK call
    // right after it did not, so a rejection there was an unhandled promise rejection with no
    // visible fallback at all - fixed, and this is the regression test for that fix.
    embedDashboard.mockReset().mockRejectedValue(new Error("iframe blocked"));
    render(<DashboardEmbed keys={["states"]} />);

    await waitFor(() =>
      expect(
        screen.getByText("This dashboard is unavailable right now. Please try again soon."),
      ).toBeInTheDocument(),
    );
  });

  it("labels known keys in plain English and falls back to the raw key for an unknown one", () => {
    render(<DashboardEmbed keys={["states", "some-future-dashboard"]} />);

    expect(screen.getByRole("tab", { name: "By state" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "some-future-dashboard" })).toBeInTheDocument();
  });
});
