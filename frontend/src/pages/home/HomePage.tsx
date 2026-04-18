import React from "react";
import { Typography} from "antd";

const { Title, Paragraph } = Typography
export const HomePage: React.FC = () => {
    return (
        <div style={{padding: '24px'}}>
            <Title level={2}>Добро пожаловать в Avito Parser!</Title>
            <Paragraph>
                Система управления парсингом Avito
            </Paragraph>

        </div>
    )
}