import React from 'react'
import {Select, Card, Form} from 'antd'
import type {ProductOption} from '../../../entities/product'

interface OptionsSectionProps {
    options: ProductOption[]
}

export const OptionsSection: React.FC<OptionsSectionProps> = ({options}) => {
    return (
        <Card title="⚙️ Опции" style={{marginBottom: '16px'}}>
            {options.map((option) => (
                <Form.Item
                    key={option.id}
                    name={['options', option.id]}
                    label={option.option_title}
                >
                    <Select placeholder={`Выберите ${option.option_title}`} allowClear>
                        {option.option_value.map((value) => (
                            <Select.Option key={value} value={value}>
                                {value}
                            </Select.Option>
                        ))}
                    </Select>
                </Form.Item>
            ))}
        </Card>
    )
}

