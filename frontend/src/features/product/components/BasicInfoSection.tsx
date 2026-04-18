import {Card, Col, Form, Input, InputNumber, Row, Select, Switch} from 'antd'
import React from "react";
import type {Project} from '../../../entities/project'

interface BasicInfoSectionProps {
    randomizeEnabled?: boolean
    onRandomizeChange?: (enable: boolean) => void
    projects: Project[]
}

export const BasicInfoSection: React.FC<BasicInfoSectionProps> = ({
                                                                      randomizeEnabled = false,
                                                                      onRandomizeChange,
                                                                      projects

                                                                  }) => {
    return (
        <Card title="📦 Основная информация" style={{marginBottom: '16px'}}>
            <Row gutter={16}>
                <Col span={8}>
                    <Form.Item
                        name="projects"
                        label="Выберите проект"
                        rules={[{required: true, message: 'Выберите хотя бы один проект'}]}
                    >
                        <Select mode="multiple" placeholder="Выберите проекты">
                            {projects.map((project) => (
                                <Select.Option key={project.id} value={project.id}>
                                    {project.project_name}
                                </Select.Option>
                            ))}
                        </Select>
                    </Form.Item>
                </Col>
                <Col span={8}>
                    <Form.Item
                        name="category"
                        label="Категория"
                        rules={[{required: true, message: 'Введите категорию'}]}
                    >
                        <Input placeholder="Например: Квартиры"/>

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

            <Form.Item label="Включить рандомизацию цены?" valuePropName="checked">
                <Switch
                    checked={randomizeEnabled}
                    onChange={onRandomizeChange}
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

