import {
    useMemo,
    useState,
} from "react";
import type {FC} from "react";
import {
    Button,
    Form,
    Steps,
    Typography,
} from "antd";

import type {
    Automation,
    AutomationActionDefinition,
    AutomationCatalogResponse,
    AutomationModuleCatalog,
} from "../../../entities/automation";
import {
    createConditionTree,
    hydrateConditionTree,
    serializeConditionTree,
    validateConditionTree,
} from "../model/conditionTree";
import type {
    ConditionTreeDraft,
} from "../model/conditionTree";
import {
    buildAutomationPayload,
    createAutomationWizardSchema,
} from "../model/schemas";
import type {
    AutomationWizardSubmission,
    AutomationWizardValues,
} from "../model/schemas";
import {AutomationConditionStep} from "./AutomationConditionStep";
import {AutomationSettingsStep} from "./AutomationSettingsStep";
import {AutomationObjectStep} from "./AutomationObjectStep";
import type {AutomationAccountOption} from "./AutomationObjectStep";

import styles from "./AutomationWizard.module.scss";

const {Text, Title} = Typography;

export interface AutomationWizardProps {
    mode: "create" | "edit";
    catalog: AutomationCatalogResponse;
    accounts: AutomationAccountOption[];
    initialAutomation?: Automation;
    accountLocked: boolean;
    submitting: boolean;
    onCancel: () => void;
    onManageAccounts: () => void;
    onSubmit: (
        payload: AutomationWizardSubmission,
    ) => Promise<void>;
}

type ScalarWizardValues = Omit<
    AutomationWizardValues,
    "conditionTree"
>;

const stepItems = [
    {title: "Объект"},
    {title: "Условия"},
    {title: "Настройки"},
];

const isSupportedAction = (
    action: AutomationActionDefinition | undefined,
): boolean => (
    action !== undefined &&
    action.config_schema.type === "object" &&
    action.config_schema.additionalProperties === false &&
    Object.keys(
        action.config_schema.properties,
    ).length === 0
);

const stepCopy = [
    {
        title: "Настройка автоматизации",
        description:
            "Сначала выберите, к чему будет применяться правило.",
    },
    {
        title: "Условия срабатывания",
        description:
            "Настройте условия, при которых будет запускаться автоматизация.",
    },
    {
        title: "Настройка автоматизации",
        description:
            "Выберите действие и ограничения его выполнения.",
    },
];


const getInitialValues = (
    catalog: AutomationCatalogResponse,
    initialAutomation?: Automation,
): {
    fields: ScalarWizardValues;
    conditionTree: ConditionTreeDraft;
} => {
    if (initialAutomation !== undefined) {
        return {
            fields: {
                name: initialAutomation.name,
                moduleType:
                initialAutomation.module_type,
                avitoAccountId:
                initialAutomation
                    .config
                    .avito_account_id,
                actionType:
                initialAutomation
                    .config
                    .action
                    .type,
                maxActionsPerRun:
                initialAutomation
                    .config
                    .max_actions_per_run,
                approvalTtlHours: Math.ceil(
                    initialAutomation
                        .config
                        .approval_ttl_minutes / 60,
                ),
            },
            conditionTree: hydrateConditionTree(
                initialAutomation.config.condition_tree,
            ),
        };
    }

    return {
        fields: {
            name: "",
            moduleType:
                catalog.modules[0]?.module_type ?? "",
            avitoAccountId: null,
            actionType: "",
            maxActionsPerRun: 10,
            approvalTtlHours: 24,
        },
        conditionTree: createConditionTree(),
    };
};

export const AutomationWizard: FC<
    AutomationWizardProps
> = ({
         mode,
         catalog,
         accounts,
         initialAutomation,
         accountLocked,
         submitting,
         onCancel,
         onManageAccounts,
         onSubmit,
     }) => {
    const [form] =
        Form.useForm<ScalarWizardValues>();

    const initialValues = useMemo(
        () => getInitialValues(
            catalog,
            initialAutomation,
        ),
        [catalog, initialAutomation],
    );

    const [currentStep, setCurrentStep] =
        useState(0);
    const [conditionTree, setConditionTree] =
        useState(initialValues.conditionTree);
    const [conditionError, setConditionError] =
        useState<string | null>(null);

    const automationName = Form.useWatch(
        "name",
        {form, preserve: true},
    ) ?? initialValues.fields.name;

    const moduleType =
        Form.useWatch("moduleType", form) ??
        initialValues.fields.moduleType;

    const actionType =
        Form.useWatch(
            "actionType",
            {
                form,
                preserve: true,
            },
        ) ?? initialValues.fields.actionType;

    const avitoAccountId = Form.useWatch(
        "avitoAccountId",
        {form, preserve: true},
    );

    const maxActionsPerRun =
        Form.useWatch("maxActionsPerRun", form) ??
        initialValues.fields.maxActionsPerRun;

    const approvalTtlHours =
        Form.useWatch("approvalTtlHours", form) ??
        initialValues.fields.approvalTtlHours;

    const currentAvitoAccountId =
        avitoAccountId === undefined
            ? initialValues.fields.avitoAccountId
            : avitoAccountId;

    const selectedAccount = accounts.find(
        (account) => account.id === currentAvitoAccountId,
    );

    const selectedModule:
        AutomationModuleCatalog | undefined =
        catalog.modules.find(
            (item) => (
                item.module_type === moduleType
            ),
        );

    const selectedAction =
        selectedModule?.actions.find(
            (action) => action.code === actionType,
        );

    const actionSupported = (
        actionType === "" ||
        isSupportedAction(selectedAction)
    );

    const computationConfigChanged = (
        initialAutomation?.state === "enabled" &&
        (
            moduleType !== initialAutomation.module_type ||
            currentAvitoAccountId !==
            initialAutomation.config.avito_account_id ||
            actionType !==
            initialAutomation.config.action.type ||
            maxActionsPerRun !==
            initialAutomation.config.max_actions_per_run ||
            approvalTtlHours * 60 !==
            initialAutomation.config.approval_ttl_minutes ||
            JSON.stringify(
                serializeConditionTree(conditionTree),
            ) !== JSON.stringify(
                initialAutomation.config.condition_tree,
            )
        )
    );

    const validateConditionStep = (): boolean => {
        if (selectedModule === undefined) {
            setConditionError(
                "Выбранный объект недоступен",
            );
            return false;
        }

        const validation = validateConditionTree(
            conditionTree,
            selectedModule.condition_limits,
        );

        if (validation.errors.includes("empty_tree")) {
            setConditionError(
                "Добавьте хотя бы одну группу условий",
            );
            return false;
        }

        if (validation.errors.includes("empty_group")) {
            setConditionError(
                "Добавьте условие в каждую группу",
            );
            return false;
        }

        if (
            validation.errors.includes(
                "invalid_operators_count",
            )
        ) {
            setConditionError(
                "Нарушена структура операторов условий",
            );
            return false;
        }

        if (
            validation.errors.includes(
                "max_conditions",
            )
        ) {
            setConditionError(
                "Превышено максимальное количество условий",
            );
            return false;
        }

        setConditionError(null);
        return true;
    };

    const handleNext = async () => {
        if (currentStep === 0) {
            try {
                await form.validateFields([
                    "name",
                    "moduleType",
                    "avitoAccountId",
                ]);
            } catch {
                return;
            }
        }

        if (
            currentStep === 1 &&
            !validateConditionStep()
        ) {
            return;
        }

        setCurrentStep((step) => step + 1);
    };

    const handleSubmit = async () => {
        try {
            await form.validateFields();
        } catch {
            return;
        }

        const fields = form.getFieldsValue(true);

        const values: AutomationWizardValues = {
            ...fields,
            conditionTree,
        };

        const result =
            createAutomationWizardSchema(
                catalog,
            ).safeParse(values);

        if (!result.success) {
            const treeIssue =
                result.error.issues.find(
                    (issue) => (
                        issue.path[0] ===
                        "conditionTree"
                    ),
                );

            setConditionError(
                treeIssue?.message ?? null,
            );

            const fieldErrors =
                result.error.issues
                    .filter(
                        (issue) => (
                            issue.path[0] !==
                            "conditionTree"
                        ),
                    )
                    .map((issue) => ({
                        name: issue.path[0] as keyof ScalarWizardValues,
                        errors: [issue.message],
                    }));

            form.setFields(fieldErrors);
            return;
        }

        await onSubmit(
            buildAutomationPayload(result.data),
        );
    };

    // /Users/artem/Desktop/avito/frontend/src/features/automation-builder/ui/AutomationWizard.tsx

    const handleModuleChange = () => {
        form.setFieldValue("actionType", "");
        setConditionTree(createConditionTree());
    };

    const renderConditionStep = () => (
        <AutomationConditionStep
            value={conditionTree}
            moduleCatalog={selectedModule}
            conditionError={conditionError}
            onChange={(nextTree) => {
                setConditionTree(nextTree);
                setConditionError(null);
            }}
        />
    );

    const renderObjectStep = () => (
        <AutomationObjectStep
            mode={mode}
            modules={catalog.modules}
            accounts={accounts}
            accountLocked={accountLocked}
            onModuleChange={handleModuleChange}
            onManageAccounts={onManageAccounts}
        />
    );

    const renderSettingsStep = () => (
        <AutomationSettingsStep
            automationName={automationName}
            accountName={selectedAccount?.name ?? null}
            selectedModule={selectedModule}
            selectedAction={selectedAction}
            actionType={actionType}
            actionSupported={actionSupported}
            maxActionsPerRun={maxActionsPerRun}
            approvalTtlHours={approvalTtlHours}
            conditionCount={conditionTree.children.reduce(
                (total, group) => total + group.children.length,
                0,
            )}
            groupCount={conditionTree.children.length}
            computationConfigChanged={computationConfigChanged}
        />
    );

    const stepContent = [
        renderObjectStep(),
        renderConditionStep(),
        renderSettingsStep(),
    ];

    return (
        <Form
            form={form}
            layout="vertical"
            initialValues={initialValues.fields}
            disabled={submitting}
            className={styles.form}
        >
            <div className={styles.shell}>
                <header className={styles.pageHeader}>
                    <Title level={2} className={styles.pageTitle}>
                        {stepCopy[currentStep]?.title}
                    </Title>
                    <Text
                        type="secondary"
                        className={styles.pageDescription}
                    >
                        {stepCopy[currentStep]?.description}
                    </Text>
                </header>

                <nav aria-label="Шаги создания автоматизации">
                    <Steps
                        current={currentStep}
                        items={stepItems}
                        size="small"
                        titlePlacement="horizontal"
                        responsive={false}
                        className={styles.steps}
                    />
                </nav>

                <div className={styles.content}>
                    {stepContent[currentStep]}
                </div>

                <footer className={styles.footer}>
                    <Button
                        size="large"
                        onClick={() => {
                            if (currentStep === 0) {
                                onCancel();
                                return;
                            }

                            setCurrentStep((step) => step - 1);
                        }}
                    >
                        Назад
                    </Button>

                    {currentStep < stepItems.length - 1 ? (
                        <Button
                            type="primary"
                            size="large"
                            className={styles.primaryAction}
                            disabled={submitting}
                            onClick={() => {
                                void handleNext();
                            }}
                        >
                            {currentStep === 0
                                ? "К условиям"
                                : "К настройкам"}
                        </Button>
                    ) : (
                        <Button
                            type="primary"
                            size="large"
                            className={styles.primaryAction}
                            loading={submitting}
                            disabled={
                                submitting || !actionSupported
                            }
                            onClick={() => {
                                void handleSubmit();
                            }}
                        >
                            {mode === "create"
                                ? "Создать автоматизацию"
                                : "Сохранить изменения"}
                        </Button>
                    )}
                </footer>
            </div>
        </Form>
    );
};
