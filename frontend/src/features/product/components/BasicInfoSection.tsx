import React from "react";
import {Card, Col, Form, InputNumber, Row, Select, Switch} from 'antd'
import type {Project} from '../../../entities/project'
import type {ProductFormValues} from "../lib/productFormMapper.ts"

interface BasicInfoSectionProps {
    projects: Project[]
    categories: string[]
}

export const BasicInfoSection: React.FC<BasicInfoSectionProps> = ({
                                                                      projects,
                                                                      categories

                                                                  }) => {
    const form = Form.useFormInstance<ProductFormValues>()
    const randomizeEnabled = Form.useWatch('price_randomization_enabled', form) ?? false

    return (
        <Card title="📦 Основная информация" style={{marginBottom: '16px'}}>
            <Row gutter={16}>
                <Col span={8}>
                    <Form.Item
                        name="projects"
                        label="Выберите проект"
                        rules={[{required: true, message: 'Выберите хотя бы один проект'}]}
                    >
                        <Select
                            mode="multiple"
                            placeholder="Выберите проекты"
                            options={projects.map((project) => ({
                                value: project.id,
                                label: project.project_name,
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
                <Switch
                    checkedChildren="Вкл"
                    unCheckedChildren="Выкл"
                />
            </Form.Item>

            {/* Поля рандомизации - показываются только при включенном тумблере */}
            {randomizeEnabled && (
                <Card type="inner" title="Диапазон цен (для рандомизации)" size="small">
                    <Row gutter={16}>
                        <Col span={8}>
                            <Form.Item
                                name="price_min"
                                label="Минимальная цена"
                                rules={[{type: 'number', min: 0}]}
                            >
                                <InputNumber style={{width: '100%'}} min={0} placeholder="0"/>
                            </Form.Item>
                        </Col>
                        <Col span={8}>
                            <Form.Item
                                name="price_max"
                                label="Максимальная цена"
                                rules={[{type: 'number', min: 0}]}
                            >
                                <InputNumber style={{width: '100%'}} min={0} placeholder="0"/>
                            </Form.Item>
                        </Col>
                        <Col span={8}>
                            <Form.Item
                                name="price_step"
                                label="Шаг цены"
                                rules={[{type: 'number', min: 0}]}
                            >
                                <InputNumber style={{width: '100%'}} min={0} placeholder="0"/>
                            </Form.Item>
                        </Col>
                    </Row>
                </Card>
            )}

        </Card>
    )
}

