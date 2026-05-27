import React from 'react'
import {Card, Form, Select} from 'antd'

export const SettingsSection: React.FC = () => {
    return (
        <Card title="Дополнительные настройки" style={{marginBottom: '16px'}}>
            <Form.Item
                name="listingfee"
                label="Размещение"
                rules={[{required: true, message: 'Выберите способ размещения'}]}
            >
                <Select placeholder="Выберите способ размещения">
                    <Select.Option value="Package">Пакет размещений</Select.Option>
                    <Select.Option value="PackageSingle">Разовое размещение из пакета</Select.Option>
                    <Select.Option value="Single">Разовое размещение</Select.Option>
                </Select>
            </Form.Item>

            <Form.Item
                name="avitostatus"
                label="Статус на Avito"
                rules={[{required: true, message: 'Выберите статус'}]}
            >
                <Select placeholder="Выберите статус">
                    <Select.Option value="Активно">Активно</Select.Option>
                    <Select.Option value="Снято с публикации">Снято с публикации</Select.Option>
                </Select>
            </Form.Item>

            <Form.Item
                name="contactmethod"
                label="Способ связи"
                rules={[{required: true, message: 'Выберите способ связи'}]}
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
                rules={[{required: true, message: 'Выберите тип объявления'}]}
            >
                <Select placeholder="Выберите тип объявления">
                    <Select.Option value="Товар от производителя">Товар от производителя</Select.Option>
                    <Select.Option value="Товар приобретен на продажу">Товар приобретен на продажу</Select.Option>
                </Select>
            </Form.Item>

            <Form.Item
                name="availability"
                label="Наличие"
                rules={[{required: true, message: 'Выберите наличие'}]}
            >
                <Select placeholder="Выберите наличие">
                    <Select.Option value="В наличии">В наличии</Select.Option>
                    <Select.Option value="Под заказ">Под заказ</Select.Option>
                </Select>
            </Form.Item>
        </Card>
    )
}