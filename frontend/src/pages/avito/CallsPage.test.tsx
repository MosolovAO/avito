import {act, cleanup, fireEvent, render, screen, waitFor, within} from "@testing-library/react";
import {QueryClient, QueryClientProvider} from "@tanstack/react-query";
import {afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi} from "vitest";
import {ConfigProvider, message} from "antd";

import {CallsPage} from "../calls/CallsPage";

const state = vi.hoisted(() => ({
    buyerPhone: "+70000000001",
    getCalls: vi.fn(),
    getCallsSyncStatus: vi.fn(),
    getCallAudio: vi.fn(),
}));

const originalClipboard = Object.getOwnPropertyDescriptor(navigator, "clipboard");

vi.mock("../../features/workspace/model/useCurrentWorkspace", () => ({
    useCurrentWorkspace: () => ({
        currentWorkspaceId: 2,
        canViewCalls: true,
    }),
}));

vi.mock("../../features/avito", () => ({
    useAvitoProjectsQuery: () => ({
        data: [{id: 8, name: "Основной"}],
        isLoading: false,
    }),
}));

vi.mock("../../shared/api/calls", () => ({
    getCalls: state.getCalls,
    getCallsSyncStatus: state.getCallsSyncStatus,
    getCallAudio: state.getCallAudio,
    getCallDailyReport: vi.fn(),
    saveCallReport: vi.fn(),
}));

describe("CallsPage", () => {
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

    afterEach(async () => {
        vi.useRealTimers();
        await act(async () => {
            cleanup();
            message.destroy();
        });
        await waitFor(() => {
            expect(document.querySelector(".ant-message-notice")).toBeNull();
        });
        vi.restoreAllMocks();
        if (originalClipboard) {
            Object.defineProperty(navigator, "clipboard", originalClipboard);
        } else {
            Reflect.deleteProperty(navigator, "clipboard");
        }
        vi.unstubAllGlobals();
    });

    beforeEach(() => {
        state.buyerPhone = "+70000000001";
        state.getCalls.mockReset();
        state.getCallsSyncStatus.mockReset();
        state.getCallAudio.mockReset();
        state.getCallsSyncStatus.mockResolvedValue({
            last_synced_at: "2026-09-26T14:46:38+00:00",
            backfill_complete: true,
            is_syncing: false,
            last_error: "",
        });
        state.getCalls.mockImplementation(({date}: {date: string}) => Promise.resolve({
            count: date === new Date().toLocaleDateString("sv-SE", {timeZone: "Europe/Moscow"}) ? 1 : 0,
            next: null,
            previous: null,
            results: date === new Date().toLocaleDateString("sv-SE", {timeZone: "Europe/Moscow"}) ? [{
                id: 1,
                external_id: "123456789",
                occurred_at: new Date().toISOString(),
                buyer_phone: state.buyerPhone,
                talk_duration: 74,
                waiting_duration: 12,
                is_missed: null,
                report_text: "",
                call_type: null,
                listing: null,
            }] : [],
        }));
    });

    it.each([
        ["+79991234567", "+7 (999) 123-45-67"],
        ["8 (999) 123-45-67", "+7 (999) 123-45-67"],
        ["9991234567", "+7 (999) 123-45-67"],
        ["+7 (999) 123-45-67", "+7 (999) 123-45-67"],
        ["+12025550123", "+12025550123"],
        ["+82101234567", "+82101234567"],
        ["", "Неизвестно"],
    ])("formats the buyer phone %s as %s", async (phone, expected) => {
        state.buyerPhone = phone;
        render(
            <QueryClientProvider client={new QueryClient({
                defaultOptions: {queries: {retry: false}},
            })}>
                <CallsPage/>
            </QueryClientProvider>,
        );
        const row = await screen.findByRole("row", {name: /Прослушать/});
        const phoneCell = within(row).getAllByRole("cell")[1];

        expect(phoneCell).toHaveTextContent(expected);
        if (!phone) {
            expect(within(phoneCell).queryByRole("button", {name: "Скопировать номер"}))
                .not.toBeInTheDocument();
        }
    });

    it("copies the displayed phone number with one click", async () => {
        state.buyerPhone = "+79991234567";
        const writeText = vi.fn().mockResolvedValue(undefined);
        Object.defineProperty(navigator, "clipboard", {
            configurable: true,
            value: {writeText},
        });
        render(
            <QueryClientProvider client={new QueryClient({
                defaultOptions: {queries: {retry: false}},
            })}>
                <CallsPage/>
            </QueryClientProvider>,
        );

        fireEvent.click(await screen.findByRole("button", {name: "Скопировать номер"}));

        await waitFor(() => expect(writeText)
            .toHaveBeenCalledExactlyOnceWith("+7 (999) 123-45-67"));
        expect(await screen.findByText("Номер скопирован")).toBeInTheDocument();
        expect(state.getCallAudio).not.toHaveBeenCalled();
    });

    it("reports a clipboard failure without claiming the number was copied", async () => {
        const writeText = vi.fn().mockRejectedValue(new DOMException("Denied", "NotAllowedError"));
        Object.defineProperty(navigator, "clipboard", {
            configurable: true,
            value: {writeText},
        });
        render(
            <QueryClientProvider client={new QueryClient({
                defaultOptions: {queries: {retry: false}},
            })}>
                <CallsPage/>
            </QueryClientProvider>,
        );

        fireEvent.click(await screen.findByRole("button", {name: "Скопировать номер"}));

        expect(await screen.findByText("Не удалось скопировать номер."))
            .toBeInTheDocument();
        expect(screen.queryByText("Номер скопирован")).not.toBeInTheDocument();
    });

    it("shows unknown for data that Avito did not provide", async () => {
        const queryClient = new QueryClient({
            defaultOptions: {queries: {retry: false}},
        });
        render(
            <QueryClientProvider client={queryClient}>
                <CallsPage/>
            </QueryClientProvider>,
        );

        expect(await screen.findByText("+7 (000) 000-00-01")).toBeInTheDocument();
        expect(screen.getAllByText("Неизвестно").length).toBeGreaterThanOrEqual(2);
    });

    it("keeps a masked buyer phone masked", async () => {
        state.getCalls.mockImplementation(({date}: {date: string}) => Promise.resolve({
            count: date === new Date().toLocaleDateString("sv-SE", {timeZone: "Europe/Moscow"}) ? 1 : 0,
            next: null,
            previous: null,
            results: date === new Date().toLocaleDateString("sv-SE", {timeZone: "Europe/Moscow"}) ? [{
                id: 1,
                external_id: "1",
                occurred_at: new Date().toISOString(),
                buyer_phone: "***1234",
                talk_duration: 0,
                waiting_duration: 12,
                is_missed: true,
                report_text: "",
                call_type: null,
                listing: null,
            }] : [],
        }));

        render(
            <QueryClientProvider client={new QueryClient({
                defaultOptions: {queries: {retry: false}},
            })}>
                <CallsPage/>
            </QueryClientProvider>,
        );

        expect(await screen.findByText("***1234")).toBeInTheDocument();
        expect(screen.queryByText("+1234")).not.toBeInTheDocument();
    });

    it("shows the service call type without a status column", async () => {
        vi.useFakeTimers({toFake: ["Date"]});
        vi.setSystemTime(new Date("2026-09-27T08:00:00Z"));
        state.getCalls.mockImplementation(({date}: {date: string}) => Promise.resolve({
            count: date === "2026-09-27" ? 2 : 0,
            next: null,
            previous: null,
            results: date === "2026-09-27" ? [
                {
                    id: 1,
                    external_id: "1",
                    occurred_at: "2026-09-27T08:00:00Z",
                    buyer_phone: "+70000000001",
                    talk_duration: 74,
                    waiting_duration: 12,
                    is_missed: false,
                    report_text: "",
                    call_type: "new",
                    listing: null,
                },
                {
                    id: 2,
                    external_id: "2",
                    occurred_at: "2026-09-27T09:00:00Z",
                    buyer_phone: "+70000000002",
                    talk_duration: 74,
                    waiting_duration: 12,
                    is_missed: true,
                    report_text: "",
                    call_type: "repeat",
                    listing: null,
                },
            ] : [],
        }));

        render(
            <QueryClientProvider client={new QueryClient({
                defaultOptions: {queries: {retry: false}},
            })}>
                <CallsPage/>
            </QueryClientProvider>,
        );

        expect(await screen.findByText("+7 (000) 000-00-01")).toBeInTheDocument();
        expect(screen.getByRole("columnheader", {name: "Тип"})).toBeInTheDocument();
        expect(screen.getByText("Новый")).toBeInTheDocument();
        expect(screen.getByText("Повторный")).toBeInTheDocument();
        expect(screen.queryByRole("columnheader", {name: "Статус"})).not.toBeInTheDocument();
        expect(screen.queryByText("Принят")).not.toBeInTheDocument();
        expect(screen.queryByText("Пропущенный")).not.toBeInTheDocument();
    });

    it("shows a background sync error while the call list loads successfully", async () => {
        state.getCallsSyncStatus.mockResolvedValue({
            last_synced_at: "2026-09-26T14:46:38+00:00",
            backfill_complete: false,
            is_syncing: false,
            last_error: "Ошибка Avito API (HTTP неизвестен).",
        });
        const queryClient = new QueryClient({
            defaultOptions: {queries: {retry: false}},
        });

        render(
            <QueryClientProvider client={queryClient}>
                <CallsPage/>
            </QueryClientProvider>,
        );

        expect(await screen.findByText("+7 (000) 000-00-01")).toBeInTheDocument();
        expect(await screen.findByText("Ошибка синхронизации звонков"))
            .toBeInTheDocument();
        expect(screen.getByText("Ошибка Avito API (HTTP неизвестен)."))
            .toBeInTheDocument();
    });

    it("refreshes visible calls when background sync advances", async () => {
        vi.useFakeTimers({toFake: ["Date"]});
        vi.setSystemTime(new Date("2026-09-27T08:00:00Z"));
        let synced = false;
        state.getCallsSyncStatus.mockImplementation(() => Promise.resolve({
            last_synced_at: synced
                ? "2026-09-27T09:00:00+00:00"
                : "2026-09-27T08:00:00+00:00",
            backfill_complete: true,
            classification_complete: true,
            is_syncing: false,
            phase: null,
            last_error: "",
        }));
        state.getCalls.mockImplementation(({date}: {date: string}) => Promise.resolve({
            count: date === "2026-09-27" ? (synced ? 2 : 1) : 0,
            next: null,
            previous: null,
            results: date === "2026-09-27" ? [
                {
                    id: 1,
                    external_id: "1",
                    occurred_at: "2026-09-27T08:00:00Z",
                    buyer_phone: "+70000000001",
                    talk_duration: 74,
                    waiting_duration: 12,
                    is_missed: false,
                    report_text: "",
                    call_type: "new",
                    listing: null,
                },
                ...(synced ? [{
                    id: 2,
                    external_id: "2",
                    occurred_at: "2026-09-27T09:00:00Z",
                    buyer_phone: "+70000000002",
                    talk_duration: 74,
                    waiting_duration: 12,
                    is_missed: false,
                    report_text: "",
                    call_type: "repeat",
                    listing: null,
                }] : []),
            ] : [],
        }));

        render(
            <QueryClientProvider client={new QueryClient({
                defaultOptions: {queries: {retry: false}},
            })}>
                <CallsPage/>
            </QueryClientProvider>,
        );

        expect(await screen.findByText("+7 (000) 000-00-01")).toBeInTheDocument();
        expect(await screen.findByText("История звонков загружена, типы определены"))
            .toBeInTheDocument();
        expect(screen.queryByText("+7 (000) 000-00-02")).not.toBeInTheDocument();

        synced = true;
        fireEvent.click(screen.getByRole("button", {name: "Обновить"}));

        expect(await screen.findByText("+7 (000) 000-00-02")).toBeInTheDocument();
    });

    it("shows every day of the selected week, including days without calls", async () => {
        vi.useFakeTimers({toFake: ["Date"]});
        vi.setSystemTime(new Date("2026-09-09T10:00:00Z"));
        state.getCalls.mockImplementation(({date}: {date: string}) => Promise.resolve({
            count: date === "2026-09-08" ? 1 : 0,
            next: null,
            previous: null,
            results: date === "2026-09-08" ? [{
                id: 2,
                external_id: "2",
                occurred_at: "2026-09-08T09:00:00+03:00",
                buyer_phone: "+70000000002",
                talk_duration: 10,
                waiting_duration: 0,
                is_missed: false,
                report_text: "",
                call_type: "new",
                listing: null,
            }] : [],
        }));

        render(
            <QueryClientProvider client={new QueryClient({
                defaultOptions: {queries: {retry: false}},
            })}>
                <CallsPage/>
            </QueryClientProvider>,
        );

        expect(await screen.findByText("+7 (000) 000-00-02")).toBeInTheDocument();
        expect(screen.getByText("7 сентября 2026 г., Понедельник")).toBeInTheDocument();
        expect(screen.getByText("8 сентября 2026 г., Вторник")).toBeInTheDocument();
        expect(screen.getByText("13 сентября 2026 г., Воскресенье")).toBeInTheDocument();
        expect(screen.getByLabelText("Количество звонков за 7 сентября")).toHaveTextContent("0");
        expect(screen.getByLabelText("Количество звонков за 8 сентября")).toHaveTextContent("1");
        expect(screen.getAllByText("Нет доступных записей")).toHaveLength(6);
        expect(state.getCalls.mock.calls.map(([args]) => args.date).sort()).toEqual([
            "2026-09-07", "2026-09-08", "2026-09-09", "2026-09-10",
            "2026-09-11", "2026-09-12", "2026-09-13",
        ]);
    });

    it("loads the next page of calls for a busy day", async () => {
        vi.useFakeTimers({toFake: ["Date"]});
        vi.setSystemTime(new Date("2026-09-09T10:00:00Z"));
        state.getCalls.mockImplementation(({date, page}: {date: string; page: number}) =>
            Promise.resolve({
                count: date === "2026-09-08" ? 31 : 0,
                next: date === "2026-09-08" && page === 1 ? "/api/calls/?page=2" : null,
                previous: null,
                results: date === "2026-09-08" ? (page === 1
                    ? Array.from({length: 30}, (_, index) => index + 1)
                    : [31]).map((id) => ({
                    id,
                    external_id: String(id),
                    occurred_at: "2026-09-08T09:00:00+03:00",
                    buyer_phone: `+7${String(id).padStart(10, "0")}`,
                    talk_duration: 10,
                    waiting_duration: 0,
                    is_missed: false,
                    report_text: "",
                    call_type: "new",
                    listing: null,
                })) : [],
            }),
        );

        render(
            <QueryClientProvider client={new QueryClient({
                defaultOptions: {queries: {retry: false}},
            })}>
                <CallsPage/>
            </QueryClientProvider>,
        );

        expect(await screen.findByText("+7 (000) 000-00-01")).toBeInTheDocument();
        expect(screen.queryByText("+7 (000) 000-00-31")).not.toBeInTheDocument();
        expect(screen.getByLabelText("Количество звонков за 8 сентября")).toHaveTextContent("31");
        expect(state.getCalls).toHaveBeenCalledTimes(7);
        fireEvent.click(screen.getByTitle("2"));
        expect(await screen.findByText("+7 (000) 000-00-31")).toBeInTheDocument();
        expect(screen.queryByText("+7 (000) 000-00-01")).not.toBeInTheDocument();
        expect(screen.getByLabelText("Количество звонков за 8 сентября")).toHaveTextContent("31");
        expect(state.getCalls).toHaveBeenCalledTimes(8);
    });

    it("switches the displayed week through the calendar", async () => {
        vi.useFakeTimers({toFake: ["Date"]});
        vi.setSystemTime(new Date("2026-09-09T10:00:00Z"));
        state.getCalls.mockImplementation(({date}: {date: string}) => Promise.resolve({
            count: date === "2026-09-22" ? 1 : 0,
            next: null,
            previous: null,
            results: date === "2026-09-22" ? [{
                id: 22,
                external_id: "22",
                occurred_at: "2026-09-22T09:00:00+03:00",
                buyer_phone: "+70000000022",
                talk_duration: 10,
                waiting_duration: 0,
                is_missed: false,
                report_text: "",
                call_type: "new",
                listing: null,
            }] : [],
        }));

        render(
            <QueryClientProvider client={new QueryClient({
                defaultOptions: {queries: {retry: false}},
            })}>
                <CallsPage/>
            </QueryClientProvider>,
        );

        expect(await screen.findByText("7 сентября 2026 г., Понедельник"))
            .toBeInTheDocument();
        fireEvent.click(screen.getByPlaceholderText("Выберите неделю"));
        fireEvent.click(await screen.findByTitle("2026-09-22"));

        expect(await screen.findByText("21 сентября 2026 г., Понедельник"))
            .toBeInTheDocument();
        expect(screen.getByText("27 сентября 2026 г., Воскресенье"))
            .toBeInTheDocument();
        expect(await screen.findByText("+7 (000) 000-00-22")).toBeInTheDocument();
        expect(screen.queryByText("7 сентября 2026 г., Понедельник"))
            .not.toBeInTheDocument();
    });

    it("filters the selected week by a formatted phone number", async () => {
        vi.useFakeTimers({toFake: ["Date"]});
        vi.setSystemTime(new Date("2026-09-27T08:00:00Z"));
        state.getCalls.mockImplementation(({date, search}: {date: string; search?: string}) => Promise.resolve({
            count: (date === "2026-09-22" || date === "2026-09-23")
                && (!search || (date === "2026-09-22"
                    && search.replace(/\D/g, "") === "79991234567")) ? 1 : 0,
            next: null,
            previous: null,
            results: (date === "2026-09-22" || date === "2026-09-23")
                && (!search || (date === "2026-09-22"
                    && search.replace(/\D/g, "") === "79991234567")) ? [{
                id: date === "2026-09-22" ? 22 : 23,
                external_id: date,
                occurred_at: `${date}T12:34:56Z`,
                buyer_phone: date === "2026-09-22" ? "+79991234567" : "+70000000023",
                talk_duration: 74,
                waiting_duration: 12,
                is_missed: false,
                report_text: "",
                call_type: "new",
                listing: null,
            }] : [],
        }));

        render(
            <QueryClientProvider client={new QueryClient({
                defaultOptions: {queries: {retry: false}},
            })}>
                <CallsPage/>
            </QueryClientProvider>,
        );

        expect(await screen.findByText("+7 (999) 123-45-67")).toBeInTheDocument();
        expect(screen.getByText("+7 (000) 000-00-23")).toBeInTheDocument();
        fireEvent.change(screen.getByPlaceholderText("Поиск по номеру или объявлению"), {
            target: {value: "+7 (999) 123-45-67"},
        });

        await waitFor(() => {
            expect(screen.getByText("+7 (999) 123-45-67")).toBeInTheDocument();
            expect(screen.queryByText("+7 (000) 000-00-23")).not.toBeInTheDocument();
        });
        expect(screen.getByText("22 сентября 2026 г., Вторник"))
            .toBeInTheDocument();
        expect(screen.queryByText("23 сентября 2026 г., Среда"))
            .not.toBeInTheDocument();
        expect(state.getCalls).toHaveBeenCalledTimes(14);
        expect(state.getCalls.mock.calls.slice(7).every(([args]) =>
            args.search === "+7 (999) 123-45-67")).toBe(true);
    });

    it("searches listing title and id, then restores the week when cleared", async () => {
        vi.useFakeTimers({toFake: ["Date"]});
        vi.setSystemTime(new Date("2026-09-27T08:00:00Z"));
        state.getCalls.mockImplementation(({date, search}: {date: string; search?: string}) => Promise.resolve({
            count: (date === "2026-09-22" || date === "2026-09-23")
                && (!search || (date === "2026-09-22"
                    ? "велосипед stels".includes(search.toLowerCase())
                    : "диван 998877".includes(search.toLowerCase()))) ? 1 : 0,
            next: null,
            previous: null,
            results: (date === "2026-09-22" || date === "2026-09-23")
                && (!search || (date === "2026-09-22"
                    ? "велосипед stels".includes(search.toLowerCase())
                    : "диван 998877".includes(search.toLowerCase()))) ? [{
                id: date === "2026-09-22" ? 22 : 23,
                external_id: date,
                occurred_at: `${date}T12:34:56Z`,
                buyer_phone: date === "2026-09-22" ? "+70000000022" : "+70000000023",
                talk_duration: 74,
                waiting_duration: 12,
                is_missed: false,
                report_text: "",
                call_type: "new",
                listing: {
                    id: 1,
                    avito_id: date === "2026-09-22" ? "554433" : "998877",
                    title: date === "2026-09-22" ? "Велосипед Stels" : "Диван",
                    url: null,
                },
            }] : [],
        }));

        render(
            <QueryClientProvider client={new QueryClient({
                defaultOptions: {queries: {retry: false}},
            })}>
                <CallsPage/>
            </QueryClientProvider>,
        );

        expect(await screen.findByText("Велосипед Stels")).toBeInTheDocument();
        const search = screen.getByPlaceholderText("Поиск по номеру или объявлению");
        fireEvent.change(search, {target: {value: "велосипед"}});
        await waitFor(() => {
            expect(screen.getByText("Велосипед Stels")).toBeInTheDocument();
            expect(screen.queryByText("Диван")).not.toBeInTheDocument();
        });

        fireEvent.change(search, {target: {value: "998877"}});
        expect(await screen.findByText("Диван")).toBeInTheDocument();
        await waitFor(() => expect(screen.queryByText("Велосипед Stels"))
            .not.toBeInTheDocument());

        fireEvent.change(search, {target: {value: "нет совпадений"}});
        expect(await screen.findByText("По выбранной неделе ничего не найдено"))
            .toBeInTheDocument();

        fireEvent.change(search, {target: {value: ""}});
        expect(await screen.findByText("Велосипед Stels")).toBeInTheDocument();
        expect(screen.getByText("Диван")).toBeInTheDocument();
    });

    it("closes the audio player with its close button", async () => {
        const NativeURL = URL;
        vi.stubGlobal("URL", class extends NativeURL {
            static createObjectURL = vi.fn(() => "blob:call");
            static revokeObjectURL = vi.fn();
        });
        state.getCallAudio.mockResolvedValue(new Blob(["audio"], {type: "audio/mpeg"}));

        render(
            <QueryClientProvider client={new QueryClient({
                defaultOptions: {queries: {retry: false}},
            })}>
                <CallsPage/>
            </QueryClientProvider>,
        );

        fireEvent.click(await screen.findByRole("button", {name: "Прослушать"}));
        const player = await screen.findByRole("region", {
            name: "Плеер записи звонка",
        });
        expect(within(player).getByText("Разговор с +7 (000) 000-00-01"))
            .toBeInTheDocument();
        fireEvent.click(screen.getByLabelText("Закрыть плеер"));

        expect(screen.queryByRole("region", {name: "Плеер записи звонка"}))
            .not.toBeInTheDocument();
        expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:call");
    });

    it("shows accessible playback controls when a call recording opens", async () => {
        const NativeURL = URL;
        vi.stubGlobal("URL", class extends NativeURL {
            static createObjectURL = vi.fn(() => "blob:call");
            static revokeObjectURL = vi.fn();
        });
        state.getCallAudio.mockResolvedValue(new Blob(["audio"], {type: "audio/mpeg"}));

        render(
            <QueryClientProvider client={new QueryClient({
                defaultOptions: {queries: {retry: false}},
            })}>
                <CallsPage/>
            </QueryClientProvider>,
        );

        fireEvent.click(await screen.findByRole("button", {name: "Прослушать"}));
        const player = await screen.findByRole("region", {
            name: "Плеер записи звонка",
        });

        expect(within(player).getByRole("button", {name: "Воспроизвести"}))
            .toBeInTheDocument();
        expect(within(player).getByRole("slider", {name: "Перемотка"}))
            .toBeInTheDocument();
        expect(within(player).getByRole("slider", {name: "Громкость"}))
            .toBeInTheDocument();
        expect(within(player).getByRole("combobox", {name: "Скорость"}))
            .toBeInTheDocument();
        expect(within(player).getByRole("button", {name: "Закрыть плеер"}))
            .toBeInTheDocument();
    });

    it("changes the recording volume from the player", async () => {
        const NativeURL = URL;
        vi.stubGlobal("URL", class extends NativeURL {
            static createObjectURL = vi.fn(() => "blob:call");
            static revokeObjectURL = vi.fn();
        });
        state.getCallAudio.mockResolvedValue(new Blob(["audio"], {type: "audio/mpeg"}));

        render(
            <QueryClientProvider client={new QueryClient({
                defaultOptions: {queries: {retry: false}},
            })}>
                <CallsPage/>
            </QueryClientProvider>,
        );

        fireEvent.click(await screen.findByRole("button", {name: "Прослушать"}));
        const player = await screen.findByRole("region", {
            name: "Плеер записи звонка",
        });
        const audio = player.querySelector("audio");
        if (!(audio instanceof HTMLAudioElement)) {
            throw new Error("Аудиоэлемент не найден в плеере");
        }

        fireEvent.keyDown(within(player).getByRole("slider", {name: "Громкость"}), {
            key: "ArrowLeft",
            code: "ArrowLeft",
            keyCode: 37,
        });

        expect(audio.volume).toBeLessThan(1);
    });
});
