import type {PropsWithChildren} from "react";
import {
    QueryClient,
    QueryClientProvider,
} from "@tanstack/react-query";
import {
    act,
    renderHook,
    waitFor,
} from "@testing-library/react";
import {
    beforeEach,
    describe,
    expect,
    it,
    vi,
} from "vitest";

import {automationKeys} from "./queryKeys";
import {
    getRunPollingInterval,
    useAutomationCatalogQuery,
    useAutomationInboxSummaryQuery,
    useAutomationsQuery,
} from "./queries";

const apiMocks = vi.hoisted(() => ({
    getAutomationCatalog: vi.fn(),
    getAutomations: vi.fn(),
    getAutomation: vi.fn(),
    getAutomationRuns: vi.fn(),
    getAutomationRun: vi.fn(),
    getAutomationDecisions: vi.fn(),
    getAutomationInboxSummary: vi.fn(),
}));

vi.mock("../api/automationApi", () => apiMocks);

const createQueryEnvironment = () => {
    const queryClient = new QueryClient({
        defaultOptions: {
            queries: {
                retry: false,
            },
        },
    });

    const QueryWrapper = ({
                              children,
                          }: PropsWithChildren) => (
        <QueryClientProvider client={queryClient}>
            {children}
        </QueryClientProvider>
    );

    return {
        queryClient,
        wrapper: QueryWrapper,
    };
};

describe("getRunPollingInterval", () => {
    it("возвращает интервал для выполняющихся запусков", () => {
        expect(getRunPollingInterval("queued")).toBe(2500);
        expect(getRunPollingInterval("evaluating")).toBe(2500);
        expect(getRunPollingInterval("waiting_for_data")).toBe(30000);
        expect(getRunPollingInterval("effect_pending")).toBe(15000);
    });

    it("останавливает polling для решений и завершённых запусков", () => {
        expect(getRunPollingInterval("waiting_approval")).toBe(false);
        expect(getRunPollingInterval("completed")).toBe(false);
        expect(getRunPollingInterval("partial")).toBe(false);
        expect(getRunPollingInterval("failed")).toBe(false);
        expect(getRunPollingInterval("cancelled")).toBe(false);
        expect(getRunPollingInterval(undefined)).toBe(false);
    });
});

describe("automation queries", () => {
    beforeEach(() => {
        vi.clearAllMocks();
    });

    it("не выполняет запрос до выбора workspace", () => {
        const {wrapper} = createQueryEnvironment();

        const {result} = renderHook(
            () => useAutomationCatalogQuery(null),
            {wrapper},
        );

        expect(result.current.fetchStatus).toBe("idle");
        expect(apiMocks.getAutomationCatalog).not.toHaveBeenCalled();
    });

    it("не загружает список автоматизаций без workspace", () => {
        const {wrapper} = createQueryEnvironment();

        const {result} = renderHook(
            () => useAutomationsQuery(null, 1),
            {wrapper},
        );

        expect(result.current.fetchStatus).toBe("idle");
        expect(apiMocks.getAutomations).not.toHaveBeenCalled();
    });

    it("обновляет inbox-счётчик раз в минуту", async () => {
        vi.useFakeTimers();
        apiMocks.getAutomationInboxSummary.mockResolvedValue({
            pending_approval_count: 0,
        });
        const {wrapper} = createQueryEnvironment();

        const {unmount} = renderHook(
            () => useAutomationInboxSummaryQuery(7),
            {wrapper},
        );

        try {
            await vi.waitFor(() => {
                expect(apiMocks.getAutomationInboxSummary)
                    .toHaveBeenCalledTimes(1);
            });

            await act(async () => {
                await vi.advanceTimersByTimeAsync(59_999);
            });
            expect(apiMocks.getAutomationInboxSummary)
                .toHaveBeenCalledTimes(1);

            await act(async () => {
                await vi.advanceTimersByTimeAsync(1);
            });
            await vi.waitFor(() => {
                expect(apiMocks.getAutomationInboxSummary)
                    .toHaveBeenCalledTimes(2);
            });
        } finally {
            unmount();
            vi.useRealTimers();
        }
    });

    it("загружает страницу в ключ текущего workspace", async () => {
        const response = {
            count: 0,
            next: null,
            previous: null,
            results: [],
        };

        apiMocks.getAutomations.mockResolvedValue(response);

        const {
            queryClient,
            wrapper,
        } = createQueryEnvironment();

        const {result} = renderHook(
            () => useAutomationsQuery(7, 2),
            {wrapper},
        );

        await waitFor(() => {
            expect(result.current.isSuccess).toBe(true);
        });

        expect(apiMocks.getAutomations).toHaveBeenCalledWith(7, 2);

        expect(
            queryClient.getQueryData(
                automationKeys.list(7, 2),
            ),
        ).toEqual(response);

        expect(
            queryClient.getQueryData(
                automationKeys.list(8, 2),
            ),
        ).toBeUndefined();
    });

    it("не смешивает запоздалые ответы разных workspace", async () => {
        const workspaceSevenResponse = {
            count: 1,
            next: null,
            previous: null,
            results: [{id: 71, name: "Workspace 7"}],
        };
        const workspaceEightResponse = {
            count: 1,
            next: null,
            previous: null,
            results: [{id: 81, name: "Workspace 8"}],
        };
        let resolveWorkspaceSeven!: (
            value: typeof workspaceSevenResponse,
        ) => void;
        const workspaceSevenRequest = new Promise<
            typeof workspaceSevenResponse
        >((resolve) => {
            resolveWorkspaceSeven = resolve;
        });

        apiMocks.getAutomations.mockImplementation(
            (workspaceId: number) => (
                workspaceId === 7
                    ? workspaceSevenRequest
                    : Promise.resolve(workspaceEightResponse)
            ),
        );

        const {
            queryClient,
            wrapper,
        } = createQueryEnvironment();
        const {result, rerender} = renderHook(
            ({workspaceId}: {workspaceId: number | null}) => (
                useAutomationsQuery(workspaceId, 1)
            ),
            {
                wrapper,
                initialProps: {workspaceId: 7},
            },
        );

        await waitFor(() => {
            expect(apiMocks.getAutomations).toHaveBeenCalledWith(
                7,
                1,
            );
        });

        rerender({workspaceId: 8});

        await waitFor(() => {
            expect(result.current.data).toEqual(
                workspaceEightResponse,
            );
        });
        expect(apiMocks.getAutomations).toHaveBeenLastCalledWith(
            8,
            1,
        );

        resolveWorkspaceSeven(workspaceSevenResponse);

        await waitFor(() => {
            expect(
                queryClient.getQueryData(
                    automationKeys.list(7, 1),
                ),
            ).toEqual(workspaceSevenResponse);
        });
        expect(result.current.data).toEqual(workspaceEightResponse);
        expect(
            queryClient.getQueryData(
                automationKeys.list(8, 1),
            ),
        ).toEqual(workspaceEightResponse);
    });
});
