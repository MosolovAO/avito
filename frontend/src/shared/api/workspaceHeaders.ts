export const requireWorkspaceId = (workspaceId: number | null): number => {
    if (workspaceId === null) {
        throw new Error("Кабинет не выбран")
    }

    return workspaceId
}

export const getWorkspaceHeaders = (
    workspaceId: number,
): { "X-Workspace-Id": string } => ({
    "X-Workspace-Id": String(workspaceId)
});