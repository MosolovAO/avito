// src/pages/ads/EditAdPublicationPage.tsx
import React, {useEffect} from "react";
import {
    Alert,
    Button,
    Form,
    Input,
    Select,
    Space,
    Spin,
    Tag,
    Typography,
} from "antd";
import {useNavigate, useParams} from "react-router-dom";
import type {
    AdPublicationStatus,
    JsonObject,
} from "../../entities/avito/types";
import {
    useAdPublicationQuery,
    useUpdateAdPublicationMutation,
} from "../../features/avito";
import {useCurrentWorkspace} from "../../features/workspace/model/useCurrentWorkspace";

const {Title, Text, Paragraph} = Typography;

interface PublicationFormValues {
    address: string;
    status: AdPublicationStatus;
    overrides: string;
}

const formatJson = (value: unknown): string => {
    if (!value) {
        return "{}";
    }

    return JSON.stringify(value, null, 2);
};

const parseJsonObject = (value: string): JsonObject => {
    try {
        const parsed = JSON.parse(value || "{}");

        if (
            parsed === null ||
            Array.isArray(parsed) ||
            typeof parsed !== "object"
        ) {
            throw new Error("overrides должен быть JSON-объектом");
        }

        return parsed as JsonObject;
    } catch (error) {
        if (error instanceof Error) {
            throw new Error(error.message);
        }

        throw new Error("Некорректный JSON");
    }
};

export const EditAdPublicationPage: React.FC = () => {
    const navigate = useNavigate();
    const params = useParams();
    const [form] = Form.useForm<PublicationFormValues>();

    const {currentWorkspace, canManageAvitoAccounts} = useCurrentWorkspace();

    const publicationId = params.id ? Number(params.id) : null;
    const publicationQuery = useAdPublicationQuery(publicationId);
    const updatePublicationMutation = useUpdateAdPublicationMutation();

    useEffect(() => {
        if (!publicationQuery.data) {
            return;
        }

        form.setFieldsValue({
            address: publicationQuery.data.address,
            status: publicationQuery.data.status,
            overrides: formatJson(publicationQuery.data.overrides),
        });
    }, [publicationQuery.data, form]);

    const handleSubmit = async () => {
        const values = await form.validateFields();

        try {
            await updatePublicationMutation.mutateAsync({
                publicationId: Number(publicationId),
                data: {
                    address: values.address.trim(),
                    status: values.status,
                    overrides: parseJsonObject(values.overrides),
                },
            });

            navigate("/ads/publications");
        } catch (error) {
            if (error instanceof Error) {
                form.setFields([
                    {
                        name: "overrides",
                        errors: [error.message],
                    },
                ]);
            }
        }
    };

    if (!currentWorkspace) {
        return (
            <Alert
                type="warning"
                message="Кабинет не выбран"
                description="Выберите кабинет, чтобы редактировать публикацию."
                showIcon
            />
        );
    }

    if (!canManageAvitoAccounts) {
        return (
            <Alert
                type="warning"
                message="Недостаточно прав"
                description="Редактирование публикаций доступно только пользователям с правом управления Avito."
                showIcon
            />
        );
    }

    if (!publicationId || Number.isNaN(publicationId)) {
        return (
            <Alert
                type="error"
                message="Некорректный ID публикации"
                showIcon
            />
        );
    }

    if (publicationQuery.isLoading) {
        return <Spin/>;
    }

    if (publicationQuery.isError || !publicationQuery.data) {
        return (
            <Alert
                type="error"
                message="Публикация не найдена"
                description="Проверьте, что публикация существует и принадлежит текущему кабинету."
                showIcon
            />
        );
    }

    const publication = publicationQuery.data;
    const overrideKeys = Object.keys(publication.overrides ?? {});

    return (
        <Space direction="vertical" size={16} style={{width: "100%"}}>
            <Space direction="vertical" size={0}>
                <Title level={2} style={{margin: 0}}>
                    Редактировать публикацию
                </Title>
                <Text type="secondary">
                    Точечные изменения применяются только к одной публикации и не меняют общий креатив.
                </Text>
            </Space>

            <Alert
                type="info"
                showIcon
                message="Наследование и переопределения"
                description="Поля в overrides имеют приоритет над общими значениями креатива. Если удалить поле из overrides, публикация снова будет использовать значение из общего креатива."
            />

            <Space wrap>
                <Tag>Креатив: {publication.creative_title}</Tag>
                <Tag>Проект: {publication.avito_account_name}</Tag>
                {publication.avito_id && <Tag color="success">Avito ID: {publication.avito_id}</Tag>}
                {overrideKeys.length > 0 ? (
                    <Tag color="warning">Переопределено: {overrideKeys.join(", ")}</Tag>
                ) : (
                    <Tag>Переопределений нет</Tag>
                )}
            </Space>

            <Form form={form} layout="vertical" style={{maxWidth: 900}}>
                <Form.Item
                    name="address"
                    label="Адрес"
                    rules={[{required: true, message: "Введите адрес"}]}
                >
                    <Input.TextArea rows={3}/>
                </Form.Item>

                <Form.Item
                    name="status"
                    label="Статус"
                    rules={[{required: true, message: "Выберите статус"}]}
                >
                    <Select
                        options={[
                            {value: "draft", label: "draft"},
                            {value: "active", label: "active"},
                            {value: "paused", label: "paused"},
                            {value: "archived", label: "archived"},
                            {value: "error", label: "error"},
                        ]}
                    />
                </Form.Item>

                <Form.Item
                    name="overrides"
                    label="overrides"
                    extra="JSON-объект с индивидуальными значениями для этой публикации. Например: { &quot;Price&quot;: 12000 }"
                    rules={[{required: true, message: "Введите overrides"}]}
                >
                    <Input.TextArea rows={10}/>
                </Form.Item>

                <Paragraph type="secondary">
                    После сохранения CSV будет помечен как требующий пересборки.
                </Paragraph>

                <Space>
                    <Button
                        type="primary"
                        loading={updatePublicationMutation.isPending}
                        onClick={handleSubmit}
                    >
                        Сохранить
                    </Button>

                    <Button onClick={() => navigate("/ads/publications")}>
                        Отмена
                    </Button>
                </Space>
            </Form>
        </Space>
    );
};
