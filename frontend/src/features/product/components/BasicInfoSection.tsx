// /Users/artem/Desktop/avito/frontend/src/features/product/components/BasicInfoSection.tsx

import React from "react";
import {
    AutoComplete,
    Card,
    Col,
    Form,
    InputNumber,
    Row,
    Select,
    Switch,
} from "antd";
import type {AvitoAccount} from "../../../entities/avito/types";
import type {ProductCategory} from "../../../entities/product";
import type {ProductFormValues} from "../lib/productFormMapper";
import {
    AVITO_AUTOLOAD_CATEGORY_OPTIONS,
} from "../../../shared/constants/avitoCategories";

interface BasicInfoSectionProps {
    avitoAccounts: AvitoAccount[]
    categories: ProductCategory[]
}

export const BasicInfoSection: React.FC<BasicInfoSectionProps> = ({
                                                                      avitoAccounts,
                                                                      categories,
                                                                  }) => {
    const form = Form.useFormInstance<ProductFormValues>()
    const randomizeEnabled = Form.useWatch('price_randomization_enabled', form) ?? false

    return (
        <Card title="Основная информация" style={{marginBottom: '16px'}}>
            <Row gutter={16}>
                <Col xs={24} xl={6}>
                    <Form.Item
                        name="avito_account_ids"
                        label="Avito аккаунт"
                        rules={[
                            {
                                required: true,
                                message: "Выберите хотя бы один Avito аккаунт",
                            },
                        ]}
                    >
                        <Select
                            mode="multiple"
                            placeholder="Выберите Avito аккаунты"
                            options={avitoAccounts.map((account) => ({
                                value: account.id,
                                label: account.name,
                            }))}
                        />
                    </Form.Item>
                </Col>

                <Col xs={24} xl={6}>
                    <Form.Item
                        name="category"
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
                            placeholder="Например: Плиты перекрытия"
                            optionFilterProp="label"
                            options={categories.map((category) => ({
                                value: category.name,
                                label: category.name,
                            }))}
                        />
                    </Form.Item>
                </Col>

                <Col xs={24} xl={6}>
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

                <Col xs={24} xl={6}>
                    <Form.Item
                        name="price"
                        label="Цена"
                        rules={[{required: true, message: "Введите цену"}]}
                    >
                        <InputNumber
                            style={{width: "100%"}}
                            min={0}
                            placeholder="0"
                        />
                    </Form.Item>
                </Col>
            </Row>

            <Form.Item label="Включить рандомизацию цены?" valuePropName="checked" name="price_randomization_enabled">
                <Switch checkedChildren="Вкл" unCheckedChildren="Выкл"/>
            </Form.Item>

            {randomizeEnabled && (
                <Card type="inner" title="Диапазон цен (для рандомизации)" size="small">
                    <Row gutter={16}>
                        <Col span={8}>
                            <Form.Item name="price_min" label="Минимальная цена" rules={[{type: 'number', min: 0}]}>
                                <InputNumber style={{width: '100%'}} min={0} placeholder="0"/>
                            </Form.Item>
                        </Col>
                        <Col span={8}>
                            <Form.Item name="price_max" label="Максимальная цена" rules={[{type: 'number', min: 0}]}>
                                <InputNumber style={{width: '100%'}} min={0} placeholder="0"/>
                            </Form.Item>
                        </Col>
                        <Col span={8}>
                            <Form.Item name="price_step" label="Шаг цены" rules={[{type: 'number', min: 0}]}>
                                <InputNumber style={{width: '100%'}} min={0} placeholder="0"/>
                            </Form.Item>
                        </Col>
                    </Row>
                </Card>
            )}
        </Card>
    )
}