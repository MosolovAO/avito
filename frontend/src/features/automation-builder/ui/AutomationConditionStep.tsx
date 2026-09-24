import {useState} from "react";
import type {FC} from "react";
import {
    Alert,
    Button,
    Typography,
} from "antd";

import type {
    AutomationModuleCatalog,
} from "../../../entities/automation";
import {formatConditionExpression} from
        "../model/conditionExpression";
import type {
    ConditionTreeDraft,
} from "../model/conditionTree";
import {ConditionTreeEditor} from "./ConditionTreeEditor";

import styles from "./AutomationConditionStep.module.scss";

const {Text} = Typography;

interface AutomationConditionStepProps {
    value: ConditionTreeDraft;
    moduleCatalog: AutomationModuleCatalog | undefined;
    conditionError: string | null;
    onChange: (value: ConditionTreeDraft) => void;
}

export const AutomationConditionStep: FC<
    AutomationConditionStepProps
> = ({
         value,
         moduleCatalog,
         conditionError,
         onChange,
     }) => {
    const [detailsVisible, setDetailsVisible] =
        useState(true);

    if (moduleCatalog === undefined) {
        return (
            <Alert
                type="error"
                showIcon
                title="Выбранный объект недоступен"
            />
        );
    }

    return (
        <div className={styles.step}>
            <section className={styles.expression}>
                <Alert
                    className={styles.expressionAlert}
                    type="info"
                    showIcon
                    title={
                        <span className={styles.expressionTitle}>
                            Сработает, когда
                        </span>
                    }
                    description={
                        <Text className={styles.expressionValue}>
                            {formatConditionExpression(
                                value,
                                moduleCatalog,
                            )}
                        </Text>
                    }
                />

                <Button
                    className={styles.detailsToggle}
                    size="small"
                    type="primary"
                    ghost
                    aria-controls="automation-condition-details"
                    aria-expanded={detailsVisible}
                    onClick={() => {
                        setDetailsVisible((visible) => !visible);
                    }}
                >
                    {detailsVisible
                        ? "Скрыть детали"
                        : "Показать детали"}
                </Button>
            </section>

            {detailsVisible ? (
                <div id="automation-condition-details">
                    <ConditionTreeEditor
                        value={value}
                        moduleCatalog={moduleCatalog}
                        onChange={onChange}
                    />
                </div>
            ) : null}

            {conditionError !== null ? (
                <Alert
                    type="error"
                    showIcon
                    title={conditionError}
                />
            ) : null}
        </div>
    );
};
