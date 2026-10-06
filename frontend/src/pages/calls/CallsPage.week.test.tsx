import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ConfigProvider } from "antd";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { getCalls, getCallsSyncStatus } from "../../shared/api/calls";
import { CallsPage } from "./CallsPage";

const state = vi.hoisted(() => ({
  getCalls: vi.fn<typeof getCalls>(),
  getCallsSyncStatus: vi.fn<typeof getCallsSyncStatus>(),
}));

vi.mock("../../features/workspace/model/useCurrentWorkspace", () => ({
  useCurrentWorkspace: () => ({
    currentWorkspaceId: 2,
    canViewCalls: true,
  }),
}));

vi.mock("../../features/avito", () => ({
  useAvitoProjectsQuery: () => ({
    data: [{ id: 8, name: "Основной" }],
    isLoading: false,
  }),
}));

vi.mock(import("../../shared/api/calls"), async (importOriginal) => ({
  ...(await importOriginal()),
  getCalls: state.getCalls,
  getCallsSyncStatus: state.getCallsSyncStatus,
}));

let client: QueryClient;

function renderPage() {
  render(
    <QueryClientProvider client={client}>
      <ConfigProvider theme={{ token: { motion: false } }}>
        <CallsPage />
      </ConfigProvider>
    </QueryClientProvider>,
  );
}

describe("CallsPage week", () => {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2026-10-11T09:00:00Z"));
    client = new QueryClient({
      defaultOptions: { queries: { retry: false, gcTime: Infinity } },
    });
    state.getCalls.mockReset().mockResolvedValue({
      count: 0,
      next: null,
      previous: null,
      results: [],
    });
    state.getCallsSyncStatus.mockReset().mockResolvedValue({
      last_synced_at: null,
      backfill_complete: true,
      classification_complete: true,
      is_syncing: false,
      phase: null,
      last_error: "",
    });
  });

  afterEach(() => {
    cleanup();
    client.clear();
    vi.useRealTimers();
  });

  it("показывает дни недели от воскресенья к понедельнику, включая дни без звонков", async () => {
    renderPage();

    const reports = await screen.findAllByRole("button", {
      name: /^Отчет за день, /,
    });

    expect(reports.map((button) => button.getAttribute("aria-label"))).toEqual([
      "Отчет за день, 11 октября",
      "Отчет за день, 10 октября",
      "Отчет за день, 9 октября",
      "Отчет за день, 8 октября",
      "Отчет за день, 7 октября",
      "Отчет за день, 6 октября",
      "Отчет за день, 5 октября",
    ]);
  });

  it.each([
    {
      time: "2026-10-06T09:00:00Z",
      description: "днём 6 октября",
      expected: ["Отчет за день, 6 октября", "Отчет за день, 5 октября"],
    },
    {
      time: "2026-10-05T20:59:59Z",
      description: "до полуночи по Москве 5 октября",
      expected: ["Отчет за день, 5 октября"],
    },
    {
      time: "2026-10-05T21:00:00Z",
      description: "после наступления 6 октября по Москве",
      expected: ["Отчет за день, 6 октября", "Отчет за день, 5 октября"],
    },
  ])("показывает только наступившие дни: $description", async ({ time, expected }) => {
    vi.setSystemTime(new Date(time));
    renderPage();

    const reports = await screen.findAllByRole("button", {
      name: /^Отчет за день, /,
    });

    expect(reports.map((button) => button.getAttribute("aria-label"))).toEqual(expected);
  });

  it("не запрашивает звонки за будущие дни", async () => {
    vi.setSystemTime(new Date("2026-10-06T09:00:00Z"));
    renderPage();

    await waitFor(() => expect(state.getCalls).toHaveBeenCalled());

    const requestedDates = new Set(
      state.getCalls.mock.calls.map(([request]) => request.date),
    );
    expect([...requestedDates].sort()).toEqual(["2026-10-05", "2026-10-06"]);
  });

  it("не показывает дни и загрузку при выборе целиком будущей недели", async () => {
    vi.setSystemTime(new Date("2026-10-06T09:00:00Z"));
    renderPage();
    await screen.findByLabelText("Количество звонков за 6 октября");

    fireEvent.click(screen.getByPlaceholderText("Выберите неделю"));
    fireEvent.click(await screen.findByTitle("2026-10-13"));

    expect(screen.getByPlaceholderText("Выберите неделю"))
      .toHaveValue("12.10.2026 – 18.10.2026");
    expect(screen.queryAllByRole("button", { name: /^Отчет за день, / })).toHaveLength(0);
    expect(screen.queryByLabelText("Загрузка звонков")).not.toBeInTheDocument();
    expect(state.getCalls.mock.calls.some(([request]) => request.date >= "2026-10-12"))
      .toBe(false);
  });
});
