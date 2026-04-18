import React from 'react'
import {Input, Card, Form} from 'antd'

export const ContactSection: React.FC = () => {
    return (
        <Card title="📞 Контактная информация" style={{marginBottom: '16px'}}>
            <Form.Item name='email' label="Email" rules={[{type: 'email'}]}>
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
    )
}