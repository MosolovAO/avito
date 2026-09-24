from collections.abc import Mapping

from rest_framework import serializers

from automations.models import (
    Automation,
    AutomationRun,
    AvitoListingDecision,
    AvitoListingRunResult,
)


class RejectUnknownFieldsMixin:
    """Запрещает неизвестные поля во входном API payload."""

    def to_internal_value(self, data):
        if isinstance(data, Mapping):
            unknown_fields = set(data) - set(self.fields)
            if unknown_fields:
                raise serializers.ValidationError({
                    field: "Неизвестное поле."
                    for field in sorted(unknown_fields)
                })

        return super().to_internal_value(data)


class AutomationCreateSerializer(
    RejectUnknownFieldsMixin,
    serializers.Serializer,
):
    name = serializers.CharField(
        max_length=255,
        allow_blank=False,
    )
    module_type = serializers.CharField(
        max_length=64,
        allow_blank=False,
    )
    config = serializers.JSONField()


class AutomationUpdateSerializer(
    RejectUnknownFieldsMixin,
    serializers.Serializer,
):
    name = serializers.CharField(
        max_length=255,
        allow_blank=False,
        required=False,
    )
    state = serializers.ChoiceField(
        choices=(
            Automation.State.DRAFT,
            Automation.State.ENABLED,
            Automation.State.DISABLED,
        ),
        required=False,
    )
    config = serializers.JSONField(required=False)


class AutomationRunRequestSerializer(
    RejectUnknownFieldsMixin,
    serializers.Serializer,
):
    """Проверяет, что команда запуска не содержит входных полей."""

    pass


class AutomationReadSerializer(serializers.ModelSerializer):
    config = serializers.SerializerMethodField()
    created_by = serializers.PrimaryKeyRelatedField(read_only=True)
    updated_by = serializers.PrimaryKeyRelatedField(read_only=True)

    class Meta:
        model = Automation
        fields = (
            "id",
            "name",
            "module_type",
            "state",
            "execution_mode",
            "version",
            "config",
            "created_by",
            "updated_by",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields

    def get_config(self, automation):
        config = automation.avito_listing_config

        return {
            "avito_account_id": config.avito_account_id,
            "condition_tree": config.condition_tree,
            "action": {
                "type": config.action_type,
                "config": config.action_config,
            },
            "max_actions_per_run": config.max_actions_per_run,
            "approval_ttl_minutes": config.approval_ttl_minutes,
        }


class AvitoListingRunSummarySerializer(serializers.ModelSerializer):
    avito_account_id = serializers.IntegerField(read_only=True)

    class Meta:
        model = AvitoListingRunResult
        fields = (
            "avito_account_id",
            "as_of_date",
            "checked",
            "ineligible",
            "insufficient_coverage",
            "not_matched",
            "matched",
            "deferred_by_run_limit",
            "pending_approval",
            "completed_actions",
            "failed_actions",
        )
        read_only_fields = fields


class AvitoListingRunDetailSerializer(
    AvitoListingRunSummarySerializer,
):
    class Meta(AvitoListingRunSummarySerializer.Meta):
        fields = AvitoListingRunSummarySerializer.Meta.fields + (
            "max_actions_per_run_snapshot",
            "approval_ttl_minutes_snapshot",
            "target_max_id_snapshot",
            "condition_snapshot",
            "action_snapshot",
            "examples_snapshot",
        )


class AutomationRunListSerializer(serializers.ModelSerializer):
    automation_id = serializers.IntegerField(read_only=True)
    kind = serializers.CharField(
        source="run_kind",
        read_only=True,
    )
    execution_mode = serializers.CharField(
        source="execution_mode_snapshot",
        read_only=True,
    )
    automation_name = serializers.CharField(
        source="automation_name_snapshot",
        read_only=True,
    )
    module_type = serializers.CharField(
        source="module_type_snapshot",
        read_only=True,
    )
    created_by = serializers.PrimaryKeyRelatedField(read_only=True)
    error = serializers.SerializerMethodField()
    result = AvitoListingRunSummarySerializer(
        source="avito_listing_result",
        read_only=True,
    )

    class Meta:
        model = AutomationRun
        fields = (
            "id",
            "automation_id",
            "kind",
            "trigger",
            "execution_mode",
            "automation_version",
            "automation_name",
            "module_type",
            "status",
            "error",
            "result",
            "created_by",
            "started_at",
            "finished_at",
            "created_at",
        )
        read_only_fields = fields

    def get_error(self, run):
        if not run.error_code and not run.error_message:
            return None

        return {
            "code": run.error_code,
            "message": run.error_message,
        }


class AutomationRunDetailSerializer(AutomationRunListSerializer):
    result = AvitoListingRunDetailSerializer(
        source="avito_listing_result",
        read_only=True,
    )

    class Meta(AutomationRunListSerializer.Meta):
        fields = AutomationRunListSerializer.Meta.fields + (
            "retry_count",
            "data_wait_attempt_count",
            "next_attempt_at",
            "wait_started_at",
            "updated_at",
        )


class AvitoListingDecisionListSerializer(serializers.ModelSerializer):
    run_id = serializers.IntegerField(read_only=True)
    automation_id = serializers.IntegerField(read_only=True)
    avito_account_id = serializers.IntegerField(read_only=True)

    listing_id = serializers.IntegerField(
        source="listing_id_snapshot",
        read_only=True,
    )
    listing = serializers.JSONField(
        source="listing_snapshot",
        read_only=True,
    )
    active_since = serializers.DateTimeField(
        source="active_since_snapshot",
        read_only=True,
    )
    metrics = serializers.JSONField(
        source="metrics_snapshot",
        read_only=True,
    )
    action = serializers.JSONField(
        source="action_snapshot",
        read_only=True,
    )

    approved_by = serializers.IntegerField(
        source="approved_by_id",
        read_only=True,
        allow_null=True,
    )
    rejected_by = serializers.IntegerField(
        source="rejected_by_id",
        read_only=True,
        allow_null=True,
    )

    error = serializers.SerializerMethodField()

    class Meta:
        model = AvitoListingDecision
        fields = (
            "id",
            "run_id",
            "automation_id",
            "avito_account_id",
            "listing_id",
            "listing",
            "status",
            "automation_version",
            "active_since",
            "metrics",
            "action",
            "expires_at",
            "approved_by",
            "approved_at",
            "rejected_by",
            "rejected_at",
            "action_applied_at",
            "completed_at",
            "terminal_at",
            "required_export_revision",
            "effect_attempts",
            "next_effect_retry_at",
            "error",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields

    def get_error(self, decision):
        if not decision.error_code and not decision.error_message:
            return None

        return {
            "code": decision.error_code,
            "message": decision.error_message,
        }
