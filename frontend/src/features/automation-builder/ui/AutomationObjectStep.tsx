import type {FC} from "react";
import {
    Alert,
    Avatar,
    Button,
    Card,
    Divider,
    Form,
    Input,
    Select,
    Typography,
} from "antd";

import type {
    AutomationModuleCatalog,
} from "../../../entities/automation";

import styles from "./AutomationObjectStep.module.scss";

const {Title} = Typography;

export interface AutomationAccountOption {
    id: number;
    name: string;
}

interface AutomationObjectStepProps {
    mode: "create" | "edit";
    modules: AutomationModuleCatalog[];
    accounts: AutomationAccountOption[];
    accountLocked: boolean;
    onModuleChange: () => void;
    onManageAccounts: () => void;
}


export const AutomationObjectStep: FC<
    AutomationObjectStepProps
> = ({
         mode,
         modules,
         accounts,
         accountLocked,
         onModuleChange,
         onManageAccounts
     }) => (
    <Card className={styles.card}>
        <div className={styles.content}>
            <Title level={4} style={{margin: 0}}>
                Объект автоматизации
            </Title>

            <Alert
                type="info"
                showIcon
                title={
                    "Проверьте аккаунт: правило будет работать " +
                    "только в выбранном кабинете."
                }
            />

            <div className={styles.fieldRow}>
                <Avatar className={styles.number}>1</Avatar>

                <Form.Item
                    className={styles.field}
                    name="name"
                    label="Название автоматизации"
                    extra="Название видно только вашей команде"
                    rules={[
                        {
                            required: true,
                            whitespace: true,
                            message:
                                "Введите название автоматизации",
                        },
                    ]}
                >
                    <Input
                        placeholder="Контроль эффективности объявлений"
                    />
                </Form.Item>
            </div>

            <Divider className={styles.divider}/>

            <div className={styles.fieldRow}>
                <Avatar className={styles.number}>2</Avatar>

                <Form.Item
                    className={styles.field}
                    name="moduleType"
                    label="Объект"
                    extra={
                        "На следующем шаге вы настроите метрики " +
                        "и условия для выбранного объекта"
                    }
                    rules={[
                        {
                            required: true,
                            message: "Выберите объект",
                        },
                    ]}
                >
                    <Select
                        aria-label="Объект"
                        disabled={mode === "edit"}
                        options={modules.map((module) => ({
                            value: module.module_type,
                            label: module.label,
                        }))}
                        onChange={onModuleChange}
                    />
                </Form.Item>
            </div>

            <Divider className={styles.divider}/>

            <div className={styles.fieldRow}>
                <Avatar className={styles.number}>3</Avatar>

                <div className={styles.accountField}>
                    <Form.Item
                        className={styles.field}
                        name="avitoAccountId"
                        label="Avito-аккаунт"
                        extra={
                            "Правило будет применяться только " +
                            "к объявлениям этого аккаунта"
                        }
                        rules={[
                            {
                                required: true,
                                message:
                                    "Выберите Avito-аккаунт",
                            },
                        ]}
                    >
                        <Select
                            aria-label="Avito-аккаунт"
                            disabled={accountLocked}
                            placeholder="Выберите кабинет"
                            options={accounts.map((account) => ({
                                value: account.id,
                                label: account.name,
                            }))}
                        />
                    </Form.Item>

                    <Button
                        type="link"
                        className={styles.manageAccounts}
                        onClick={onManageAccounts}
                    >
                        Управлять аккаунтами
                    </Button>
                </div>
            </div>
        </div>
    </Card>
);
