import {act, cleanup, fireEvent, render, screen, within} from "@testing-library/react";
import {QueryClient, QueryClientProvider} from "@tanstack/react-query";
import {afterEach, beforeEach, describe, expect, it, vi} from "vitest";
import {message} from "antd";

import {CallsPage} from "../calls/CallsPage";

const activeRowClass = /(?:^|_)activeRow(?:_|$)/;

const state = vi.hoisted(() => ({
    workspaceId: 2,
    getCalls: vi.fn(),
    getCallsSyncStatus: vi.fn(),
    getCallAudio: vi.fn(),
}));

vi.mock("../../features/workspace/model/useCurrentWorkspace", () => ({
    useCurrentWorkspace: () => ({
        currentWorkspaceId: state.workspaceId,
        canViewCalls: true,
    }),
}));
vi.mock("../../features/avito", () => ({
    useAvitoProjectsQuery: () => ({data: [{id: 8, name: "Основной"}], isLoading: false}),
}));
vi.mock("../../shared/api/calls", () => ({
    getCalls: state.getCalls,
    getCallsSyncStatus: state.getCallsSyncStatus,
    getCallAudio: state.getCallAudio,
    getCallDailyReport: vi.fn(),
    saveCallReport: vi.fn(),
}));

function pendingAudio() {
    let resolve!: (blob: Blob) => void;
    let reject!: (error: Error) => void;
    const promise = new Promise<Blob>((onResolve, onReject) => {
        resolve = onResolve;
        reject = onReject;
    });
    return {promise, resolve, reject};
}

function renderPage() {
    const client = new QueryClient({
        defaultOptions: {queries: {retry: false, gcTime: Infinity}},
    });
    const page = () => (
        <QueryClientProvider client={client}>
            <CallsPage/>
        </QueryClientProvider>
    );
    return {...render(page()), page};
}

describe("CallsPage audio lifecycle", () => {
    beforeEach(() => {
        vi.useFakeTimers({toFake: ["Date"]});
        vi.setSystemTime(new Date("2026-09-28T09:00:00Z"));
        state.workspaceId = 2;
        state.getCalls.mockReset();
        state.getCallsSyncStatus.mockReset();
        state.getCallAudio.mockReset();
        state.getCallsSyncStatus.mockResolvedValue({
            last_synced_at: null, backfill_complete: true,
            classification_complete: true, is_syncing: false, phase: null, last_error: "",
        });
        state.getCalls.mockImplementation(({date}: {date: string}) => Promise.resolve({
            count: date === "2026-09-28" ? 2 : 0,
            next: null,
            previous: null,
            results: date === "2026-09-28" ? [1, 2].map((id) => ({
                id, external_id: String(id), occurred_at: "2026-09-28T09:00:00Z",
                buyer_phone: `+7000000000${id}`, talk_duration: 60, waiting_duration: 0,
                is_missed: false, report_text: "", call_type: "new", listing: null,
            })) : [],
        }));
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
    });

    afterEach(() => {
        cleanup();
        message.destroy();
        vi.restoreAllMocks();
        vi.unstubAllGlobals();
        vi.useRealTimers();
    });

    it("starts playback automatically once the opened recording has loaded", async () => {
        state.getCallAudio.mockResolvedValue(new Blob(["audio"]));
        renderPage();
        fireEvent.click((await screen.findAllByRole("button", {name: "Прослушать"}))[0]);
        const player = await screen.findByRole("region", {name: "Плеер записи звонка"});
        const audio = player.querySelector("audio");
        if (!(audio instanceof HTMLAudioElement)) {
            throw new Error("Аудиоэлемент не найден в плеере");
        }
        expect(HTMLMediaElement.prototype.play).not.toHaveBeenCalled();

        fireEvent.loadedMetadata(audio);

        expect(await within(player).findByRole("button", {name: "Пауза"}))
            .toBeInTheDocument();
        expect(HTMLMediaElement.prototype.play).toHaveBeenCalledOnce();
    });

    it("reports blocked autoplay and allows starting playback manually", async () => {
        vi.mocked(HTMLMediaElement.prototype.play)
            .mockRejectedValueOnce(new DOMException("Denied", "NotAllowedError"));
        state.getCallAudio.mockResolvedValue(new Blob(["audio"]));
        renderPage();
        fireEvent.click((await screen.findAllByRole("button", {name: "Прослушать"}))[0]);
        const player = await screen.findByRole("region", {name: "Плеер записи звонка"});
        const audio = player.querySelector("audio");
        if (!(audio instanceof HTMLAudioElement)) {
            throw new Error("Аудиоэлемент не найден в плеере");
        }

        fireEvent.loadedMetadata(audio);

        expect(await screen.findByText(
            "Не удалось автоматически запустить аудио. Нажмите «Воспроизвести».",
        )).toBeInTheDocument();
        fireEvent.click(within(player).getByRole("button", {name: "Воспроизвести"}));
        expect(await within(player).findByRole("button", {name: "Пауза"}))
            .toBeInTheDocument();
    });

    it.each([
        {scenario: "when switching recordings", nextCallIndex: 1, closeFirst: false},
        {scenario: "when reopening the player", nextCallIndex: 0, closeFirst: true},
    ])("keeps the selected playback speed $scenario", async ({nextCallIndex, closeFirst}) => {
        state.getCallAudio.mockResolvedValue(new Blob(["audio"]));
        renderPage();
        const buttons = await screen.findAllByRole("button", {name: "Прослушать"});
        fireEvent.click(buttons[0]);
        const firstPlayer = await screen.findByRole("region", {
            name: "Плеер записи звонка",
        });
        const firstAudio = firstPlayer.querySelector("audio");
        if (!(firstAudio instanceof HTMLAudioElement)) {
            throw new Error("Аудиоэлемент не найден в плеере");
        }
        fireEvent.mouseDown(within(firstPlayer).getByRole("combobox", {name: "Скорость"}));
        fireEvent.click(await screen.findByText("1.5×"));
        expect(firstAudio.playbackRate).toBe(1.5);

        if (closeFirst) {
            fireEvent.click(within(firstPlayer).getByRole("button", {name: "Закрыть плеер"}));
        }
        fireEvent.click(buttons[nextCallIndex]);
        const nextPlayer = await screen.findByRole("region", {
            name: "Плеер записи звонка",
        });
        const nextAudio = nextPlayer.querySelector("audio");
        if (!(nextAudio instanceof HTMLAudioElement)) {
            throw new Error("Аудиоэлемент не найден в плеере");
        }
        fireEvent.loadedMetadata(nextAudio);

        expect(nextAudio.playbackRate).toBe(1.5);
        expect(within(nextPlayer).getByText("1.5×")).toBeInTheDocument();
    });

    it("highlights only the recording row after its player opens", async () => {
        const pending = pendingAudio();
        state.getCallAudio.mockReturnValue(pending.promise);
        renderPage();
        const firstRow = await screen.findByRole("row", {name: /\+7 \(000\) 000-00-01/});
        const secondRow = screen.getByRole("row", {name: /\+7 \(000\) 000-00-02/});

        expect(firstRow).not.toHaveClass(activeRowClass);
        expect(secondRow).not.toHaveClass(activeRowClass);
        fireEvent.click(within(firstRow).getByRole("button", {name: "Прослушать"}));
        expect(firstRow).not.toHaveClass(activeRowClass);
        expect(screen.queryByRole("region", {name: "Плеер записи звонка"}))
            .not.toBeInTheDocument();

        await act(async () => pending.resolve(new Blob(["audio"])));

        expect(screen.getByRole("region", {name: "Плеер записи звонка"}))
            .toBeInTheDocument();
        expect(firstRow).toHaveClass(activeRowClass);
        expect(secondRow).not.toHaveClass(activeRowClass);
    });

    it("moves the highlight to another recording after it loads", async () => {
        const pending = pendingAudio();
        state.getCallAudio
            .mockResolvedValueOnce(new Blob(["first audio"]))
            .mockReturnValueOnce(pending.promise);
        renderPage();
        const firstRow = await screen.findByRole("row", {name: /\+7 \(000\) 000-00-01/});
        const secondRow = screen.getByRole("row", {name: /\+7 \(000\) 000-00-02/});
        fireEvent.click(within(firstRow).getByRole("button", {name: "Прослушать"}));
        await screen.findByText("Разговор с +7 (000) 000-00-01");
        expect(firstRow).toHaveClass(activeRowClass);

        fireEvent.click(within(secondRow).getByRole("button", {name: "Прослушать"}));
        expect(firstRow).not.toHaveClass(activeRowClass);
        expect(secondRow).not.toHaveClass(activeRowClass);
        await act(async () => pending.resolve(new Blob(["second audio"])));

        expect(screen.getByText("Разговор с +7 (000) 000-00-02")).toBeInTheDocument();
        expect(firstRow).not.toHaveClass(activeRowClass);
        expect(secondRow).toHaveClass(activeRowClass);
    });

    it("keeps the recording row highlighted while playback is paused", async () => {
        state.getCallAudio.mockResolvedValue(new Blob(["audio"]));
        renderPage();
        const row = await screen.findByRole("row", {name: /\+7 \(000\) 000-00-01/});
        fireEvent.click(within(row).getByRole("button", {name: "Прослушать"}));
        const player = await screen.findByRole("region", {name: "Плеер записи звонка"});
        const audio = player.querySelector("audio");
        if (!(audio instanceof HTMLAudioElement)) {
            throw new Error("Аудиоэлемент не найден в плеере");
        }
        fireEvent.play(audio);
        expect(within(player).getByRole("button", {name: "Пауза"})).toBeInTheDocument();

        fireEvent.pause(audio);

        expect(within(player).getByRole("button", {name: "Воспроизвести"}))
            .toBeInTheDocument();
        expect(row).toHaveClass(activeRowClass);
    });

    it("removes the recording row highlight when the player closes", async () => {
        state.getCallAudio.mockResolvedValue(new Blob(["audio"]));
        renderPage();
        const row = await screen.findByRole("row", {name: /\+7 \(000\) 000-00-01/});
        fireEvent.click(within(row).getByRole("button", {name: "Прослушать"}));
        await screen.findByRole("region", {name: "Плеер записи звонка"});
        expect(row).toHaveClass(activeRowClass);

        fireEvent.click(screen.getByRole("button", {name: "Закрыть плеер"}));

        expect(screen.queryByRole("region", {name: "Плеер записи звонка"}))
            .not.toBeInTheDocument();
        expect(row).not.toHaveClass(activeRowClass);
    });

    it("aborts on unmount and creates no URL for a late successful response", async () => {
        const pending = pendingAudio();
        state.getCallAudio.mockReturnValue(pending.promise);
        const {unmount} = renderPage();
        fireEvent.click((await screen.findAllByRole("button", {name: "Прослушать"}))[0]);
        const signal: AbortSignal | undefined = state.getCallAudio.mock.calls[0][2];
        unmount();
        await act(async () => pending.resolve(new Blob(["late audio"])));
        expect(URL.createObjectURL).not.toHaveBeenCalled();
        expect(signal?.aborted).toBe(true);
    });

    it("aborts the previous recording and ignores its late response", async () => {
        const first = pendingAudio();
        const second = pendingAudio();
        state.getCallAudio.mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);
        renderPage();
        const buttons = await screen.findAllByRole("button", {name: "Прослушать"});
        fireEvent.click(buttons[0]);
        const firstSignal: AbortSignal | undefined = state.getCallAudio.mock.calls[0][2];
        fireEvent.click(buttons[1]);
        expect(firstSignal?.aborted).toBe(true);
        await act(async () => first.resolve(new Blob(["stale audio"])));
        expect(URL.createObjectURL).not.toHaveBeenCalled();
        const currentAudio = new Blob(["current audio"]);
        await act(async () => second.resolve(currentAudio));
        expect(URL.createObjectURL).toHaveBeenCalledExactlyOnceWith(currentAudio);
        expect(screen.getByText("Разговор с +7 (000) 000-00-02")).toBeInTheDocument();
    });

    it("aborts on workspace change without showing an error for the cancelled request", async () => {
        const pending = pendingAudio();
        state.getCallAudio.mockReturnValue(pending.promise);
        const errors = vi.spyOn(message, "error");
        const {rerender, page} = renderPage();
        fireEvent.click((await screen.findAllByRole("button", {name: "Прослушать"}))[0]);
        const signal: AbortSignal | undefined = state.getCallAudio.mock.calls[0][2];
        state.workspaceId = 3;
        rerender(page());
        await act(async () => pending.reject(new Error("Request cancelled")));
        expect(signal?.aborted).toBe(true);
        expect(errors).not.toHaveBeenCalled();
        expect(URL.createObjectURL).not.toHaveBeenCalled();
    });

    it("does not display a late request error after unmount", async () => {
        const pending = pendingAudio();
        state.getCallAudio.mockReturnValue(pending.promise);
        const errors = vi.spyOn(message, "error");
        const {unmount} = renderPage();
        fireEvent.click((await screen.findAllByRole("button", {name: "Прослушать"}))[0]);
        unmount();
        await act(async () => pending.reject(new Error("Connection closed")));
        expect(errors).not.toHaveBeenCalled();
    });

    it("releases the URL when unmounted before the loaded player is committed", async () => {
        const pending = pendingAudio();
        state.getCallAudio.mockReturnValue(pending.promise);
        const {unmount} = renderPage();
        fireEvent.click((await screen.findAllByRole("button", {name: "Прослушать"}))[0]);
        await act(async () => {
            pending.resolve(new Blob(["audio"]));
            await pending.promise;
            unmount();
        });
        expect(URL.createObjectURL).toHaveBeenCalledOnce();
        expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:recording");
    });

    it("releases an already loaded recording on unmount", async () => {
        state.getCallAudio.mockResolvedValue(new Blob(["audio"]));
        const {unmount} = renderPage();
        fireEvent.click((await screen.findAllByRole("button", {name: "Прослушать"}))[0]);
        await screen.findByRole("region", {name: "Плеер записи звонка"});
        unmount();
        expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:recording");
    });
});
