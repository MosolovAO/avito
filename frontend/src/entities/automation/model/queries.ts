import {useQuery} from "@tanstack/react-query";

import {requireWorkspaceId} from "../../../shared/api/workspaceHeaders";
import {
    getAutomation,
    getAutomationCatalog,
    getAutomationDecisions,
    getAutomationInboxSummary,
    getAutomationRun,
    getAutomationRuns,
    getAutomations,
} from "../api/automationApi";
import type {AutomationRunStatus} from "./types";
import {automationKeys} from "./queryKeys";

type WorkspaceId = number | null;

export const getRunPollingInterval = (
    status: AutomationRunStatus | undefined,
): number | false => {
    switch (status) {
        case "queued":
        case "evaluating":
            return 2500;

        case "waiting_for_data":
            return 30000;

        case "effect_pending":
            return 15000;

        default:
            return false;
    }
};

export const useAutomationCatalogQuery = (
    workspaceId: WorkspaceId,
) => useQuery({
    queryKey: automationKeys.catalog(workspaceId),
    queryFn: () => getAutomationCatalog(
        requireWorkspaceId(workspaceId),
    ),
    enabled: workspaceId !== null,
});

export const useAutomationsQuery = (
    workspaceId: WorkspaceId,
    page: number,
) => useQuery({
    queryKey: automationKeys.list(workspaceId, page),
    queryFn: () => getAutomations(
        requireWorkspaceId(workspaceId),
        page,
    ),
    enabled: workspaceId !== null,
});

export const useAutomationQuery = (
    workspaceId: WorkspaceId,
    automationId: number,
) => useQuery({
    queryKey: automationKeys.detail(
        workspaceId,
        automationId,
    ),
    queryFn: () => getAutomation(
        requireWorkspaceId(workspaceId),
        automationId,
    ),
    enabled: workspaceId !== null,
});

export const useAutomationRunsQuery = (
    workspaceId: WorkspaceId,
    automationId: number,
    page: number,
) => useQuery({
    queryKey: automationKeys.runs(
        workspaceId,
        automationId,
        page,
    ),
    queryFn: () => getAutomationRuns(
        requireWorkspaceId(workspaceId),
        automationId,
        page,
    ),
    enabled: workspaceId !== null,
});

export const useAutomationRunQuery = (
    workspaceId: WorkspaceId,
    runId: number,
) => useQuery({
    queryKey: automationKeys.run(workspaceId, runId),
    queryFn: () => getAutomationRun(
        requireWorkspaceId(workspaceId),
        runId,
    ),
    enabled: workspaceId !== null,
    refetchInterval: (query) =>
        getRunPollingInterval(query.state.data?.status),
    refetchIntervalInBackground: false,
});

export const useAutomationDecisionsQuery = (
    workspaceId: WorkspaceId,
    runId: number,
    page: number,
) => useQuery({
    queryKey: automationKeys.decisions(
        workspaceId,
        runId,
        page,
    ),
    queryFn: () => getAutomationDecisions(
        requireWorkspaceId(workspaceId),
        runId,
        page,
    ),
    enabled: workspaceId !== null,
});

export const useAutomationInboxSummaryQuery = (
    workspaceId: WorkspaceId,
    shouldFetch = true,
) => useQuery({
    queryKey: automationKeys.inboxSummary(workspaceId),
    queryFn: () => getAutomationInboxSummary(
        requireWorkspaceId(workspaceId),
    ),
    enabled: workspaceId !== null && shouldFetch,
    refetchInterval: 60_000,
    refetchOnWindowFocus: true,
});