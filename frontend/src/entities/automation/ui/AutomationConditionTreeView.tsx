// /Users/artem/Desktop/avito/frontend/src/entities/automation/ui/AutomationConditionTreeView.tsx

import {Fragment} from "react";
import type {FC} from "react";
import {
    Card,
    Space,
    Tag,
    Typography,
} from "antd";

import type {
    AutomationConditionLeaf,
    AutomationConditionOperator,
    AutomationConditionRoot,
    AutomationModuleCatalog,
} from "../model/types";

const {Text} = Typography;

interface AutomationConditionTreeViewProps {
    tree: AutomationConditionRoot;
    module?: AutomationModuleCatalog;
}

interface ConditionLeafViewProps {
    condition: AutomationConditionLeaf;
    module: AutomationModuleCatalog | undefined;
}

const operatorLabels: Record<
    AutomationConditionOperator,
    string
> = {
    and: "И",
    or: "ИЛИ",
};

const OperatorView: FC<{
    operator: AutomationConditionOperator;
}> = ({operator}) => (
    <Tag color="blue">
        {operatorLabels[operator]}
    </Tag>
);

const ConditionLeafView: FC<ConditionLeafViewProps> = ({
                                                           condition,
                                                           module,
                                                       }) => {
    const metricLabel = module?.metrics.find(
        (metric) => metric.code === condition.metric,
    )?.label ?? condition.metric;

    const aggregationLabel = module?.aggregations.find(
        (aggregation) => (
            aggregation.code === condition.aggregation
        ),
    )?.label ?? condition.aggregation;

    const comparatorLabel = module?.comparators.find(
        (comparator) => (
            comparator.code === condition.comparator
        ),
    )?.symbol ?? condition.comparator;

    return (
        <Card size="small">
            <Space size={8} wrap>
                <Text strong>{metricLabel}</Text>
                <Text>{aggregationLabel}</Text>
                <Text>
                    за {condition.window_days} дней
                </Text>
                <Text>{comparatorLabel}</Text>
                <Text strong>{condition.value}</Text>
            </Space>
        </Card>
    );
};

export const AutomationConditionTreeView: FC<
    AutomationConditionTreeViewProps
> = ({
         tree,
         module,
     }) => {
    if (tree.children.length === 0) {
        return (
            <Text type="secondary">
                Условия не настроены
            </Text>
        );
    }

    return (
        <Space
            orientation="vertical"
            size={12}
            style={{width: "100%"}}
        >
            {tree.children.map((group, groupIndex) => (
                <Fragment key={`group-${groupIndex}`}>
                    {groupIndex > 0 ? (
                        <OperatorView
                            operator={
                                tree.operators[groupIndex - 1] ??
                                "and"
                            }
                        />
                    ) : null}

                    <Card
                        size="small"
                        title={`Группа ${groupIndex + 1}`}
                    >
                        <Space
                            orientation="vertical"
                            size={12}
                            style={{width: "100%"}}
                        >
                            {group.children.length === 0 ? (
                                <Text type="secondary">
                                    В группе нет условий
                                </Text>
                            ) : (
                                group.children.map(
                                    (condition, conditionIndex) => (
                                        <Fragment
                                            key={
                                                `condition-${conditionIndex}`
                                            }
                                        >
                                            {conditionIndex > 0 ? (
                                                <OperatorView
                                                    operator={
                                                        group.operators[
                                                        conditionIndex - 1
                                                            ] ?? "and"
                                                    }
                                                />
                                            ) : null}

                                            <ConditionLeafView
                                                condition={condition}
                                                module={module}
                                            />
                                        </Fragment>
                                    ),
                                )
                            )}
                        </Space>
                    </Card>
                </Fragment>
            ))}
        </Space>
    );
};