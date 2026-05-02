import React from 'react'
import {Card, Typography} from 'antd'

const {Paragraph, Title} = Typography

export const BotsPage: React.FC = () => {
    return (
        <Card>
            <Title level={2}>Боты</Title>
            <Paragraph style={{marginBottom: 0}}>
                Раздел находится в разработке. Здесь появятся сценарии автоматизации и управление ботами.
            </Paragraph>
        </Card>
    )
}
