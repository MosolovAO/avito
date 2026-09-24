import type {
    AutomationConditionLeaf,
    AutomationConditionOperator,
    AutomationConditionRoot,
    AutomationModuleCatalog,
} from "../../../entities/automation";

const operatorLabels: Record<
    AutomationConditionOperator,
    string
> = {
    and: "И",
    or: "ИЛИ",
};

const formatSequence = <T>(
    items: T[],
    operators: AutomationConditionOperator[],
    formatItem: (item: T) => string,
): string => (
    items.reduce(
        (expression, item, index) => {
            const itemExpression = formatItem(item);

            if (index === 0) {
                return itemExpression;
            }

            const operator = operators[index - 1] ?? "and";

            return (
                `${expression} ${operatorLabels[operator]} ` +
                itemExpression
            );
        },
        "",
    )
);

const formatCondition = (
    condition: AutomationConditionLeaf,
    moduleCatalog: AutomationModuleCatalog,
): string => {
    const metricLabel = moduleCatalog.metrics.find(
        (metric) => metric.code === condition.metric,
    )?.label ?? condition.metric;

    const comparatorSymbol =
        moduleCatalog.comparators.find(
            (comparator) => (
                comparator.code === condition.comparator
            ),
        )?.symbol ?? condition.comparator;

    return (
        `${metricLabel} за ${condition.window_days} дней ` +
        `${comparatorSymbol} ${condition.value}`
    );
};

const formatGroup = (
    group: AutomationConditionRoot["children"][number],
    moduleCatalog: AutomationModuleCatalog,
): string => {
    if (group.children.length === 0) {
        return "Добавьте условие";
    }

    return formatSequence(
        group.children,
        group.operators,
        (condition) => (
            formatCondition(condition, moduleCatalog)
        ),
    );
};

export const formatConditionExpression = (
    tree: AutomationConditionRoot,
    moduleCatalog: AutomationModuleCatalog,
): string => {
    if (tree.children.length === 0) {
        return "Добавьте группу условий";
    }

    const hasMultipleGroups = tree.children.length > 1;

    return formatSequence(
        tree.children,
        tree.operators,
        (group) => {
            const expression = formatGroup(
                group,
                moduleCatalog,
            );

            return hasMultipleGroups
                ? `(${expression})`
                : expression;
        },
    );
};