import {Fragment} from "react";
import type {FC} from "react";
import {
    Button,
    Segmented,
    Typography,
} from "antd";

import type {
    AutomationConditionOperator,
    AutomationModuleCatalog,
} from "../../../entities/automation";
import {
    addGroup,
    createConditionGroup,
    updateOperator,
    validateConditionTree,
} from "../model/conditionTree";
import type {
    ConditionTreeDraft,
} from "../model/conditionTree";
import {ConditionGroupCard} from "./ConditionGroupCard";
import {PlusOutlined} from "@ant-design/icons";
import styles from "./ConditionTreeEditor.module.scss";

const {Text} = Typography;

export interface ConditionTreeEditorProps {
    value: ConditionTreeDraft;
    moduleCatalog: AutomationModuleCatalog;
    onChange: (value: ConditionTreeDraft) => void;
}

const operatorOptions = [
    {
        value: "and",
        label: "И",
    },
    {
        value: "or",
        label: "ИЛИ",
    },
];

const getRootOperatorDescription = (
    operator: AutomationConditionOperator,
): string => (
    operator === "or"
        ? "Достаточно, чтобы выполнилась хотя бы одна группа."
        : "Должны выполниться обе соседние группы."
);

const isLogicalOperator = (
    value: string | number,
): value is AutomationConditionOperator => (
    value === "and" || value === "or"
);

export const ConditionTreeEditor: FC<
    ConditionTreeEditorProps
> = ({
         value,
         moduleCatalog,
         onChange,
     }) => {
    const validation = validateConditionTree(
        value,
        moduleCatalog.condition_limits,
    );

    const handleAddGroup = () => {
        const result = addGroup(
            value,
            createConditionGroup(),
        );

        if (result.error === null) {
            onChange(result.tree);
        }
    };

    const handleRootOperatorChange = (
        operatorIndex: number,
        nextValue: string | number,
    ) => {
        if (!isLogicalOperator(nextValue)) {
            return;
        }

        const result = updateOperator(
            value,
            value.uiId,
            operatorIndex,
            nextValue,
        );

        if (result.error === null) {
            onChange(result.tree);
        }
    };

    return (
        <div className={styles.editor}>
            <div className={styles.meta}>
                <Text className={styles.conditionCount}>
                    Условий: {validation.conditionCount} из{" "}
                    {moduleCatalog.condition_limits.max_conditions}
                </Text>

                <span
                    className={styles.metaSeparator}
                    aria-hidden="true"
                />

                <Text type="secondary">
                    Группа — скобки в логическом выражении.
                </Text>
            </div>

            <div className={styles.groups}>
                {value.children.map((group, index) => {
                    const operator = value.operators[index - 1] ??
                        "and";

                    return (
                        <Fragment key={group.uiId}>
                            {index > 0 ? (
                                <section
                                    className={styles.groupConnector}
                                    aria-label={
                                        `Связь между группами ${index} ` +
                                        `и ${index + 1}`
                                    }
                                >
                                    <Text
                                        strong
                                        className={
                                            styles.connectorTitle
                                        }
                                    >
                                        Связь между группами
                                    </Text>

                                    <div
                                        className={
                                            styles.connectorControl
                                        }
                                    >
                                        <span
                                            className={styles.connectorLine}
                                            aria-hidden="true"
                                        />
                                        <Segmented
                                            className={styles.groupOperator}
                                            aria-label={
                                                `Оператор между группами ` +
                                                `${index} и ${index + 1}`
                                            }
                                            value={operator}
                                            options={operatorOptions}
                                            onChange={(nextValue) => {
                                                handleRootOperatorChange(
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

                                    <Text
                                        type="secondary"
                                        className={
                                            styles.connectorDescription
                                        }
                                    >
                                        {getRootOperatorDescription(
                                            operator,
                                        )}
                                    </Text>
                                </section>
                            ) : null}

                            <ConditionGroupCard
                                tree={value}
                                group={group}
                                groupIndex={index}
                                totalGroupCount={
                                    value.children.length
                                }
                                conditionCount={
                                    validation.conditionCount
                                }
                                moduleCatalog={moduleCatalog}
                                onChange={onChange}
                            />
                        </Fragment>
                    );
                })}
            </div>

            <Button
                className={styles.addGroup}
                type="primary"
                ghost
                icon={<PlusOutlined/>}
                aria-label="Добавить группу"
                onClick={handleAddGroup}
            >
                Добавить группу
            </Button>
        </div>
    );
};
