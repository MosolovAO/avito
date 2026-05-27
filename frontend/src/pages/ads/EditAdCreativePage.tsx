// src/pages/ads/EditAdCreativePage.tsx
import React, {useEffect} from "react";
import {
    Alert,
    Button,
    Form,
    Input,
    Space,
    Spin,
    Typography,
} from "antd";
import {useNavigate, useParams} from "react-router-dom";
import {
    useAdCreativeQuery,
    useUpdateAdCreativeMutation,
} from "../../features/avito";
import {useCurrentWorkspace} from "../../features/workspace/model/useCurrentWorkspace";
import type {JsonObject} from "../../entities/avito/types";

const {Title, Text} = Typography;

interface CreativeFormValues {
    title: string;
    description: string;
    image_urls: string;
    base_data: string;
    option_data: string;
    clear_publication_override_fields?: string;
}

const formatJson = (value: unknown): string => {
    if (!value) {
        return "{}";
    }

    return JSON.stringify(value, null, 2);
};

const parseJsonObject = (value: string, fieldLabel: string): JsonObject => {
    try {
        const parsed = JSON.parse(value || "{}");

        if (
            parsed === null ||
            Array.isArray(parsed) ||
            typeof parsed !== "object"
        ) {
            throw new Error(`${fieldLabel} должен быть JSON-объектом`);
        }

        return parsed as JsonObject;
    } catch (error) {
        if (error instanceof Error) {
            throw new Error(`${fieldLabel}: ${error.message}`);
        }

        throw new Error(`${fieldLabel}: некорректный JSON`);
    }
};

const parseImageUrls = (value: string): string[] => {
    return value
        .split("\n")
        .map((url) => url.trim())
        .filter(Boolean);
};

const parseClearOverrideFields = (value?: string): string[] | undefined => {
    const fields = (value ?? "")
        .split(",")
        .map((field) => field.trim())
        .filter(Boolean);

    return fields.length > 0 ? fields : undefined;
};

export const EditAdCreativePage: React.FC = () => {
    const navigate = useNavigate();
    const params = useParams();
    const [form] = Form.useForm<CreativeFormValues>();

    const {currentWorkspace, canManageAvitoAccounts} = useCurrentWorkspace();

    const creativeId = params.id ? Number(params.id) : null;
    const creativeQuery = useAdCreativeQuery(creativeId);
    const updateCreativeMutation = useUpdateAdCreativeMutation();

    useEffect(() => {
        if (!creativeQuery.data) {
            return;
        }

        form.setFieldsValue({
            title: creativeQuery.data.title,
            description: creativeQuery.data.description,
            image_urls: creativeQuery.data.image_urls.join("\n"),
            base_data: formatJson(creativeQuery.data.base_data),
            option_data: formatJson(creativeQuery.data.option_data),
            clear_publication_override_fields: "",
        });
    }, [creativeQuery.data, form]);

    const handleSubmit = async () => {
        const values = await form.validateFields();

        try {
            await updateCreativeMutation.mutateAsync({
                creativeId: Number(creativeId),
                data: {
                    title: values.title.trim(),
                    description: values.description.trim(),
                    image_urls: parseImageUrls(values.image_urls),
                    base_data: parseJsonObject(values.base_data, "base_data"),
                    option_data: parseJsonObject(values.option_data, "option_data"),
                    clear_publication_override_fields: parseClearOverrideFields(
                        values.clear_publication_override_fields,
                    ),
                },
            });

            navigate("/ads/creatives");
        } catch (error) {
            if (!(error instanceof Error)) {
                return;
            }

            const fieldName = error.message.startsWith("option_data")
                ? "option_data"
                : "base_data";

            form.setFields([
                {
                    name: fieldName,
                    errors: [error.message],
                },
            ]);
        }
    };

    if (!currentWorkspace) {
        return (
            <Alert
                type="warning"
                message="Кабинет не выбран"
                description="Выберите кабинет, чтобы редактировать креатив."
                showIcon
            />
        );
    }

    if (!canManageAvitoAccounts) {
        return (
            <Alert
                type="warning"
                message="Недостаточно прав"
                description="Редактирование креативов доступно только пользователям с правом управления Avito."
                showIcon
            />
        );
    }

    if (!creativeId || Number.isNaN(creativeId)) {
        return (
            <Alert
                type="error"
                message="Некорректный ID креатива"
                showIcon
            />
        );
    }

    if (creativeQuery.isLoading) {
        return <Spin/>;
    }

    if (creativeQuery.isError || !creativeQuery.data) {
        return (
            <Alert
                type="error"
                message="Креатив не найден"
                description="Проверьте, что креатив существует и принадлежит текущему кабинету."
                showIcon
            />
        );
    }

    return (
        <Space direction="vertical" size={16} style={{width: "100%"}}>
            <Space direction="vertical" size={0}>
                <Title level={2} style={{margin: 0}}>
                    Редактировать креатив
                </Title>
                <Text type="secondary">
                    Изменения применятся ко всем публикациям этого креатива, кроме полей, переопределенных на уровне
                    публикации.
                </Text>
            </Space>

            <Form form={form} layout="vertical" style={{maxWidth: 900}}>
                <Form.Item
                    name="title"
                    label="Заголовок"
                    rules={[
                        {required: true, message: "Введите заголовок"},
                        {max: 255, message: "Максимум 255 символов"},
                    ]}
                >
                    <Input/>
                </Form.Item>

                <Form.Item
                    name="description"
                    label="Описание"
                    rules={[{required: true, message: "Введите описание"}]}
                >
                    <Input.TextArea rows={8}/>
                </Form.Item>

                <Form.Item
                    name="image_urls"
                    label="Изображения"
                    extra="Один URL на строку."
                >
                    <Input.TextArea rows={6}/>
                </Form.Item>

                <Form.Item
                    name="base_data"
                    label="base_data"
                    extra="JSON-объект с общими CSV-полями: Price, ContactPhone и т.д."
                    rules={[{required: true, message: "Введите base_data"}]}
                >
                    <Input.TextArea rows={10}/>
                </Form.Item>

                <Form.Item
                    name="option_data"
                    label="option_data"
                    extra="JSON-объект с параметрами Avito."
                    rules={[{required: true, message: "Введите option_data"}]}
                >
                    <Input.TextArea rows={10}/>
                </Form.Item>

                <Form.Item
                    name="clear_publication_override_fields"
                    label="Очистить переопределения в публикациях"
                    extra="Список полей через запятую. Например: Price, ContactPhone. Эти поля снова будут наследоваться из креатива."
                >
                    <Input placeholder="Price, ContactPhone"/>
                </Form.Item>

                <Space>
                    <Button
                        type="primary"
                        loading={updateCreativeMutation.isPending}
                        onClick={handleSubmit}
                    >
                        Сохранить
                    </Button>

                    <Button onClick={() => navigate("/ads/creatives")}>
                        Отмена
                    </Button>
                </Space>
            </Form>
        </Space>
    );
};
