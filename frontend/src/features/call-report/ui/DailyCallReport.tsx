import { useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { Alert, Button, Empty, Input, Space, Spin, message } from "antd";

import { getCallDailyReport } from "../../../shared/api/calls";
import styles from "./DailyCallReport.module.scss";
import { CloseOutlined, CopyOutlined } from "@ant-design/icons";

interface DailyCallReportProps {
  workspaceId: number;
  accountId: number;
  date: string;
  dateLabel: string;
  heading: ReactNode;
}

function DailyCallReportPreview({
  workspaceId,
  accountId,
  date,
  dateLabel,
  onClose,
}: DailyCallReportProps & { onClose: () => void }) {
  const [copying, setCopying] = useState(false);
  const query = useQuery({
    queryKey: ["calls", workspaceId, accountId, "daily-report", date],
    queryFn: ({ signal }) =>
      getCallDailyReport({
        workspaceId,
        avitoAccountId: accountId,
        date,
        signal,
      }),
    staleTime: 0,
    retry: false,
  });
  const loading = query.isPending || query.isFetching;

  async function copyReport() {
    if (!query.data || loading || copying) return;

    setCopying(true);
    try {
      await navigator.clipboard.writeText(query.data.report_text);
      message.success("Отчет скопирован");
    } catch {
      message.error("Не удалось скопировать отчет.");
    } finally {
      setCopying(false);
    }
  }

  return (
    <section
      role="region"
      aria-label={`Дневной отчет за ${dateLabel}`}
      className={styles.preview}>
      <Space wrap>
        <Space>
          {!loading && query.isSuccess && query.data.report_count > 0 && (
            <Button
              type="primary"
              icon={<CopyOutlined aria-hidden="true" />}
              loading={copying}
              disabled={copying}
              onClick={() => void copyReport()}>
              Копировать отчет
            </Button>
          )}

          <Button
            type="primary"
            danger
            icon={<CloseOutlined aria-hidden="true" />}
            onClick={onClose}>
            Закрыть отчет
          </Button>
        </Space>
      </Space>

      {loading && <Spin aria-label="Формирование дневного отчета" />}

      {!loading && query.isError && (
        <Alert
          type="error"
          showIcon
          title="Не удалось сформировать отчет"
          action={
            <Button onClick={() => void query.refetch()}>Повторить</Button>
          }
        />
      )}

      {!loading &&
        query.isSuccess &&
        (query.data.report_count === 0 ? (
          <Empty description="За этот день нет сохраненных отчетов" />
        ) : (
          <>
            <Input.TextArea
              aria-label="Текст дневного отчета"
              readOnly
              rows={10}
              value={query.data.report_text}
            />
          </>
        ))}
    </section>
  );
}

export function DailyCallReport(props: DailyCallReportProps) {
  const [open, setOpen] = useState(false);

  return (
    <div className={styles.root}>
      <div className={styles.header}>
        <div className={styles.heading}>{props.heading}</div>

        <Button
          type="primary"
          className={styles.action}
          aria-label={`Отчет за день, ${props.dateLabel}`}
          disabled={open}
          onClick={() => setOpen(true)}>
          Отчет за день
        </Button>
      </div>

      {open && (
        <DailyCallReportPreview {...props} onClose={() => setOpen(false)} />
      )}
    </div>
  );
}
