import {useAuth} from "../../auth/model/AuthProvider";
import {useWorkspaceStore} from "./workspaceStore";
import type {WorkspaceContext} from "../../../shared/api/auth";

export const WorkspacePermission = {
    MANAGE_USERS: "manage_users",
    MANAGE_AVITO_ACCOUNTS: "manage_avito_accounts",
    VIEW_TASKS: "view_tasks",
} as const;


type WorkspacePermissionValue =
    (typeof WorkspacePermission)[keyof typeof WorkspacePermission];

interface CurrentWorkcpaceResult {
    currentWorkspace: WorkspaceContext | null;
    currentWorkspaceId: number | null;
    workspaces: WorkspaceContext[];
    selectedWorkspaceId: number | null;
    setSelectedWorkspaceId: (workspaceId: number) => void;
    hasPermission: (permission: WorkspacePermissionValue) => boolean;
    canManageUsers: boolean;
    canManageAvitoAccounts: boolean;
    canViewTasks: boolean;
}

export const useCurrentWorkspace = (): CurrentWorkcpaceResult => {
    const {workspaces} = useAuth();

    const selectedWorkspaceId = useWorkspaceStore(
        (state) => state.selectedWorkspaceId,
    );

    const setSelectedWorkspaceId = useWorkspaceStore(
        (state) => state.setSelectedWorkspaceId,
    )

    const selectedWorkspace =
        selectedWorkspaceId === null
            ? undefined
            : workspaces.find((workspace) => workspace.id === selectedWorkspaceId);

    const currentWorkspace = selectedWorkspace ?? workspaces[0] ?? null;

    const hasPermission = (permission: WorkspacePermissionValue): boolean => {
        if (!currentWorkspace) {
            return false;
        }

        return currentWorkspace.permissions.includes(permission);
    }

    return {
        currentWorkspace,
        currentWorkspaceId: currentWorkspace?.id ?? null,
        workspaces,
        selectedWorkspaceId,
        setSelectedWorkspaceId,
        hasPermission,
        canManageUsers: hasPermission(WorkspacePermission.MANAGE_USERS),
        canManageAvitoAccounts: hasPermission(
            WorkspacePermission.MANAGE_AVITO_ACCOUNTS,
        ),
        canViewTasks: hasPermission((WorkspacePermission.VIEW_TASKS))
    }
};
