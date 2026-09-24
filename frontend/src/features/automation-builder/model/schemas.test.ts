import {describe, expect, it} from "vitest";

import type {
    AutomationCatalogResponse,
} from "../../../entities/automation";
import {
    buildAutomationPayload,
    createAutomationWizardSchema,
} from "./schemas";
import type {AutomationWizardValues} from "./schemas";

const catalog: AutomationCatalogResponse = {
    modules: [
        {
            module_type: "avito_listings",
            label: "Объявления Avito",
            metrics: [
                {
                    code: "views",
                    label: "Просмотры",
                    description: "Количество просмотров",
                    value_type: "integer",
                    allowed_aggregations: ["sum"],
                },
            ],
            aggregations: [
                {
                    code: "sum",
                    label: "Сумма",
                },
            ],
            comparators: [
                {
                    code: "lt",
                    symbol: "<",
                    label: "Меньше",
                },
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
            ],
            condition_limits: {
                min_window_days: 1,
                max_window_days: 365,
                max_conditions: 50,
            },
        },
    ],
};

const validValues = (): AutomationWizardValues => ({
    name: "Мало просмотров",
    moduleType: "avito_listings",
    avitoAccountId: 17,
    conditionTree: {
        uiId: "root",
        type: "group",
        operators: [],
        children: [
            {
                uiId: "group-1",
                type: "group",
                operators: [],
                children: [{
                    uiId: "condition-1",
                    type: "condition",
                    metric: "views",
                    aggregation: "sum",
                    window_days: 10,
                    comparator: "lt",
                    value: 10,
                }],
            },
        ],
    },
    actionType: "pause",
    maxActionsPerRun: 10,
    approvalTtlHours: 24,
});

describe("createAutomationWizardSchema", () => {
    const schema = createAutomationWizardSchema(catalog);

    it("принимает корректное двухуровневое дерево", () => {
        const result = schema.safeParse(validValues());

        expect(result.success).toBe(true);
    });

    it.each([
        ["name", {name: "   "}],
        ["avitoAccountId", {avitoAccountId: null}],
        [
            "conditionTree",
            {
                conditionTree: {
                    uiId: "root",
                    type: "group",
                    operators: [],
                    children: [],
                },
            },
        ],
        ["actionType", {actionType: ""}],
    ] satisfies Array<[
        keyof AutomationWizardValues,
        Partial<AutomationWizardValues>,
    ]>)(
        "отклоняет невалидное обязательное поле %s",
        (field, changes) => {
            const result = schema.safeParse({
                ...validValues(),
                ...changes,
            });

            expect(result.success).toBe(false);

            if (result.success) {
                throw new Error(
                    "Схема приняла невалидные данные",
                );
            }

            expect(
                result.error.issues.some(
                    (issue) => issue.path[0] === field,
                ),
            ).toBe(true);
        },
    );

    it.each([0, 101])(
        "отклоняет лимит действий %s вне диапазона 1–100",
        (maxActionsPerRun) => {
            const result = schema.safeParse({
                ...validValues(),
                maxActionsPerRun,
            });

            expect(result.success).toBe(false);
        },
    );

    it.each([0, 169])(
        "отклоняет TTL %s часов вне диапазона 1–168",
        (approvalTtlHours) => {
            const result = schema.safeParse({
                ...validValues(),
                approvalTtlHours,
            });

            expect(result.success).toBe(false);
        },
    );

    it("отклоняет пустую пользовательскую группу", () => {
        const result = schema.safeParse({
            ...validValues(),
            conditionTree: {
                uiId: "root",
                type: "group",
                operators: [],
                children: [{
                    uiId: "group-1",
                    type: "group",
                    operators: [],
                    children: [],
                }],
            },
        });

        expect(result.success).toBe(false);
    });

    it("отклоняет вложенную пользовательскую группу", () => {
        const values = validValues();
        const result = schema.safeParse({
            ...values,
            conditionTree: {
                ...values.conditionTree,
                children: [{
                    uiId: "group-1",
                    type: "group",
                    operators: [],
                    children: [{
                        uiId: "group-2",
                        type: "group",
                        operators: [],
                        children: [],
                    }],
                }],
            },
        });

        expect(result.success).toBe(false);
    });

    it("отклоняет несогласованный массив операторов", () => {
        const values = validValues();
        const result = schema.safeParse({
            ...values,
            conditionTree: {
                ...values.conditionTree,
                operators: ["or"],
            },
        });

        expect(result.success).toBe(false);
    });
});

describe("buildAutomationPayload", () => {
    it("преобразует часы в минуты и удаляет временные UI ID", () => {
        const payload = buildAutomationPayload(validValues());

        expect(payload.config.approval_ttl_minutes).toBe(1440);
        expect(payload).toEqual({
            name: "Мало просмотров",
            module_type: "avito_listings",
            config: {
                avito_account_id: 17,
                condition_tree: {
                    type: "group",
                    operators: [],
                    children: [
                        {
                            type: "group",
                            operators: [],
                            children: [{
                                type: "condition",
                                metric: "views",
                                aggregation: "sum",
                                window_days: 10,
                                comparator: "lt",
                                value: 10,
                            }],
                        },
                    ],
                },
                action: {
                    type: "pause",
                    config: {},
                },
                max_actions_per_run: 10,
                approval_ttl_minutes: 1440,
            },
        });

        expect(
            JSON.stringify(payload),
        ).not.toContain("uiId");
    });
});
