import {
    QueryClient,
    QueryClientProvider,
} from "@tanstack/react-query";
import {
    render,
    screen,
    waitFor,
    within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {
    MemoryRouter,
    Route,
    Routes,
    useLocation,
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
    AutomationRunDetail,
    AutomationRunStatus,
    AutomationRunSummary,
} from "../../entities/automation";
import {automationKeys} from "../../entities/automation";
import {AutomationStateTag} from "../../entities/automation";
import type {AvitoAccount} from "../../entities/avito/types";
import {RunStatus} from "../../features/automation-execution";
import {ROUTES} from "../../shared/config/constants";
import {AutomationDetailPage} from "./AutomationDetailPage";

const testState = vi.hoisted(() => ({
    currentWorkspace: {
        currentWorkspaceId: 7 as number | null,
        canManageAutomations: true,
    },
    getAvitoAccounts: vi.fn(),
    getAutomationCatalog: vi.fn(),
    getAutomation: vi.fn(),
    getAutomationRuns: vi.fn(),
    getAutomationRun: vi.fn(),
    updateAutomation: vi.fn(),
    createAutomationPreview: vi.fn(),
    createAutomationRun: vi.fn(),
    archiveAutomation: vi.fn(),
    modalConfirm: vi.fn(),
    messageError: vi.fn(),
    notificationWarning: vi.fn(),
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
            getAutomation: testState.getAutomation,
            getAutomationRuns: testState.getAutomationRuns,
            getAutomationRun: testState.getAutomationRun,
            updateAutomation: testState.updateAutomation,
            createAutomationPreview:
                testState.createAutomationPreview,
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
        notification: {
            ...actual.notification,
            warning: testState.notificationWarning,
        },
    };
});

const config: Automation["config"] = {
    avito_account_id: 17,
    condition_tree: {
        type: "group",
        operators: ["or"],
        children: [
            {
                type: "group",
                operators: ["and"],
                children: [
                    {
                        type: "condition",
                        metric: "views",
                        aggregation: "sum",
                        window_days: 10,
                        comparator: "lt",
                        value: 10,
                    },
                    {
                        type: "condition",
                        metric: "views",
                        aggregation: "sum",
                        window_days: 7,
                        comparator: "lt",
                        value: 5,
                    },
                ],
            },
            {
                type: "group",
                operators: [],
                children: [
                    {
                        type: "condition",
                        metric: "views",
                        aggregation: "sum",
                        window_days: 3,
                        comparator: "lt",
                        value: 2,
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
    state: Automation["state"] = "disabled",
): Automation => ({
    id: 41,
    name: "Мало просмотров",
    module_type: "avito_listings",
    state,
    execution_mode: "manual",
    version: 3,
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
            metrics: [
                {
                    code: "views",
                    label: "Просмотры",
                    description: "Просмотры объявления",
                    value_type: "integer",
                    allowed_aggregations: ["sum"],
                },
            ],
            aggregations: [
                {code: "sum", label: "Сумма"},
            ],
            comparators: [
                {code: "lt", symbol: "<", label: "Меньше"},
            ],
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

const buildApiError = (
    status: number,
    data: Record<string, unknown>,
) => ({
    isAxiosError: true,
    response: {status, data},
});

const resultSummary = {
    avito_account_id: 17,
    as_of_date: "2026-09-02",
    checked: 101,
    ineligible: 12,
    insufficient_coverage: 13,
    not_matched: 14,
    matched: 15,
    deferred_by_run_limit: 16,
    pending_approval: 0,
    completed_actions: 0,
    failed_actions: 0,
};

const buildRunSummary = (
    id: number,
    kind: AutomationRunSummary["kind"],
    status: AutomationRunStatus = "completed",
): AutomationRunSummary => ({
    id,
    automation_id: 41,
    kind,
    trigger: "manual",
    execution_mode: "manual",
    automation_version: 3,
    automation_name: "Мало просмотров",
    module_type: "avito_listings",
    status,
    error: null,
    result: resultSummary,
    created_by: 1,
    started_at: "2026-09-03T07:00:00Z",
    finished_at: status === "completed"
        ? "2026-09-03T07:01:00Z"
        : null,
    created_at: "2026-09-03T07:00:00Z",
});

const buildRunDetail = (
    id: number,
    status: AutomationRunStatus = "completed",
    exampleCount = 1,
): AutomationRunDetail => ({
    ...buildRunSummary(id, "preview", status),
    result: {
        ...resultSummary,
        max_actions_per_run_snapshot: 10,
        approval_ttl_minutes_snapshot: 1440,
        target_max_id_snapshot: 500,
        condition_snapshot: config.condition_tree,
        action_snapshot: config.action,
        examples_snapshot: Array.from(
            {length: exampleCount},
            (_, index) => ({
                listing_id: index + 1,
                avito_id: `avito-${index + 1}`,
                title: `Объявление ${index + 1}`,
                active_since: "2026-08-01T09:00:00+03:00",
                metrics: [
                    {
                        metric: "views",
                        aggregation: "sum",
                        window_days: 10,
                        date_from: "2026-08-24",
                        date_to: "2026-09-02",
                        value: index + 1,
                    },
                ],
            }),
        ),
    },
    retry_count: 0,
    data_wait_attempt_count:
        status === "waiting_for_data" ? 1 : 0,
    next_attempt_at:
        status === "waiting_for_data"
            ? "2026-09-03T07:30:00Z"
            : null,
    wait_started_at:
        status === "waiting_for_data"
            ? "2026-09-03T07:00:00Z"
            : null,
    updated_at: "2026-09-03T07:01:00Z",
});

const LocationProbe = () => {
    const location = useLocation();

    return <div data-testid="pathname">{location.pathname}</div>;
};

const renderDetail = (
    path = "/automations/41/settings",
) => {
    const queryClient = new QueryClient({
        defaultOptions: {
            queries: {retry: false},
            mutations: {retry: false},
        },
    });
    const invalidateQueries = vi.spyOn(
        queryClient,
        "invalidateQueries",
    );

    render(
        <QueryClientProvider client={queryClient}>
            <MemoryRouter initialEntries={[path]}>
                <Routes>
                    <Route
                        path="/automations/:automationId/:tab"
                        element={(
                            <>
                                <AutomationDetailPage/>
                                <LocationProbe/>
                            </>
                        )}
                    />
                    <Route
                        path="/automations/:automationId/edit"
                        element={<div>Редактор автоматизации</div>}
                    />
                    <Route
                        path="/automation-runs/:runId"
                        element={(
                            <>
                                <div>Страница запуска</div>
                                <LocationProbe/>
                            </>
                        )}
                    />
                    <Route
                        path="/automations"
                        element={<div>Список автоматизаций</div>}
                    />
                </Routes>
            </MemoryRouter>
        </QueryClientProvider>,
    );

    return {
        invalidateQueries,
        queryClient,
        user: userEvent.setup(),
    };
};

describe("automation status presentation", () => {
    it.each([
        ["draft", "Черновик"],
        ["enabled", "Включена"],
        ["disabled", "Выключена"],
        ["archived", "В архиве"],
        ["future", "Неизвестное состояние (future)"],
    ])("показывает состояние %s текстом", (state, label) => {
        render(<AutomationStateTag state={state}/>);

        expect(screen.getByText(label)).toBeVisible();
    });

    it.each([
        ["queued", "В очереди"],
        ["waiting_for_data", "Ожидает данные"],
        ["evaluating", "Выполняется проверка"],
        ["waiting_approval", "Ожидает подтверждения"],
        ["effect_pending", "Формируется CSV"],
        ["completed", "Завершён"],
        ["partial", "Завершён частично"],
        ["failed", "Ошибка"],
        ["cancelled", "Отменён"],
        ["future", "Неизвестный статус (future)"],
    ])("показывает статус запуска %s текстом", (status, label) => {
        render(<RunStatus status={status}/>);

        expect(screen.getByText(label)).toBeVisible();
    });
});

describe("automation detail routes", () => {
    it("задаёт базовый адрес и адрес вкладок", () => {
        expect(ROUTES.AUTOMATION_DETAIL).toBe(
            "/automations/:automationId",
        );
        expect(ROUTES.AUTOMATION_TAB).toBe(
            "/automations/:automationId/:tab",
        );
    });
});

describe("AutomationDetailPage", () => {
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
        testState.getAutomation.mockResolvedValue(
            buildAutomation(),
        );
        testState.getAutomationRuns.mockResolvedValue({
            count: 0,
            next: null,
            previous: null,
            results: [],
        });
        testState.getAutomationRun.mockResolvedValue(
            buildRunDetail(92, "queued"),
        );
        testState.updateAutomation.mockResolvedValue(
            buildAutomation("enabled"),
        );
        testState.createAutomationPreview.mockResolvedValue({
            run_id: 92,
            status: "queued",
            created: true,
        });
        testState.createAutomationRun.mockResolvedValue({
            run_id: 92,
            status: "queued",
            created: true,
        });
        testState.archiveAutomation.mockResolvedValue(undefined);
    });

    it("показывает типизированную настройку и синхронизирует вкладки с URL", async () => {
        const {user} = renderDetail();

        expect(
            await screen.findByRole("heading", {
                name: "Мало просмотров",
            }),
        ).toBeVisible();
        expect(screen.getByText("Выключена")).toBeVisible();
        expect(screen.getByText("Объявления Avito")).toBeVisible();
        expect(screen.getByText("Основной аккаунт")).toBeVisible();
        expect(screen.getByText("Группа 1")).toBeVisible();
        expect(screen.getByText("И")).toBeVisible();
        expect(screen.getByText("ИЛИ")).toBeVisible();
        expect(screen.getByText("Группа 2")).toBeVisible();
        expect(screen.getAllByText("Просмотры"))
            .toHaveLength(3);
        expect(screen.getByText("Приостановить")).toBeVisible();
        expect(screen.getByText("10 объявлений")).toBeVisible();
        expect(screen.getByText("24 часа")).toBeVisible();
        expect(screen.getByText("Ручной")).toBeVisible();
        expect(screen.getAllByText("Версия 3")).toHaveLength(2);

        await user.click(screen.getByRole("tab", {name: "Preview"}));

        expect(screen.getByTestId("pathname")).toHaveTextContent(
            "/automations/41/preview",
        );
    });

    it("включает automation через PATCH только состояния", async () => {
        const {user} = renderDetail();

        await user.click(
            await screen.findByRole("button", {name: "Включить"}),
        );

        await waitFor(() => {
            expect(testState.updateAutomation).toHaveBeenCalledWith(
                7,
                41,
                {state: "enabled"},
            );
        });
    });

    it("переводит на Preview при backend-ошибке preview_required", async () => {
        testState.updateAutomation.mockRejectedValue(
            buildApiError(409, {
                code: "preview_required",
                message: "Сначала выполните preview текущей версии.",
            }),
        );
        const {user} = renderDetail();

        await user.click(
            await screen.findByRole("button", {name: "Включить"}),
        );

        await waitFor(() => {
            expect(screen.getByTestId("pathname")).toHaveTextContent(
                "/automations/41/preview",
            );
        });
    });

    it("не разрешает ручной запуск выключенной automation", async () => {
        renderDetail();

        expect(
            await screen.findByRole("button", {name: "Запустить"}),
        ).toBeDisabled();
        expect(testState.createAutomationRun).not.toHaveBeenCalled();
    });

    it("при конфликте переходит к уже открытому запуску", async () => {
        testState.getAutomation.mockResolvedValue(
            buildAutomation("enabled"),
        );
        testState.createAutomationRun.mockRejectedValue(
            buildApiError(409, {
                code: "open_run_conflict",
                message: "Уже есть открытый запуск.",
                open_run_id: 77,
            }),
        );
        const randomUuid = vi.spyOn(crypto, "randomUUID")
            .mockReturnValue(
                "33333333-3333-4333-8333-333333333333",
            );
        const {user} = renderDetail();

        await user.click(
            await screen.findByRole("button", {name: "Запустить"}),
        );

        expect(
            await screen.findByText("Страница запуска"),
        ).toBeVisible();
        expect(randomUuid).toHaveBeenCalledTimes(1);
        expect(screen.getByTestId("pathname")).toHaveTextContent(
            "/automation-runs/77",
        );
    });

    it("показывает resource_busy и обновляет detail", async () => {
        testState.getAutomation.mockResolvedValue(
            buildAutomation("enabled"),
        );
        testState.createAutomationRun.mockRejectedValue(
            buildApiError(409, {
                code: "resource_busy",
                message: "Avito-аккаунт уже обрабатывается.",
            }),
        );
        const {invalidateQueries, user} = renderDetail();

        await user.click(
            await screen.findByRole("button", {name: "Запустить"}),
        );

        await waitFor(() => {
            expect(testState.notificationWarning).toHaveBeenCalledWith({
                message: "Автоматизация уже выполняется",
                description: "Avito-аккаунт уже обрабатывается.",
            });
        });
        expect(invalidateQueries).toHaveBeenCalledWith({
            queryKey: automationKeys.detail(7, 41),
        });
    });

    it("архивирует после подтверждения и возвращает к списку", async () => {
        const {user} = renderDetail();

        await user.click(
            await screen.findByRole("button", {name: "Архивировать"}),
        );

        expect(testState.archiveAutomation).not.toHaveBeenCalled();
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
        expect(
            await screen.findByText("Список автоматизаций"),
        ).toBeVisible();
    });

    it("показывает пустое состояние и открывает созданный preview напрямую", async () => {
        testState.getAutomationRuns
            .mockResolvedValueOnce({
                count: 0,
                next: null,
                previous: null,
                results: [],
            })
            .mockImplementation(() => new Promise(() => undefined));
        const randomUuid = vi.spyOn(crypto, "randomUUID")
            .mockReturnValue(
                "44444444-4444-4444-8444-444444444444",
            );
        const {user} = renderDetail(
            "/automations/41/preview",
        );

        expect(
            await screen.findByText("Нет доступного preview"),
        ).toBeVisible();

        await user.click(
            screen.getByRole("button", {
                name: "Запустить preview",
            }),
        );

        await waitFor(() => {
            expect(testState.createAutomationPreview)
                .toHaveBeenCalledWith(
                    7,
                    41,
                    "44444444-4444-4444-8444-444444444444",
                );
        });
        await waitFor(() => {
            expect(testState.getAutomationRun)
                .toHaveBeenCalledWith(7, 92);
        });
        expect(await screen.findByText("В очереди")).toBeVisible();
        expect(randomUuid).toHaveBeenCalledTimes(1);
    });

    it("выбирает последний preview и показывает его immutable snapshot", async () => {
        testState.getAutomationRuns.mockResolvedValue({
            count: 3,
            next: null,
            previous: null,
            results: [
                buildRunSummary(103, "execute"),
                buildRunSummary(102, "preview"),
                buildRunSummary(101, "preview"),
            ],
        });
        testState.getAutomationRun.mockResolvedValue(
            buildRunDetail(102, "completed", 21),
        );

        renderDetail("/automations/41/preview");

        const assertStatistic = async (
            label: string,
            value: string,
        ) => {
            const title = await screen.findByText(label);
            const card = title.closest(".ant-card");

            expect(card).not.toBeNull();
            expect(within(card as HTMLElement).getByText(value))
                .toBeVisible();
        };

        await assertStatistic("Проверено", "101");
        await assertStatistic("Не подходит", "12");
        await assertStatistic("Недостаточно статистики", "13");
        await assertStatistic("Условие не выполнено", "14");
        await assertStatistic("Условие выполнено", "15");
        await assertStatistic("Отложено лимитом", "16");

        expect(testState.getAutomationRun).toHaveBeenCalledWith(
            7,
            102,
        );
        expect(screen.getByText("Объявление 1")).toBeVisible();
        expect(screen.getByText("Объявление 20")).toBeVisible();
        expect(screen.queryByText("Объявление 21"))
            .not.toBeInTheDocument();
        expect(
            screen.getAllByText(
                /01\.08\.2026.*09:00/,
            ),
        ).toHaveLength(20);
        expect(
            screen.getByText(
                "Просмотры: 1 · 10 дней · 24.08.2026—02.09.2026",
            ),
        ).toBeVisible();
    });

    it.each([
        ["queued", "В очереди"],
        ["evaluating", "Выполняется проверка"],
    ] as const)(
        "показывает незавершённый preview %s как выполняющийся",
        async (status, label) => {
            testState.getAutomationRuns.mockResolvedValue({
                count: 1,
                next: null,
                previous: null,
                results: [
                    buildRunSummary(92, "preview", status),
                ],
            });
            testState.getAutomationRun.mockResolvedValue(
                buildRunDetail(92, status),
            );

            renderDetail("/automations/41/preview");

            expect(await screen.findByText(label)).toBeVisible();
            expect(
                screen.getByText("Preview выполняется"),
            ).toBeVisible();
            expect(screen.queryByText("Проверено"))
                .not.toBeInTheDocument();
        },
    );

    it("объясняет ожидание полной статистики", async () => {
        testState.getAutomationRuns.mockResolvedValue({
            count: 1,
            next: null,
            previous: null,
            results: [
                buildRunSummary(
                    92,
                    "preview",
                    "waiting_for_data",
                ),
            ],
        });
        testState.getAutomationRun.mockResolvedValue(
            buildRunDetail(92, "waiting_for_data"),
        );

        renderDetail("/automations/41/preview");

        expect(
            await screen.findByText(
                "Ожидаем накопления статистики",
            ),
        ).toBeVisible();
        expect(
            screen.getByText(
                "Запуск продолжится автоматически, когда данные " +
                "за выбранные периоды будут готовы.",
            ),
        ).toBeVisible();
    });

    it("при конфликте preview открывает существующий запуск", async () => {
        testState.createAutomationPreview.mockRejectedValue(
            buildApiError(409, {
                code: "open_preview_conflict",
                message: "Preview уже выполняется.",
                open_run_id: 88,
            }),
        );
        testState.getAutomationRun.mockResolvedValue(
            buildRunDetail(88, "evaluating"),
        );
        const {user} = renderDetail(
            "/automations/41/preview",
        );

        await user.click(
            await screen.findByRole("button", {
                name: "Запустить preview",
            }),
        );

        await waitFor(() => {
            expect(testState.getAutomationRun)
                .toHaveBeenCalledWith(7, 88);
        });
        expect(
            await screen.findByText("Выполняется проверка"),
        ).toBeVisible();
    });

    it("показывает лёгкий журнал запусков без detail-запросов", async () => {
        testState.getAutomationRuns.mockResolvedValue({
            count: 2,
            next: null,
            previous: null,
            results: [
                {
                    ...buildRunSummary(103, "execute"),
                    automation_version: 4,
                    created_by: null,
                    started_at: "2026-09-03T07:05:00Z",
                    finished_at: "2026-09-03T07:06:00Z",
                    result: {
                        ...resultSummary,
                        matched: 7,
                        pending_approval: 5,
                        completed_actions: 2,
                        failed_actions: 1,
                    },
                },
                buildRunSummary(102, "preview"),
            ],
        });

        renderDetail("/automations/41/runs");

        for (const column of [
            "ID",
            "Тип",
            "Версия",
            "Статус",
            "Результат",
            "Автор",
            "Создан",
            "Начат",
            "Завершён",
        ]) {
            expect(
                await screen.findByRole(
                    "columnheader",
                    {name: column},
                ),
            ).toBeVisible();
        }

        expect(screen.getByText("#103")).toBeVisible();
        expect(screen.getByText("Выполнение")).toBeVisible();
        expect(
            within(
                screen.getByRole("row", {name: /#102/}),
            ).getByText("Preview"),
        ).toBeVisible();
        expect(screen.getByText("Версия 4")).toBeVisible();
        expect(screen.getByText("Система")).toBeVisible();
        expect(screen.getByText("Пользователь #1")).toBeVisible();
        expect(
            screen.getByText(
                "Проверено: 101 · Подошло: 7 · " +
                "Ожидает: 5 · Выполнено: 2 · Ошибок: 1",
            ),
        ).toBeVisible();
        expect(screen.getAllByText(/03\.09\.2026.*10:00/))
            .not.toHaveLength(0);
        expect(screen.getByText(/03\.09\.2026.*10:05/))
            .toBeVisible();
        expect(screen.getByText(/03\.09\.2026.*10:06/))
            .toBeVisible();
        expect(testState.getAutomationRun).not.toHaveBeenCalled();
    });

    it("запрашивает выбранную страницу журнала", async () => {
        testState.getAutomationRuns.mockImplementation(
            async (
                _workspaceId: number,
                _automationId: number,
                page: number,
            ) => ({
                count: 21,
                next: page === 1
                    ? "/api/automations/41/runs/?page=2"
                    : null,
                previous: page === 2
                    ? "/api/automations/41/runs/?page=1"
                    : null,
                results: [
                    buildRunSummary(
                        page === 1 ? 103 : 81,
                        "execute",
                    ),
                ],
            }),
        );
        const {user} = renderDetail("/automations/41/runs");

        expect(await screen.findByText("#103")).toBeVisible();
        await user.click(screen.getByTitle("2"));

        expect(await screen.findByText("#81")).toBeVisible();
        expect(testState.getAutomationRuns)
            .toHaveBeenLastCalledWith(7, 41, 2);
    });

    it("открывает подробную страницу по строке запуска", async () => {
        testState.getAutomationRuns.mockResolvedValue({
            count: 1,
            next: null,
            previous: null,
            results: [buildRunSummary(103, "execute")],
        });
        const {user} = renderDetail("/automations/41/runs");

        await user.click(
            await screen.findByRole("row", {name: /#103/}),
        );

        expect(screen.getByTestId("pathname")).toHaveTextContent(
            "/automation-runs/103",
        );
    });
});
