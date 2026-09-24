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
} from "react-router-dom";
import {
    beforeEach,
    describe,
    expect,
    it,
    vi,
} from "vitest";

import type {
    AutomationCatalogResponse,
    AutomationDecision,
    AutomationDecisionStatus,
    AutomationRunDetail,
    AutomationRunStatus,
} from "../../entities/automation";
import {automationKeys} from "../../entities/automation";
import {ROUTES} from "../../shared/config/constants";
import {AutomationRunPage} from "./AutomationRunPage";

const testState = vi.hoisted(() => ({
    currentWorkspace: {
        currentWorkspaceId: 7 as number | null,
        canManageAutomations: true,
    },
    getAutomationCatalog: vi.fn(),
    getAutomationRun: vi.fn(),
    getAutomationDecisions: vi.fn(),
    approveAutomationDecision: vi.fn(),
    rejectAutomationDecision: vi.fn(),
    decisionStatus: "pending_approval" as AutomationDecisionStatus,
    decisionAction: "pause",
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

vi.mock(
    "../../entities/automation/api/automationApi",
    async (importOriginal) => {
        const actual = await importOriginal<
            typeof import(
                "../../entities/automation/api/automationApi"
            )
        >();

        return {
            ...actual,
            getAutomationCatalog:
                testState.getAutomationCatalog,
            getAutomationRun: testState.getAutomationRun,
            getAutomationDecisions:
                testState.getAutomationDecisions,
            approveAutomationDecision:
                testState.approveAutomationDecision,
            rejectAutomationDecision:
                testState.rejectAutomationDecision,
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
                {
                    code: "archive",
                    label: "Архивировать",
                    description: "Окончательно снять объявление",
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

const buildRun = (
    status: AutomationRunStatus = "completed",
): AutomationRunDetail => ({
    id: 205,
    automation_id: 41,
    kind: "execute",
    trigger: "manual",
    execution_mode: "manual",
    automation_version: 7,
    automation_name: "Мало просмотров",
    module_type: "avito_listings",
    status,
    error: null,
    result: {
        avito_account_id: 17,
        as_of_date: "2026-09-02",
        checked: 101,
        ineligible: 12,
        insufficient_coverage: 13,
        not_matched: 14,
        matched: 15,
        deferred_by_run_limit: 5,
        pending_approval: 10,
        completed_actions: 3,
        failed_actions: 2,
        max_actions_per_run_snapshot: 10,
        approval_ttl_minutes_snapshot: 1440,
        target_max_id_snapshot: 500,
        condition_snapshot: {
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
        action_snapshot: {
            type: "pause",
            config: {},
        },
        examples_snapshot: [],
    },
    created_by: 9,
    retry_count: 0,
    data_wait_attempt_count: 0,
    next_attempt_at: null,
    wait_started_at: null,
    started_at: "2026-09-03T07:05:00Z",
    finished_at: "2026-09-03T07:06:00Z",
    created_at: "2026-09-03T07:00:00Z",
    updated_at: "2026-09-03T07:07:00Z",
});

const buildDecision = (): AutomationDecision => ({
    id: 501,
    run_id: 205,
    automation_id: 41,
    avito_account_id: 17,
    listing_id: 301,
    listing: {
        avito_id: "123456789",
        title: "Тестовое объявление",
    },
    status: testState.decisionStatus,
    automation_version: 7,
    active_since: "2026-08-24T09:00:00Z",
    metrics: [
        {
            metric: "views",
            aggregation: "sum",
            window_days: 10,
            date_from: "2026-08-24",
            date_to: "2026-09-02",
            value: 7,
        },
    ],
    action: {
        type: testState.decisionAction,
        config: {},
    },
    expires_at: "2026-09-03T12:00:00Z",
    approved_by: null,
    approved_at: null,
    rejected_by: null,
    rejected_at: null,
    action_applied_at: null,
    completed_at: null,
    terminal_at: null,
    required_export_revision:
        testState.decisionStatus === "effect_pending" ? 8 : null,
    effect_attempts: 0,
    next_effect_retry_at: null,
    error: null,
    created_at: "2026-09-02T12:00:00Z",
    updated_at: "2026-09-02T12:00:00Z",
});

const renderPage = () => {
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
            <MemoryRouter
                initialEntries={["/automation-runs/205"]}
            >
                <Routes>
                    <Route
                        path="/automation-runs/:runId"
                        element={<AutomationRunPage/>}
                    />
                </Routes>
            </MemoryRouter>
        </QueryClientProvider>,
    );

    return {
        invalidateQueries,
        user: userEvent.setup(),
    };
};

describe("AutomationRunPage", () => {
    beforeEach(() => {
        vi.clearAllMocks();
        testState.currentWorkspace.currentWorkspaceId = 7;
        testState.currentWorkspace.canManageAutomations = true;
        testState.getAutomationCatalog.mockResolvedValue(catalog);
        testState.getAutomationRun.mockResolvedValue(buildRun());
        testState.decisionStatus = "pending_approval";
        testState.decisionAction = "pause";
        testState.getAutomationDecisions.mockImplementation(
            async () => ({
                count: 1,
                next: null,
                previous: null,
                results: [buildDecision()],
            }),
        );
        testState.approveAutomationDecision.mockImplementation(
            async () => {
                testState.decisionStatus = "effect_pending";

                return {
                    decision_id: 501,
                    status: "effect_pending",
                    outcome: "effect_pending",
                    reason: null,
                    changed: true,
                    required_export_revision: 8,
                };
            },
        );
        testState.rejectAutomationDecision.mockImplementation(
            async () => {
                testState.decisionStatus = "rejected";

                return {
                    decision_id: 501,
                    status: "rejected",
                    outcome: "rejected",
                    reason: null,
                    changed: true,
                    required_export_revision: null,
                };
            },
        );
    });

    it("показывает immutable snapshot запуска", async () => {
        renderPage();

        const heading = await screen.findByRole("heading", {
                name: "Запуск #205",
            });
        const headingRow = heading.closest(".ant-space");

        expect(heading).toBeVisible();
        expect(headingRow).not.toBeNull();
        expect(
            within(headingRow as HTMLElement).getByText("Завершён"),
        ).toBeVisible();
        expect(screen.getByText("Мало просмотров")).toBeVisible();
        expect(screen.getByText("Версия 7")).toBeVisible();
        expect(screen.getByText("Выполнение")).toBeVisible();
        expect(screen.getByText("Ручной запуск")).toBeVisible();
        expect(screen.getByText("Пользователь #9")).toBeVisible();
        expect(screen.getByText(/03\.09\.2026.*10:00/))
            .toBeVisible();
        expect(screen.getByText(/03\.09\.2026.*10:05/))
            .toBeVisible();
        expect(screen.getByText(/03\.09\.2026.*10:06/))
            .toBeVisible();
        expect(screen.getByText(/03\.09\.2026.*10:07/))
            .toBeVisible();

        const checkedTitle = screen.getByText("Проверено");
        const checkedCard = checkedTitle.closest(".ant-card");
        expect(checkedCard).not.toBeNull();
        expect(
            within(checkedCard as HTMLElement).getByText("101"),
        ).toBeVisible();

        expect(screen.getByText("Группа 1")).toBeVisible();
        expect(screen.getByText("И")).toBeVisible();
        expect(screen.getByText("ИЛИ")).toBeVisible();
        expect(screen.getByText("Группа 2")).toBeVisible();
        expect(screen.getAllByText("Просмотры")).toHaveLength(3);
        expect(screen.getAllByText("Сумма")).toHaveLength(3);
        expect(screen.getByText("за 10 дней")).toBeVisible();
        expect(screen.getAllByText("<")).toHaveLength(3);
        expect(screen.getByText("Приостановить")).toBeVisible();
        expect(screen.getByText("10 объявлений")).toBeVisible();
        expect(screen.getByText("24 часа")).toBeVisible();
    });

    it("показывает сведения ожидания данных", async () => {
        testState.getAutomationRun.mockResolvedValue({
            ...buildRun("waiting_for_data"),
            error: {
                code: "insufficient_data",
                message: "Статистика аккаунта ещё не накоплена.",
            },
            retry_count: 2,
            data_wait_attempt_count: 3,
            wait_started_at: "2026-09-03T06:00:00Z",
            next_attempt_at: "2026-09-03T08:30:00Z",
        });

        renderPage();

        expect(await screen.findByText("Ожидает данные"))
            .toBeVisible();
        expect(screen.getByText("Ожидаем накопления статистики"))
            .toBeVisible();
        expect(screen.getByText("insufficient_data")).toBeVisible();
        expect(
            screen.getByText("Статистика аккаунта ещё не накоплена."),
        ).toBeVisible();
        expect(screen.queryByText("Ошибка запуска"))
            .not.toBeInTheDocument();
        const retryRow = screen.getByText("Попытки выполнения")
            .closest("tr");
        const dataWaitRow = screen
            .getByText("Попытки ожидания данных")
            .closest("tr");

        expect(retryRow).not.toBeNull();
        expect(within(retryRow as HTMLElement).getByText("2"))
            .toBeVisible();
        expect(dataWaitRow).not.toBeNull();
        expect(within(dataWaitRow as HTMLElement).getByText("3"))
            .toBeVisible();
        expect(screen.getByText(/03\.09\.2026.*09:00/))
            .toBeVisible();
        expect(screen.getByText(/03\.09\.2026.*11:30/))
            .toBeVisible();
    });

    it("показывает безопасную ошибку backend", async () => {
        testState.getAutomationRun.mockResolvedValue({
            ...buildRun("failed"),
            error: {
                code: "stats_timeout",
                message: "Не удалось прочитать статистику.",
            },
        });

        renderPage();

        expect(await screen.findByText("Ошибка запуска"))
            .toBeVisible();
        expect(screen.getByText("stats_timeout")).toBeVisible();
        expect(
            screen.getByText("Не удалось прочитать статистику."),
        ).toBeVisible();
    });

    it("не выдаёт CSV-эффект за подтверждённое изменение Avito", async () => {
        testState.getAutomationRun.mockResolvedValue(
            buildRun("effect_pending"),
        );

        renderPage();

        expect(await screen.findByText("Формируется CSV"))
            .toBeVisible();
        expect(
            screen.getByText(
                "Действие включено в сформированный CSV нужной " +
                "ревизии. Это ещё не является подтверждением, " +
                "что изменение уже принято и применено Avito.",
            ),
        ).toBeVisible();
    });

    it("показывает решения выполнения и открывает Drawer по объявлению", async () => {
        const {user} = renderPage();

        expect(await screen.findByRole("heading", {
            name: "Решения",
        })).toBeVisible();
        expect(testState.getAutomationDecisions)
            .toHaveBeenCalledWith(7, 205, 1);

        await user.click(await screen.findByRole("button", {
            name: "Тестовое объявление",
        }));

        expect(await screen.findByText("Решение #501"))
            .toBeVisible();
        expect(screen.getAllByText("123456789").length)
            .toBeGreaterThanOrEqual(1);
        expect(screen.getAllByText("Группа 1").length)
            .toBeGreaterThanOrEqual(2);
    });

    it("не загружает решения для preview", async () => {
        testState.getAutomationRun.mockResolvedValue({
            ...buildRun(),
            kind: "preview",
        });

        renderPage();

        expect(await screen.findByRole("heading", {
            name: "Запуск #205",
        })).toBeVisible();
        expect(testState.getAutomationDecisions)
            .not.toHaveBeenCalled();
        expect(screen.queryByRole("heading", {
            name: "Решения",
        })).not.toBeInTheDocument();
    });

    it("подтверждает pause одним действием и обновляет открытый Drawer", async () => {
        const {invalidateQueries, user} = renderPage();

        await user.click(await screen.findByRole("button", {
            name: "Тестовое объявление",
        }));
        await user.click(screen.getByRole("button", {
            name: "Подтвердить действие",
        }));

        await waitFor(() => {
            expect(testState.approveAutomationDecision)
                .toHaveBeenCalledWith(7, 205, 501);
        });
        expect(testState.approveAutomationDecision)
            .toHaveBeenCalledOnce();
        expect(testState.modalConfirm).not.toHaveBeenCalled();
        await waitFor(() => {
            expect(screen.getAllByText("Формируется CSV").length)
                .toBeGreaterThanOrEqual(2);
        });
        expect(screen.getByText("Решение #501")).toBeVisible();

        expect(invalidateQueries).toHaveBeenCalledWith({
            queryKey: automationKeys.run(7, 205),
        });
        expect(invalidateQueries).toHaveBeenCalledWith({
            queryKey: automationKeys.decisionsRoot(7, 205),
        });
        expect(invalidateQueries).toHaveBeenCalledWith({
            queryKey: automationKeys.inboxSummary(7),
        });
    });

    it("требует danger-подтверждение перед approve действия archive", async () => {
        testState.decisionAction = "archive";
        const {user} = renderPage();

        await user.click(await screen.findByRole("button", {
            name: "Тестовое объявление",
        }));
        await user.click(screen.getByRole("button", {
            name: "Подтвердить действие",
        }));

        expect(testState.approveAutomationDecision)
            .not.toHaveBeenCalled();
        expect(testState.modalConfirm).toHaveBeenCalledOnce();

        const confirmation = testState.modalConfirm.mock
            .lastCall?.[0] as {
            title: string;
            okText: string;
            okType: string;
            onOk: () => Promise<void>;
        };

        expect(confirmation.title).toBe(
            "Архивировать объявление?",
        );
        expect(confirmation.okText).toBe("Архивировать");
        expect(confirmation.okType).toBe("danger");

        await confirmation.onOk();

        expect(testState.approveAutomationDecision)
            .toHaveBeenCalledOnce();
    });

    it("отклоняет решение только после отдельного подтверждения", async () => {
        const {user} = renderPage();

        await user.click(await screen.findByRole("button", {
            name: "Тестовое объявление",
        }));
        await user.click(screen.getByRole("button", {
            name: "Отклонить",
        }));

        expect(testState.rejectAutomationDecision)
            .not.toHaveBeenCalled();
        expect(testState.modalConfirm).toHaveBeenCalledOnce();

        const confirmation = testState.modalConfirm.mock
            .lastCall?.[0] as {
            title: string;
            okText: string;
            onOk: () => Promise<void>;
        };

        expect(confirmation.title).toBe("Отклонить решение?");
        expect(confirmation.okText).toBe("Отклонить");

        await confirmation.onOk();

        expect(testState.rejectAutomationDecision)
            .toHaveBeenCalledWith(7, 205, 501);
        await waitFor(() => {
            expect(screen.getAllByText("Отклонено").length)
                .toBeGreaterThanOrEqual(2);
        });
        expect(screen.getByText("Решение #501")).toBeVisible();
    });

    it("блокирует обе команды пока mutation не завершилась", async () => {
        testState.approveAutomationDecision.mockReturnValue(
            new Promise(() => undefined),
        );
        const {user} = renderPage();

        await user.click(await screen.findByRole("button", {
            name: "Тестовое объявление",
        }));
        await user.click(screen.getByRole("button", {
            name: "Подтвердить действие",
        }));

        await waitFor(() => {
            expect(screen.getByRole("button", {
                name: /Подтвердить действие/,
            })).toBeDisabled();
        });
        expect(screen.getByRole("button", {
            name: "Отклонить",
        })).toBeDisabled();
    });

    it("при resource_busy оставляет Drawer открытым и обновляет данные", async () => {
        testState.approveAutomationDecision.mockRejectedValue(
            buildApiError(409, {
                code: "resource_busy",
                message: "Avito-аккаунт уже обрабатывается.",
            }),
        );
        const {user} = renderPage();

        await user.click(await screen.findByRole("button", {
            name: "Тестовое объявление",
        }));
        await user.click(screen.getByRole("button", {
            name: "Подтвердить действие",
        }));

        await waitFor(() => {
            expect(testState.notificationWarning)
                .toHaveBeenCalledWith({
                    message: "Avito-аккаунт уже обрабатывается",
                    description:
                        "Avito-аккаунт уже обрабатывается.",
                });
        });
        expect(screen.getByText("Решение #501")).toBeVisible();
        expect(testState.getAutomationRun.mock.calls.length)
            .toBeGreaterThan(1);
        expect(testState.getAutomationDecisions.mock.calls.length)
            .toBeGreaterThan(1);
    });

    it("задаёт маршрут подробной страницы запуска", () => {
        expect(ROUTES.AUTOMATION_RUN).toBe(
            "/automation-runs/:runId",
        );
    });
});
