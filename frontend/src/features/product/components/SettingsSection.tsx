import React from 'react'
import {Input, Select, Card, Form} from 'antd'

export const SettingsSection: React.FC = () => {
    return (
        <Card title="⚙️ Дополнительные настройки" style={{marginBottom: '16px'}}>
            <Form.Item name="listingfee" label="Размещение">
                <Select placeholder="Выберите тип размещения">
                    <Select.Option value="Regular">Обычное</Select.Option>
                    <Select.Option value="Premium">Премиум</Select.Option>
                </Select>
            </Form.Item>

            <Form.Item name="avitostatus" label="Статус на авито">
                <Select placeholder="Выберите статус">
                    <Select.Option value="active">Активно</Select.Option>
                    <Select.Option value="moderation">На модерации</Select.Option>
                    <Select.Option value="rejected">Отклонено</Select.Option>
                </Select>
            </Form.Item>

            <Form.Item name="contactmethod" label="Способ связи">
                <Select placeholder="Выберите способ связи">
                    <Select.Option value="phone">Телефон</Select.Option>
                    <Select.Option value="message">Сообщение</Select.Option>
                    <Select.Option value="both">Оба</Select.Option>
                </Select>
            </Form.Item>

            <Form.Item name="adtype" label="Тип объявления">
                <Select placeholder="Выберите тип">
                    <Select.Option value="offer">Предложение</Select.Option>
                    <Select.Option value="demand">Спрос</Select.Option>
                </Select>
            </Form.Item>

            <Form.Item name="availability" label="Доступность">
                <Input placeholder="Например: В наличии"/>
            </Form.Item>
        </Card>
    )
}