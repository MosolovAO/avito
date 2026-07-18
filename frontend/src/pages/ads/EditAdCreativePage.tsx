// src/pages/ads/EditAdCreativePage.tsx
import React, {useEffect} from "react";
import {
    Alert,
    Button,
    Card,
    Col,
    Form,
    Input,
    AutoComplete,
    InputNumber,
    Row,
    Select,
    Space,
    Spin,
    Typography,
    Collapse,
    Upload,
    message,
} from "antd";
import {useNavigate, useParams} from "react-router-dom";
import {
    useAdCreativeQuery,
    useUpdateAdCreativeMutation,
} from "../../features/avito";
import {useCurrentWorkspace} from "../../features/workspace/model/useCurrentWorkspace";
import type {ProductOption} from "../../entities/product";
import {useProductOptions} from "../../features/product/model/useProductOptions";
import {RichTextEditor} from "../../shared/RichTextEditor";
import {InboxOutlined} from "@ant-design/icons";
import type {UploadFile, UploadProps} from "antd";
import {
    buildBaseData,
    buildBaseDataFormValues,
    buildOptionData,
    buildOptionFormValues,
    getCreativeAutoloadCategory,
    getCreativePrice,
    mergeUnknownOptionData,
    parseClearOverrideFields,
    type EditableOptionValue,
} from "../../features/avito/lib/adCreativeFormMapper";
import {
    getAdImageValidationError as getImageValidationError,
    MAX_AD_IMAGE_FILES as MAX_IMAGE_FILES,
    resolveAdImageUrls as resolveCreativeImageUrls,
    revokeTemporaryPreviewUrl,
} from "../../features/avito/lib/adImageUpload";
import {countCharsWithoutHtml, hasTextContent} from "../../shared/lib/htmlText";
import {useQuery} from "@tanstack/react-query";
import {getProductCategories} from "../../shared/api/products";
import {
    AVITO_AUTOLOAD_CATEGORY_OPTIONS,
} from "../../shared/constants/avitoCategories";


const {Title, Text} = Typography;

interface CreativeFormValues {
    option_category_id: number | undefined;
    autoload_category: string;
    title: string;
    price: number;
    description: string;
    base_data: Record<string, string | undefined>;
    options: Record<string, EditableOptionValue | undefined>;
    clear_publication_override_fields?: string;
}

const EMPTY_PRODUCT_OPTIONS: ProductOption[] = [];

const buildInitialImageFiles = (imageUrls: string[]): UploadFile[] =>
    imageUrls.map((url, index) => ({
        uid: `existing-${index}-${url}`,
        name: `Изображение ${index + 1}`,
        status: "done",
        url,
    }));

const parsePositiveIntegerParam = (value: string | undefined): number | null => {
    if (!value) {
        return null;
    }

    const parsedValue = Number(value);

    return Number.isInteger(parsedValue) && parsedValue > 0 ? parsedValue : null;
};

export const EditAdCreativePage: React.FC = () => {
    const navigate = useNavigate();
    const params = useParams();
    const [form] = Form.useForm<CreativeFormValues>();
    const watchedDescription = Form.useWatch("description", form) ?? "";
    const {currentWorkspace, canManageAvitoAccounts} = useCurrentWorkspace();

    const creativeId = parsePositiveIntegerParam(params.id);
    const hasInvalidCreativeId = creativeId === null;
    const creativeQuery = useAdCreativeQuery(creativeId);
    const updateCreativeMutation = useUpdateAdCreativeMutation();
    const [imageFiles, setImageFiles] = React.useState<UploadFile[]>([]);
    const [isSubmitting, setIsSubmitting] = React.useState(false);
    const initializedCreativeIdRef = React.useRef<number | null>(null);
    const initializedOptionsCreativeIdRef = React.useRef<number | null>(null);

    const categoriesQuery = useQuery({
        queryKey: ["product-categories"],
        queryFn: getProductCategories,
        staleTime: 5 * 60 * 1000,
    });

    const watchedOptionCategoryId = Form.useWatch(
        "option_category_id",
        form,
    );

    const effectiveOptionCategoryId = (
        watchedOptionCategoryId
        ?? creativeQuery.data?.option_category_id
        ?? null
    );

    const selectedOptionCategory = (
        categoriesQuery.data ?? []
    ).find(
        (category) => category.id === effectiveOptionCategoryId,
    );

    const optionCategoryName = (
        selectedOptionCategory?.name
        ?? (
            effectiveOptionCategoryId
            === creativeQuery.data?.option_category_id
                ? creativeQuery.data?.option_category
                : ""
        )
        ?? ""
    );

    const {
        data: productOptionsData,
        isFetching: productOptionsLoading,
        error: productOptionsError,
    } = useProductOptions(optionCategoryName);

    const productOptions = productOptionsData ?? EMPTY_PRODUCT_OPTIONS;
    const isSaving = isSubmitting || updateCreativeMutation.isPending;


    useEffect(() => {
        const creative = creativeQuery.data;

        if (!creative || initializedCreativeIdRef.current === creative.id) {
            return;
        }

        initializedCreativeIdRef.current = creative.id;
        initializedOptionsCreativeIdRef.current = null;

        form.setFieldsValue({
            option_category_id: creative.option_category_id ?? undefined,
            autoload_category: getCreativeAutoloadCategory(
                creative.base_data,
            ),
            title: creative.title,
            price: getCreativePrice(creative.base_data),
            description: creative.description,
            base_data: buildBaseDataFormValues(creative.base_data),
            options: {},
            clear_publication_override_fields: "",
        });

        setImageFiles(buildInitialImageFiles(creative.image_urls));
    }, [creativeQuery.data, form]);

    useEffect(() => {
        const creative = creativeQuery.data;

        if (
            !creative
            || initializedOptionsCreativeIdRef.current === creative.id
        ) {
            return;
        }

        if (
            optionCategoryName
            && productOptionsData === undefined
        ) {
            return;
        }

        form.setFieldValue(
            "options",
            buildOptionFormValues(
                creative.option_data,
                productOptions,
            ),
        );

        initializedOptionsCreativeIdRef.current = creative.id;
    }, [
        creativeQuery.data,
        form,
        optionCategoryName,
        productOptions,
        productOptionsData,
    ]);

    const handleValuesChange = (
        changedValues: Partial<CreativeFormValues>,
    ) => {
        if ("option_category_id" in changedValues) {
            form.setFieldValue("options", {});
            initializedOptionsCreativeIdRef.current = null;
        }
    };

    const imageUploadProps: UploadProps = {
        multiple: true,
        accept: "image/jpeg,image/png",
        fileList: imageFiles,
        listType: "picture-card",
        disabled: isSaving,
        beforeUpload: (file) => {
            if (imageFiles.length >= MAX_IMAGE_FILES) {
                message.warning(`Максимум ${MAX_IMAGE_FILES} изображений`);
                return Upload.LIST_IGNORE;
            }

            const validationError = getImageValidationError(file);

            if (validationError) {
                message.error(validationError);
                return Upload.LIST_IGNORE;
            }

            return false;
        },
        onChange: ({fileList}) => {
            setImageFiles(fileList.slice(0, MAX_IMAGE_FILES));
        },
        onRemove: (file) => {
            setImageFiles((currentFiles) =>
                currentFiles.filter((currentFile) => currentFile.uid !== file.uid),
            );
        },
        onPreview: async (file) => {
            const previewUrl =
                file.url ??
                (file.originFileObj ? URL.createObjectURL(file.originFileObj) : undefined);

            if (!previewUrl) {
                return;
            }

            window.open(previewUrl, "_blank", "noopener,noreferrer");

            if (!file.url) {
                revokeTemporaryPreviewUrl(previewUrl);
            }
        },
    };

    const handleSubmit = async () => {
        if (isSaving) {
            return;
        }

        setIsSubmitting(true);

        try {
            const values = await form.validateFields();
            const creative = creativeQuery.data;

            if (!creative || creativeId === null) {
                return;
            }

            let imageUrls: string[];

            try {
                imageUrls = await resolveCreativeImageUrls(imageFiles);
            } catch {
                message.error("Не удалось загрузить изображения");
                return;
            }

            const baseData = buildBaseData(
                creative.base_data,
                values.base_data ?? {},
                values.price,
                values.autoload_category,
            );

            const nextKnownOptionData = buildOptionData(
                values.options ?? {},
                productOptions,
            );

            const optionCategoryChanged = (
                creative.option_category_id
                !== values.option_category_id
            );

            const nextOptionData = optionCategoryChanged
                ? nextKnownOptionData
                : mergeUnknownOptionData(
                    creative.option_data,
                    nextKnownOptionData,
                    productOptions,
                );

            await updateCreativeMutation.mutateAsync({
                creativeId,
                data: {
                    option_category_id: values.option_category_id,
                    title: values.title.trim(),
                    description: values.description,
                    image_urls: imageUrls,
                    base_data: baseData,
                    option_data: nextOptionData,
                    clear_publication_override_fields:
                        parseClearOverrideFields(
                            values.clear_publication_override_fields,
                        ),
                    expected_updated_at: creative.updated_at,
                },
            });

            navigate("/ads/creatives");
        } catch (error) {
            if (!(error instanceof Error)) {
                return;
            }

            message.error(error.message);
        } finally {
            setIsSubmitting(false);
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

    if (hasInvalidCreativeId) {
        return (
            <Alert
                type="error"
                message="Некорректный ID креатива"
                showIcon
            />
        );
    }

    if (creativeQuery.isLoading) {
        return (
            <div style={{padding: 24, textAlign: "center"}}>
                <Spin size="large"/>
            </div>
        );
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

    const baseDataFieldKeys = Object.keys(
        buildBaseDataFormValues(creativeQuery.data.base_data),
    );

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

            <Form
                form={form}
                layout="vertical"
                onValuesChange={handleValuesChange}
            >
                <Card title="Основная информация" style={{marginBottom: 16}}>
                    <Row gutter={16}>
                        <Col xs={24} lg={6}>
                            <Form.Item
                                name="title"
                                label="Заголовок"
                                rules={[
                                    {
                                        required: true,
                                        message: "Введите заголовок",
                                    },
                                    {
                                        max: 255,
                                        message: "Максимум 255 символов",
                                    },
                                ]}
                            >
                                <Input placeholder="Введите заголовок"/>
                            </Form.Item>
                        </Col>

                        <Col xs={24} lg={6}>
                            <Form.Item
                                name="price"
                                label="Цена"
                                rules={[
                                    {
                                        required: true,
                                        message: "Введите цену",
                                    },
                                ]}
                            >
                                <InputNumber
                                    min={0}
                                    precision={0}
                                    style={{width: "100%"}}
                                    placeholder="0"
                                />
                            </Form.Item>
                        </Col>

                        <Col xs={24} lg={6}>
                            <Form.Item
                                name="option_category_id"
                                label="Категория для отбора опций"
                                rules={[
                                    {
                                        required: true,
                                        message: "Выберите категорию для отбора опций",
                                    },
                                ]}
                            >
                                <Select
                                    showSearch
                                    loading={categoriesQuery.isLoading}
                                    options={(categoriesQuery.data ?? []).map(
                                        (category) => ({
                                            value: category.id,
                                            label: category.name,
                                        }),
                                    )}
                                    optionFilterProp="label"
                                    placeholder="Выберите категорию"
                                />
                            </Form.Item>
                        </Col>

                        <Col xs={24} lg={6}>
                            <Form.Item
                                name="autoload_category"
                                label="Категория для файла Avito"
                                rules={[
                                    {
                                        required: true,
                                        message: "Укажите категорию автозагрузки",
                                    },
                                ]}
                            >
                                <AutoComplete
                                    options={AVITO_AUTOLOAD_CATEGORY_OPTIONS}
                                    placeholder="Например: Ремонт и строительство"
                                    filterOption={(inputValue, option) =>
                                        String(option?.value ?? "")
                                            .toLowerCase()
                                            .includes(inputValue.toLowerCase())
                                    }
                                />
                            </Form.Item>
                        </Col>
                    </Row>
                </Card>

                <Card title="Описание" style={{marginBottom: 16}}>
                    <Form.Item
                        name="description"
                        rules={[
                            {
                                validator: async (_, value: string | undefined) => {
                                    if (!hasTextContent(value)) {
                                        throw new Error("Введите описание");
                                    }
                                },
                            },
                        ]}
                    >
                        <RichTextEditor
                            content={watchedDescription}
                            onChange={(value) => form.setFieldValue("description", value)}
                            placeholder="Введите описание..."
                        />
                    </Form.Item>

                    <Text type="secondary">
                        Всего символов: {countCharsWithoutHtml(watchedDescription)}
                    </Text>
                </Card>

                <Card title="Изображения" style={{marginBottom: 16}}>
                    <Upload.Dragger {...imageUploadProps}>
                        <p className="ant-upload-drag-icon">
                            <InboxOutlined/>
                        </p>

                        <p className="ant-upload-text">
                            Перетащите изображения сюда или нажмите для выбора
                        </p>

                        <p className="ant-upload-hint">
                            JPEG или PNG, до 2MB. Максимум {MAX_IMAGE_FILES} изображений.
                        </p>
                    </Upload.Dragger>
                </Card>

                <Card title="Базовые CSV-поля" style={{marginBottom: 16}}>
                    {baseDataFieldKeys.length === 0 ? (
                        <Text type="secondary">
                            Нет дополнительных базовых полей.
                        </Text>
                    ) : (
                        <Row gutter={16}>
                            {baseDataFieldKeys.map((key) => (
                                <Col key={key} xs={24} md={12}>
                                    <Form.Item
                                        name={["base_data", key]}
                                        label={key}
                                    >
                                        <Input placeholder={`Введите ${key}`}/>
                                    </Form.Item>
                                </Col>
                            ))}
                        </Row>
                    )}
                </Card>

                <Card title="Опции" loading={productOptionsLoading} style={{marginBottom: 16}}>
                    {productOptionsError && (
                        <Alert
                            type="error"
                            showIcon
                            message="Не удалось загрузить опции"
                            description={productOptionsError.message}
                            style={{marginBottom: 16}}
                        />
                    )}

                    {!optionCategoryName ? (
                        <Text type="secondary">
                            Выберите категорию для отбора опций.
                        </Text>
                    ) : productOptions.length === 0 ? (
                        <Text type="secondary">
                            Для категории "{optionCategoryName}" нет дополнительных опций.
                        </Text>
                    ) : (
                        <Row gutter={16}>
                            {productOptions.map((option) => {
                                const allowMultiple =
                                    option.allow_multiple ?? option.allow_multiple_options;
                                const label = option.option_title;

                                return (
                                    <Col key={option.id} xs={24} md={12}>
                                        <Form.Item
                                            name={["options", String(option.id)]}
                                            label={label}
                                        >
                                            {allowMultiple ? (
                                                <Select
                                                    mode="tags"
                                                    placeholder={`Введите ${label}`}
                                                    tokenSeparators={[","]}
                                                    allowClear
                                                />
                                            ) : (
                                                <Input placeholder={`Введите ${label}`}/>
                                            )}
                                        </Form.Item>
                                    </Col>
                                );
                            })}
                        </Row>
                    )}
                </Card>

                <Collapse
                    style={{marginBottom: 16}}
                    items={[
                        {
                            key: "advanced",
                            label: "Расширенные действия",
                            children: (
                                <Space direction="vertical" size={16} style={{width: "100%"}}>
                                    <Alert
                                        type="warning"
                                        showIcon
                                        message="Очистка индивидуальных изменений публикаций"
                                        description="Если публикация была отредактирована отдельно, ее значения важнее значений креатива. Укажите поля здесь только если нужно снова наследовать эти значения из креатива для всех связанных публикаций."
                                    />

                                    <Form.Item
                                        name="clear_publication_override_fields"
                                        label="Поля для очистки"
                                        extra="Список полей через запятую. Например: Price, ContactPhone."
                                    >
                                        <Input placeholder="Price, ContactPhone"/>
                                    </Form.Item>
                                </Space>
                            ),
                        },
                    ]}
                />

                <Card>
                    <Space>
                        <Button
                            type="primary"
                            loading={isSaving}
                            onClick={handleSubmit}
                        >
                            Сохранить
                        </Button>

                        <Button
                            disabled={isSaving}
                            onClick={() => navigate("/ads/creatives")}
                        >
                            Отмена
                        </Button>
                    </Space>
                </Card>
            </Form>
        </Space>
    );
};
