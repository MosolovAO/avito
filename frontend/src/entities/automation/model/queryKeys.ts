type WorkspaceId = number | null;

export const automationKeys = {
    all: ["automations"] as const,

    workspace: (workspaceId: WorkspaceId) =>
        [...automationKeys.all, workspaceId] as const,

    catalog: (workspaceId: WorkspaceId) =>
        [...automationKeys.workspace(workspaceId), "catalog"] as const,

    listRoot: (workspaceId: WorkspaceId) =>
        [...automationKeys.workspace(workspaceId), "list"] as const,

    list: (workspaceId: WorkspaceId, page: number) =>
        [...automationKeys.listRoot(workspaceId), page] as const,

    detail: (
        workspaceId: WorkspaceId,
        automationId: number,
    ) => [
        ...automationKeys.workspace(workspaceId),
        "detail",
        automationId,
    ] as const,

    runsRoot: (
        workspaceId: WorkspaceId,
        automationId: number,
    ) => [
        ...automationKeys.workspace(workspaceId),
        "runs",
        automationId,
    ] as const,

    runs: (
        workspaceId: WorkspaceId,
        automationId: number,
        page: number,
    ) => [
        ...automationKeys.runsRoot(workspaceId, automationId),
        page,
    ] as const,

    run: (
        workspaceId: WorkspaceId,
        runId: number,
    ) => [
        ...automationKeys.workspace(workspaceId),
        "run",
        runId,
    ] as const,

    decisionsRoot: (
        workspaceId: WorkspaceId,
        runId: number,
    ) => [
        ...automationKeys.run(workspaceId, runId),
        "decisions",
    ] as const,

    decisions: (
        workspaceId: WorkspaceId,
        runId: number,
        page: number,
    ) => [
        ...automationKeys.decisionsRoot(workspaceId, runId),
        page,
    ] as const,

    inboxSummary: (workspaceId: WorkspaceId) =>
        [
            ...automationKeys.workspace(workspaceId),
            "inbox-summary",
        ] as const,
};