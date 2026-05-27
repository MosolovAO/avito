// /Users/artem/Desktop/avito/frontend/src/features/product/components/ScheduleSection.tsx

import React from 'react'
import {Form, Card, Row, Col, Radio, Typography, TimePicker} from 'antd'
import dayjs from "dayjs"

const days = [
    'Понедельник',
    'Вторник',
    'Среда',
    'Четверг',
    'Пятница',
    'Суббота',
    'Воскресенье',
]

const frequencyOptions = [
    {label: 'Каждые 7 дней', value: 1},
    {label: 'Каждые 14 дней', value: 2},
    {label: 'Каждые 21 день', value: 3},
    {label: 'Каждые 28 дней', value: 4},
]

export const ScheduleSection: React.FC = () => {
    return (
        <Card title="Расписание публикаций" style={{marginBottom: '16px'}}>
            <Form.Item
                label="Частота публикаций"
                name={['schedule', 'frequency']}
                rules={[{required: true, message: 'Выберите частоту публикаций'}]}
            >
                <Radio.Group options={frequencyOptions} optionType="button" buttonStyle="solid"/>
            </Form.Item>

            <Form.Item
                label="Дни и время публикации"
                required
                shouldUpdate
            >
                {({getFieldValue}) => (
                    <Form.Item
                        name={['schedule', 'days']}
                        noStyle
                        rules={[
                            {
                                validator: () => {
                                    const values = getFieldValue(['schedule', 'days']) as unknown

                                    const hasSelectedTime = Array.isArray(values)
                                        ? values.some(Boolean)
                                        : values !== null && typeof values === 'object'
                                            ? Object.values(values).some(Boolean)
                                            : false

                                    if (hasSelectedTime) {
                                        return Promise.resolve()
                                    }

                                    return Promise.reject(new Error('Укажите время хотя бы для одного дня недели'))
                                },
                            },
                        ]}
                    >
                        <Row gutter={[10, 8]}>
                            {days.map((day, index) => (
                                <Col
                                    key={day}
                                    xs={24}
                                    sm={12}
                                    md={8}
                                    lg={6}
                                    xl={3}
                                    style={{display: 'flex', flexDirection: 'column', gap: 6}}
                                >
                                    <Typography.Text style={{fontSize: 12, fontWeight: 600}}>
                                        {day}
                                    </Typography.Text>

                                    <Form.Item
                                        name={['schedule', 'days', index]}
                                        noStyle
                                        getValueProps={(value?: string) => ({
                                            value: value ? dayjs(value, 'HH:mm') : undefined,
                                        })}
                                        getValueFromEvent={(value: dayjs.Dayjs | null) => value?.format('HH:mm')}
                                    >
                                        <TimePicker
                                            placeholder="Время"
                                            allowClear
                                            format="HH:mm"
                                            style={{width: '100%'}}
                                        />
                                    </Form.Item>
                                </Col>
                            ))}
                        </Row>
                    </Form.Item>
                )}
            </Form.Item>
        </Card>
    )
}
