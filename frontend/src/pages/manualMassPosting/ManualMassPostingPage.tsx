import React from "react";
import {RichTextEditor} from "../../shared/RichTextEditor";
import {
    Alert,
    Button,
    Card,
    Col,
    Form,
    Input,
    InputNumber,
    Row,
    Select,
    Space,
    Spin,
    Typography,
    Upload,
    message,
    Table,
    AutoComplete,
} from "antd";
import {useQuery} from "@tanstack/react-query";
import {useNavigate} from "react-router-dom";
import {
    useAvitoProjectsQuery,
    useCreateManualMassPostingMutation,
} from "../../features/avito";
import {useCurrentWorkspace} from "../../features/workspace/model/useCurrentWorkspace";
import {getProductCategories} from "../../shared/api/products";
import type {ColumnsType} from "antd/es/table";
import type {UploadFile, UploadProps} from "antd";
import {InboxOutlined, DeleteOutlined, PlusOutlined} from "@ant-design/icons";
import {useProductOptions} from "../../features/product/model/useProductOptions";
import {
    buildManualMassPostingRequest,
    type ManualMassPostingFormValues,
} from "../../features/avito/lib/manualMassPostingFormMapper";
import {
    getAdImageValidationError as getImageValidationError,
    MAX_AD_IMAGE_FILES as MAX_IMAGE_FILES,
    resolveAdImageUrls,
    revokeTemporaryPreviewUrl,
} from "../../features/avito/lib/adImageUpload";
import {countCharsWithoutHtml, hasTextContent} from "../../shared/lib/htmlText";
import {
    AVITO_AUTOLOAD_CATEGORY_OPTIONS,
} from "../../shared/constants/avitoCategories";


const {Title, Text} = Typography;

interface AddressRow {
    key: string;
    index: number;
    address: string;
}

const normalizeCategory = (category: string | undefined): string => category?.trim() ?? "";

const normalizeAddress = (address: string): string =>
    address.trim().replace(/\s+/g, " ").toLocaleLowerCase("ru-RU");

export const ManualMassPostingPage: React.FC = () => {

    const navigate = useNavigate();
    const [form] = Form.useForm<ManualMassPostingFormValues>();
    const watchedDescription = Form.useWatch("description", form) ?? "";
    const [imageFiles, setImageFiles] = React.useState<UploadFile[]>([]);
    const {currentWorkspace, canManageAvitoAccounts} = useCurrentWorkspace();
    const projectsQuery = useAvitoProjectsQuery();

    const categoriesQuery = useQuery({
        queryKey: ["product-categories"],
        queryFn: getProductCategories,
        staleTime: 5 * 60 * 1000,
    });

    const watchedOptionCategoryId = Form.useWatch(
        "option_category_id",
        form,
    );

    const selectedOptionCategory = (
        categoriesQuery.data ?? []
    ).find(
        (category) => category.id === watchedOptionCategoryId,
    );

    const category = normalizeCategory(
        selectedOptionCategory?.name,
    );

    const [isSubmitting, setIsSubmitting] = React.useState(false);

    const watchedAddresses = Form.useWatch("addresses", {form, preserve: true});
    const addresses = watchedAddresses ?? [];
    const [bulkAddressInput, setBulkAddressInput] = React.useState("");


    const createMassPostingMutation = useCreateManualMassPostingMutation();

    const {
        data: productOptions = [],
        isFetching: productOptionsLoading,
        error: productOptionsError,
    } = useProductOptions(category);

    const imageUploadProps: UploadProps = {
        multiple: true,
        accept: "image/jpeg,image/png",
        fileList: imageFiles,
        listType: "picture-card",
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

    const connectedProjectOptions = (projectsQuery.data ?? [])
        .filter((project) => project.external_account_id)
        .map((project) => ({
            value: project.id,
            label: project.name,
        }));

    const categoryOptions = (categoriesQuery.data ?? []).map(
        (category) => ({
            value: category.id,
            label: category.name,
        }),
    );

    const handleValuesChange = (
        changedValues: Partial<ManualMassPostingFormValues>,
    ) => {
        if ("option_category_id" in changedValues) {
            form.setFieldValue("options", {});
        }
    };

    const handleAddBulkAddresses = () => {
        const existingAddressKeys = new Set(addresses.map(normalizeAddress));
        const uniqueAddresses: string[] = [];
        let skippedCount = 0;

        bulkAddressInput
            .split("\n")
            .map((line) => line.trim().replace(/\s+/g, " "))
            .filter(Boolean)
            .forEach((address) => {
                const addressKey = normalizeAddress(address);

                if (existingAddressKeys.has(addressKey)) {
                    skippedCount += 1;
                    return;
                }

                existingAddressKeys.add(addressKey);
                uniqueAddresses.push(address);
            });

        if (uniqueAddresses.length === 0) {
            message.warning("Все адреса уже добавлены");
            return;
        }

        form.setFieldValue("addresses", [...addresses, ...uniqueAddresses]);
        setBulkAddressInput("");

        if (skippedCount > 0) {
            message.warning(`Пропущено дублей: ${skippedCount}`);
        }
    };

    const handleRemoveAddress = (indexToRemove: number) => {
        form.setFieldValue(
            "addresses",
            addresses.filter((_, index) => index !== indexToRemove),
        );
    };

    const addressColumns: ColumnsType<AddressRow> = [
        {
            title: "Адрес",
            dataIndex: "address",
            key: "address",
            width: 500,
            render: (address: string) => <Text>{address}</Text>,
        },
        {
            title: "Действия",
            key: "actions",
            width: 120,
            align: "right",
            render: (_, record) => (
                <Button
                    size="small"
                    danger
                    icon={<DeleteOutlined/>}
                    onClick={() => handleRemoveAddress(record.index)}
                />
            ),
        },
    ];

    const addressRows: AddressRow[] = addresses.map((address, index) => ({
        key: `${index}-${address}`,
        index,
        address,
    }));

    const handleSubmit = async () => {
        if (isSubmitting || createMassPostingMutation.isPending) {
            return;
        }

        setIsSubmitting(true);

        try {
            const values = await form.validateFields();
            const addresses = form.getFieldValue("addresses") as string[] | undefined;

            if (!addresses?.length) {
                message.warning("Добавьте хотя бы один адрес");
                return;
            }

            let imageUrls: string[];

            try {
                imageUrls = await resolveAdImageUrls(imageFiles);
            } catch {
                message.error("Не удалось загрузить изображения");
                return;
            }

            const result = await createMassPostingMutation.mutateAsync(buildManualMassPostingRequest({
                ...values,
                addresses,
            }, {
                imageUrls,
                productOptions,
            }));

            navigate(`/ads/publications?batch=${result.batch.id}`);
        } catch (error) {
            if (error instanceof Error) {
                message.error(error.message);
            }
        } finally {
            setIsSubmitting(false);
        }
    };

    if (!currentWorkspace) {
        return (
            <Alert
                type="warning"
                message="Кабинет не выбран"
                description="Выберите кабинет, чтобы создать ручной масс-постинг."
                showIcon
            />
        );
    }

    if (!canManageAvitoAccounts) {
        return (
            <Alert
                type="warning"
                message="Недостаточно прав"
                description="Ручной масс-постинг доступен только пользователям с правом управления Avito."
                showIcon
            />
        );
    }

    const isInitialLoading = projectsQuery.isLoading || categoriesQuery.isLoading;

    if (isInitialLoading) {
        return (
            <div style={{padding: 24, textAlign: "center"}}>
                <Spin size="large"/>
            </div>
        );
    }

    return (
        <Space direction="vertical" size={16} style={{width: "100%"}}>
            <Space direction="vertical" size={0}>
                <Title level={2} style={{margin: 0}}>
                    Ручной масс-постинг
                </Title>
                <Text type="secondary">
                    Создает один общий креатив и публикации по выбранным проектам и адресам.
                </Text>
            </Space>

            <Form
                form={form}
                layout="vertical"
                initialValues={{
                    avito_account_ids: [],
                    addresses: [],
                    description: "",
                    options: {},
                    listingfee: "Package",
                    avitostatus: "Активно",
                    contactmethod: "По телефону и в сообщениях",
                    adtype: "Товар от производителя",
                    availability: "В наличии",
                }}
                onValuesChange={handleValuesChange}
            >
                <Card title="Основная информация" style={{marginBottom: 16}}>
                    <Row gutter={16}>
                        <Col xs={24} lg={8}>
                            <Form.Item
                                name="avito_account_ids"
                                label="Проекты"
                                rules={[{required: true, message: "Выберите хотя бы один проект"}]}
                            >
                                <Select
                                    mode="multiple"
                                    loading={projectsQuery.isLoading}
                                    options={connectedProjectOptions}
                                    placeholder="Выберите проекты с подключенным Avito API"
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
                                    options={categoryOptions}
                                    optionFilterProp="label"
                                    placeholder="Например: Газобетонные блоки"
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

                        <Col xs={24} lg={8}>
                            <Form.Item
                                name="price"
                                label="Цена"
                                rules={[{required: true, message: "Введите цену"}]}
                            >
                                <InputNumber
                                    min={0}
                                    precision={0}
                                    style={{width: "100%"}}
                                    placeholder="0"
                                />
                            </Form.Item>
                        </Col>

                        <Col xs={24} lg={24}>
                            <Form.Item
                                name="title"
                                label="Заголовок"
                                rules={[
                                    {required: true, message: "Введите заголовок"},
                                    {max: 255, message: "Максимум 255 символов"},
                                ]}
                            >
                                <Input placeholder="Например: Бетон М300 с доставкой"/>
                            </Form.Item>
                        </Col>


                    </Row>

                    {connectedProjectOptions.length === 0 && (
                        <Alert
                            type="info"
                            message="Нет подключенных проектов"
                            description="Сначала подключите Avito API в разделе Проекты."
                            showIcon
                        />
                    )}
                </Card>

                <Card title="Описание" style={{marginBottom: 16}}>
                    <Form.Item
                        name="description"
                        label="Описание"
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

                <Card title="Адреса" style={{marginBottom: 16}}>
                    <Space direction="vertical" style={{width: "100%"}}>


                        <div>
                            <Input.TextArea
                                rows={3}
                                placeholder="Массовое добавление (каждый адрес с новой строки)"
                                value={bulkAddressInput}
                                onChange={(event) => setBulkAddressInput(event.target.value)}
                            />

                            <Button
                                type="default"
                                icon={<PlusOutlined/>}
                                onClick={handleAddBulkAddresses}
                                disabled={!bulkAddressInput.trim()}
                                style={{marginTop: 8}}
                            >
                                Добавить все адреса
                            </Button>
                        </div>

                        {addresses.length > 0 && (
                            <Table
                                columns={addressColumns}
                                dataSource={addressRows}
                                pagination={false}
                                size="small"
                                scroll={{y: 300}}
                            />
                        )}
                    </Space>
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

                    {!category ? (
                        <Text type="secondary">Выберите категорию, чтобы загрузить доступные опции.</Text>
                    ) : productOptions.length === 0 ? (
                        <Text type="secondary">Для выбранной категории нет дополнительных опций.</Text>
                    ) : (
                        <Row gutter={16}>
                            {productOptions.map((option) => {
                                const allowMultiple = option.allow_multiple ?? option.allow_multiple_options;
                                const label = option.option_title;

                                return (
                                    <Col key={option.id} xs={24} md={12}>
                                        <Form.Item name={["options", String(option.id)]} label={label}>
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

                <Row gutter={[16, 16]}>
                    <Col xs={24} lg={12}>
                        <Card title="Контактная информация" style={{marginBottom: 16}}>

                            <Form.Item name="email" label="Email" rules={[{type: "email"}]}>
                                <Input placeholder="email@example.com"/>
                            </Form.Item>


                            <Form.Item name="contactphone" label="Телефон">
                                <Input placeholder="+7 999 000-00-00"/>
                            </Form.Item>


                            <Form.Item name="managername" label="Имя менеджера">
                                <Input placeholder="Иван Иванов"/>
                            </Form.Item>


                            <Form.Item name="companyname" label="Название компании">
                                <Input placeholder="ООО Ромашка"/>
                            </Form.Item>


                        </Card>
                    </Col>

                    <Col xs={24} lg={12}>
                        <Card title="Дополнительные настройки" style={{marginBottom: 16}}>

                            <Form.Item
                                name="listingfee"
                                label="Размещение"
                                rules={[{required: true, message: "Выберите способ размещения"}]}
                            >
                                <Select placeholder="Выберите способ размещения">
                                    <Select.Option value="Package">Пакет размещений</Select.Option>
                                    <Select.Option value="PackageSingle">Разовое размещение из
                                        пакета</Select.Option>
                                    <Select.Option value="Single">Разовое размещение</Select.Option>
                                </Select>
                            </Form.Item>

                            <Form.Item
                                name="avitostatus"
                                label="Статус на Avito"
                                rules={[{required: true, message: "Выберите статус"}]}
                            >
                                <Select placeholder="Выберите статус">
                                    <Select.Option value="Активно">Активно</Select.Option>
                                    <Select.Option value="Снято с публикации">Снято с публикации</Select.Option>
                                </Select>
                            </Form.Item>

                            <Form.Item
                                name="contactmethod"
                                label="Способ связи"
                                rules={[{required: true, message: "Выберите способ связи"}]}
                            >
                                <Select placeholder="Выберите способ связи">
                                    <Select.Option value="По телефону и в сообщениях">
                                        По телефону и в сообщениях
                                    </Select.Option>
                                    <Select.Option value="По телефону">По телефону</Select.Option>
                                    <Select.Option value="В сообщениях">В сообщениях</Select.Option>
                                </Select>
                            </Form.Item>

                            <Form.Item
                                name="adtype"
                                label="Тип объявления"
                                rules={[{required: true, message: "Выберите тип объявления"}]}
                            >
                                <Select placeholder="Выберите тип объявления">
                                    <Select.Option value="Товар от производителя">Товар от
                                        производителя</Select.Option>
                                    <Select.Option value="Товар приобретен на продажу">
                                        Товар приобретен на продажу
                                    </Select.Option>
                                </Select>
                            </Form.Item>

                            <Form.Item
                                name="availability"
                                label="Наличие"
                                rules={[{required: true, message: "Выберите наличие"}]}
                            >
                                <Select placeholder="Выберите наличие">
                                    <Select.Option value="В наличии">В наличии</Select.Option>
                                    <Select.Option value="Под заказ">Под заказ</Select.Option>
                                </Select>
                            </Form.Item>
                        </Card>
                    </Col>
                </Row>


                <Card>
                    <Space>
                        <Button
                            type="primary"
                            loading={isSubmitting || createMassPostingMutation.isPending}
                            disabled={connectedProjectOptions.length === 0}
                            onClick={handleSubmit}
                        >
                            Создать публикации
                        </Button>

                        <Button onClick={() => navigate("/ads/publications")}>
                            Отмена
                        </Button>
                    </Space>
                </Card>
            </Form>
        </Space>
    );
};
