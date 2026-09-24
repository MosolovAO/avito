import {describe, expect, it} from "vitest";

import type {
    AutomationConditionLimits,
    AutomationConditionRoot,
} from "../../../entities/automation";
import {
    addCondition,
    addGroup,
    createConditionTree,
    hydrateConditionTree,
    removeCondition,
    removeGroup,
    serializeConditionTree,
    updateCondition,
    updateOperator,
    validateConditionTree,
} from "./conditionTree";
import type {
    ConditionGroupDraft,
    ConditionLeafDraft,
    ConditionTreeDraft,
} from "./conditionTree";

const limits: AutomationConditionLimits = {
    min_window_days: 1,
    max_window_days: 365,
    max_conditions: 50,
};

const createCondition = (
    uiId: string,
    value = 10,
): ConditionLeafDraft => ({
    uiId,
    type: "condition",
    metric: "views",
    aggregation: "sum",
    window_days: 10,
    comparator: "lt",
    value,
});

const createGroup = (
    uiId: string,
    children: ConditionLeafDraft[] = [],
    operators: Array<"and" | "or"> = [],
): ConditionGroupDraft => ({
    uiId,
    type: "group",
    operators,
    children,
});

const createTree = (
    groups: ConditionGroupDraft[],
    operators: Array<"and" | "or"> = [],
): ConditionTreeDraft => ({
    uiId: "root",
    type: "group",
    operators,
    children: groups,
});

const createIdFactory = (
    ...ids: string[]
): (() => string) => {
    let index = 0;

    return () => {
        const id = ids[index];
        index += 1;

        if (id === undefined) {
            throw new Error("Для теста не подготовлен следующий uiId");
        }

        return id;
    };
};

describe("создание и сериализация дерева условий", () => {
    it("создаёт корень с одной пустой пользовательской группой", () => {
        expect(
            createConditionTree(
                createIdFactory("root", "group-1"),
            ),
        ).toEqual({
            uiId: "root",
            type: "group",
            operators: [],
            children: [{
                uiId: "group-1",
                type: "group",
                operators: [],
                children: [],
            }],
        });
    });

    it("восстанавливает два уровня и удаляет uiId при сериализации", () => {
        const source: AutomationConditionRoot = {
            type: "group",
            operators: ["or"],
            children: [
                {
                    type: "group",
                    operators: ["and"],
                    children: [
                        {
                            type: "condition",
                            metric: "contacts",
                            aggregation: "sum",
                            window_days: 10,
                            comparator: "lt",
                            value: 5,
                        },
                        {
                            type: "condition",
                            metric: "views",
                            aggregation: "sum",
                            window_days: 30,
                            comparator: "gte",
                            value: 100,
                        },
                    ],
                },
                {
                    type: "group",
                    operators: [],
                    children: [{
                        type: "condition",
                        metric: "views",
                        aggregation: "sum",
                        window_days: 7,
                        comparator: "eq",
                        value: 0,
                    }],
                },
            ],
        };

        const draft = hydrateConditionTree(
            source,
            createIdFactory(
                "root",
                "group-1",
                "condition-1",
                "condition-2",
                "group-2",
                "condition-3",
            ),
        );

        expect(draft.children[0]?.uiId).toBe("group-1");
        expect(draft.children[0]?.children[1]?.uiId).toBe(
            "condition-2",
        );
        expect(serializeConditionTree(draft)).toEqual(source);
        expect(JSON.stringify(serializeConditionTree(draft))).not.toContain(
            "uiId",
        );
    });
});

describe("валидация дерева условий", () => {
    it("отклоняет корень без пользовательских групп", () => {
        expect(validateConditionTree(createTree([]), limits)).toEqual({
            valid: false,
            conditionCount: 0,
            errors: ["empty_tree"],
        });
    });

    it("отклоняет пустую пользовательскую группу", () => {
        expect(
            validateConditionTree(
                createTree([createGroup("group-1")]),
                limits,
            ),
        ).toEqual({
            valid: false,
            conditionCount: 0,
            errors: ["empty_group"],
        });
    });

    it("отклоняет несогласованные операторы корня и группы", () => {
        const tree = createTree([
            createGroup(
                "group-1",
                [
                    createCondition("condition-1"),
                    createCondition("condition-2"),
                ],
            ),
            createGroup(
                "group-2",
                [createCondition("condition-3")],
            ),
        ]);

        expect(validateConditionTree(tree, limits)).toEqual({
            valid: false,
            conditionCount: 3,
            errors: ["invalid_operators_count"],
        });
    });

    it("отклоняет пятьдесят первое условие", () => {
        const tree = createTree([
            createGroup(
                "group-1",
                Array.from(
                    {length: 51},
                    (_, index) => createCondition(
                        `condition-${index + 1}`,
                    ),
                ),
                Array.from({length: 50}, () => "and"),
            ),
        ]);

        expect(validateConditionTree(tree, limits)).toEqual({
            valid: false,
            conditionCount: 51,
            errors: ["max_conditions"],
        });
    });
});

describe("добавление элементов", () => {
    it("добавляет группу только в корень и создаёт соединение И", () => {
        const firstGroup = createGroup("group-1");
        const secondGroup = createGroup("group-2");
        const tree = createTree([firstGroup]);

        const result = addGroup(tree, secondGroup);

        expect(result).toEqual({
            tree: createTree(
                [firstGroup, secondGroup],
                ["and"],
            ),
            error: null,
        });
        expect(tree.operators).toEqual([]);
    });

    it("добавляет условие в выбранную группу и создаёт соединение И", () => {
        const firstCondition = createCondition("condition-1");
        const secondCondition = createCondition("condition-2");
        const tree = createTree([
            createGroup("group-1", [firstCondition]),
        ]);

        const result = addCondition(
            tree,
            "group-1",
            secondCondition,
            limits,
        );

        expect(result.error).toBeNull();
        expect(result.tree.children[0]).toEqual(
            createGroup(
                "group-1",
                [firstCondition, secondCondition],
                ["and"],
            ),
        );
        expect(tree.children[0]?.operators).toEqual([]);
    });

    it("не добавляет пятьдесят первое условие", () => {
        const conditions = Array.from(
            {length: 50},
            (_, index) => createCondition(
                `condition-${index + 1}`,
            ),
        );
        const tree = createTree([
            createGroup(
                "group-1",
                conditions,
                Array.from({length: 49}, () => "and"),
            ),
        ]);

        expect(
            addCondition(
                tree,
                "group-1",
                createCondition("condition-51"),
                limits,
            ),
        ).toEqual({
            tree,
            error: "max_conditions",
        });
    });
});

describe("удаление элементов и выравнивание операторов", () => {
    it("при удалении первого условия удаляет следующий оператор", () => {
        const secondCondition = createCondition("condition-2");
        const thirdCondition = createCondition("condition-3");
        const tree = createTree([
            createGroup(
                "group-1",
                [
                    createCondition("condition-1"),
                    secondCondition,
                    thirdCondition,
                ],
                ["or", "and"],
            ),
        ]);

        const result = removeCondition(
            tree,
            "group-1",
            "condition-1",
        );

        expect(result.error).toBeNull();
        expect(result.tree.children[0]).toEqual(
            createGroup(
                "group-1",
                [secondCondition, thirdCondition],
                ["and"],
            ),
        );
    });

    it("при удалении остальных условий удаляет предыдущий оператор", () => {
        const firstCondition = createCondition("condition-1");
        const thirdCondition = createCondition("condition-3");
        const tree = createTree([
            createGroup(
                "group-1",
                [
                    firstCondition,
                    createCondition("condition-2"),
                    thirdCondition,
                ],
                ["or", "and"],
            ),
        ]);

        const result = removeCondition(
            tree,
            "group-1",
            "condition-2",
        );

        expect(result.error).toBeNull();
        expect(result.tree.children[0]).toEqual(
            createGroup(
                "group-1",
                [firstCondition, thirdCondition],
                ["and"],
            ),
        );
    });

    it("не удаляет последнюю группу", () => {
        const tree = createTree([createGroup("group-1")]);

        expect(removeGroup(tree, "group-1")).toEqual({
            tree,
            error: "last_group_removal_forbidden",
        });
    });

    it("выравнивает операторы после удаления первой группы", () => {
        const secondGroup = createGroup("group-2");
        const thirdGroup = createGroup("group-3");
        const tree = createTree(
            [
                createGroup("group-1"),
                secondGroup,
                thirdGroup,
            ],
            ["or", "and"],
        );

        const result = removeGroup(tree, "group-1");

        expect(result).toEqual({
            tree: createTree(
                [secondGroup, thirdGroup],
                ["and"],
            ),
            error: null,
        });
    });
});

describe("изменение условий и операторов", () => {
    it("изменяет оператор корня по индексу", () => {
        const tree = createTree(
            [
                createGroup("group-1"),
                createGroup("group-2"),
            ],
            ["and"],
        );

        const result = updateOperator(
            tree,
            "root",
            0,
            "or",
        );

        expect(result.error).toBeNull();
        expect(result.tree.operators).toEqual(["or"]);
        expect(tree.operators).toEqual(["and"]);
    });

    it("изменяет оператор выбранной группы по индексу", () => {
        const tree = createTree([
            createGroup(
                "group-1",
                [
                    createCondition("condition-1"),
                    createCondition("condition-2"),
                ],
                ["and"],
            ),
        ]);

        const result = updateOperator(
            tree,
            "group-1",
            0,
            "or",
        );

        expect(result.error).toBeNull();
        expect(result.tree.children[0]?.operators).toEqual(["or"]);
    });

    it("заменяет выбранное условие", () => {
        const tree = createTree([
            createGroup(
                "group-1",
                [createCondition("condition-1")],
            ),
        ]);

        const result = updateCondition(
            tree,
            "group-1",
            "condition-1",
            createCondition("condition-1", 25),
        );

        expect(result.error).toBeNull();
        expect(
            result.tree.children[0]?.children[0]?.value,
        ).toBe(25);
    });

    it("возвращает ошибку для неизвестного узла или оператора", () => {
        const tree = createTree([createGroup("group-1")]);

        expect(removeGroup(tree, "missing")).toEqual({
            tree,
            error: "node_not_found",
        });
        expect(
            updateOperator(tree, "root", 0, "or"),
        ).toEqual({
            tree,
            error: "operator_not_found",
        });
    });
});
