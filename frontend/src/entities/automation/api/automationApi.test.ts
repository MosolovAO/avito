import {beforeEach, describe, expect, it, vi} from "vitest";

import type {
    CreateAutomationRequest,
    UpdateAutomationRequest,
} from "../model/types";
import {
    approveAutomationDecision,
    archiveAutomation,
    createAutomation,
    createAutomationPreview,
    createAutomationRun,
    getAutomation,
    getAutomationApiError,
    getAutomationCatalog,
    getAutomationDecisions,
    getAutomationInboxSummary,
    getAutomationRun,
    getAutomationRuns,
    getAutomations,
    rejectAutomationDecision,
    updateAutomation,
} from "./automationApi";

const apiMocks = vi.hoisted(() => ({
    get: vi.fn(),
    post: vi.fn(),
    patch: vi.fn(),
    delete: vi.fn(),
}));

vi.mock("../../../shared/api/axios", () => ({
    default: apiMocks,
}));

const workspaceHeaders = {
    "X-Workspace-Id": "7",
};

const createPayload: CreateAutomationRequest = {
    name: "Мало контактов",
    module_type: "avito_listings",
    config: {
        avito_account_id: 15,
        condition_tree: {
            type: "group",
            operators: [],
            children: [{
                type: "group",
                operators: [],
                children: [{
                    type: "condition",
                    metric: "contacts",
                    aggregation: "sum",
                    window_days: 10,
                    comparator: "lt",
                    value: 10,
                }],
            }],
        },
        action: {
            type: "pause",
            config: {},
        },
        max_actions_per_run: 10,
        approval_ttl_minutes: 1440,
    },
};

describe("automationApi", () => {
    beforeEach(() => {
        vi.clearAllMocks();

        apiMocks.get.mockResolvedValue({data: {}});
        apiMocks.post.mockResolvedValue({data: {}});
        apiMocks.patch.mockResolvedValue({data: {}});
        apiMocks.delete.mockResolvedValue({data: undefined});
    });

    it("выполняет workspace-scoped GET-запросы", async () => {
        await getAutomationCatalog(7);
        await getAutomations(7, 2);
        await getAutomation(7, 12);
        await getAutomationRuns(7, 12, 3);
        await getAutomationRun(7, 25);
        await getAutomationDecisions(7, 25, 4);
        await getAutomationInboxSummary(7);

        expect(apiMocks.get).toHaveBeenNthCalledWith(
            1,
            "/api/automations/catalog/",
            {headers: workspaceHeaders},
        );

        expect(apiMocks.get).toHaveBeenNthCalledWith(
            2,
            "/api/automations/",
            {
                headers: workspaceHeaders,
                params: {page: 2},
            },
        );

        expect(apiMocks.get).toHaveBeenNthCalledWith(
            3,
            "/api/automations/12/",
            {headers: workspaceHeaders},
        );

        expect(apiMocks.get).toHaveBeenNthCalledWith(
            4,
            "/api/automations/12/runs/",
            {
                headers: workspaceHeaders,
                params: {page: 3},
            },
        );

        expect(apiMocks.get).toHaveBeenNthCalledWith(
            5,
            "/api/automation-runs/25/",
            {headers: workspaceHeaders},
        );

        expect(apiMocks.get).toHaveBeenNthCalledWith(
            6,
            "/api/automation-runs/25/decisions/",
            {
                headers: workspaceHeaders,
                params: {page: 4},
            },
        );

        expect(apiMocks.get).toHaveBeenNthCalledWith(
            7,
            "/api/automations/inbox-summary/",
            {headers: workspaceHeaders},
        );
    });

    it("создаёт, изменяет и архивирует automation", async () => {
        const updatePayload: UpdateAutomationRequest = {
            state: "disabled",
        };

        await createAutomation(7, createPayload);
        await updateAutomation(7, 12, updatePayload);
        await archiveAutomation(7, 12);

        expect(apiMocks.post).toHaveBeenCalledWith(
            "/api/automations/",
            createPayload,
            {headers: workspaceHeaders},
        );

        expect(apiMocks.patch).toHaveBeenCalledWith(
            "/api/automations/12/",
            updatePayload,
            {headers: workspaceHeaders},
        );

        expect(apiMocks.delete).toHaveBeenCalledWith(
            "/api/automations/12/",
            {headers: workspaceHeaders},
        );
    });

    it("передаёт стабильный Idempotency-Key для preview и run", async () => {
        await createAutomationPreview(7, 12, "preview-key");
        await createAutomationRun(7, 12, "run-key");

        expect(apiMocks.post).toHaveBeenNthCalledWith(
            1,
            "/api/automations/12/preview/",
            {},
            {
                headers: {
                    ...workspaceHeaders,
                    "Idempotency-Key": "preview-key",
                },
            },
        );

        expect(apiMocks.post).toHaveBeenNthCalledWith(
            2,
            "/api/automations/12/run/",
            {},
            {
                headers: {
                    ...workspaceHeaders,
                    "Idempotency-Key": "run-key",
                },
            },
        );
    });

    it("отправляет пустой payload для approve и reject", async () => {
        await approveAutomationDecision(7, 25, 31);
        await rejectAutomationDecision(7, 25, 31);

        expect(apiMocks.post).toHaveBeenNthCalledWith(
            1,
            "/api/automation-runs/25/decisions/31/approve/",
            {},
            {headers: workspaceHeaders},
        );

        expect(apiMocks.post).toHaveBeenNthCalledWith(
            2,
            "/api/automation-runs/25/decisions/31/reject/",
            {},
            {headers: workspaceHeaders},
        );
    });

    it("возвращает data, а не полный AxiosResponse", async () => {
        const responseData = {
            pending_approval_count: 4,
        };

        apiMocks.get.mockResolvedValueOnce({
            data: responseData,
        });

        await expect(
            getAutomationInboxSummary(7),
        ).resolves.toEqual(responseData);
    });
});

const buildAxiosError = (
    status: number,
    data: unknown,
): unknown => ({
    isAxiosError: true,
    response: {
        status,
        data,
    },
});

describe("getAutomationApiError", () => {
    it("извлекает domain error и идентификатор открытого запуска", () => {
        const error = buildAxiosError(409, {
            code: "open_preview_conflict",
            message: "Preview уже выполняется.",
            open_run_id: 42,
        });

        expect(getAutomationApiError(error)).toEqual({
            status: 409,
            code: "open_preview_conflict",
            message: "Preview уже выполняется.",
            openRunId: 42,
            fields: {},
        });
    });

    it("извлекает ошибки полей из DRF payload", () => {
        const error = buildAxiosError(400, {
            name: ["Обязательное поле."],
            config: {
                condition_tree: ["Некорректное дерево условий."],
            },
        });

        expect(getAutomationApiError(error)).toEqual({
            status: 400,
            code: null,
            message: "Не удалось выполнить запрос",
            openRunId: null,
            fields: {
                name: ["Обязательное поле."],
                config: ["Некорректное дерево условий."],
            },
        });
    });

    it("поддерживает стандартное поле detail", () => {
        const error = buildAxiosError(403, {
            detail: "Недостаточно прав.",
        });

        expect(getAutomationApiError(error)).toEqual({
            status: 403,
            code: null,
            message: "Недостаточно прав.",
            openRunId: null,
            fields: {},
        });
    });

    it("не интерпретирует HTML и обычные ошибки как backend payload", () => {
        expect(
            getAutomationApiError(
                buildAxiosError(500, "<!doctype html>"),
            ),
        ).toBeNull();

        expect(
            getAutomationApiError(new Error("Локальная ошибка")),
        ).toBeNull();
    });
});
