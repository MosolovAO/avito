import React from 'react'
import {Card, Typography} from 'antd'

const {Paragraph, Title} = Typography

export const ChatsPage: React.FC = () => {
    return (
        <Card>
            <Title level={2}>Чаты</Title>
            <Paragraph style={{marginBottom: 0}}>
                Раздел находится в разработке. Здесь появится управление диалогами и история сообщений.
            </Paragraph>
        </Card>
    )
}
