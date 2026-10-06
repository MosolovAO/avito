import {act, cleanup, fireEvent, render, screen, waitFor, within} from "@testing-library/react";
import {QueryClient, QueryClientProvider} from "@tanstack/react-query";
import {afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi} from "vitest";
import {ConfigProvider, message} from "antd";

import {CallsPage} from "./CallsPage";

const state = vi.hoisted(() => ({
    workspaceId: 2,
    getCalls: vi.fn(),
    getCallsSyncStatus: vi.fn(),
    getCallDailyReport: vi.fn(),
    saveCallReport: vi.fn(),
}));

vi.mock("../../features/workspace/model/useCurrentWorkspace", () => ({
    useCurrentWorkspace: () => ({currentWorkspaceId: state.workspaceId, canViewCalls: true}),
}));
vi.mock("../../features/avito", () => ({
    useAvitoProjectsQuery: () => ({data: [{id: 8, name: "Основной"}], isLoading: false}),
}));
vi.mock("../../shared/api/calls", () => ({
    getCalls: state.getCalls,
    getCallsSyncStatus: state.getCallsSyncStatus,
    getCallDailyReport: state.getCallDailyReport,
    getCallAudio: vi.fn(),
    saveCallReport: state.saveCallReport,
}));

const reportText = "Понедельник, 28 сентября\nОсновной\n\n+7 (000) 000-00-01\nВиктория\n40 кубов\n\n+7 (906) 543-66-45\nОтчет со следующей страницы";
const originalClipboard = Object.getOwnPropertyDescriptor(navigator, "clipboard");
const clients: QueryClient[] = [];
let savedText = "Виктория\n40 кубов";

function renderPage() {
    const client = new QueryClient({
        defaultOptions: {queries: {retry: false, gcTime: Infinity}, mutations: {retry: false}},
    });
    clients.push(client);
    const page = () => (
        <QueryClientProvider client={client}>
            <ConfigProvider theme={{token: {motion: false}}}>
                <CallsPage/>
            </ConfigProvider>
        </QueryClientProvider>
    );
    return {...render(page()), page};
}

async function openDailyReport() {
    fireEvent.click(await screen.findByRole("button", {name: "Отчет за день, 28 сентября"}));
    return screen.findByRole("region", {name: "Дневной отчет за 28 сентября"});
}

describe("CallsPage daily reports", () => {
    beforeAll(() => {
        ConfigProvider.config({holderRender: (children) => (
            <ConfigProvider theme={{token: {motion: false}}}>{children}</ConfigProvider>
        )});
    });

    afterAll(() => ConfigProvider.config({holderRender: undefined}));

    beforeEach(() => {
        vi.useFakeTimers({toFake: ["Date"]});
        vi.setSystemTime(new Date("2026-09-28T09:00:00Z"));
        state.workspaceId = 2;
        savedText = "Виктория\n40 кубов";
        state.getCalls.mockReset();
        state.getCallsSyncStatus.mockReset();
        state.getCallDailyReport.mockReset();
        state.saveCallReport.mockReset();
        state.getCallsSyncStatus.mockResolvedValue({
            last_synced_at: null, backfill_complete: true,
            classification_complete: true, is_syncing: false, phase: null, last_error: "",
        });
        state.getCalls.mockImplementation(({date}: {date: string}) => Promise.resolve({
            count: date === "2026-09-28" ? 1 : 0, next: null, previous: null,
            results: date === "2026-09-28" ? [{
                id: 1, external_id: "1", occurred_at: "2026-09-28T09:00:00Z",
                buyer_phone: "+70000000001", talk_duration: 60, waiting_duration: 0,
                is_missed: false, call_type: "new", listing: null, report_text: savedText,
            }] : [],
        }));
        state.getCallDailyReport.mockResolvedValue({
            avito_account_id: 8, account_name: "Основной", date: "2026-09-28",
            report_count: 2, report_text: reportText,
        });
        state.saveCallReport.mockImplementation(async (_workspaceId: number, _callId: number, text: string) => {
            savedText = text;
            return {report_text: text};
        });
    });

    afterEach(async () => {
        await act(async () => {cleanup(); message.destroy();});
        clients.splice(0).forEach((client) => client.clear());
        await waitFor(() => expect(document.querySelector(".ant-message-notice")).toBeNull());
        vi.restoreAllMocks();
        if (originalClipboard) {
            Object.defineProperty(navigator, "clipboard", originalClipboard);
        } else {
            Reflect.deleteProperty(navigator, "clipboard");
        }
        vi.useRealTimers();
    });

    it("requests the full report only after clicking, without table search or pagination", async () => {
        renderPage();
        await screen.findByRole("button", {name: "Отчет за день, 28 сентября"});
        expect(state.getCallDailyReport).not.toHaveBeenCalled();
        fireEvent.change(screen.getByRole("searchbox", {name: "Поиск по номеру или объявлению"}), {
            target: {value: "Виктория"},
        });
        await waitFor(() => expect(state.getCalls).toHaveBeenCalledWith(expect.objectContaining({search: "Виктория"})));

        const preview = await openDailyReport();

        expect(await within(preview).findByRole("textbox", {name: "Текст дневного отчета"}))
            .toHaveValue(reportText);
        expect(within(preview).getByRole("textbox")).toHaveAttribute("readonly");
        expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
        expect(state.getCallDailyReport).toHaveBeenCalledExactlyOnceWith({
            workspaceId: 2, avitoAccountId: 8, date: "2026-09-28", signal: expect.any(AbortSignal),
        });
    });

    it("copies exactly the generated report including line breaks", async () => {
        const writeText = vi.fn().mockResolvedValue(undefined);
        Object.defineProperty(navigator, "clipboard", {configurable: true, value: {writeText}});
        renderPage();
        const preview = await openDailyReport();

        fireEvent.click(await within(preview).findByRole("button", {name: "Копировать отчет"}));

        await waitFor(() => expect(writeText).toHaveBeenCalledExactlyOnceWith(reportText));
        expect(await screen.findByText("Отчет скопирован")).toBeInTheDocument();
    });

    it("reports a clipboard failure and keeps the text available for manual copying", async () => {
        const writeText = vi.fn().mockRejectedValue(new DOMException("Denied", "NotAllowedError"));
        Object.defineProperty(navigator, "clipboard", {configurable: true, value: {writeText}});
        renderPage();
        const preview = await openDailyReport();

        fireEvent.click(await within(preview).findByRole("button", {name: "Копировать отчет"}));

        expect(await screen.findByText("Не удалось скопировать отчет.")).toBeInTheDocument();
        expect(screen.queryByText("Отчет скопирован")).not.toBeInTheDocument();
        expect(within(preview).getByRole("textbox")).toHaveValue(reportText);
    });

    it("shows an empty state when the day has no saved reports", async () => {
        state.getCallDailyReport.mockResolvedValue({
            avito_account_id: 8, account_name: "Основной", date: "2026-09-28",
            report_count: 0, report_text: "",
        });
        renderPage();
        const preview = await openDailyReport();

        expect(await within(preview).findByText("За этот день нет сохраненных отчетов"))
            .toBeInTheDocument();
        expect(within(preview).queryByRole("button", {name: "Копировать отчет"})).not.toBeInTheDocument();
        expect(within(preview).queryByRole("textbox")).not.toBeInTheDocument();
    });

    it("shows a request error and allows retrying", async () => {
        state.getCallDailyReport.mockRejectedValueOnce(new Error("Network error"));
        renderPage();
        const preview = await openDailyReport();
        expect(await within(preview).findByText("Не удалось сформировать отчет"))
            .toBeInTheDocument();
        expect(within(preview).queryByRole("button", {name: "Копировать отчет"})).not.toBeInTheDocument();

        fireEvent.click(within(preview).getByRole("button", {name: "Повторить"}));

        expect(await within(preview).findByRole("textbox")).toHaveValue(reportText);
    });

    it("aborts a pending request when closed and ignores its late response", async () => {
        let finish!: (value: object) => void;
        state.getCallDailyReport.mockImplementationOnce(() => new Promise((resolve) => {finish = resolve;}));
        renderPage();
        const preview = await openDailyReport();
        expect(await within(preview).findByLabelText("Формирование дневного отчета"))
            .toBeInTheDocument();
        const signal: AbortSignal = state.getCallDailyReport.mock.calls[0][0].signal;

        fireEvent.click(within(preview).getByRole("button", {name: "Закрыть отчет"}));

        expect(signal.aborted).toBe(true);
        await act(async () => finish({
            avito_account_id: 8, account_name: "Основной", date: "2026-09-28",
            report_count: 2, report_text: reportText,
        }));
        expect(screen.queryByRole("region", {name: "Дневной отчет за 28 сентября"})).not.toBeInTheDocument();
        expect(screen.queryByText("Не удалось сформировать отчет")).not.toBeInTheDocument();
    });

    it("closes the report when workspace changes and uses the new workspace on reopening", async () => {
        const {rerender, page} = renderPage();
        const preview = await openDailyReport();
        await within(preview).findByRole("textbox");

        state.workspaceId = 3;
        rerender(page());

        expect(screen.queryByRole("region", {name: "Дневной отчет за 28 сентября"})).not.toBeInTheDocument();
        await openDailyReport();
        await waitFor(() => expect(state.getCallDailyReport).toHaveBeenLastCalledWith({
            workspaceId: 3, avitoAccountId: 8, date: "2026-09-28", signal: expect.any(AbortSignal),
        }));
    });

    it("refreshes an open daily report after saving a call summary", async () => {
        state.getCallDailyReport.mockImplementation(async () => ({
            avito_account_id: 8, account_name: "Основной", date: "2026-09-28",
            report_count: 1, report_text: `Понедельник, 28 сентября\nОсновной\n\n+7 (000) 000-00-01\n${savedText}`,
        }));
        renderPage();
        const preview = await openDailyReport();
        await within(preview).findByRole("textbox");
        fireEvent.click(await screen.findByRole("button", {name: "Редактировать отчет"}));
        const editor = await screen.findByRole("region", {name: "Редактор отчета по звонку"});
        fireEvent.change(within(editor).getByRole("textbox"), {target: {value: "Заказ подтвержден"}});

        fireEvent.click(within(editor).getByRole("button", {name: "Сохранить"}));

        await waitFor(() => expect(within(preview).getByRole("textbox"))
            .toHaveValue("Понедельник, 28 сентября\nОсновной\n\n+7 (000) 000-00-01\nЗаказ подтвержден"));
    });
});
