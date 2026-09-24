import type {FC} from "react";
import {
    Alert,
    Avatar,
    Card,
    Col,
    Descriptions,
    Divider,
    Form,
    InputNumber,
    Radio,
    Row,
    Space,
    Typography,
} from "antd";

import styles from "./AutomationSettingsStep.module.scss";

import type {
    AutomationActionDefinition,
    AutomationModuleCatalog,
} from "../../../entities/automation";

const {Text, Title} = Typography;

interface AutomationSettingsStepProps {
    automationName: string;
    accountName: string | null;
    selectedModule: AutomationModuleCatalog | undefined;
    selectedAction: AutomationActionDefinition | undefined;
    actionType: string;
    actionSupported: boolean;
    maxActionsPerRun: number;
    approvalTtlHours: number;
    conditionCount: number;
    groupCount: number;
    computationConfigChanged: boolean;
}

export const AutomationSettingsStep: FC<
    AutomationSettingsStepProps
> = ({
         automationName,
         accountName,
         selectedModule,
         selectedAction,
         actionType,
         actionSupported,
         maxActionsPerRun,
         approvalTtlHours,
         conditionCount,
         groupCount,
         computationConfigChanged,
     }) => (
    <Card className={styles.card}>
        <div className={styles.content}>
            <Title level={4} className={styles.title}>
                Настройки
            </Title>
            <Text type="secondary">
                Выберите действие и ограничения для запуска
                автоматизации.
            </Text>

        <section className={styles.section}>
            <Avatar className={styles.number}>1</Avatar>
            <Space
                className={styles.sectionContent}
                orientation="vertical"
                size={16}
                style={{width: "100%"}}
            >
                <div>
                    <Title level={5} style={{margin: 0}}>
                        Действие после срабатывания
                    </Title>
                    <Text type="secondary">
                        Выберите, что произойдёт с подходящим
                        объявлением.
                    </Text>
                </div>

                <Form.Item
                    className={styles.actionField}
                    name="actionType"
                    extra={
                        "Действие будет применено к объявлениям, " +
                        "которые подходят под условия."
                    }
                    rules={[
                        {
                            required: true,
                            message: "Выберите действие",
                        },
                    ]}
                >
                    <Radio.Group
                        aria-label="Действие"
                        className={styles.actions}
                    >
                        {selectedModule?.actions.map((action) => (
                            <div
                                key={action.code}
                                className={styles.actionOption}
                                data-selected={
                                    actionType === action.code
                                }
                            >
                                <Radio
                                    className={styles.actionRadio}
                                    value={action.code}
                                >
                                    <span className={styles.actionCopy}>
                                        <Text strong>
                                            {action.label}
                                        </Text>
                                        <Text type="secondary">
                                            {action.description}
                                        </Text>
                                    </span>
                                </Radio>
                            </div>
                        ))}
                    </Radio.Group>
                </Form.Item>

                {actionType === "archive" ? (
                    <Alert
                        type="warning"
                        showIcon
                        title="Архивирование необратимо"
                        description={
                            "После архивирования это правило " +
                            "не сможет вернуть объявление."
                        }
                    />
                ) : null}

                {!actionSupported ? (
                    <Alert
                        type="error"
                        showIcon
                        title={
                            "Настройки этого действия пока " +
                            "не поддерживаются данной версией клиента"
                        }
                    />
                ) : null}
            </Space>
        </section>

        <Divider className={styles.divider}/>

        <section className={styles.section}>
            <Avatar className={styles.number}>2</Avatar>
            <Space
                className={styles.sectionContent}
                orientation="vertical"
                size={16}
                style={{width: "100%"}}
            >
                <div>
                    <Title level={5} style={{margin: 0}}>
                        Ограничения запуска
                    </Title>
                    <Text type="secondary">
                        Ограничения помогают контролировать
                        масштаб изменений за один запуск.
                    </Text>
                </div>

                <Row gutter={[16, 0]}>
                    <Col xs={24} md={12}>
                        <Form.Item
                            name="maxActionsPerRun"
                            label="Максимум действий за запуск"
                            extra="Не более 100 действий за один запуск."
                            rules={[
                                {
                                    required: true,
                                    message:
                                        "Укажите лимит действий",
                                },
                                {
                                    type: "number",
                                    min: 1,
                                    max: 100,
                                    message:
                                        "Допустимо от 1 до 100",
                                },
                            ]}
                        >
                            <InputNumber
                                min={1}
                                max={100}
                                precision={0}
                                style={{width: "100%"}}
                            />
                        </Form.Item>
                    </Col>

                    <Col xs={24} md={12}>
                        <Form.Item
                            name="approvalTtlHours"
                            label="Срок подтверждения, часов"
                            extra={
                                "После окончания срока решение " +
                                "нельзя будет подтвердить."
                            }
                            rules={[
                                {
                                    required: true,
                                    message:
                                        "Укажите срок подтверждения",
                                },
                                {
                                    type: "number",
                                    min: 1,
                                    max: 168,
                                    message:
                                        "Допустимо от 1 до 168 часов",
                                },
                            ]}
                        >
                            <InputNumber
                                min={1}
                                max={168}
                                precision={0}
                                style={{width: "100%"}}
                            />
                        </Form.Item>
                    </Col>
                </Row>

                <Alert
                    type="info"
                    showIcon
                    title={
                        "Лимит защищает от массовых изменений " +
                        "за один запуск."
                    }
                />
            </Space>
        </section>

        <Divider className={styles.divider}/>

        {computationConfigChanged ? (
            <Alert
                type="warning"
                showIcon
                title="После сохранения автоматизация будет выключена"
                description={
                    "Изменение вычислительной конфигурации создаёт " +
                    "новую версию. Для повторного включения " +
                    "потребуется успешный preview."
                }
            />
        ) : null}

        <section className={styles.section}>
            <Avatar className={styles.number}>3</Avatar>
            <Space
                className={styles.sectionContent}
                orientation="vertical"
                size={12}
                style={{width: "100%"}}
            >
                <div>
                    <Title level={5} style={{margin: 0}}>
                        Проверьте перед запуском
                    </Title>
                    <Text type="secondary">
                        Preview покажет результат без выполнения
                        действия.
                    </Text>
                </div>

                <Descriptions
                    colon={false}
                    size="small"
                    column={1}
                >
                    <Descriptions.Item label="Название">
                        {automationName}
                    </Descriptions.Item>
                    <Descriptions.Item label="Объект">
                        {selectedModule?.label ?? "—"}
                    </Descriptions.Item>
                    <Descriptions.Item label="Avito-аккаунт">
                        {accountName ?? "—"}
                    </Descriptions.Item>
                    <Descriptions.Item label="Условия">
                        {conditionCount} · групп: {groupCount}
                    </Descriptions.Item>
                    <Descriptions.Item label="Действие">
                        {selectedAction?.label ?? "—"}
                    </Descriptions.Item>
                    <Descriptions.Item label="Лимит действий">
                        {maxActionsPerRun} за запуск
                    </Descriptions.Item>
                    <Descriptions.Item label="Срок подтверждения">
                        {approvalTtlHours} ч.
                    </Descriptions.Item>
                </Descriptions>
            </Space>
        </section>
        </div>
    </Card>
);
