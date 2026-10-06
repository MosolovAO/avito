import { cleanup, render, screen, within } from "@testing-library/react";
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
  useCurrentWorkspace: () => ({ currentWorkspaceId: 2, canViewCalls: true }),
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

describe("CallsPage actions", () => {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2026-10-06T09:00:00Z"));
    client = new QueryClient({
      defaultOptions: { queries: { retry: false, gcTime: Infinity } },
    });
    state.getCalls.mockReset();
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

  it.each([
    { reportText: "", actionName: "Добавить отчет" },
    { reportText: "Клиент заказал доставку", actionName: "Редактировать отчет" },
  ])("объединяет прослушивание и $actionName в колонке Действия", async ({ reportText, actionName }) => {
    state.getCalls.mockImplementation(async ({ date }) => ({
      count: date === "2026-10-06" ? 1 : 0,
      next: null,
      previous: null,
      results: date === "2026-10-06" ? [{
        id: 1,
        external_id: "1",
        occurred_at: "2026-10-06T09:00:00Z",
        buyer_phone: "+79991234567",
        talk_duration: 60,
        waiting_duration: 0,
        report_text: reportText,
        is_missed: false,
        call_type: "new",
        listing: null,
      }] : [],
    }));

    render(
      <QueryClientProvider client={client}>
        <ConfigProvider theme={{ token: { motion: false } }}>
          <CallsPage />
        </ConfigProvider>
      </QueryClientProvider>,
    );

    await screen.findByText("+7 (999) 123-45-67");
    expect(screen.getByRole("columnheader", { name: "Действия" })).toBeInTheDocument();
    expect(screen.queryByRole("columnheader", { name: "Запись" })).not.toBeInTheDocument();
    expect(screen.queryByRole("columnheader", { name: "Отчет" })).not.toBeInTheDocument();

    const reportButton = screen.getByRole("button", { name: actionName });
    expect(reportButton.textContent).toBe("");
    const cell = reportButton.closest("td");
    if (cell === null) throw new Error("Кнопка отчета должна находиться в ячейке таблицы");
    expect(within(cell).getByRole("button", { name: "Послушать" })).toBeInTheDocument();
  });
});
