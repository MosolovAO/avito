import React from 'react'
import {Select, Card, Form, Input, Empty} from 'antd'
import type {ProductOption} from '../../../entities/product'

interface OptionsSectionProps {
    options: ProductOption[]
    loading?: boolean
}

export const OptionsSection: React.FC<OptionsSectionProps> = ({options, loading = false}) => {
    return (
        <Card title="⚙️ Опции" loading={loading} style={{marginBottom: '16px'}}>
            {options.length === 0 ? (
                <Empty description="Выберите категорию, чтобы загрузить доступные опции"/>
            ) : (
                options.map((option) => {
                    const allowMultiple = option.allow_multiple ?? option.allow_multiple_options
                    return (
                        <Form.Item
                            key={option.id}
                            name={['options', option.id]}
                            label={option.option_title}
                        >
                            {allowMultiple ? (
                                <Select
                                    mode="tags"
                                    placeholder={`Введите ${option.option_title}`}
                                    tokenSeparators={[',']}
                                    allowClear
                                />
                            ) : (
                                <Input placeholder={`Введите ${option.option_title}`}/>
                            )}
                        </Form.Item>
                    )
                })
            )}
        </Card>
    )
}

