import api from "../../../shared/api/axios";
import type {PaginatedResponse} from "../../../shared/api/pagination";
import {getWorkspaceHeaders} from "../../../shared/api/workspaceHeaders";
import {isAxiosError} from "axios";
import type {
    Automation,
    AutomationCatalogResponse,
    AutomationDecision,
    AutomationInboxSummary,
    AutomationRunDetail,
    AutomationRunSummary,
    CreateAutomationRequest,
    CreateRunResponse,
    DecisionCommandResponse,
    UpdateAutomationRequest,
    AutomationApiError,
} from "../model/types";

const getCommandHeaders = (
    workspaceId: number,
    idempotencyKey: string,
) => ({
    ...getWorkspaceHeaders(workspaceId),
    "Idempotency-Key": idempotencyKey,
});

const defaultAutomationErrorMessage = "Не удалось выполнить запрос";

const reservedErrorFields = new Set([
    "code",
    "message",
    "detail",
    "open_run_id",
]);

const isRecord = (
    value: unknown,
): value is Record<string, unknown> =>
    typeof value === "object" &&
    value !== null &&
    !Array.isArray(value);

const getNonEmptyString = (
    value: unknown,
): string | null => {
    if (typeof value !== "string") {
        return null;
    }

    const normalized = value.trim();

    return normalized || null;
};

const collectErrorMessages = (
    value: unknown,
): string[] => {
    const directMessage = getNonEmptyString(value);

    if (directMessage !== null) {
        return [directMessage];
    }

    if (Array.isArray(value)) {
        return value.flatMap(collectErrorMessages);
    }

    if (isRecord(value)) {
        return Object.values(value).flatMap(
            collectErrorMessages,
        );
    }

    return [];
};

export const getAutomationApiError = (
    error: unknown,
): AutomationApiError | null => {
    if (!isAxiosError<unknown>(error)) {
        return null;
    }

    const data = error.response?.data;

    if (!isRecord(data)) {
        return null;
    }

    const code = getNonEmptyString(data.code);

    const backendMessage =
        getNonEmptyString(data.message) ??
        getNonEmptyString(data.detail);

    const openRunId =
        typeof data.open_run_id === "number" &&
        Number.isInteger(data.open_run_id) &&
        data.open_run_id > 0
            ? data.open_run_id
            : null;

    const fields: Record<string, string[]> = {};

    for (const [field, value] of Object.entries(data)) {
        if (reservedErrorFields.has(field)) {
            continue;
        }

        const messages = collectErrorMessages(value);

        if (messages.length > 0) {
            fields[field] = messages;
        }
    }

    if (
        code === null &&
        backendMessage === null &&
        Object.keys(fields).length === 0
    ) {
        return null;
    }

    return {
        status: error.response?.status ?? null,
        code,
        message:
            backendMessage ??
            defaultAutomationErrorMessage,
        openRunId,
        fields,
    };
};

export const getAutomationCatalog = async (
    workspaceId: number,
): Promise<AutomationCatalogResponse> => {
    const response = await api.get<AutomationCatalogResponse>(
        "/api/automations/catalog/",
        {
            headers: getWorkspaceHeaders(workspaceId),
        },
    );

    return response.data;
};

export const getAutomations = async (
    workspaceId: number,
    page: number,
): Promise<PaginatedResponse<Automation>> => {
    const response = await api.get<PaginatedResponse<Automation>>(
        "/api/automations/",
        {
            headers: getWorkspaceHeaders(workspaceId),
            params: {page},
        },
    );

    return response.data;
};

export const getAutomation = async (
    workspaceId: number,
    automationId: number,
): Promise<Automation> => {
    const response = await api.get<Automation>(
        `/api/automations/${automationId}/`,
        {
            headers: getWorkspaceHeaders(workspaceId),
        },
    );

    return response.data;
};

export const createAutomation = async (
    workspaceId: number,
    payload: CreateAutomationRequest,
): Promise<Automation> => {
    const response = await api.post<Automation>(
        "/api/automations/",
        payload,
        {
            headers: getWorkspaceHeaders(workspaceId),
        },
    );

    return response.data;
};

export const updateAutomation = async (
    workspaceId: number,
    automationId: number,
    payload: UpdateAutomationRequest,
): Promise<Automation> => {
    const response = await api.patch<Automation>(
        `/api/automations/${automationId}/`,
        payload,
        {
            headers: getWorkspaceHeaders(workspaceId),
        },
    );

    return response.data;
};

export const archiveAutomation = async (
    workspaceId: number,
    automationId: number,
): Promise<void> => {
    await api.delete(
        `/api/automations/${automationId}/`,
        {
            headers: getWorkspaceHeaders(workspaceId),
        },
    );
};

export const getAutomationRuns = async (
    workspaceId: number,
    automationId: number,
    page: number,
): Promise<PaginatedResponse<AutomationRunSummary>> => {
    const response = await api.get<
        PaginatedResponse<AutomationRunSummary>
    >(
        `/api/automations/${automationId}/runs/`,
        {
            headers: getWorkspaceHeaders(workspaceId),
            params: {page},
        },
    );

    return response.data;
};

export const getAutomationRun = async (
    workspaceId: number,
    runId: number,
): Promise<AutomationRunDetail> => {
    const response = await api.get<AutomationRunDetail>(
        `/api/automation-runs/${runId}/`,
        {
            headers: getWorkspaceHeaders(workspaceId),
        },
    );

    return response.data;
};

export const getAutomationDecisions = async (
    workspaceId: number,
    runId: number,
    page: number,
): Promise<PaginatedResponse<AutomationDecision>> => {
    const response = await api.get<
        PaginatedResponse<AutomationDecision>
    >(
        `/api/automation-runs/${runId}/decisions/`,
        {
            headers: getWorkspaceHeaders(workspaceId),
            params: {page},
        },
    );

    return response.data;
};

export const getAutomationInboxSummary = async (
    workspaceId: number,
): Promise<AutomationInboxSummary> => {
    const response = await api.get<AutomationInboxSummary>(
        "/api/automations/inbox-summary/",
        {
            headers: getWorkspaceHeaders(workspaceId),
        },
    );

    return response.data;
};

export const createAutomationPreview = async (
    workspaceId: number,
    automationId: number,
    idempotencyKey: string,
): Promise<CreateRunResponse> => {
    const response = await api.post<CreateRunResponse>(
        `/api/automations/${automationId}/preview/`,
        {},
        {
            headers: getCommandHeaders(
                workspaceId,
                idempotencyKey,
            ),
        },
    );

    return response.data;
};

export const createAutomationRun = async (
    workspaceId: number,
    automationId: number,
    idempotencyKey: string,
): Promise<CreateRunResponse> => {
    const response = await api.post<CreateRunResponse>(
        `/api/automations/${automationId}/run/`,
        {},
        {
            headers: getCommandHeaders(
                workspaceId,
                idempotencyKey,
            ),
        },
    );

    return response.data;
};

export const approveAutomationDecision = async (
    workspaceId: number,
    runId: number,
    decisionId: number,
): Promise<DecisionCommandResponse> => {
    const response = await api.post<DecisionCommandResponse>(
        `/api/automation-runs/${runId}/decisions/${decisionId}/approve/`,
        {},
        {
            headers: getWorkspaceHeaders(workspaceId),
        },
    );

    return response.data;
};

export const rejectAutomationDecision = async (
    workspaceId: number,
    runId: number,
    decisionId: number,
): Promise<DecisionCommandResponse> => {
    const response = await api.post<DecisionCommandResponse>(
        `/api/automation-runs/${runId}/decisions/${decisionId}/reject/`,
        {},
        {
            headers: getWorkspaceHeaders(workspaceId),
        },
    );

    return response.data;
};