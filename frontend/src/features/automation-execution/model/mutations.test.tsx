import type {PropsWithChildren} from "react";
import {
    QueryClient,
    QueryClientProvider,
} from "@tanstack/react-query";
import {
    act,
    renderHook,
} from "@testing-library/react";
import {
    beforeEach,
    describe,
    expect,
    it,
    vi,
} from "vitest";

import type {
    Automation,
    CreateAutomationRequest,
} from "../../../entities/automation";
import {automationKeys} from "../../../entities/automation";
import {
    useArchiveAutomationMutation,
    useCreateAutomationMutation,
    useCreateAutomationPreviewMutation,
    useCreateAutomationRunMutation,
    useUpdateAutomationMutation,
} from "./mutations";

const apiMocks = vi.hoisted(() => ({
    archiveAutomation: vi.fn(),
    createAutomation: vi.fn(),
    updateAutomation: vi.fn(),
    createAutomationPreview: vi.fn(),
    createAutomationRun: vi.fn(),
}));

vi.mock(
    "../../../entities/automation/api/automationApi",
    async (importOriginal) => {
        const actual = await importOriginal<
            typeof import("../../../entities/automation/api/automationApi")
        >();

        return {
            ...actual,
            ...apiMocks,
        };
    },
);

const payload: CreateAutomationRequest = {
    name: "Мало просмотров",
    module_type: "avito_listings",
    config: {
        avito_account_id: 17,
        condition_tree: {
            type: "group",
            operators: [],
            children: [
                {
                    type: "group",
                    operators: [],
                    children: [
                        {
                            type: "condition",
                            metric: "views",
                            aggregation: "sum",
                            window_days: 10,
                            comparator: "lt",
                            value: 10,
                        },
                    ],
                },
            ],
        },
        action: {
            type: "pause",
            config: {},
        },
        max_actions_per_run: 10,
        approval_ttl_minutes: 1440,
    },
};

const automation: Automation = {
    id: 41,
    name: payload.name,
    module_type: payload.module_type,
    state: "draft",
    execution_mode: "manual",
    version: 1,
    config: payload.config,
    created_by: 1,
    updated_by: 1,
    created_at: "2026-09-03T08:00:00Z",
    updated_at: "2026-09-03T08:00:00Z",
};

const createEnvironment = () => {
    const queryClient = new QueryClient({
        defaultOptions: {
            queries: {retry: false},
            mutations: {retry: false},
        },
    });

    const Wrapper = ({children}: PropsWithChildren) => (
        <QueryClientProvider client={queryClient}>
            {children}
        </QueryClientProvider>
    );

    return {
        queryClient,
        wrapper: Wrapper,
    };
};

const seedAutomationCache = (
    queryClient: QueryClient,
    workspaceId: number,
    automationId: number,
) => {
    queryClient.setQueryData(
        automationKeys.list(workspaceId, 1),
        {results: []},
    );
    queryClient.setQueryData(
        automationKeys.detail(workspaceId, automationId),
        automation,
    );
    queryClient.setQueryData(
        automationKeys.runs(workspaceId, automationId, 1),
        {results: []},
    );
};

const expectAutomationCacheInvalidated = (
    queryClient: QueryClient,
    workspaceId: number,
    automationId: number,
) => {
    expect(
        queryClient.getQueryState(
            automationKeys.list(workspaceId, 1),
        )?.isInvalidated,
    ).toBe(true);
    expect(
        queryClient.getQueryState(
            automationKeys.detail(workspaceId, automationId),
        )?.isInvalidated,
    ).toBe(true);
    expect(
        queryClient.getQueryState(
            automationKeys.runs(workspaceId, automationId, 1),
        )?.isInvalidated,
    ).toBe(true);
};

describe("automation execution mutations", () => {
    beforeEach(() => {
        vi.clearAllMocks();
        apiMocks.createAutomation.mockResolvedValue(automation);
        apiMocks.updateAutomation.mockResolvedValue(automation);
        apiMocks.createAutomationPreview.mockResolvedValue({
            run_id: 91,
            status: "queued",
            created: true,
        });
        apiMocks.createAutomationRun.mockResolvedValue({
            run_id: 92,
            status: "queued",
            created: true,
        });
        apiMocks.archiveAutomation.mockResolvedValue(undefined);
    });

    it("создаёт automation и инвалидирует её workspace cache", async () => {
        const {queryClient, wrapper} = createEnvironment();
        seedAutomationCache(queryClient, 7, 41);

        const {result} = renderHook(
            () => useCreateAutomationMutation(),
            {wrapper},
        );

        await act(async () => {
            await result.current.mutateAsync({
                workspaceId: 7,
                payload,
            });
        });

        expect(apiMocks.createAutomation).toHaveBeenCalledWith(
            7,
            payload,
        );
        expectAutomationCacheInvalidated(queryClient, 7, 41);
    });

    it("обновляет automation и инвалидирует её workspace cache", async () => {
        const {queryClient, wrapper} = createEnvironment();
        seedAutomationCache(queryClient, 7, 41);

        const {result} = renderHook(
            () => useUpdateAutomationMutation(),
            {wrapper},
        );

        await act(async () => {
            await result.current.mutateAsync({
                workspaceId: 7,
                automationId: 41,
                payload: {
                    name: payload.name,
                    config: payload.config,
                },
            });
        });

        expect(apiMocks.updateAutomation).toHaveBeenCalledWith(
            7,
            41,
            {
                name: payload.name,
                config: payload.config,
            },
        );
        expectAutomationCacheInvalidated(queryClient, 7, 41);
    });

    it("передаёт готовый idempotency key в preview и инвалидирует cache", async () => {
        const {queryClient, wrapper} = createEnvironment();
        seedAutomationCache(queryClient, 7, 41);
        const idempotencyKey =
            "11111111-1111-4111-8111-111111111111";

        const {result} = renderHook(
            () => useCreateAutomationPreviewMutation(),
            {wrapper},
        );

        await act(async () => {
            await result.current.mutateAsync({
                workspaceId: 7,
                automationId: 41,
                idempotencyKey,
            });
        });

        expect(
            apiMocks.createAutomationPreview,
        ).toHaveBeenCalledWith(7, 41, idempotencyKey);
        expectAutomationCacheInvalidated(queryClient, 7, 41);
    });

    it("передаёт готовый idempotency key в execute и инвалидирует cache", async () => {
        const {queryClient, wrapper} = createEnvironment();
        seedAutomationCache(queryClient, 7, 41);
        const idempotencyKey =
            "22222222-2222-4222-8222-222222222222";

        const {result} = renderHook(
            () => useCreateAutomationRunMutation(),
            {wrapper},
        );

        await act(async () => {
            await result.current.mutateAsync({
                workspaceId: 7,
                automationId: 41,
                idempotencyKey,
            });
        });

        expect(apiMocks.createAutomationRun).toHaveBeenCalledWith(
            7,
            41,
            idempotencyKey,
        );
        expectAutomationCacheInvalidated(queryClient, 7, 41);
    });

    it("архивирует automation и инвалидирует её workspace cache", async () => {
        const {queryClient, wrapper} = createEnvironment();
        seedAutomationCache(queryClient, 7, 41);

        const {result} = renderHook(
            () => useArchiveAutomationMutation(),
            {wrapper},
        );

        await act(async () => {
            await result.current.mutateAsync({
                workspaceId: 7,
                automationId: 41,
            });
        });

        expect(apiMocks.archiveAutomation).toHaveBeenCalledWith(
            7,
            41,
        );
        expectAutomationCacheInvalidated(queryClient, 7, 41);
    });
});
