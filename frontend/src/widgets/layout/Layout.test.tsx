import {
    render,
    screen,
    waitFor,
    within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {
    QueryClient,
    QueryClientProvider,
} from "@tanstack/react-query";
import {
    MemoryRouter,
    useLocation,
} from "react-router-dom";
import {
    beforeEach,
    describe,
    expect,
    it,
    vi,
} from "vitest";

import {Layout} from "./Layout";

const testState = vi.hoisted(() => ({
    currentWorkspace: {
        currentWorkspaceId: 7 as number | null,
        canManageAutomations: true,
    },
    getAutomationInboxSummary: vi.fn(),
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
            getAutomationInboxSummary:
                testState.getAutomationInboxSummary,
        };
    },
);

vi.mock(
    "../../features/workspace/components",
    () => ({
        WorkspaceSwitcher: () => (
            <div>Переключатель workspace</div>
        ),
    }),
);

vi.mock(
    "../../features/auth/model/AuthProvider",
    () => ({
        useAuth: () => ({
            user: {email: "owner@example.com"},
            workspaces: [],
            isAuthenticated: true,
            isChecking: false,
            login: vi.fn(),
            register: vi.fn(),
            logout: vi.fn(),
            loginLoading: false,
            registerLoading: false,
            logoutLoading: false,
        }),
    }),
);

const LocationProbe = () => {
    const location = useLocation();

    return <div data-testid="pathname">{location.pathname}</div>;
};

const renderLayout = (path = "/") => {
    const queryClient = new QueryClient({
        defaultOptions: {
            queries: {retry: false},
        },
    });

    render(
        <QueryClientProvider client={queryClient}>
            <MemoryRouter initialEntries={[path]}>
                <Layout>
                    <LocationProbe/>
                </Layout>
            </MemoryRouter>
        </QueryClientProvider>,
    );

    return userEvent.setup();
};

describe("Layout automation navigation", () => {
    beforeEach(() => {
        vi.clearAllMocks();
        testState.currentWorkspace.currentWorkspaceId = 7;
        testState.currentWorkspace.canManageAutomations = true;
        testState.getAutomationInboxSummary.mockResolvedValue({
            pending_approval_count: 4,
        });
    });

    it("показывает один пункт Автоматизации в группе Инструменты", () => {
        renderLayout();

        expect(screen.getByText("Инструменты")).toBeVisible();
        expect(
            screen.getAllByText("Автоматизации"),
        ).toHaveLength(1);
    });

    it("скрывает пункт без права управления автоматизациями", () => {
        testState.currentWorkspace.canManageAutomations = false;

        renderLayout();

        expect(
            screen.queryByText("Автоматизации"),
        ).not.toBeInTheDocument();
        expect(testState.getAutomationInboxSummary)
            .not.toHaveBeenCalled();
    });

    it("переходит из меню в общий список", async () => {
        const user = renderLayout();

        await user.click(screen.getByText("Автоматизации"));

        expect(screen.getByTestId("pathname")).toHaveTextContent(
            "/automations",
        );
    });

    it("выделяет пункт на вложенном automation-маршруте", () => {
        renderLayout("/automations/12/preview");

        expect(
            screen.getByText("Автоматизации").closest("li"),
        ).toHaveClass("ant-menu-item-selected");
    });

    it("показывает число решений, ожидающих подтверждения", async () => {
        renderLayout();

        const automationItem = screen
            .getByText("Автоматизации")
            .closest("li");

        expect(automationItem).not.toBeNull();
        expect(
            await within(
                automationItem as HTMLElement,
            ).findByText("4"),
        ).toBeVisible();
        expect(testState.getAutomationInboxSummary)
            .toHaveBeenCalledWith(7);
    });

    it("не показывает badge при отсутствии ожидающих решений", async () => {
        testState.getAutomationInboxSummary.mockResolvedValue({
            pending_approval_count: 0,
        });

        renderLayout();

        await waitFor(() => {
            expect(testState.getAutomationInboxSummary)
                .toHaveBeenCalledWith(7);
        });

        const automationItem = screen
            .getByText("Автоматизации")
            .closest("li");

        expect(automationItem).not.toBeNull();
        expect(
            within(automationItem as HTMLElement)
                .queryByText("0"),
        ).not.toBeInTheDocument();
    });

    it("не запрашивает счётчик без выбранного workspace", async () => {
        testState.currentWorkspace.currentWorkspaceId = null;

        renderLayout();

        await waitFor(() => {
            expect(testState.getAutomationInboxSummary)
                .not.toHaveBeenCalled();
        });
        expect(screen.getByText("Автоматизации"))
            .toBeVisible();
    });
});
