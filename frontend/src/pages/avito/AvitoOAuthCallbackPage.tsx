import React, {useEffect, useRef} from "react";
import {Button, Result, Spin, Typography} from "antd";
import {useNavigate, useSearchParams} from "react-router-dom";


const {Paragraph, Text} = Typography

export const AvitoOAuthCallbackPage: React.FC = () => {
    const navigate = useNavigate();
    const [searchParams] = useSearchParams();
    const hasSubmittedRef = useRef(false)

    const completeOAuthMutation = useCompleteAvitoOAuthMutation();

    const code = searchParams.get("code") ?? undefined
    const state = searchParams.get("state") ?? undefined
    const avitoError = searchParams.get("error") ?? undefined
    const avitoErrorDescription = searchParams.get("error_description") ?? undefined
    const hasRequiredParams = Boolean(code && state);

    useEffect(() => {
        if (hasSubmittedRef.current || avitoError || !hasRequiredParams) {
            return;
        }

        hasSubmittedRef.current = true

        completeOAuthMutation.mutate({
            code,
            state
        })

    }, [avitoError, code, completeOAuthMutation, hasRequiredParams, state]);

    const goToProjects = () => {
        navigate("/projects", {replace: true});
    };

    if (avitoError) {
        return (
            <Result
                status="error"
                title="Авито отклонил подключение"
                subTitle={avitoErrorDescription ?? avitoError}
                extra={
                    <Button
                        type="primary"
                        onClick={goToProjects}
                    >
                        Вернуться к Avito-аккаунтам
                    </Button>
                }
            />
        )
    }

    if (!hasRequiredParams) {
        return (
            <Result
                status="error"
                title="Некорректный ответ Avito"
                subTitle="В callback URL нет обязательных параметров code и state."
                extra={
                    <Button
                        type="primary"
                        onClick={goToProjects}
                    >
                        Вернуться к Avito-аккаунтам
                    </Button>
                }
            />
        );
    }

    if (completeOAuthMutation.isSuccess) {
        return (
            <Result
                status="success"
                title="Avito-аккаунт подключен"
                subTitle={`External account ID: ${
                    completeOAuthMutation.data.external_account_id ?? "не получен"
                }`}
                extra={
                    <Button
                        type="primary"
                        onClick={goToProjects}
                    >
                        Вернуться к Avito-аккаунтам
                    </Button>
                }
            />
        );
    }

    if (completeOAuthMutation.isError) {
        return (
            <Result
                status="error"
                title="Не удалось подключить Avito-аккаунт"
                subTitle="Попробуйте повторить подключение из настроек Avito-аккаунтов."
                extra={
                    <Button
                        type="primary"
                        onClick={goToProjects}
                    >
                        Вернуться к Avito-аккаунтам
                    </Button>
                }
            />
        );
    }

    return (
        <Result
            icon={<Spin size="large"/>}
            title="Подключаем Avito-аккаунт"
            subTitle={
                <Paragraph>
                    <Text type="secondary">
                        Проверяем OAuth-код и сохраняем связь с кабинетом.
                    </Text>
                </Paragraph>
            }
        />
    );
}