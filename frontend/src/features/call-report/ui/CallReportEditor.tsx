import {useMutation, useQueryClient} from "@tanstack/react-query";
import {Button, Form, Input, Space, message} from "antd";

import {
    saveCallReport,
    type CallRecord,
} from "../../../shared/api/calls";

interface CallReportEditorProps {
    call: CallRecord;
    workspaceId: number;
    accountId: number;
    onClose: () => void;
}

interface ReportFormValues {
    report_text: string;
}

export function CallReportEditor({
                                     call, workspaceId, accountId, onClose,
                                 }: CallReportEditorProps) {
    const queryClient = useQueryClient();

    const save = useMutation({
        mutationFn: (reportText: string) =>
            saveCallReport(workspaceId, call.id, reportText),
        onSuccess: async () => {
            await queryClient.invalidateQueries({
                queryKey: ["calls", workspaceId, accountId],
            });
            onClose();
            message.success("Отчет сохранен");
        },
        onError: () => {
            message.error("Не удалось сохранить отчет.");
        },
    });

    return (
        <section
            role="region"
            aria-label="Редактор отчета по звонку"
        >
            <Form<ReportFormValues>
                layout="vertical"
                disabled={save.isPending}
                initialValues={{report_text: call.report_text}}
                onFinish={({report_text}) => {
                    if (!save.isPending) save.mutate(report_text);
                }}
            >
                <Form.Item
                    name="report_text"
                    label="Краткий итог звонка"
                    rules={[
                        {
                            required: true,
                            whitespace: true,
                            message: "Введите текст отчета.",
                        },
                        {
                            max: 20_000,
                            message: "Максимум 20 000 символов.",
                        },
                    ]}
                >
                    <Input.TextArea
                        autoSize={{minRows: 8, maxRows: 18}}
                        maxLength={20_000}
                        showCount
                        placeholder="Введите краткий итог звонка"
                    />
                </Form.Item>

                <Space>
                    <Button disabled={save.isPending} onClick={onClose}>
                        Отменить
                    </Button>
                    <Button
                        type="primary"
                        htmlType="submit"
                        loading={save.isPending}
                        disabled={save.isPending}
                    >
                        Сохранить
                    </Button>
                </Space>
            </Form>
        </section>
    );
}