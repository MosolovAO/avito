import {useState} from "react";
import {
    render,
    screen,
    within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {
    describe,
    expect,
    it,
    vi,
} from "vitest";

import type {
    AutomationConditionLimits,
    AutomationModuleCatalog,
} from "../../../entities/automation";
import type {
    ConditionGroupDraft,
    ConditionLeafDraft,
    ConditionTreeDraft,
} from "../model/conditionTree";
import {ConditionTreeEditor} from "./ConditionTreeEditor";

const conditionLimits: AutomationConditionLimits = {
    min_window_days: 1,
    max_window_days: 365,
    max_conditions: 50,
};

const createCatalog = (
    limits: AutomationConditionLimits = conditionLimits,
): AutomationModuleCatalog => ({
    module_type: "avito_listings",
    label: "Объявления Avito",
    metrics: [
        {
            code: "views",
            label: "Просмотры",
            description: "Количество просмотров объявления",
            value_type: "integer",
            allowed_aggregations: ["sum"],
        },
        {
            code: "contacts",
            label: "Контакты",
            description: "Количество контактов по объявлению",
            value_type: "integer",
            allowed_aggregations: ["sum"],
        },
    ],
    aggregations: [{
        code: "sum",
        label: "Сумма",
    }],
    comparators: [
        {
            code: "lt",
            symbol: "<",
            label: "Меньше",
        },
        {
            code: "gte",
            symbol: "≥",
            label: "Больше или равно",
        },
    ],
    actions: [],
    condition_limits: limits,
});

const createCondition = (
    uiId: string,
    overrides: Partial<
        Omit<ConditionLeafDraft, "uiId" | "type">
    > = {},
): ConditionLeafDraft => ({
    uiId,
    type: "condition",
    metric: "views",
    aggregation: "sum",
    window_days: 10,
    comparator: "lt",
    value: 10,
    ...overrides,
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

interface RenderEditorOptions {
    initialValue?: ConditionTreeDraft;
    catalog?: AutomationModuleCatalog;
}

const renderEditor = ({
    initialValue = createTree([
        createGroup("group-1"),
    ]),
    catalog = createCatalog(),
}: RenderEditorOptions = {}) => {
    const onChange = vi.fn<
        (value: ConditionTreeDraft) => void
    >();

    const EditorHarness = () => {
        const [value, setValue] = useState(initialValue);

        const handleChange = (nextValue: ConditionTreeDraft) => {
            onChange(nextValue);
            setValue(nextValue);
        };

        return (
            <ConditionTreeEditor
                value={value}
                moduleCatalog={catalog}
                onChange={handleChange}
            />
        );
    };

    render(<EditorHarness/>);

    return {
        onChange,
        user: userEvent.setup(),
    };
};

describe("ConditionTreeEditor", () => {
    it("показывает пользовательскую группу без корневой карточки", () => {
        renderEditor();

        expect(
            screen.getByRole("group", {name: "Группа 1"}),
        ).toBeInTheDocument();
        expect(
            screen.queryByText("Корневая группа"),
        ).not.toBeInTheDocument();
        expect(
            screen.getByText("Условий: 0 из 50"),
        ).toBeInTheDocument();
    });

    it("добавляет условие в выбранную группу", async () => {
        const {onChange, user} = renderEditor();

        await user.click(
            screen.getByRole(
                "button",
                {name: "Добавить условие"},
            ),
        );

        const nextTree = onChange.mock.lastCall?.[0];

        expect(nextTree?.children[0]?.children).toHaveLength(1);
        expect(nextTree?.children[0]?.children[0]).toMatchObject({
            type: "condition",
            metric: "views",
            aggregation: "sum",
            comparator: "lt",
        });
    });

    it("оставляет синюю границу только в шапке группы", () => {
        renderEditor({
            initialValue: createTree([
                createGroup("group-1", [
                    createCondition("condition-1"),
                ]),
            ]),
        });

        const group = screen.getByRole(
            "group",
            {name: "Группа 1"},
        );
        const card = group.querySelector(".ant-card");
        const header = group.querySelector(".ant-card-head");

        expect(card).not.toBeNull();
        expect(header).not.toBeNull();
        expect(getComputedStyle(card as Element).borderLeft).not.toBe(
            "4px solid rgb(22, 119, 255)",
        );
        expect(getComputedStyle(header as Element).borderLeft).toBe(
            "4px solid rgb(22, 119, 255)",
        );
    });

    it("добавляет параллельную группу только кнопкой редактора", async () => {
        const {onChange, user} = renderEditor();

        await user.click(
            screen.getByRole(
                "button",
                {name: "Добавить группу"},
            ),
        );

        expect(onChange.mock.lastCall?.[0].children).toHaveLength(2);
        expect(onChange.mock.lastCall?.[0].operators).toEqual([
            "and",
        ]);
        expect(
            screen.getByRole("group", {name: "Группа 2"}),
        ).toBeInTheDocument();
        expect(
            screen.getAllByRole(
                "button",
                {name: "Добавить группу"},
            ),
        ).toHaveLength(1);
    });

    it("изменяет оператор между группами", async () => {
        const {onChange, user} = renderEditor({
            initialValue: createTree(
                [
                    createGroup("group-1"),
                    createGroup("group-2"),
                ],
                ["and"],
            ),
        });

        await user.click(
            screen.getByTitle("ИЛИ"),
        );

        expect(onChange.mock.lastCall?.[0].operators).toEqual([
            "or",
        ]);
    });

    it("объясняет связь между соседними группами", () => {
        renderEditor({
            initialValue: createTree(
                [
                    createGroup("group-1"),
                    createGroup("group-2"),
                ],
                ["or"],
            ),
        });

        expect(
            screen.getByText("Связь между группами"),
        ).toBeInTheDocument();
        expect(
            screen.getByText(
                "Достаточно, чтобы выполнилась хотя бы " +
                "одна группа.",
            ),
        ).toBeInTheDocument();
    });

    it("изменяет оператор между условиями внутри группы", async () => {
        const {onChange, user} = renderEditor({
            initialValue: createTree([
                createGroup(
                    "group-1",
                    [
                        createCondition("condition-1"),
                        createCondition("condition-2"),
                    ],
                    ["and"],
                ),
            ]),
        });

        const group = screen.getByRole(
            "group",
            {name: "Группа 1"},
        );

        expect(
            within(group).getByLabelText(
                "Оператор между условиями 1 и 2",
            ).className,
        ).toContain("conditionOperator");

        await user.click(
            within(group).getByTitle("ИЛИ"),
        );

        expect(
            onChange.mock.lastCall?.[0].children[0]?.operators,
        ).toEqual(["or"]);
    });

    it("объясняет логику условий в заголовке группы", () => {
        renderEditor({
            initialValue: createTree([
                createGroup(
                    "group-1",
                    [
                        createCondition("condition-1"),
                        createCondition("condition-2"),
                    ],
                    ["and"],
                ),
            ]),
        });

        expect(
            screen.getByText(
                "Все условия в группе должны " +
                "выполняться (логическое И).",
            ),
        ).toBeInTheDocument();
    });

    it("удаляет условие из группы и оставляет группу", async () => {
        const {onChange, user} = renderEditor({
            initialValue: createTree([
                createGroup("group-1", [
                    createCondition("condition-1"),
                ]),
            ]),
        });

        await user.click(
            screen.getByRole(
                "button",
                {name: "Удалить условие"},
            ),
        );

        expect(onChange.mock.lastCall?.[0].children).toHaveLength(1);
        expect(
            onChange.mock.lastCall?.[0].children[0]?.children,
        ).toEqual([]);
        expect(
            screen.getByRole("group", {name: "Группа 1"}),
        ).toBeInTheDocument();
    });

    it("блокирует добавление условия после достижения лимита", () => {
        renderEditor({
            initialValue: createTree([
                createGroup("group-1", [
                    createCondition("condition-1"),
                ]),
            ]),
            catalog: createCatalog({
                ...conditionLimits,
                max_conditions: 1,
            }),
        });

        expect(
            screen.getByRole(
                "button",
                {name: "Добавить условие"},
            ),
        ).toBeDisabled();
        expect(
            screen.getByText("Условий: 1 из 1"),
        ).toBeInTheDocument();
    });

    it("показывает неизвестные metric и comparator", () => {
        renderEditor({
            initialValue: createTree([
                createGroup("group-1", [
                    createCondition("condition-1", {
                        metric: "legacy_metric",
                        comparator: "legacy_comparator",
                    }),
                ]),
            ]),
        });

        expect(
            screen.getByText("Недоступно: legacy_metric"),
        ).toBeInTheDocument();
        expect(
            screen.getByText("Недоступно: legacy_comparator"),
        ).toBeInTheDocument();
    });
});
