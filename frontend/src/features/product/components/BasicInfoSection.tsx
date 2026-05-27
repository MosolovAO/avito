// /Users/artem/Desktop/avito/frontend/src/features/product/components/BasicInfoSection.tsx

import React from "react";
import {Card, Col, Form, InputNumber, Row, Select, Switch, Input} from 'antd'
import type {AvitoAccount} from '../../../entities/avito/types'
import type {ProductFormValues} from "../lib/productFormMapper.ts"

interface BasicInfoSectionProps {
    avitoAccounts: AvitoAccount[]
    categories: string[]
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
                <Col span={24}>
                    <Form.Item
                        name="name"
                        label="Название продукта"
                        rules={[{required: true, message: 'Введите название продукта'}]}
                    >
                        <Input placeholder="Например: iPhone 15 Pro Max"/>
                    </Form.Item>
                </Col>

                <Col span={8}>
                    <Form.Item
                        name="avito_account_ids"
                        label="Avito аккаунт"
                        rules={[{required: true, message: 'Выберите хотя бы один Avito аккаунт'}]}
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

                <Col span={8}>
                    <Form.Item
                        name="category"
                        label="Категория"
                        rules={[{required: true, message: 'Введите категорию'}]}
                    >
                        <Select
                            showSearch
                            placeholder="Выберите категорию"
                            optionFilterProp="label"
                            options={categories.map((category) => ({
                                value: category,
                                label: category,
                            }))}
                        />
                    </Form.Item>
                </Col>

                <Col span={8}>
                    <Form.Item
                        name="price"
                        label="Цена"
                        rules={[{required: true, message: 'Введите цену'}]}
                    >
                        <InputNumber style={{width: '100%'}} min={0} placeholder="0"/>
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