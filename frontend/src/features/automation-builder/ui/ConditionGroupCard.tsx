import type {FC} from "react";
import {
    Avatar,
    Button,
    Card,
    InputNumber,
    Segmented,
    Select,
    Typography,
} from "antd";

import {
    DeleteOutlined,
    PlusOutlined,
} from "@ant-design/icons";

import type {
    AutomationConditionOperator,
    AutomationModuleCatalog,
} from "../../../entities/automation";
import {
    addCondition,
    removeCondition,
    removeGroup,
    updateCondition,
    updateOperator,
} from "../model/conditionTree";
import type {
    ConditionGroupDraft,
    ConditionLeafDraft,
    ConditionTreeDraft,
    ConditionTreeMutationResult,
} from "../model/conditionTree";

import styles from "./ConditionGroupCard.module.scss";

interface ConditionGroupCardProps {
    tree: ConditionTreeDraft;
    group: ConditionGroupDraft;
    groupIndex: number;
    totalGroupCount: number;
    conditionCount: number;
    moduleCatalog: AutomationModuleCatalog;
    onChange: (value: ConditionTreeDraft) => void;
}

interface ConditionCardProps {
    tree: ConditionTreeDraft;
    groupUiId: string;
    condition: ConditionLeafDraft;
    conditionIndex: number;
    moduleCatalog: AutomationModuleCatalog;
    onChange: (value: ConditionTreeDraft) => void;
}

interface SelectOption {
    value: string;
    label: string;
}

type ConditionChanges = Partial<
    Omit<ConditionLeafDraft, "uiId" | "type">
>;

const includeUnavailableOption = (
    options: SelectOption[],
    currentValue: string,
): SelectOption[] => {
    if (
        options.some(
            (option) => option.value === currentValue,
        )
    ) {
        return options;
    }

    return [
        ...options,
        {
            value: currentValue,
            label: `Недоступно: ${currentValue}`,
        },
    ];
};

const createConditionDraft = (
    moduleCatalog: AutomationModuleCatalog,
): ConditionLeafDraft | null => {
    const metric = moduleCatalog.metrics[0];
    const comparator = moduleCatalog.comparators[0];
    const aggregation =
        metric?.allowed_aggregations[0] ??
        moduleCatalog.aggregations[0]?.code;

    if (
        metric === undefined ||
        comparator === undefined ||
        aggregation === undefined
    ) {
        return null;
    }

    const {min_window_days, max_window_days} =
        moduleCatalog.condition_limits;

    return {
        uiId: globalThis.crypto.randomUUID(),
        type: "condition",
        metric: metric.code,
        aggregation,
        window_days: Math.min(
            Math.max(10, min_window_days),
            max_window_days,
        ),
        comparator: comparator.code,
        value: 0,
    };
};

const applyMutation = (
    result: ConditionTreeMutationResult,
    onChange: (value: ConditionTreeDraft) => void,
) => {
    if (result.error === null) {
        onChange(result.tree);
    }
};

const conditionOperatorOptions = [
    {
        value: "and",
        label: "И",
    },
    {
        value: "or",
        label: "ИЛИ",
    },
];

const getGroupDescription = (
    group: ConditionGroupDraft,
): string => {
    if (group.children.length < 2) {
        return "Добавьте ещё одно условие, чтобы настроить логику.";
    }

    if (group.operators.every((operator) => operator === "and")) {
        return (
            "Все условия в группе должны " +
            "выполняться (логическое И)."
        );
    }

    if (group.operators.every((operator) => operator === "or")) {
        return (
            "Достаточно выполнения одного условия " +
            "(логическое ИЛИ)."
        );
    }

    return "Условия связаны последовательной логикой.";
};

const isLogicalOperator = (
    value: string | number,
): value is AutomationConditionOperator => (
    value === "and" || value === "or"
);

const ConditionCard: FC<ConditionCardProps> = ({
    tree,
    groupUiId,
    condition,
    conditionIndex,
    moduleCatalog,
    onChange,
}) => {
    const metricOptions = includeUnavailableOption(
        moduleCatalog.metrics.map((metric) => ({
            value: metric.code,
            label: metric.label,
        })),
        condition.metric,
    );

    const selectedMetric = moduleCatalog.metrics.find(
        (metric) => metric.code === condition.metric,
    );

    const allowedAggregations =
        selectedMetric?.allowed_aggregations ?? [];

    const aggregationOptions =
        includeUnavailableOption(
            moduleCatalog.aggregations
                .filter((aggregation) => (
                    allowedAggregations.includes(
                        aggregation.code,
                    )
                ))
                .map((aggregation) => ({
                    value: aggregation.code,
                    label: aggregation.label,
                })),
            condition.aggregation,
        );

    const comparatorOptions = includeUnavailableOption(
        moduleCatalog.comparators.map((comparator) => ({
            value: comparator.code,
            label: [
                comparator.symbol,
                comparator.label,
            ].filter(Boolean).join(" "),
        })),
        condition.comparator,
    );

    const changeCondition = (
        changes: ConditionChanges,
    ) => {
        applyMutation(
            updateCondition(
                tree,
                groupUiId,
                condition.uiId,
                {
                    ...condition,
                    ...changes,
                },
            ),
            onChange,
        );
    };

    const handleMetricChange = (
        metricCode: string,
    ) => {
        const metric = moduleCatalog.metrics.find(
            (item) => item.code === metricCode,
        );

        const aggregation =
            metric?.allowed_aggregations.includes(
                condition.aggregation,
            )
                ? condition.aggregation
                : (
                    metric?.allowed_aggregations[0] ??
                    condition.aggregation
                );

        changeCondition({
            metric: metricCode,
            aggregation,
        });
    };

    return (
        <div className={styles.conditionRow}>
            <Avatar className={styles.conditionNumber}>
                {conditionIndex + 1}
            </Avatar>

            <div className={styles.conditionFields}>
                <label className={styles.field}>
                    <span className={styles.fieldLabel}>
                        Метрика
                    </span>
                    <Select
                        aria-label="Метрика"
                        className={styles.control}
                        value={condition.metric}
                        options={metricOptions}
                        onChange={handleMetricChange}
                    />
                </label>

                <label className={styles.field}>
                    <span className={styles.fieldLabel}>
                        Агрегация
                    </span>
                    <Select
                        aria-label="Агрегация"
                        className={styles.control}
                        value={condition.aggregation}
                        options={aggregationOptions}
                        disabled={
                            aggregationOptions.length <= 1
                        }
                        onChange={(aggregation) => {
                            changeCondition({aggregation});
                        }}
                    />
                </label>

                <label className={styles.field}>
                    <span className={styles.fieldLabel}>
                        Период, дней
                    </span>
                    <InputNumber
                        aria-label="Период, дней"
                        className={styles.control}
                        value={condition.window_days}
                        min={
                            moduleCatalog
                                .condition_limits
                                .min_window_days
                        }
                        max={
                            moduleCatalog
                                .condition_limits
                                .max_window_days
                        }
                        precision={0}
                        onChange={(windowDays) => {
                            if (
                                typeof windowDays ===
                                "number"
                            ) {
                                changeCondition({
                                    window_days: windowDays,
                                });
                            }
                        }}
                    />
                </label>

                <label className={styles.field}>
                    <span className={styles.fieldLabel}>
                        Сравнение
                    </span>
                    <Select
                        aria-label="Сравнение"
                        className={styles.control}
                        value={condition.comparator}
                        options={comparatorOptions}
                        onChange={(comparator) => {
                            changeCondition({comparator});
                        }}
                    />
                </label>

                <label className={styles.field}>
                    <span className={styles.fieldLabel}>
                        Значение
                    </span>
                    <InputNumber
                        aria-label="Значение"
                        className={styles.control}
                        value={condition.value}
                        precision={0}
                        onChange={(value) => {
                            if (typeof value === "number") {
                                changeCondition({value});
                            }
                        }}
                    />
                </label>
            </div>

            <Button
                className={styles.deleteCondition}
                danger
                icon={<DeleteOutlined/>}
                aria-label="Удалить условие"
                onClick={() => {
                    applyMutation(
                        removeCondition(
                            tree,
                            groupUiId,
                            condition.uiId,
                        ),
                        onChange,
                    );
                }}
            >
                Удалить
            </Button>
        </div>
    );
};

export const ConditionGroupCard: FC<
    ConditionGroupCardProps
> = ({
    tree,
    group,
    groupIndex,
    totalGroupCount,
    conditionCount,
    moduleCatalog,
    onChange,
}) => {
    const limits = moduleCatalog.condition_limits;

    const canCreateCondition = (
        moduleCatalog.metrics.length > 0 &&
        moduleCatalog.comparators.length > 0 &&
        (
            moduleCatalog.metrics[0]
                ?.allowed_aggregations[0] !== undefined ||
            moduleCatalog.aggregations[0] !== undefined
        )
    );

    const conditionLimitReached = (
        conditionCount >= limits.max_conditions
    );


    const handleAddCondition = () => {
        const condition = createConditionDraft(moduleCatalog);

        if (condition === null) {
            return;
        }

        applyMutation(
            addCondition(
                tree,
                group.uiId,
                condition,
                limits,
            ),
            onChange,
        );
    };

    const handleOperatorChange = (
        operatorIndex: number,
        nextValue: string | number,
    ) => {
        if (!isLogicalOperator(nextValue)) {
            return;
        }

        applyMutation(
            updateOperator(
                tree,
                group.uiId,
                operatorIndex,
                nextValue,
            ),
            onChange,
        );
    };

    return (
        <section
            className={styles.group}
            role="group"
            aria-label={`Группа ${groupIndex + 1}`}
        >
            <Card
                className={styles.card}
                styles={{
                    header: {
                        padding: "14px 16px",
                        borderLeft: "4px solid #1677ff",
                    },
                    body: {
                        padding: "16px",
                    },
                }}
                title={
                    <div className={styles.groupHeading}>
                        <Avatar className={styles.groupNumber}>
                            {groupIndex + 1}
                        </Avatar>

                        <div>
                            <Typography.Title
                                level={5}
                                className={styles.groupTitle}
                            >
                                Группа {groupIndex + 1}
                            </Typography.Title>
                            <Typography.Text
                                type="secondary"
                                className={styles.groupDescription}
                            >
                                {getGroupDescription(group)}
                            </Typography.Text>
                        </div>
                    </div>
                }
                extra={
                    <Button
                        danger
                        size="small"
                        icon={<DeleteOutlined/>}
                        aria-label="Удалить группу"
                        disabled={totalGroupCount === 1}
                        onClick={() => {
                            applyMutation(
                                removeGroup(
                                    tree,
                                    group.uiId,
                                ),
                                onChange,
                            );
                        }}
                    >
                        Удалить группу
                    </Button>
                }
            >
                <div className={styles.groupBody}>
                    {group.children.map((condition, index) => (
                        <div key={condition.uiId}>
                            {index > 0 ? (
                                <div
                                    className={
                                        styles.conditionConnector
                                    }
                                >
                                    <span
                                        className={styles.connectorLine}
                                        aria-hidden="true"
                                    />
                                    <Segmented
                                        className={
                                            styles.conditionOperator
                                        }
                                        aria-label={
                                            `Оператор между условиями ${
                                                index
                                            } и ${index + 1}`
                                        }
                                        value={
                                            group.operators[index - 1] ??
                                            "and"
                                        }
                                        options={conditionOperatorOptions}
                                        onChange={(nextValue) => {
                                            handleOperatorChange(
                                                index - 1,
                                                nextValue,
                                            );
                                        }}
                                    />
                                    <span
                                        className={styles.connectorLine}
                                        aria-hidden="true"
                                    />
                                </div>
                            ) : null}

                            <ConditionCard
                                tree={tree}
                                groupUiId={group.uiId}
                                condition={condition}
                                conditionIndex={index}
                                moduleCatalog={moduleCatalog}
                                onChange={onChange}
                            />
                        </div>
                    ))}

                    <Button
                        className={styles.addCondition}
                        type="primary"
                        ghost
                        icon={<PlusOutlined/>}
                        aria-label="Добавить условие"
                        disabled={
                            !canCreateCondition ||
                            conditionLimitReached
                        }
                        onClick={handleAddCondition}
                    >
                        Добавить условие
                    </Button>
                </div>
            </Card>
        </section>
    );
};
