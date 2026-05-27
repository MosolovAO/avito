import React from 'react'
import {Alert, Card, Col, Empty, Form, Input, Row, Select} from 'antd'
import type {ProductOption} from '../../../entities/product'

interface OptionsSectionProps {
    options: ProductOption[]
    loading?: boolean
    error?: Error | null
}


export const OptionsSection: React.FC<OptionsSectionProps> = ({options, loading = false, error}) => {
    return (
        <Card title="Опции" loading={loading} style={{marginBottom: '16px'}}>
            {error && (
                <Alert
                    type="error"
                    showIcon
                    message="Не удалось загрузить опции"
                    description={error.message}
                    style={{marginBottom: 16}}
                />
            )}

            {options.length === 0 ? (
                <Empty description="Выберите категорию, чтобы загрузить доступные опции"/>
            ) : (
                <Row gutter={16}>
                    {options.map((option) => {
                        const allowMultiple = option.allow_multiple ?? option.allow_multiple_options
                        const label = option.option_title

                        return (
                            <Col key={option.id} xs={24} md={12}>
                                <Form.Item
                                    name={['options', option.id]}
                                    label={label}
                                >
                                    {allowMultiple ? (
                                        <Select
                                            mode="tags"
                                            placeholder={`Введите ${label}`}
                                            tokenSeparators={[',']}
                                            allowClear
                                        />
                                    ) : (
                                        <Input placeholder={`Введите ${label}`}/>
                                    )}
                                </Form.Item>
                            </Col>
                        )
                    })}
                </Row>
            )}
        </Card>
    )
}