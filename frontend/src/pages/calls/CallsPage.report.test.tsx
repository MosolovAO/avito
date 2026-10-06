import {act, cleanup, fireEvent, render, screen, waitFor, within} from "@testing-library/react";
import {QueryClient, QueryClientProvider} from "@tanstack/react-query";
import {afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi} from "vitest";
import {ConfigProvider, message} from "antd";

import {CallsPage} from "./CallsPage";

const state = vi.hoisted(() => ({
    workspaceId: 2,
    getCalls: vi.fn(),
    getCallsSyncStatus: vi.fn(),
    getCallAudio: vi.fn(),
    saveCallReport: vi.fn(),
}));

vi.mock("../../features/workspace/model/useCurrentWorkspace", () => ({
    useCurrentWorkspace: () => ({
        currentWorkspaceId: state.workspaceId,
        canViewCalls: true,
    }),
}));
vi.mock("../../features/avito", () => ({
    useAvitoProjectsQuery: () => ({
        data: [{id: 8, name: "Основной"}], isLoading: false,
    }),
}));
vi.mock("../../shared/api/calls", () => ({
    getCalls: state.getCalls,
    getCallsSyncStatus: state.getCallsSyncStatus,
    getCallAudio: state.getCallAudio,
    getCallDailyReport: vi.fn(),
    saveCallReport: state.saveCallReport,
}));

function makeCall(id: number, reportText = "") {
    return {
        id, external_id: String(id), occurred_at: "2026-09-28T09:00:00Z",
        buyer_phone: `+7000000000${id}`, talk_duration: 60, waiting_duration: 0,
        is_missed: false, call_type: "new" as const, listing: null,
        report_text: reportText,
    };
}

let calls = [makeCall(1)];
const clients: QueryClient[] = [];

function renderPage() {
    const client = new QueryClient({
        defaultOptions: {
            queries: {retry: false, gcTime: Infinity},
            mutations: {retry: false},
        },
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

async function openReport(buttonName = "Добавить отчет") {
    fireEvent.click(await screen.findByRole("button", {name: buttonName}));
    return screen.findByRole("region", {name: "Редактор отчета по звонку"});
}

describe("CallsPage call reports", () => {
    beforeAll(() => {
        ConfigProvider.config({
            holderRender: (children) => (
                <ConfigProvider theme={{token: {motion: false}}}>
                    {children}
                </ConfigProvider>
            ),
        });
    });

    afterAll(() => {
        ConfigProvider.config({holderRender: undefined});
    });

    beforeEach(() => {
        vi.useFakeTimers({toFake: ["Date"]});
        vi.setSystemTime(new Date("2026-09-28T09:00:00Z"));
        state.workspaceId = 2;
        calls = [makeCall(1)];
        state.getCalls.mockReset();
        state.getCallsSyncStatus.mockReset();
        state.getCallAudio.mockReset();
        state.saveCallReport.mockReset();
        state.getCallsSyncStatus.mockResolvedValue({
            last_synced_at: null, backfill_complete: true,
            classification_complete: true, is_syncing: false,
            phase: null, last_error: "",
        });
        state.getCalls.mockImplementation(({date}: {date: string}) => Promise.resolve({
            count: date === "2026-09-28" ? calls.length : 0,
            next: null, previous: null,
            results: date === "2026-09-28" ? calls.map((call) => ({...call})) : [],
        }));
        state.saveCallReport.mockImplementation(async (
            _workspaceId: number, callId: number, reportText: string,
        ) => {
            const call = calls.find((item) => item.id === callId);
            if (!call) throw new Error("Звонок не найден в тестовых данных");
            call.report_text = reportText;
            return {report_text: reportText};
        });
    });

    afterEach(async () => {
        await act(async () => {
            cleanup();
            message.destroy();
        });
        clients.splice(0).forEach((client) => client.clear());
        await waitFor(() => {
            expect(document.querySelector(".ant-message-notice")).toBeNull();
        });
        vi.restoreAllMocks();
        vi.unstubAllGlobals();
        vi.useRealTimers();
    });

    it("opens an empty inline report editor for a call", async () => {
        renderPage();

        const editor = await openReport();

        expect(within(editor).getByRole("textbox", {name: "Краткий итог звонка"}))
            .toHaveValue("");
        expect(within(editor).getByRole("button", {name: "Сохранить"})).toBeEnabled();
        expect(within(editor).getByRole("button", {name: "Отменить"})).toBeEnabled();
    });

    it("saves the text with line breaks and shows it when reopening the report", async () => {
        renderPage();
        const editor = await openReport();
        const report = "Виктория\nГСБ 40 кубов / Москва / Перезвонит клиенту";
        fireEvent.change(within(editor).getByRole("textbox", {name: "Краткий итог звонка"}), {
            target: {value: report},
        });

        fireEvent.click(within(editor).getByRole("button", {name: "Сохранить"}));

        await waitFor(() => expect(screen.queryByRole("region", {name: "Редактор отчета по звонку"})).not.toBeInTheDocument());
        const reopened = await openReport("Редактировать отчет");
        expect(within(reopened).getByRole("textbox", {name: "Краткий итог звонка"}))
            .toHaveValue(report);
        expect(state.saveCallReport).toHaveBeenCalledExactlyOnceWith(2, 1, report);
    });

    it("loads an existing report and saves changes to that call", async () => {
        calls[0].report_text = "Клиент перезвонит";
        renderPage();
        const editor = await openReport("Редактировать отчет");
        const input = within(editor).getByRole("textbox", {name: "Краткий итог звонка"});
        expect(input).toHaveValue("Клиент перезвонит");
        fireEvent.change(input, {target: {value: "Заказ подтвержден\n40 кубов"}});

        fireEvent.click(within(editor).getByRole("button", {name: "Сохранить"}));

        await waitFor(() => expect(screen.queryByRole("region", {name: "Редактор отчета по звонку"})).not.toBeInTheDocument());
        const reopened = await openReport("Редактировать отчет");
        expect(within(reopened).getByRole("textbox", {name: "Краткий итог звонка"}))
            .toHaveValue("Заказ подтвержден\n40 кубов");
    });

    it("discards unsaved changes on cancel", async () => {
        calls[0].report_text = "Сохраненный отчет";
        renderPage();
        const editor = await openReport("Редактировать отчет");
        fireEvent.change(within(editor).getByRole("textbox", {name: "Краткий итог звонка"}), {
            target: {value: "Несохраненные изменения"},
        });

        fireEvent.click(within(editor).getByRole("button", {name: "Отменить"}));

        await waitFor(() => expect(screen.queryByRole("region", {name: "Редактор отчета по звонку"})).not.toBeInTheDocument());
        const reopened = await openReport("Редактировать отчет");
        expect(within(reopened).getByRole("textbox", {name: "Краткий итог звонка"}))
            .toHaveValue("Сохраненный отчет");
        expect(state.saveCallReport).not.toHaveBeenCalled();
    });

    it("keeps the entered text after a save error and allows a retry", async () => {
        state.saveCallReport.mockRejectedValueOnce(new Error("Network failure"));
        renderPage();
        const editor = await openReport();
        fireEvent.change(within(editor).getByRole("textbox", {name: "Краткий итог звонка"}), {
            target: {value: "Клиент перезвонит"},
        });

        fireEvent.click(within(editor).getByRole("button", {name: "Сохранить"}));

        expect(await screen.findByText("Не удалось сохранить отчет."))
            .toBeInTheDocument();
        expect(within(editor).getByRole("textbox", {name: "Краткий итог звонка"}))
            .toHaveValue("Клиент перезвонит");
        fireEvent.click(within(editor).getByRole("button", {name: "Сохранить"}));
        await waitFor(() => expect(screen.queryByRole("region", {name: "Редактор отчета по звонку"})).not.toBeInTheDocument());
        expect(await screen.findByRole("button", {name: "Редактировать отчет"}))
            .toBeInTheDocument();
    });

    it("rejects a report containing only whitespace", async () => {
        renderPage();
        const editor = await openReport();
        fireEvent.change(within(editor).getByRole("textbox", {name: "Краткий итог звонка"}), {
            target: {value: " \n\t "},
        });

        fireEvent.click(within(editor).getByRole("button", {name: "Сохранить"}));

        expect(await within(editor).findByText("Введите текст отчета."))
            .toBeInTheDocument();
        expect(state.saveCallReport).not.toHaveBeenCalled();
    });

    it("locks the editor and prevents cancellation and duplicate saves while pending", async () => {
        let finishSave!: (value: {report_text: string}) => void;
        state.saveCallReport.mockImplementationOnce(() => new Promise<{report_text: string}>((resolve) => {
            finishSave = resolve;
        }));
        renderPage();
        const editor = await openReport();
        fireEvent.change(within(editor).getByRole("textbox", {name: "Краткий итог звонка"}), {
            target: {value: "Клиент перезвонит"},
        });

        const saveButton = within(editor).getByRole("button", {name: "Сохранить"});
        fireEvent.click(saveButton);

        await waitFor(() => expect(state.saveCallReport).toHaveBeenCalledOnce());
        expect(within(editor).getByRole("textbox", {name: "Краткий итог звонка"})).toBeDisabled();
        expect(within(editor).getByRole("button", {name: "Отменить"})).toBeDisabled();
        expect(saveButton).toBeDisabled();
        fireEvent.click(saveButton);
        expect(state.saveCallReport).toHaveBeenCalledOnce();
        await act(async () => finishSave({report_text: "Клиент перезвонит"}));
        await waitFor(() => expect(screen.queryByRole("region", {name: "Редактор отчета по звонку"})).not.toBeInTheDocument());
    });

    it("keeps the report draft while pausing and seeking outside the editor", async () => {
        const NativeURL = URL;
        vi.stubGlobal("URL", class extends NativeURL {
            static createObjectURL = vi.fn(() => "blob:recording");
            static revokeObjectURL = vi.fn();
        });
        vi.spyOn(HTMLMediaElement.prototype, "play").mockImplementation(function (this: HTMLMediaElement) {
            Object.defineProperty(this, "paused", {configurable: true, value: false});
            fireEvent.play(this);
            return Promise.resolve();
        });
        vi.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(function (this: HTMLMediaElement) {
            Object.defineProperty(this, "paused", {configurable: true, value: true});
            fireEvent.pause(this);
        });
        state.getCallAudio.mockResolvedValue(new Blob(["audio"]));
        renderPage();
        fireEvent.click(await screen.findByRole("button", {name: "Прослушать"}));
        const player = await screen.findByRole("region", {name: "Плеер записи звонка"});
        const audio = player.querySelector("audio");
        if (!(audio instanceof HTMLAudioElement)) {
            throw new Error("Аудиоэлемент не найден в плеере");
        }
        Object.defineProperty(audio, "duration", {configurable: true, value: 60});
        fireEvent.loadedMetadata(audio);
        await within(player).findByRole("button", {name: "Пауза"});

        fireEvent.click(await screen.findByRole("button", {name: "Добавить отчет"}));
        const input = await screen.findByRole("textbox", {name: "Краткий итог звонка"});
        fireEvent.change(input, {target: {value: "Клиент перезвонит"}});
        expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
        const editor = screen.getByRole("region", {name: "Редактор отчета по звонку"});
        expect(editor.closest("tr")).not.toBeNull();

        fireEvent.click(within(player).getByRole("button", {name: "Пауза"}));
        expect(audio.paused).toBe(true);
        expect(within(player).getByRole("button", {name: "Воспроизвести"}))
            .toBeInTheDocument();
        fireEvent.keyDown(within(player).getByRole("slider", {name: "Перемотка"}), {
            key: "ArrowRight", code: "ArrowRight", keyCode: 39,
        });
        expect(audio.currentTime).toBe(1);
        fireEvent.click(screen.getByRole("heading", {name: "Звонки"}));
        expect(input).toHaveValue("Клиент перезвонит");
        expect(editor).toBeInTheDocument();
        expect(state.saveCallReport).not.toHaveBeenCalled();

        fireEvent.click(within(editor).getByRole("button", {name: "Сохранить"}));
        await waitFor(() => expect(editor).not.toBeInTheDocument());
        const reopened = await openReport("Редактировать отчет");
        expect(within(reopened).getByRole("textbox", {name: "Краткий итог звонка"}))
            .toHaveValue("Клиент перезвонит");
    });

    it("closes the draft when the workspace changes and does not reopen it on return", async () => {
        const {rerender, page} = renderPage();
        const editor = await openReport();
        fireEvent.change(within(editor).getByRole("textbox", {name: "Краткий итог звонка"}), {
            target: {value: "Черновик другого workspace"},
        });

        state.workspaceId = 3;
        rerender(page());

        await waitFor(() => expect(screen.queryByRole("region", {name: "Редактор отчета по звонку"})).not.toBeInTheDocument());
        state.workspaceId = 2;
        rerender(page());
        expect(screen.queryByRole("region", {name: "Редактор отчета по звонку"})).not.toBeInTheDocument();
        expect(state.saveCallReport).not.toHaveBeenCalled();
    });
});
