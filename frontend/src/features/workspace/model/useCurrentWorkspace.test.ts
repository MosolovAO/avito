import {renderHook} from "@testing-library/react";
import {beforeEach, describe, expect, it, vi} from "vitest";

import {useAuth} from "../../auth/model/AuthProvider";
import {
    useCurrentWorkspace,
    WorkspacePermission,
} from "./useCurrentWorkspace";
import {useWorkspaceStore} from "./workspaceStore";

vi.mock("../../auth/model/AuthProvider", () => ({
    useAuth: vi.fn(),
}));

const workspace = {
    id: 7,
    name: "Основной кабинет",
    slug: "main",
    role: "owner",
    status: "active",
};

const buildAuthContext = (
    permissions: string[],
): ReturnType<typeof useAuth> => ({
    user: null,
    workspaces: [{
        ...workspace,
        permissions,
    }],
    isAuthenticated: false,
    isChecking: false,
    login: async () => undefined,
    register: async () => undefined,
    logout: async () => undefined,
    loginLoading: false,
    registerLoading: false,
    logoutLoading: false,
});

describe("WorkspacePermission", () => {
    it("использует backend-код управления автоматизациями", () => {
        expect(WorkspacePermission.MANAGE_AUTOMATIONS).toBe(
            "manage_automations",
        );
    });
});

describe("useCurrentWorkspace", () => {
    beforeEach(() => {
        useWorkspaceStore.setState({
            selectedWorkspaceId: workspace.id,
        });

        vi.mocked(useAuth).mockReturnValue(
            buildAuthContext(["manage_automations"]),
        );
    });

    it("разрешает управление автоматизациями при наличии права", () => {
        const {result} = renderHook(() => useCurrentWorkspace());

        expect(result.current.canManageAutomations).toBe(true);
    });

    it("запрещает управление автоматизациями без права", () => {
        vi.mocked(useAuth).mockReturnValue(buildAuthContext([]));

        const {result} = renderHook(() => useCurrentWorkspace());

        expect(result.current.canManageAutomations).toBe(false);
    });
});