import {
    render,
    screen,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {
    describe,
    expect,
    it,
    vi,
} from "vitest";

import type {
    AutomationConditionRoot,
    AutomationDecision,
    AutomationDecisionStatus,
} from "../../../entities/automation";
import {DecisionDrawer} from "./DecisionDrawer";

const conditionSnapshot: AutomationConditionRoot = {
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
                    metric: "contacts",
                    aggregation: "sum",
                    window_days: 7,
                    comparator: "lte",
                    value: 2,
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
                    value: 5,
                },
            ],
        },
    ],
};

const buildDecision = (
    status: AutomationDecisionStatus = "pending_approval",
): AutomationDecision => ({
    id: 501,
    run_id: 205,
    automation_id: 41,
    avito_account_id: 17,
    listing_id: 301,
    listing: {
        avito_id: "123456789",
        title: "Тестовое объявление",
    },
    status,
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
        {
            metric: "contacts",
            aggregation: "sum",
            window_days: 7,
            date_from: "2026-08-27",
            date_to: "2026-09-02",
            value: 1,
        },
    ],
    action: {
        type: "pause",
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
    required_export_revision: null,
    effect_attempts: 0,
    next_effect_retry_at: null,
    error: null,
    created_at: "2026-09-02T12:00:00Z",
    updated_at: "2026-09-02T12:00:00Z",
});

interface RenderDrawerOptions {
    decision?: AutomationDecision | null;
    submitting?: boolean;
}

const renderDrawer = ({
    decision = buildDecision(),
    submitting = false,
}: RenderDrawerOptions = {}) => {
    const onClose = vi.fn();
    const onApprove = vi.fn().mockResolvedValue(undefined);
    const onReject = vi.fn().mockResolvedValue(undefined);

    render(
        <DecisionDrawer
            open
            decision={decision}
            conditionSnapshot={conditionSnapshot}
            onClose={onClose}
            onApprove={onApprove}
            onReject={onReject}
            submitting={submitting}
        />,
    );

    return {
        onClose,
        onApprove,
        onReject,
    };
};

describe("DecisionDrawer", () => {
    it("показывает immutable snapshot объявления и результата проверки", () => {
        renderDrawer();

        expect(screen.getByText("Решение #501")).toBeVisible();
        expect(screen.getByText("Тестовое объявление"))
            .toBeVisible();
        expect(screen.getByText("123456789")).toBeVisible();
        expect(screen.getByText("301")).toBeVisible();
        expect(screen.getByText("Ожидает подтверждения"))
            .toBeVisible();
        expect(screen.getByText(/24\.08\.2026.*12:00/))
            .toBeVisible();
        expect(screen.getByText(/03\.09\.2026.*15:00/))
            .toBeVisible();

        expect(screen.getAllByText("views").length)
            .toBeGreaterThan(0);
        expect(screen.getAllByText("contacts").length)
            .toBeGreaterThan(0);
        expect(screen.getByText("7")).toBeVisible();
        expect(screen.getByText("1")).toBeVisible();
        expect(screen.getByText("24.08.2026 — 02.09.2026"))
            .toBeVisible();
        expect(screen.getByText("27.08.2026 — 02.09.2026"))
            .toBeVisible();

        expect(screen.getByText("Группа 1"))
            .toBeVisible();
        expect(screen.getByText("И"))
            .toBeVisible();
        expect(screen.getByText("ИЛИ"))
            .toBeVisible();
        expect(screen.getByText("Группа 2"))
            .toBeVisible();
        expect(screen.getByText("pause")).toBeVisible();
    });

    it("показывает безопасную ошибку решения", () => {
        renderDrawer({
            decision: {
                ...buildDecision("failed"),
                error: {
                    code: "export_failed",
                    message: "Не удалось сформировать CSV.",
                },
            },
        });

        expect(screen.getByText("Ошибка выполнения"))
            .toBeVisible();
        expect(screen.getByText("export_failed")).toBeVisible();
        expect(screen.getByText("Не удалось сформировать CSV."))
            .toBeVisible();
    });

    it("передаёт pending решение в команды подтверждения и отклонения", async () => {
        const user = userEvent.setup();
        const decision = buildDecision();
        const {onApprove, onReject} = renderDrawer({decision});

        await user.click(screen.getByRole("button", {
            name: "Подтвердить действие",
        }));
        await user.click(screen.getByRole("button", {
            name: "Отклонить",
        }));

        expect(onApprove).toHaveBeenCalledOnce();
        expect(onApprove).toHaveBeenCalledWith(decision);
        expect(onReject).toHaveBeenCalledOnce();
        expect(onReject).toHaveBeenCalledWith(decision);
    });

    it.each<AutomationDecisionStatus>([
        "applying",
        "effect_pending",
        "completed",
        "rejected",
        "expired",
        "stale",
        "superseded",
        "failed",
    ])("не показывает команды для terminal или уже обрабатываемого статуса %s", (status) => {
        renderDrawer({decision: buildDecision(status)});

        expect(screen.queryByRole("button", {
            name: "Подтвердить действие",
        })).not.toBeInTheDocument();
        expect(screen.queryByRole("button", {
            name: "Отклонить",
        })).not.toBeInTheDocument();
    });

    it("блокирует обе команды во время отправки", () => {
        renderDrawer({submitting: true});

        expect(screen.getByRole("button", {
            name: /Подтвердить действие/,
        })).toBeDisabled();
        expect(screen.getByRole("button", {
            name: "Отклонить",
        })).toBeDisabled();
    });

    it("не показывает содержимое без выбранного решения", () => {
        renderDrawer({decision: null});

        expect(screen.queryByText(/Решение #/))
            .not.toBeInTheDocument();
        expect(screen.queryByRole("button", {
            name: "Подтвердить действие",
        })).not.toBeInTheDocument();
    });
});
