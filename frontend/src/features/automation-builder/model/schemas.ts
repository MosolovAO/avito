import {z} from "zod";

import type {
    AutomationCatalogResponse,
    CreateAutomationRequest,
} from "../../../entities/automation";
import {
    serializeConditionTree,
    validateConditionTree,
} from "./conditionTree";
import type {
    ConditionGroupDraft,
    ConditionLeafDraft,
    ConditionTreeDraft,
} from "./conditionTree";

export interface AutomationWizardValues {
    name: string;
    moduleType: string;
    avitoAccountId: number | null;
    conditionTree: ConditionTreeDraft;
    actionType: string;
    maxActionsPerRun: number;
    approvalTtlHours: number;
}

export type AutomationWizardSubmission =
    CreateAutomationRequest;

const logicalOperatorSchema = z.enum([
    "and",
    "or",
]);

const conditionLeafSchema: z.ZodType<
    ConditionLeafDraft
> = z.object({
    uiId: z.string().min(1),
    type: z.literal("condition"),
    metric: z.string().min(1),
    aggregation: z.string().min(1),
    window_days: z.number().int(),
    comparator: z.string().min(1),
    value: z.number().int(),
}).strict();

const conditionGroupSchema: z.ZodType<
    ConditionGroupDraft
> = z.object({
    uiId: z.string().min(1),
    type: z.literal("group"),
    operators: z.array(logicalOperatorSchema),
    children: z.array(conditionLeafSchema),
}).strict();

const conditionTreeSchema: z.ZodType<
    ConditionTreeDraft
> = z.object({
    uiId: z.string().min(1),
    type: z.literal("group"),
    operators: z.array(logicalOperatorSchema),
    children: z.array(conditionGroupSchema),
}).strict();

export const createAutomationWizardSchema = (
    catalog: AutomationCatalogResponse,
) => (
    z.object({
        name: z
            .string()
            .trim()
            .min(
                1,
                "Введите название автоматизации",
            ),
        moduleType: z
            .string()
            .min(1, "Выберите объект"),
        avitoAccountId: z
            .number()
            .int()
            .positive()
            .nullable()
            .refine(
                (value) => value !== null,
                {
                    message:
                        "Выберите Avito-аккаунт",
                },
            ),
        conditionTree: conditionTreeSchema,
        actionType: z
            .string()
            .min(1, "Выберите действие"),
        maxActionsPerRun: z
            .number()
            .int()
            .min(
                1,
                "Минимум одно действие за запуск",
            )
            .max(
                100,
                "Максимум 100 действий за запуск",
            ),
        approvalTtlHours: z
            .number()
            .int()
            .min(
                1,
                "Минимальный срок — 1 час",
            )
            .max(
                168,
                "Максимальный срок — 168 часов",
            ),
    }).superRefine((values, context) => {
        const moduleCatalog = catalog.modules.find(
            (item) => (
                item.module_type === values.moduleType
            ),
        );

        if (moduleCatalog === undefined) {
            context.addIssue({
                code: "custom",
                path: ["moduleType"],
                message: "Выбранный объект недоступен",
            });
            return;
        }

        const actionExists =
            moduleCatalog.actions.some(
                (action) => (
                    action.code === values.actionType
                ),
            );

        if (!actionExists) {
            context.addIssue({
                code: "custom",
                path: ["actionType"],
                message: "Выбранное действие недоступно",
            });
        }

                const treeValidation = validateConditionTree(
            values.conditionTree,
            moduleCatalog.condition_limits,
        );

        if (
            treeValidation.errors.includes(
                "empty_tree",
            )
        ) {
            context.addIssue({
                code: "custom",
                path: ["conditionTree"],
                message:
                    "Добавьте хотя бы одну группу условий",
            });
        }

        if (
            treeValidation.errors.includes(
                "empty_group",
            )
        ) {
            context.addIssue({
                code: "custom",
                path: ["conditionTree"],
                message:
                    "Добавьте условие в каждую группу",
            });
        }

        if (
            treeValidation.errors.includes(
                "invalid_operators_count",
            )
        ) {
            context.addIssue({
                code: "custom",
                path: ["conditionTree"],
                message:
                    "Нарушена структура операторов условий",
            });
        }

        if (
            treeValidation.errors.includes(
                "max_conditions",
            )
        ) {
            context.addIssue({
                code: "custom",
                path: ["conditionTree"],
                message:
                    "Превышено максимальное количество условий",
            });
        }
    })
);

export const buildAutomationPayload = (
    values: AutomationWizardValues,
): AutomationWizardSubmission => {
    if (values.avitoAccountId === null) {
        throw new Error(
            "Нельзя собрать payload без Avito-аккаунта",
        );
    }

    return {
        name: values.name.trim(),
        module_type: values.moduleType,
        config: {
            avito_account_id:
            values.avitoAccountId,
            condition_tree:
                serializeConditionTree(
                    values.conditionTree,
                ),
            action: {
                type: values.actionType,
                config: {},
            },
            max_actions_per_run:
            values.maxActionsPerRun,
            approval_ttl_minutes:
                values.approvalTtlHours * 60,
        },
    };
};