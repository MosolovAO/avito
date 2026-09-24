import type {
    AutomationConditionGroup,
    AutomationConditionLeaf,
    AutomationConditionLimits,
    AutomationConditionOperator,
    AutomationConditionRoot,
} from "../../../entities/automation";

export interface ConditionLeafDraft
    extends AutomationConditionLeaf {
    uiId: string;
}

export interface ConditionGroupDraft {
    uiId: string;
    type: "group";
    operators: AutomationConditionOperator[];
    children: ConditionLeafDraft[];
}

export interface ConditionTreeDraft {
    uiId: string;
    type: "group";
    operators: AutomationConditionOperator[];
    children: ConditionGroupDraft[];
}

export type ConditionTreeMutationError =
    | "max_conditions"
    | "node_not_found"
    | "operator_not_found"
    | "last_group_removal_forbidden";

export interface ConditionTreeMutationResult {
    tree: ConditionTreeDraft;
    error: ConditionTreeMutationError | null;
}

export type ConditionTreeValidationError =
    | "empty_tree"
    | "empty_group"
    | "invalid_operators_count"
    | "max_conditions";

export interface ConditionTreeValidationResult {
    valid: boolean;
    conditionCount: number;
    errors: ConditionTreeValidationError[];
}

type UiIdFactory = () => string;

const createDefaultUiId = (): string => (
    globalThis.crypto.randomUUID()
);

export const createConditionGroup = (
    createUiId: UiIdFactory = createDefaultUiId,
): ConditionGroupDraft => ({
    uiId: createUiId(),
    type: "group",
    operators: [],
    children: [],
});

export const createConditionTree = (
    createUiId: UiIdFactory = createDefaultUiId,
): ConditionTreeDraft => ({
    uiId: createUiId(),
    type: "group",
    operators: [],
    children: [
        createConditionGroup(createUiId),
    ],
});

const hydrateCondition = (
    condition: AutomationConditionLeaf,
    createUiId: UiIdFactory,
): ConditionLeafDraft => ({
    uiId: createUiId(),
    type: "condition",
    metric: condition.metric,
    aggregation: condition.aggregation,
    window_days: condition.window_days,
    comparator: condition.comparator,
    value: condition.value,
});

const hydrateGroup = (
    group: AutomationConditionGroup,
    createUiId: UiIdFactory,
): ConditionGroupDraft => ({
    uiId: createUiId(),
    type: "group",
    operators: [...group.operators],
    children: group.children.map(
        (condition) => (
            hydrateCondition(condition, createUiId)
        ),
    ),
});

export const hydrateConditionTree = (
    tree: AutomationConditionRoot,
    createUiId: UiIdFactory = createDefaultUiId,
): ConditionTreeDraft => ({
    uiId: createUiId(),
    type: "group",
    operators: [...tree.operators],
    children: tree.children.map(
        (group) => hydrateGroup(group, createUiId),
    ),
});

const serializeCondition = (
    condition: ConditionLeafDraft,
): AutomationConditionLeaf => ({
    type: "condition",
    metric: condition.metric,
    aggregation: condition.aggregation,
    window_days: condition.window_days,
    comparator: condition.comparator,
    value: condition.value,
});

const serializeGroup = (
    group: ConditionGroupDraft,
): AutomationConditionGroup => ({
    type: "group",
    operators: [...group.operators],
    children: group.children.map(serializeCondition),
});

export const serializeConditionTree = (
    tree: ConditionTreeDraft,
): AutomationConditionRoot => ({
    type: "group",
    operators: [...tree.operators],
    children: tree.children.map(serializeGroup),
});

const hasAlignedOperators = (
    childCount: number,
    operators: AutomationConditionOperator[],
): boolean => (
    operators.length === Math.max(0, childCount - 1)
);

const countConditions = (
    tree: ConditionTreeDraft,
): number => (
    tree.children.reduce(
        (count, group) => (
            count + group.children.length
        ),
        0,
    )
);

export const validateConditionTree = (
    tree: ConditionTreeDraft,
    limits: AutomationConditionLimits,
): ConditionTreeValidationResult => {
    const conditionCount = countConditions(tree);
    const errors: ConditionTreeValidationError[] = [];

    if (tree.children.length === 0) {
        errors.push("empty_tree");
    }

    if (
        tree.children.some(
            (group) => group.children.length === 0,
        )
    ) {
        errors.push("empty_group");
    }

    if (
        !hasAlignedOperators(
            tree.children.length,
            tree.operators,
        )
        || tree.children.some(
            (group) => (
                !hasAlignedOperators(
                    group.children.length,
                    group.operators,
                )
            ),
        )
    ) {
        errors.push("invalid_operators_count");
    }

    if (conditionCount > limits.max_conditions) {
        errors.push("max_conditions");
    }

    return {
        valid: errors.length === 0,
        conditionCount,
        errors,
    };
};

const appendDefaultOperator = (
    operators: AutomationConditionOperator[],
    currentChildCount: number,
): AutomationConditionOperator[] => (
    currentChildCount === 0
        ? operators
        : [...operators, "and"]
);

const removeSequenceItem = <T>(
    children: T[],
    operators: AutomationConditionOperator[],
    childIndex: number,
): {
    children: T[];
    operators: AutomationConditionOperator[];
} => {
    const nextChildren = [
        ...children.slice(0, childIndex),
        ...children.slice(childIndex + 1),
    ];

    if (children.length <= 1) {
        return {
            children: nextChildren,
            operators: [],
        };
    }

    const operatorIndex = childIndex === 0
        ? 0
        : childIndex - 1;

    return {
        children: nextChildren,
        operators: operators.filter(
            (_, index) => index !== operatorIndex,
        ),
    };
};

const replaceGroup = (
    tree: ConditionTreeDraft,
    groupIndex: number,
    group: ConditionGroupDraft,
): ConditionTreeDraft => {
    const children = [...tree.children];
    children[groupIndex] = group;

    return {
        ...tree,
        children,
    };
};

export const addGroup = (
    tree: ConditionTreeDraft,
    group: ConditionGroupDraft,
): ConditionTreeMutationResult => ({
    tree: {
        ...tree,
        operators: appendDefaultOperator(
            tree.operators,
            tree.children.length,
        ),
        children: [...tree.children, group],
    },
    error: null,
});

export const addCondition = (
    tree: ConditionTreeDraft,
    groupUiId: string,
    condition: ConditionLeafDraft,
    limits: AutomationConditionLimits,
): ConditionTreeMutationResult => {
    if (
        countConditions(tree)
        >= limits.max_conditions
    ) {
        return {
            tree,
            error: "max_conditions",
        };
    }

    const groupIndex = tree.children.findIndex(
        (group) => group.uiId === groupUiId,
    );

    if (groupIndex === -1) {
        return {
            tree,
            error: "node_not_found",
        };
    }

    const group = tree.children[groupIndex];

    if (group === undefined) {
        return {
            tree,
            error: "node_not_found",
        };
    }

    return {
        tree: replaceGroup(
            tree,
            groupIndex,
            {
                ...group,
                operators: appendDefaultOperator(
                    group.operators,
                    group.children.length,
                ),
                children: [
                    ...group.children,
                    condition,
                ],
            },
        ),
        error: null,
    };
};

export const removeGroup = (
    tree: ConditionTreeDraft,
    groupUiId: string,
): ConditionTreeMutationResult => {
    const groupIndex = tree.children.findIndex(
        (group) => group.uiId === groupUiId,
    );

    if (groupIndex === -1) {
        return {
            tree,
            error: "node_not_found",
        };
    }

    if (tree.children.length === 1) {
        return {
            tree,
            error: "last_group_removal_forbidden",
        };
    }

    const result = removeSequenceItem(
        tree.children,
        tree.operators,
        groupIndex,
    );

    return {
        tree: {
            ...tree,
            children: result.children,
            operators: result.operators,
        },
        error: null,
    };
};

export const removeCondition = (
    tree: ConditionTreeDraft,
    groupUiId: string,
    conditionUiId: string,
): ConditionTreeMutationResult => {
    const groupIndex = tree.children.findIndex(
        (group) => group.uiId === groupUiId,
    );
    const group = tree.children[groupIndex];

    if (groupIndex === -1 || group === undefined) {
        return {
            tree,
            error: "node_not_found",
        };
    }

    const conditionIndex = group.children.findIndex(
        (condition) => (
            condition.uiId === conditionUiId
        ),
    );

    if (conditionIndex === -1) {
        return {
            tree,
            error: "node_not_found",
        };
    }

    const result = removeSequenceItem(
        group.children,
        group.operators,
        conditionIndex,
    );

    return {
        tree: replaceGroup(
            tree,
            groupIndex,
            {
                ...group,
                children: result.children,
                operators: result.operators,
            },
        ),
        error: null,
    };
};

const replaceOperator = (
    operators: AutomationConditionOperator[],
    operatorIndex: number,
    operator: AutomationConditionOperator,
): AutomationConditionOperator[] | null => {
    if (
        !Number.isInteger(operatorIndex)
        || operatorIndex < 0
        || operatorIndex >= operators.length
    ) {
        return null;
    }

    const nextOperators = [...operators];
    nextOperators[operatorIndex] = operator;

    return nextOperators;
};

export const updateOperator = (
    tree: ConditionTreeDraft,
    containerUiId: string,
    operatorIndex: number,
    operator: AutomationConditionOperator,
): ConditionTreeMutationResult => {
    if (containerUiId === tree.uiId) {
        const operators = replaceOperator(
            tree.operators,
            operatorIndex,
            operator,
        );

        return operators === null
            ? {
                tree,
                error: "operator_not_found",
            }
            : {
                tree: {
                    ...tree,
                    operators,
                },
                error: null,
            };
    }

    const groupIndex = tree.children.findIndex(
        (group) => group.uiId === containerUiId,
    );
    const group = tree.children[groupIndex];

    if (groupIndex === -1 || group === undefined) {
        return {
            tree,
            error: "node_not_found",
        };
    }

    const operators = replaceOperator(
        group.operators,
        operatorIndex,
        operator,
    );

    if (operators === null) {
        return {
            tree,
            error: "operator_not_found",
        };
    }

    return {
        tree: replaceGroup(
            tree,
            groupIndex,
            {
                ...group,
                operators,
            },
        ),
        error: null,
    };
};

export const updateCondition = (
    tree: ConditionTreeDraft,
    groupUiId: string,
    conditionUiId: string,
    replacement: ConditionLeafDraft,
): ConditionTreeMutationResult => {
    const groupIndex = tree.children.findIndex(
        (group) => group.uiId === groupUiId,
    );
    const group = tree.children[groupIndex];

    if (groupIndex === -1 || group === undefined) {
        return {
            tree,
            error: "node_not_found",
        };
    }

    const conditionIndex = group.children.findIndex(
        (condition) => (
            condition.uiId === conditionUiId
        ),
    );

    if (conditionIndex === -1) {
        return {
            tree,
            error: "node_not_found",
        };
    }

    const children = [...group.children];
    children[conditionIndex] = {
        ...replacement,
        uiId: conditionUiId,
    };

    return {
        tree: replaceGroup(
            tree,
            groupIndex,
            {
                ...group,
                children,
            },
        ),
        error: null,
    };
};