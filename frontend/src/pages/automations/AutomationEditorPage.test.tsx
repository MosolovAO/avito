import {
    QueryClient,
    QueryClientProvider,
} from "@tanstack/react-query";
import {
    render,
    screen,
    waitFor,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {
    MemoryRouter,
    Route,
    Routes,
} from "react-router-dom";
import {
    afterEach,
    beforeEach,
    describe,
    expect,
    it,
    vi,
} from "vitest";

import type {
    Automation,
    AutomationCatalogResponse,
} from "../../entities/automation";
import {automationKeys} from "../../entities/automation";
import type {AvitoAccount} from "../../entities/avito/types";
import {AutomationEditorPage} from "./AutomationEditorPage";

const testState = vi.hoisted(() => ({
    currentWorkspace: {
        currentWorkspaceId: 7 as number | null,
        canManageAutomations: true,
    },
    messageError: vi.fn(),
    getAvitoAccounts: vi.fn(),
    getAutomationCatalog: vi.fn(),
    getAutomations: vi.fn(),
    getAutomation: vi.fn(),
    getAutomationRuns: vi.fn(),
    getAutomationRun: vi.fn(),
    getAutomationDecisions: vi.fn(),
    getAutomationInboxSummary: vi.fn(),
    createAutomation: vi.fn(),
    updateAutomation: vi.fn(),
    createAutomationPreview: vi.fn(),
    wizardPayload: {
        name: "Мало просмотров",
        module_type: "avito_listings",
        config: {
            avito_account_id: 17,
            condition_tree: {
                type: "group" as const,
                operators: [],
                children: [
                    {
                        type: "group" as const,
                        operators: [],
                        children: [
                            {
                                type: "condition" as const,
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
    },
}));

vi.mock(
    "../../features/workspace/model/useCurrentWorkspace",
    () => ({
        useCurrentWorkspace: () => testState.currentWorkspace,
    }),
);

vi.mock("../../shared/api/avito", async (importOriginal) => {
    const actual = await importOriginal<
        typeof import("../../shared/api/avito")
    >();

    return {
        ...actual,
        getAvitoAccounts: testState.getAvitoAccounts,
    };
});

vi.mock(
    "../../entities/automation/api/automationApi",
    async (importOriginal) => {
        const actual = await importOriginal<
            typeof import("../../entities/automation/api/automationApi")
        >();

        return {
            ...actual,
            getAutomationCatalog:
                testState.getAutomationCatalog,
            getAutomations: testState.getAutomations,
            getAutomation: testState.getAutomation,
            getAutomationRuns: testState.getAutomationRuns,
            getAutomationRun: testState.getAutomationRun,
            getAutomationDecisions:
                testState.getAutomationDecisions,
            getAutomationInboxSummary:
                testState.getAutomationInboxSummary,
            createAutomation: testState.createAutomation,
            updateAutomation: testState.updateAutomation,
            createAutomationPreview:
                testState.createAutomationPreview,
        };
    },
);

vi.mock("../../features/automation-builder", async (importOriginal) => {
    const actual = await importOriginal<
        typeof import("../../features/automation-builder")
    >();

    return {
        ...actual,
        AutomationWizard: ({
                               mode,
                               submitting,
                               onSubmit,
                           }: {
            mode: "create" | "edit";
            submitting: boolean;
            onSubmit: (
                payload: typeof testState.wizardPayload,
            ) => Promise<void>;
        }) => (
            <div>
                <span>
                    {mode === "create"
                        ? "Новая автоматизация"
                        : "Редактирование автоматизации"}
                </span>
                <button
                    type="button"
                    disabled={submitting}
                    onClick={() => {
                        void onSubmit(testState.wizardPayload);
                    }}
                >
                    Сохранить автоматизацию
                </button>
            </div>
        ),
    };
});

vi.mock("antd", async (importOriginal) => {
    const actual = await importOriginal<typeof import("antd")>();

    return {
        ...actual,
        message: {
            ...actual.message,
            error: testState.messageError,
        },
    };
});

const catalog: AutomationCatalogResponse = {
    modules: [],
};

const automation: Automation = {
    id: 41,
    name: "Мало просмотров",
    module_type: "avito_listings",
    state: "draft",
    execution_mode: "manual",
    version: 1,
    config: testState.wizardPayload.config,
    created_by: 1,
    updated_by: 1,
    created_at: "2026-09-03T08:00:00Z",
    updated_at: "2026-09-03T08:00:00Z",
};

const avitoAccount: AvitoAccount = {
    id: 17,
    name: "Основной аккаунт",
    external_account_id: "123456",
    client_id: "client-id",
    has_client_secret: true,
    connection_status: "connected",
    connection_error: null,
    last_verified_at: "2026-09-03T07:00:00Z",
    is_active: true,
    feed_url: null,
    export_status: "clean",
    export_file_path: null,
    export_requested_at: null,
    export_started_at: null,
    last_exported_at: null,
    export_error: null,
    created_at: "2026-09-01T08:00:00Z",
    updated_at: "2026-09-03T08:00:00Z",
    sync_status: "idle",
    sync_requested_at: null,
    sync_started_at: null,
    last_synced_at: null,
    sync_error: null,
    last_sync_total_received: 0,
    last_sync_created_listings: 0,
    last_sync_updated_listings: 0,
};

const emptyRunsPage = {
    count: 0,
    next: null,
    previous: null,
    results: [],
};

const renderEditor = (initialEntry: string) => {
    const queryClient = new QueryClient({
        defaultOptions: {
            queries: {retry: false},
            mutations: {retry: false},
        },
    });

    const Wrapper = () => (
        <QueryClientProvider client={queryClient}>
            <MemoryRouter initialEntries={[initialEntry]}>
                <Routes>
                    <Route
                        path="/automations/new"
                        element={<AutomationEditorPage/>}
                    />
                    <Route
                        path="/automations/:automationId/edit"
                        element={<AutomationEditorPage/>}
                    />
                    <Route
                        path="/automations/:automationId/preview"
                        element={<div>Страница preview</div>}
                    />
                </Routes>
            </MemoryRouter>
        </QueryClientProvider>
    );

    render(<Wrapper/>);

    return {
        queryClient,
        user: userEvent.setup(),
    };
};

describe("AutomationEditorPage", () => {
    beforeEach(() => {
        vi.clearAllMocks();

        testState.currentWorkspace.currentWorkspaceId = 7;
        testState.currentWorkspace.canManageAutomations = true;

        testState.getAvitoAccounts.mockResolvedValue([
            avitoAccount,
        ]);
        testState.getAutomationCatalog.mockResolvedValue(catalog);
        testState.getAutomation.mockResolvedValue(automation);
        testState.getAutomationRuns.mockResolvedValue(
            emptyRunsPage,
        );
        testState.createAutomation.mockResolvedValue(automation);
        testState.updateAutomation.mockResolvedValue(automation);
        testState.createAutomationPreview.mockResolvedValue({
            run_id: 91,
            status: "queued",
            created: true,
        });
    });

    afterEach(() => {
        vi.restoreAllMocks();
    });

    it("создаёт automation, один раз создаёт ключ и запускает preview", async () => {
        const events: string[] = [];
        const idempotencyKey =
            "11111111-1111-4111-8111-111111111111";

        testState.createAutomation.mockImplementation(async () => {
            events.push("create");
            return automation;
        });
        testState.createAutomationPreview.mockImplementation(
            async () => {
                events.push("preview");
                return {
                    run_id: 91,
                    status: "queued",
                    created: true,
                };
            },
        );
        const randomUUID = vi
            .spyOn(globalThis.crypto, "randomUUID")
            .mockImplementation(() => {
                events.push("uuid");
                return idempotencyKey;
            });

        const {user} = renderEditor("/automations/new");

        await user.click(
            await screen.findByRole("button", {
                name: "Сохранить автоматизацию",
            }),
        );

        expect(
            await screen.findByText("Страница preview"),
        ).toBeInTheDocument();
        expect(events).toEqual(["create", "uuid", "preview"]);
        expect(randomUUID).toHaveBeenCalledTimes(1);
        expect(testState.createAutomation).toHaveBeenCalledWith(
            7,
            testState.wizardPayload,
        );
        expect(
            testState.createAutomationPreview,
        ).toHaveBeenCalledWith(7, 41, idempotencyKey);
    });

    it("переходит к preview и показывает ошибку, если его запуск не удался", async () => {
        testState.createAutomationPreview.mockRejectedValue(
            new Error("preview failed"),
        );
        vi.spyOn(globalThis.crypto, "randomUUID").mockReturnValue(
            "22222222-2222-4222-8222-222222222222",
        );

        const {user} = renderEditor("/automations/new");

        await user.click(
            await screen.findByRole("button", {
                name: "Сохранить автоматизацию",
            }),
        );

        expect(
            await screen.findByText("Страница preview"),
        ).toBeInTheDocument();
        expect(testState.messageError).toHaveBeenCalledWith(
            "Автоматизация сохранена, но preview не запущен. " +
            "Повторите запуск на вкладке Preview.",
        );
    });

    it("обновляет automation без state=enabled и запускает preview сохранённой версии", async () => {
        const idempotencyKey =
            "33333333-3333-4333-8333-333333333333";
        vi.spyOn(globalThis.crypto, "randomUUID").mockReturnValue(
            idempotencyKey,
        );

        const {user} = renderEditor("/automations/41/edit");

        await user.click(
            await screen.findByRole("button", {
                name: "Сохранить автоматизацию",
            }),
        );

        expect(
            await screen.findByText("Страница preview"),
        ).toBeInTheDocument();
        expect(testState.updateAutomation).toHaveBeenCalledWith(
            7,
            41,
            {
                name: testState.wizardPayload.name,
                config: testState.wizardPayload.config,
            },
        );
        expect(
            testState.updateAutomation.mock.calls[0]?.[2],
        ).not.toHaveProperty("state");
        expect(
            testState.createAutomationPreview,
        ).toHaveBeenCalledWith(7, 41, idempotencyKey);
    });

    it("инвалидирует list, detail и runs после успешного flow", async () => {
        vi.spyOn(globalThis.crypto, "randomUUID").mockReturnValue(
            "44444444-4444-4444-8444-444444444444",
        );

        const {queryClient, user} = renderEditor(
            "/automations/new",
        );

        queryClient.setQueryData(
            automationKeys.list(7, 1),
            {
                count: 0,
                next: null,
                previous: null,
                results: [],
            },
        );
        queryClient.setQueryData(
            automationKeys.detail(7, 41),
            automation,
        );
        queryClient.setQueryData(
            automationKeys.runs(7, 41, 1),
            emptyRunsPage,
        );

        await user.click(
            await screen.findByRole("button", {
                name: "Сохранить автоматизацию",
            }),
        );

        await waitFor(() => {
            expect(
                queryClient.getQueryState(
                    automationKeys.list(7, 1),
                )?.isInvalidated,
            ).toBe(true);
            expect(
                queryClient.getQueryState(
                    automationKeys.detail(7, 41),
                )?.isInvalidated,
            ).toBe(true);
            expect(
                queryClient.getQueryState(
                    automationKeys.runs(7, 41, 1),
                )?.isInvalidated,
            ).toBe(true);
        });
    });

    it("не загружает данные без права manage_automations", async () => {
        testState.currentWorkspace.canManageAutomations = false;

        renderEditor("/automations/new");

        expect(
            await screen.findByText("Недостаточно прав"),
        ).toBeInTheDocument();
        expect(
            testState.getAutomationCatalog,
        ).not.toHaveBeenCalled();
        expect(testState.getAvitoAccounts).not.toHaveBeenCalled();
    });
});
