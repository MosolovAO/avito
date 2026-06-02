// src/features/auth/components/RegisterForm.tsx
import React from "react";
import {Button, Col, Form, Input, Row} from "antd";
import {
    LockOutlined,
    MailOutlined,
    ShopOutlined,
    UserOutlined,
} from "@ant-design/icons";
import {registerSchema, type RegisterFormValues} from "../model/schemas";

interface RegisterFormProps {
    loading: boolean;
    onSubmit: (values: RegisterFormValues) => Promise<void>;
}

export const RegisterForm: React.FC<RegisterFormProps> = ({
                                                              loading,
                                                              onSubmit,
                                                          }) => {
    const [form] = Form.useForm<RegisterFormValues>();

    const handleFinish = async (values: RegisterFormValues) => {
        const parsed = registerSchema.safeParse(values);

        if (!parsed.success) {
            form.setFields(
                parsed.error.issues.map((issue) => ({
                    name: issue.path as [keyof RegisterFormValues],
                    errors: [issue.message],
                })),
            );
            return;
        }

        await onSubmit(parsed.data);
    };

    return (
        <Form form={form} layout="vertical" onFinish={handleFinish}>
            <Form.Item name="workspace_name" label="Название кабинета">
                <Input
                    prefix={<ShopOutlined/>}
                    placeholder="Например: Основной кабинет"
                />
            </Form.Item>

            <Form.Item name="email" label="Email">
                <Input prefix={<MailOutlined/>} placeholder="user@example.com"/>
            </Form.Item>

            <Row gutter={12}>
                <Col span={12}>
                    <Form.Item name="first_name" label="Имя">
                        <Input prefix={<UserOutlined/>}/>
                    </Form.Item>
                </Col>

                <Col span={12}>
                    <Form.Item name="last_name" label="Фамилия">
                        <Input prefix={<UserOutlined/>}/>
                    </Form.Item>
                </Col>
            </Row>

            <Form.Item name="password" label="Пароль">
                <Input.Password prefix={<LockOutlined/>}/>
            </Form.Item>

            <Form.Item name="confirmPassword" label="Повтор пароля">
                <Input.Password prefix={<LockOutlined/>}/>
            </Form.Item>

            <Button type="primary" htmlType="submit" block loading={loading}>
                Зарегистрироваться
            </Button>
        </Form>
    );
};
