import React from 'react'
import {Form, Card, Row, Col, Radio, Typography, TimePicker} from 'antd'
import dayjs from "dayjs"


export const ScheduleSection: React.FC = () => {
    const days = ['Понедельник', 'Вторник', 'Среда', 'Четверг', 'Пятница', 'Суббота', 'Воскресенье']

    const frequencyOptions = [
        {label: 'Каждый 7 дней', value: 1},
        {label: 'Каждые 14 дней ', value: 2},
        {label: 'Каждые 21 день', value: 3},
        {label: 'Каждые 28 дней', value: 4},
    ]


    return (
        <Card title="📅 Расписание публикаций" style={{marginBottom: '16px'}}>
            <Form.Item label="Частота публикаций" name={['schedule', 'frequency']}>
                <Radio.Group options={frequencyOptions} optionType="button" buttonStyle="solid"/>
            </Form.Item>

            <Form.Item label="Дни и время публикации">
                <Row gutter={[10, 8]} style={{display: 'flex'}}>
                    {days.map((day, index) => (
                        <Col
                            key={`time-${index}`}
                            flex={1}
                            style={{ display: 'flex', flexDirection: "column"}}
                        >
                            {/* Заголовки дней недели */}
                            <Typography.Text style={{fontSize: '11px', fontWeight: 'bold', marginTop: '5px'}}>{day}</Typography.Text>
                            <Form.Item
                                name={['schedule', 'days', index]}
                                noStyle
                                getValueProps={(value) => ({
                                    value: value ? dayjs(value, 'HH:mm') : undefined
                                })}
                                getValueFromEvent={(value) => value?.format('HH:mm')}
                            >
                                {/* Селекты времени */}
                                <TimePicker
                                    placeholder="Время"
                                    allowClear
                                    format="HH:mm"
                                    style={{}}
                                />
                            </Form.Item>
                        </Col>
                    ))}
                </Row>


            </Form.Item>
        </Card>

    )
}
