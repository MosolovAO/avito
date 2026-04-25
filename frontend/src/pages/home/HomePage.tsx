import React from "react";
import {Card, Col, Row, Statistic, Typography} from "antd";

const {Title, Paragraph, Text} = Typography

export const HomePage: React.FC = () => {
    return (
        <Row gutter={[24, 24]}>
            <Col xs={24} xl={12}>
                <Card>
                    <Statistic
                        title="Всего задач поставлено на выполнение"
                        value={128}
                        suffix="шт."
                    />
                    <Paragraph type="secondary" style={{marginTop: 16, marginBottom: 0}}>
                        Временная метрика. После подключения API здесь будут отображаться реальные данные.
                    </Paragraph>
                </Card>
            </Col>

            <Col xs={24} xl={12}>
                <Card title="Статистика кабинетов Avito">
                    <Paragraph>
                        Блок подготовлен под будущую интеграцию с API кабинетов.
                    </Paragraph>
                    <Text type="secondary">
                        После подключения здесь появятся агрегированные показатели по всем связанным кабинетам.
                    </Text>
                </Card>
            </Col>

            <Col span={24}>
                <Card>
                    <Title level={4}>Обзор рабочего пространства</Title>
                    <Paragraph style={{marginBottom: 0}}>
                        Этот экран будет развиваться в dashboard: общая статистика, состояние кабинетов, последние события и ключевые показатели по проектам.
                    </Paragraph>
                </Card>
            </Col>
        </Row>
    )
}
