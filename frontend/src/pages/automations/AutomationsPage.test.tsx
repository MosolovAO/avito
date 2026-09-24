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
import type {AvitoAccount} from "../../entities/avito/types";
import {AutomationsPage} from "./AutomationsPage";

const testState = vi.hoisted(() => ({
    currentWorkspace: {
        currentWorkspaceId: 7 as number | null,
        canManageAutomations: true,
    },
    getAvitoAccounts: vi.fn(),
    getAutomationCatalog: vi.fn(),
    getAutomations: vi.fn(),
    getAutomationRuns: vi.fn(),
    updateAutomation: vi.fn(),
    createAutomationRun: vi.fn(),
    archiveAutomation: vi.fn(),
    modalConfirm: vi.fn(),
    messageError: vi.fn(),
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
            getAutomationRuns: testState.getAutomationRuns,
            updateAutomation: testState.updateAutomation,
            createAutomationRun: testState.createAutomationRun,
            archiveAutomation: testState.archiveAutomation,
        };
    },
);

vi.mock("antd", async (importOriginal) => {
    const actual = await importOriginal<typeof import("antd")>();

    return {
        ...actual,
        Modal: {
            ...actual.Modal,
            confirm: testState.modalConfirm,
        },
        message: {
            ...actual.message,
            error: testState.messageError,
        },
    };
});

const config = {
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
};

const buildAutomation = (
    id: number,
    name: string,
    state: Automation["state"] = "draft",
): Automation => ({
    id,
    name,
    module_type: "avito_listings",
    state,
    execution_mode: "manual",
    version: 1,
    config,
    created_by: 1,
    updated_by: 1,
    created_at: "2026-09-01T08:00:00Z",
    updated_at: "2026-09-03T08:00:00Z",
});

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

const catalog: AutomationCatalogResponse = {
    modules: [
        {
            module_type: "avito_listings",
            label: "Объявления Avito",
            metrics: [],
            aggregations: [],
            comparators: [],
            actions: [
                {
                    code: "pause",
                    label: "Приостановить",
                    description: "Временно скрыть объявление",
                    config_schema: {
                        type: "object",
                        properties: {},
                        additionalProperties: false,
                    },
                },
            ],
            condition_limits: {
                min_window_days: 1,
                max_window_days: 365,
                max_conditions: 50,
            },
        },
    ],
};

const buildPageTree = (queryClient: QueryClient) => (
    <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={["/automations"]}>
            <Routes>
                <Route
                    path="/automations"
                    element={<AutomationsPage/>}
                />
                <Route
                    path="/automations/:automationId/settings"
                    element={<div>Настройка автоматизации</div>}
                />
                <Route
                    path="/automation-runs/:runId"
                    element={<div>Страница запуска</div>}
                />
            </Routes>
        </MemoryRouter>
    </QueryClientProvider>
);

const createQueryClient = () => new QueryClient({
    defaultOptions: {
        queries: {retry: false},
        mutations: {retry: false},
    },
});

const renderPage = () => {
    const queryClient = createQueryClient();

    render(buildPageTree(queryClient));

    return userEvent.setup();
};

const renderSwitchablePage = () => {
    const queryClient = createQueryClient();
    const rendered = render(buildPageTree(queryClient));

    return {
        rerenderPage: () => {
            rendered.rerender(buildPageTree(queryClient));
        },
    };
};

describe("AutomationsPage", () => {
    beforeEach(() => {
        vi.clearAllMocks();
        testState.currentWorkspace.currentWorkspaceId = 7;
        testState.currentWorkspace.canManageAutomations = true;
        testState.getAvitoAccounts.mockResolvedValue([
            avitoAccount,
        ]);
        testState.getAutomationCatalog.mockResolvedValue(
            catalog,
        );
        testState.getAutomations.mockResolvedValue({
            count: 21,
            next: "/api/automations/?page=2",
            previous: null,
            results: [
                buildAutomation(41, "Мало просмотров"),
                buildAutomation(42, "Мало контактов", "enabled"),
            ],
        });
        testState.updateAutomation.mockImplementation(
            async (
                _workspaceId: number,
                automationId: number,
                payload: {state: Automation["state"]},
            ) => buildAutomation(
                automationId,
                "Мало контактов",
                payload.state,
            ),
        );
        testState.createAutomationRun.mockResolvedValue({
            run_id: 92,
            status: "queued",
            created: true,
        });
        testState.archiveAutomation.mockResolvedValue(undefined);
    });

    it("показывает утверждённые колонки и справочные названия", async () => {
        renderPage();

        for (const column of [
            "Название",
            "Avito-аккаунт",
            "Действие",
            "Состояние",
            "Версия",
            "Дата изменения",
            "Операции",
        ]) {
            expect(
                await screen.findByRole(
                    "columnheader",
                    {name: column},
                ),
            ).toBeVisible();
        }

        expect(
            screen.getAllByText("Основной аккаунт"),
        ).toHaveLength(2);
        expect(
            screen.getAllByText("Приостановить"),
        ).toHaveLength(2);
    });

    it("открывает настройку автоматизации по названию", async () => {
        const user = renderPage();

        await user.click(
            await screen.findByRole("link", {
                name: "Мало просмотров",
            }),
        );

        expect(
            screen.getByText("Настройка автоматизации"),
        ).toBeVisible();
    });

    it("запрашивает выбранную серверную страницу", async () => {
        testState.getAutomations.mockImplementation(
            async (_workspaceId: number, page: number) => ({
                count: 21,
                next: null,
                previous: page === 2
                    ? "/api/automations/?page=1"
                    : null,
                results: page === 2
                    ? [buildAutomation(61, "Вторая страница")]
                    : [buildAutomation(41, "Мало просмотров")],
            }),
        );

        const user = renderPage();

        await screen.findByText("Мало просмотров");
        await user.click(screen.getByTitle("2"));

        expect(
            await screen.findByText("Вторая страница"),
        ).toBeVisible();
        expect(testState.getAutomations).toHaveBeenLastCalledWith(
            7,
            2,
        );
    });

    it("не запрашивает историю отдельно для строк списка", async () => {
        renderPage();

        await screen.findByText("Мало просмотров");

        expect(testState.getAutomationRuns).not.toHaveBeenCalled();
    });

    it("не показывает строки прежнего workspace после переключения", async () => {
        let resolveWorkspaceEight!: (
            value: {
                count: number;
                next: null;
                previous: null;
                results: Automation[];
            },
        ) => void;
        const workspaceEightRequest = new Promise<{
            count: number;
            next: null;
            previous: null;
            results: Automation[];
        }>((resolve) => {
            resolveWorkspaceEight = resolve;
        });

        testState.getAutomations.mockImplementation(
            (workspaceId: number) => (
                workspaceId === 7
                    ? Promise.resolve({
                        count: 1,
                        next: null,
                        previous: null,
                        results: [
                            buildAutomation(71, "Workspace 7"),
                        ],
                    })
                    : workspaceEightRequest
            ),
        );

        const {rerenderPage} = renderSwitchablePage();

        expect(
            await screen.findByText("Workspace 7"),
        ).toBeVisible();

        testState.currentWorkspace.currentWorkspaceId = 8;
        rerenderPage();

        expect(
            screen.queryByText("Workspace 7"),
        ).not.toBeInTheDocument();
        await waitFor(() => {
            expect(testState.getAutomations).toHaveBeenLastCalledWith(
                8,
                1,
            );
        });

        resolveWorkspaceEight({
            count: 1,
            next: null,
            previous: null,
            results: [buildAutomation(81, "Workspace 8")],
        });

        expect(
            await screen.findByText("Workspace 8"),
        ).toBeVisible();
        expect(
            screen.queryByText("Workspace 7"),
        ).not.toBeInTheDocument();
    });

    it("показывает компактное меню операций строки", async () => {
        const user = renderPage();

        await user.click(
            await screen.findByRole("button", {
                name: "Операции: Мало просмотров",
            }),
        );

        expect(
            screen.getByRole("menuitem", {name: "Запустить"}),
        ).toHaveAttribute("aria-disabled", "true");
        expect(
            screen.getByRole("menuitem", {name: "Включить"}),
        ).toBeInTheDocument();
        expect(
            screen.getByRole("menuitem", {name: "Архивировать"}),
        ).toBeInTheDocument();
    });

    it("запускает enabled automation с одним ключом и открывает run", async () => {
        const idempotencyKey =
            "22222222-2222-4222-8222-222222222222";
        const randomUuid = vi.spyOn(crypto, "randomUUID")
            .mockReturnValue(idempotencyKey);
        const user = renderPage();

        await user.click(
            await screen.findByRole("button", {
                name: "Операции: Мало контактов",
            }),
        );
        await user.click(screen.getByText("Запустить"));

        expect(
            await screen.findByText("Страница запуска"),
        ).toBeVisible();
        expect(randomUuid).toHaveBeenCalledTimes(1);
        expect(testState.createAutomationRun).toHaveBeenCalledWith(
            7,
            42,
            idempotencyKey,
        );
    });

    it("выключает enabled automation через PATCH состояния", async () => {
        const user = renderPage();

        await user.click(
            await screen.findByRole("button", {
                name: "Операции: Мало контактов",
            }),
        );
        await user.click(screen.getByText("Выключить"));

        await waitFor(() => {
            expect(testState.updateAutomation).toHaveBeenCalledWith(
                7,
                42,
                {state: "disabled"},
            );
        });
    });

    it("архивирует automation только после подтверждения", async () => {
        const user = renderPage();

        await user.click(
            await screen.findByRole("button", {
                name: "Операции: Мало просмотров",
            }),
        );
        await user.click(screen.getByText("Архивировать"));

        expect(testState.archiveAutomation).not.toHaveBeenCalled();
        expect(testState.modalConfirm).toHaveBeenCalledTimes(1);

        const confirmation = testState.modalConfirm.mock.lastCall?.[0] as {
            title: string;
            onOk: () => Promise<void>;
        };

        expect(confirmation.title).toBe(
            "Архивировать автоматизацию?",
        );
        await confirmation.onOk();

        expect(testState.archiveAutomation).toHaveBeenCalledWith(
            7,
            41,
        );
    });

    it("показывает 403 и не запускает automation queries без права", async () => {
        testState.currentWorkspace.canManageAutomations = false;

        renderPage();

        expect(
            await screen.findByText("Доступ запрещён"),
        ).toBeVisible();
        expect(
            screen.getByText(
                "У вас нет права управлять автоматизациями.",
            ),
        ).toBeVisible();
        await waitFor(() => {
            expect(testState.getAutomations).not.toHaveBeenCalled();
            expect(testState.getAutomationCatalog)
                .not.toHaveBeenCalled();
            expect(testState.getAutomationRuns)
                .not.toHaveBeenCalled();
            expect(testState.getAvitoAccounts).not.toHaveBeenCalled();
        });
    });

    it("не загружает данные без выбранного workspace", async () => {
        testState.currentWorkspace.currentWorkspaceId = null;

        renderPage();

        expect(
            await screen.findByText("Рабочий кабинет не выбран"),
        ).toBeVisible();
        await waitFor(() => {
            expect(testState.getAutomations).not.toHaveBeenCalled();
            expect(testState.getAutomationCatalog).not.toHaveBeenCalled();
            expect(testState.getAvitoAccounts).not.toHaveBeenCalled();
        });
    });
});
