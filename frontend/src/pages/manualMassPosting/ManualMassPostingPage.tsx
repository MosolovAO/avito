// src/pages/manualMassPosting/ManualMassPostingPage.tsx
import React from "react";
import {
  Alert,
  Button,
  Form,
  Input,
  Select,
  Space,
  Typography,
} from "antd";
import { useNavigate } from "react-router-dom";
import {
  useAvitoProjectsQuery,
  useCreateManualMassPostingMutation,
} from "../../features/avito";
import { useCurrentWorkspace } from "../../features/workspace/model/useCurrentWorkspace";
import type { JsonObject } from "../../entities/avito/types";

const { Title, Text } = Typography;

interface ManualMassPostingFormValues {
  avito_account_ids: number[];
  title: string;
  description: string;
  image_urls?: string;
  addresses: string;
  base_data?: string;
  option_data?: string;
}

const parseLines = (value?: string): string[] => {
  return (value ?? "")
    .split("\n")
    .map((item) => item.trim())
    .filter(Boolean);
};

const parseJsonObject = (
  value: string | undefined,
  fieldLabel: string,
): JsonObject => {
  if (!value?.trim()) {
    return {};
  }

  try {
    const parsed = JSON.parse(value);

    if (
      parsed === null ||
      Array.isArray(parsed) ||
      typeof parsed !== "object"
    ) {
      throw new Error(`${fieldLabel} должен быть JSON-объектом`);
    }

    return parsed as JsonObject;
  } catch (error) {
    if (error instanceof Error) {
      throw new Error(`${fieldLabel}: ${error.message}`);
    }

    throw new Error(`${fieldLabel}: некорректный JSON`);
  }
};

export const ManualMassPostingPage: React.FC = () => {
  const navigate = useNavigate();
  const [form] = Form.useForm<ManualMassPostingFormValues>();

  const { currentWorkspace, canManageAvitoAccounts } = useCurrentWorkspace();
  const projectsQuery = useAvitoProjectsQuery();
  const createMassPostingMutation = useCreateManualMassPostingMutation();

  const connectedProjectOptions = (projectsQuery.data ?? [])
    .filter((project) => project.external_account_id)
    .map((project) => ({
      value: project.id,
      label: project.name,
    }));

  const handleSubmit = async () => {
    const values = await form.validateFields();

    try {
      const addresses = parseLines(values.addresses);
      const imageUrls = parseLines(values.image_urls);

      if (addresses.length === 0) {
        form.setFields([
          {
            name: "addresses",
            errors: ["Добавьте хотя бы один адрес"],
          },
        ]);
        return;
      }

      const result = await createMassPostingMutation.mutateAsync({
        avito_account_ids: values.avito_account_ids,
        title: values.title.trim(),
        description: values.description.trim(),
        addresses,
        image_urls: imageUrls,
        base_data: parseJsonObject(values.base_data, "base_data"),
        option_data: parseJsonObject(values.option_data, "option_data"),
      });

      navigate(`/ads/publications?batch=${result.batch.id}`);
    } catch (error) {
      if (!(error instanceof Error)) {
        return;
      }

      const fieldName = error.message.startsWith("option_data")
        ? "option_data"
        : "base_data";

      form.setFields([
        {
          name: fieldName,
          errors: [error.message],
        },
      ]);
    }
  };

  if (!currentWorkspace) {
    return (
      <Alert
        type="warning"
        message="Кабинет не выбран"
        description="Выберите кабинет, чтобы создать ручной масс-постинг."
        showIcon
      />
    );
  }

  if (!canManageAvitoAccounts) {
    return (
      <Alert
        type="warning"
        message="Недостаточно прав"
        description="Ручной масс-постинг доступен только пользователям с правом управления Avito."
        showIcon
      />
    );
  }

  return (
    <Space direction="vertical" size={16} style={{ width: "100%" }}>
      <Space direction="vertical" size={0}>
        <Title level={2} style={{ margin: 0 }}>
          Ручной масс-постинг
        </Title>
        <Text type="secondary">
          Создает один общий креатив и публикации по выбранным проектам и адресам.
        </Text>
      </Space>

      <Form
        form={form}
        layout="vertical"
        style={{ maxWidth: 900 }}
        initialValues={{
          avito_account_ids: [],
          base_data: "{}",
          option_data: "{}",
        }}
      >
        <Form.Item
          name="avito_account_ids"
          label="Проекты"
          rules={[
            { required: true, message: "Выберите хотя бы один проект" },
          ]}
        >
          <Select
            mode="multiple"
            loading={projectsQuery.isLoading}
            options={connectedProjectOptions}
            placeholder="Выберите проекты с подключенным Avito API"
          />
        </Form.Item>

        {connectedProjectOptions.length === 0 && (
          <Alert
            type="info"
            message="Нет подключенных проектов"
            description="Сначала подключите Avito API в разделе Проекты."
            showIcon
          />
        )}

        <Form.Item
          name="title"
          label="Заголовок"
          rules={[
            { required: true, message: "Введите заголовок" },
            { max: 255, message: "Максимум 255 символов" },
          ]}
        >
          <Input />
        </Form.Item>

        <Form.Item
          name="description"
          label="Описание"
          rules={[{ required: true, message: "Введите описание" }]}
        >
          <Input.TextArea rows={8} />
        </Form.Item>

        <Form.Item
          name="image_urls"
          label="Изображения"
          extra="Один URL на строку."
        >
          <Input.TextArea rows={6} />
        </Form.Item>

        <Form.Item
          name="addresses"
          label="Адреса"
          extra="Один адрес на строку. Для каждого адреса будет создана отдельная публикация."
          rules={[{ required: true, message: "Введите адреса" }]}
        >
          <Input.TextArea rows={8} />
        </Form.Item>

        <Form.Item
          name="base_data"
          label="base_data"
          extra="JSON-объект с общими CSV-полями. Например: { &quot;Price&quot;: 12000 }"
        >
          <Input.TextArea rows={8} />
        </Form.Item>

        <Form.Item
          name="option_data"
          label="option_data"
          extra="JSON-объект с параметрами Avito."
        >
          <Input.TextArea rows={8} />
        </Form.Item>

        <Space>
          <Button
            type="primary"
            loading={createMassPostingMutation.isPending}
            disabled={connectedProjectOptions.length === 0}
            onClick={handleSubmit}
          >
            Создать публикации
          </Button>

          <Button onClick={() => navigate("/ads/publications")}>
            Отмена
          </Button>
        </Space>
      </Form>
    </Space>
  );
};
