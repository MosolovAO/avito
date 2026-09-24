import json
from dataclasses import replace
from datetime import date, datetime, timedelta
from importlib import import_module
from queue import Queue
from threading import Event, Thread
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from django.apps import apps
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import (
    IntegrityError,
    OperationalError,
    close_old_connections,
    connection,
    transaction,
)
from django.db.models.deletion import RestrictedError
from django.test import SimpleTestCase, TestCase, TransactionTestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import Workspace, WorkspaceMembership
from analytics.models import (
    AvitoListingDailyStats,
    AvitoListingStatsCoverage,
    AvitoStatsSyncState,
)
from avitotask.models import (
    AdCreative,
    AdPublication,
    AvitoAccount,
    AvitoListing,
)


def build_condition_tree(*conditions, operators=None):
    if operators is None:
        operators = ["and"] * max(0, len(conditions) - 1)

    return {
        "type": "group",
        "operators": [],
        "children": [
            {
                "type": "group",
                "operators": operators,
                "children": list(conditions),
            },
        ],
    }


class AutomationsAppRegistrationTests(SimpleTestCase):
    def test_automations_app_is_registered(self):
        self.assertTrue(apps.is_installed("automations"))


class AutomationCeleryQueueConfigurationTests(SimpleTestCase):
    def test_single_worker_declares_default_and_automation_queues(self):
        celery_app = import_module("system.celery").app
        queues = celery_app.amqp.queues

        self.assertTrue(
            {"celery", "automations"}.issubset(
                queues.keys(),
            ),
            (
                "Единственный MVP worker должен слушать основную "
                "очередь celery и очередь automations."
            ),
        )
        self.assertEqual(queues["celery"].routing_key, "celery")
        self.assertEqual(
            queues["automations"].routing_key,
            "automations",
        )


class AutomationCorsConfigurationTests(SimpleTestCase):
    def test_idempotency_key_header_is_allowed_for_browser_commands(self):
        self.assertIn(
            "idempotency-key",
            {
                header.lower()
                for header in settings.CORS_ALLOW_HEADERS
            },
            (
                "Браузер должен пропускать обязательный "
                "Idempotency-Key для preview и run команд."
            ),
        )


class AvitoListingCatalogTests(SimpleTestCase):
    module_path = "automations.modules.avito_listings.catalog"

    def get_catalog_module(self):
        try:
            return import_module(self.module_path)
        except ModuleNotFoundError as exc:
            expected_missing_modules = {
                "automations.modules",
                "automations.modules.avito_listings",
                self.module_path,
            }
            if exc.name not in expected_missing_modules:
                raise

            self.fail(
                "Модуль объявлений Avito должен предоставлять явный catalog.",
            )

    def test_catalog_contains_only_approved_mvp_codes_and_limits(self):
        catalog_module = self.get_catalog_module()

        self.assertEqual(
            set(catalog_module.METRICS_BY_CODE),
            {"views", "contacts"},
        )
        self.assertEqual(
            set(catalog_module.AGGREGATIONS_BY_CODE),
            {"sum"},
        )
        self.assertEqual(
            set(catalog_module.COMPARATORS_BY_CODE),
            {"lt", "lte", "eq", "gte", "gt"},
        )
        self.assertEqual(
            set(catalog_module.ACTIONS_BY_CODE),
            {"pause", "archive"},
        )
        self.assertEqual(
            catalog_module.CONDITION_LIMITS,
            {
                "min_window_days": 1,
                "max_window_days": 365,
                "max_conditions": 50,
            },
        )

    def test_metric_definitions_reference_real_stats_and_coverage_fields(self):
        catalog_module = self.get_catalog_module()

        for code in ("views", "contacts"):
            with self.subTest(metric=code):
                definition = catalog_module.METRICS_BY_CODE[code]

                self.assertEqual(definition.code, code)
                self.assertEqual(definition.value_type, "integer")
                self.assertEqual(
                    set(definition.allowed_aggregations),
                    {"sum"},
                )
                self.assertEqual(definition.stats_field, code)
                self.assertEqual(
                    definition.coverage_from_field,
                    "coverage_from",
                )
                self.assertEqual(
                    definition.coverage_through_field,
                    "finalized_through",
                )
                self.assertTrue(definition.label)
                self.assertTrue(definition.description)

    def test_catalog_payload_is_safe_json_without_python_import_paths(self):
        catalog_module = self.get_catalog_module()

        payload = catalog_module.build_catalog_payload()
        serialized_payload = json.dumps(payload, ensure_ascii=False)

        self.assertEqual(payload["module_type"], "avito_listings")
        self.assertEqual(
            {metric["code"] for metric in payload["metrics"]},
            {"views", "contacts"},
        )
        self.assertEqual(
            {action["code"] for action in payload["actions"]},
            {"pause", "archive"},
        )
        for action in payload["actions"]:
            with self.subTest(action=action["code"]):
                self.assertEqual(
                    action["config_schema"],
                    {
                        "type": "object",
                        "properties": {},
                        "additionalProperties": False,
                    },
                )
        self.assertNotIn("import_path", serialized_payload)
        self.assertNotIn("callable", serialized_payload)


class AvitoListingConditionTreeStructureTests(SimpleTestCase):
    module_path = "automations.modules.avito_listings.validators"

    def get_validator_module(self):
        try:
            return import_module(self.module_path)
        except ModuleNotFoundError as exc:
            expected_missing_modules = {
                self.module_path,
            }
            if exc.name not in expected_missing_modules:
                raise

            self.fail(
                "Модуль объявлений Avito должен предоставлять validator.",
            )

    def assert_tree_error(self, tree, *, code, path):
        validator_module = self.get_validator_module()

        with self.assertRaises(
                validator_module.ConditionTreeValidationError,
        ) as caught:
            validator_module.validate_condition_tree(tree)

        self.assertEqual(caught.exception.code, code)
        self.assertEqual(caught.exception.path, path)

    def build_condition(self, **overrides):
        condition = {
            "type": "condition",
            "metric": "contacts",
            "aggregation": "sum",
            "window_days": 10,
            "comparator": "lt",
            "value": 10,
        }
        condition.update(overrides)
        return condition

    def build_group(self, *conditions, operators=None):
        if operators is None:
            operators = ["and"] * max(0, len(conditions) - 1)

        return {
            "type": "group",
            "operators": operators,
            "children": list(conditions),
        }

    def build_tree(self, *groups, operators=None):
        if operators is None:
            operators = ["and"] * max(0, len(groups) - 1)

        return {
            "type": "group",
            "operators": operators,
            "children": list(groups),
        }

    def test_accepts_flat_groups_with_mixed_operators_without_mutation(self):
        validator_module = self.get_validator_module()
        tree = self.build_tree(
            self.build_group(
                self.build_condition(),
                self.build_condition(
                    metric="views",
                    window_days=5,
                    comparator="eq",
                    value=0,
                ),
                operators=["or"],
            ),
            self.build_group(self.build_condition(value=5)),
            operators=["and"],
        )
        original_tree = json.loads(json.dumps(tree))

        result = validator_module.validate_condition_tree(tree)

        self.assertIs(result, tree)
        self.assertEqual(tree, original_tree)

    def test_root_must_be_a_group_object(self):
        invalid_roots = (
            None,
            [],
            "group",
            self.build_condition(),
        )

        for tree in invalid_roots:
            with self.subTest(tree=tree):
                self.assert_tree_error(
                    tree,
                    code="invalid_root",
                    path="condition_tree",
                )

    def test_group_requires_operators_and_non_empty_children_list(self):
        cases = (
            (
                {
                    "type": "group",
                    "children": [
                        self.build_group(self.build_condition()),
                    ],
                },
                "missing_field",
                "condition_tree.operators",
            ),
            (
                {
                    "type": "group",
                    "operators": [],
                },
                "missing_field",
                "condition_tree.children",
            ),
            (
                {
                    "type": "group",
                    "operators": [],
                    "children": {},
                },
                "invalid_children",
                "condition_tree.children",
            ),
            (
                {
                    "type": "group",
                    "operators": [],
                    "children": [],
                },
                "empty_children",
                "condition_tree.children",
            ),
        )

        for tree, code, path in cases:
            with self.subTest(code=code):
                self.assert_tree_error(tree, code=code, path=path)

    def test_operators_must_be_a_list_with_one_valid_item_per_gap(self):
        two_groups = [
            self.build_group(self.build_condition()),
            self.build_group(self.build_condition()),
        ]
        cases = (
            (
                {
                    "type": "group",
                    "operators": "and",
                    "children": two_groups,
                },
                "invalid_operators",
                "condition_tree.operators",
            ),
            (
                {
                    "type": "group",
                    "operators": [],
                    "children": two_groups,
                },
                "invalid_operators_count",
                "condition_tree.operators",
            ),
            (
                {
                    "type": "group",
                    "operators": ["xor"],
                    "children": two_groups,
                },
                "invalid_operator",
                "condition_tree.operators[0]",
            ),
        )

        for tree, code, path in cases:
            with self.subTest(code=code):
                self.assert_tree_error(tree, code=code, path=path)

    def test_root_may_contain_only_groups(self):
        self.assert_tree_error(
            self.build_tree(self.build_condition()),
            code="invalid_root_child",
            path="condition_tree.children[0]",
        )

    def test_user_group_may_contain_only_conditions(self):
        tree = self.build_tree(
            self.build_group(
                self.build_group(self.build_condition()),
            ),
        )

        self.assert_tree_error(
            tree,
            code="nested_group",
            path="condition_tree.children[0].children[0]",
        )

    def test_rejects_unknown_node_type_and_non_object_child(self):
        cases = (
            (
                {
                    "type": "unknown",
                },
                "unknown_node_type",
            ),
            (
                "condition",
                "invalid_node",
            ),
        )

        for child, code in cases:
            with self.subTest(code=code):
                self.assert_tree_error(
                    self.build_tree(
                        self.build_group(child),
                    ),
                    code=code,
                    path="condition_tree.children[0].children[0]",
                )

    def test_rejects_unknown_group_and_condition_fields(self):
        cases = (
            (
                {
                    "type": "group",
                    "operators": [],
                    "children": [
                        self.build_group(self.build_condition()),
                    ],
                    "unexpected": True,
                },
                "condition_tree.unexpected",
            ),
            (
                self.build_tree(
                    self.build_group(
                        self.build_condition(unexpected=True),
                    ),
                ),
                "condition_tree.children[0].children[0].unexpected",
            ),
        )

        for tree, path in cases:
            with self.subTest(path=path):
                self.assert_tree_error(
                    tree,
                    code="unknown_field",
                    path=path,
                )

    def test_rejects_cyclic_python_structure(self):
        tree = {
            "type": "group",
            "operators": [],
            "children": [],
        }
        tree["children"].append(tree)

        self.assert_tree_error(
            tree,
            code="cyclic_tree",
            path="condition_tree.children[0]",
        )


class AvitoListingConditionLeafValidationTests(SimpleTestCase):
    module_path = "automations.modules.avito_listings.validators"

    def get_validator_module(self):
        return import_module(self.module_path)

    def build_condition(self, **overrides):
        condition = {
            "type": "condition",
            "metric": "contacts",
            "aggregation": "sum",
            "window_days": 10,
            "comparator": "lt",
            "value": 10,
        }
        condition.update(overrides)
        return condition

    def build_tree(self, *conditions):
        return {
            "type": "group",
            "operators": [],
            "children": [
                {
                    "type": "group",
                    "operators": [
                        "and"
                        for _ in range(max(0, len(conditions) - 1))
                    ],
                    "children": list(conditions),
                },
            ],
        }

    def build_tree_with_groups(self, *groups):
        return {
            "type": "group",
            "operators": [
                "and"
                for _ in range(max(0, len(groups) - 1))
            ],
            "children": list(groups),
        }

    def build_group(self, *conditions):
        return {
            "type": "group",
            "operators": [
                "and"
                for _ in range(max(0, len(conditions) - 1))
            ],
            "children": list(conditions),
        }

    def assert_tree_error(self, tree, *, code, path):
        validator_module = self.get_validator_module()

        with self.assertRaises(
                validator_module.ConditionTreeValidationError,
        ) as caught:
            validator_module.validate_condition_tree(tree)

        self.assertEqual(caught.exception.code, code)
        self.assertEqual(caught.exception.path, path)

    def test_accepts_registered_leaf_values_at_allowed_boundaries(self):
        validator_module = self.get_validator_module()
        tree = self.build_tree(
            self.build_condition(
                metric="views",
                window_days=1,
                comparator="eq",
                value=0,
            ),
            self.build_condition(
                metric="contacts",
                window_days=365,
                comparator="gte",
                value=10,
            ),
        )

        result = validator_module.validate_condition_tree(tree)

        self.assertIs(result, tree)

    def test_condition_requires_every_leaf_field(self):
        required_fields = (
            "metric",
            "aggregation",
            "window_days",
            "comparator",
            "value",
        )

        for field in required_fields:
            condition = self.build_condition()
            del condition[field]

            with self.subTest(field=field):
                self.assert_tree_error(
                    self.build_tree(condition),
                    code="missing_field",
                    path=(
                        "condition_tree.children[0]"
                        f".children[0].{field}"
                    ),
                )

    def test_condition_uses_only_registered_catalog_codes(self):
        cases = (
            ("metric", "clicks", "unknown_metric"),
            ("metric", [], "unknown_metric"),
            ("aggregation", "average", "unknown_aggregation"),
            ("aggregation", {}, "unknown_aggregation"),
            ("comparator", "contains", "unknown_comparator"),
            ("comparator", [], "unknown_comparator"),
        )

        for field, value, code in cases:
            with self.subTest(field=field, value=value):
                self.assert_tree_error(
                    self.build_tree(
                        self.build_condition(**{field: value}),
                    ),
                    code=code,
                    path=(
                        "condition_tree.children[0]"
                        f".children[0].{field}"
                    ),
                )

    def test_aggregation_must_be_allowed_for_selected_metric(self):
        validator_module = self.get_validator_module()
        catalog_module = import_module(
            "automations.modules.avito_listings.catalog",
        )
        tree = self.build_tree(
            self.build_condition(aggregation="average"),
        )
        registered_aggregations = {
            **catalog_module.AGGREGATIONS_BY_CODE,
            "average": object(),
        }

        with patch.object(
                catalog_module,
                "AGGREGATIONS_BY_CODE",
                registered_aggregations,
        ):
            with self.assertRaises(
                    validator_module.ConditionTreeValidationError,
            ) as caught:
                validator_module.validate_condition_tree(tree)

        self.assertEqual(
            caught.exception.code,
            "aggregation_not_allowed",
        )
        self.assertEqual(
            caught.exception.path,
            "condition_tree.children[0].children[0].aggregation",
        )

    def test_window_days_must_be_an_integer_from_1_to_365(self):
        invalid_values = (
            0,
            366,
            -1,
            1.5,
            "10",
            True,
            None,
        )

        for value in invalid_values:
            with self.subTest(value=value):
                self.assert_tree_error(
                    self.build_tree(
                        self.build_condition(window_days=value),
                    ),
                    code="invalid_window_days",
                    path=(
                        "condition_tree.children[0]"
                        ".children[0].window_days"
                    ),
                )

    def test_value_must_be_a_non_negative_integer(self):
        invalid_values = (
            -1,
            1.5,
            "10",
            True,
            None,
        )

        for value in invalid_values:
            with self.subTest(value=value):
                self.assert_tree_error(
                    self.build_tree(
                        self.build_condition(value=value),
                    ),
                    code="invalid_value",
                    path=(
                        "condition_tree.children[0]"
                        ".children[0].value"
                    ),
                )

    def test_tree_accepts_50_conditions_and_rejects_the_51st(self):
        validator_module = self.get_validator_module()
        allowed_tree = self.build_tree_with_groups(
            self.build_group(*[
                self.build_condition()
                for _ in range(25)
            ]),
            self.build_group(*[
                self.build_condition()
                for _ in range(25)
            ]),
        )
        too_large_tree = self.build_tree_with_groups(
            self.build_group(*[
                self.build_condition()
                for _ in range(25)
            ]),
            self.build_group(*[
                self.build_condition()
                for _ in range(26)
            ]),
        )

        self.assertIs(
            validator_module.validate_condition_tree(allowed_tree),
            allowed_tree,
        )
        self.assert_tree_error(
            too_large_tree,
            code="max_conditions_exceeded",
            path="condition_tree.children[1].children[25]",
        )


class AvitoListingActionValidationTests(SimpleTestCase):
    module_path = "automations.modules.avito_listings.validators"

    def get_validator_module(self):
        return import_module(self.module_path)

    def get_action_validator(self):
        validator = getattr(
            self.get_validator_module(),
            "validate_action",
            None,
        )
        self.assertIsNotNone(
            validator,
            "Модуль объявлений Avito должен валидировать действие.",
        )
        return validator

    def assert_action_error(
            self,
            action_type,
            action_config,
            *,
            code,
            path,
    ):
        validator_module = self.get_validator_module()
        validator = self.get_action_validator()

        with self.assertRaises(
                validator_module.ActionValidationError,
        ) as caught:
            validator(action_type, action_config)

        self.assertEqual(caught.exception.code, code)
        self.assertEqual(caught.exception.path, path)

    def test_pause_and_archive_accept_empty_config_without_mutation(self):
        validator = self.get_action_validator()

        for action_type in ("pause", "archive"):
            action_config = {}

            with self.subTest(action_type=action_type):
                result = validator(action_type, action_config)

                self.assertIs(result, action_config)
                self.assertEqual(action_config, {})

    def test_unknown_action_code_is_rejected_safely(self):
        for action_type in ("delete", [], None):
            with self.subTest(action_type=action_type):
                self.assert_action_error(
                    action_type,
                    {},
                    code="unknown_action",
                    path="action.type",
                )

    def test_action_config_must_be_an_object(self):
        for action_config in (None, [], "", 1):
            with self.subTest(action_config=action_config):
                self.assert_action_error(
                    "pause",
                    action_config,
                    code="invalid_action_config",
                    path="action.config",
                )

    def test_unknown_action_config_field_is_rejected(self):
        for action_type in ("pause", "archive"):
            with self.subTest(action_type=action_type):
                self.assert_action_error(
                    action_type,
                    {"bid": 100},
                    code="unknown_action_config_field",
                    path="action.config.bid",
                )


class AutomationModuleRegistryTests(SimpleTestCase):
    module_path = "automations.registry"

    def get_registry_module(self):
        try:
            return import_module(self.module_path)
        except ModuleNotFoundError as exc:
            if exc.name != self.module_path:
                raise

            self.fail(
                "Ядро автоматизаций должно предоставлять явный registry.",
            )

    def build_condition_tree(self):
        return build_condition_tree({
            "type": "condition",
            "metric": "contacts",
            "aggregation": "sum",
            "window_days": 10,
            "comparator": "lt",
            "value": 10,
        })

    def test_registry_contains_only_explicit_avito_listing_module(self):
        registry_module = self.get_registry_module()

        self.assertEqual(
            set(registry_module.MODULES_BY_TYPE),
            {"avito_listings"},
        )

        definition = registry_module.get_module_definition(
            "avito_listings",
        )

        self.assertEqual(definition.module_type, "avito_listings")
        self.assertTrue(callable(definition.build_catalog_payload))
        self.assertTrue(callable(definition.validate_condition_tree))
        self.assertTrue(callable(definition.validate_action))
        get_run_data_readiness = getattr(
            definition,
            "get_run_data_readiness",
            None,
        )
        self.assertIsNotNone(
            get_run_data_readiness,
            "Зарегистрированный модуль должен проверять готовность "
            "данных run.",
        )
        self.assertTrue(callable(get_run_data_readiness))
        evaluate_run = getattr(definition, "evaluate_run", None)
        save_run_evaluation = getattr(
            definition,
            "save_run_evaluation",
            None,
        )
        self.assertIsNotNone(
            evaluate_run,
            "Зарегистрированный модуль должен вычислять run.",
        )
        self.assertIsNotNone(
            save_run_evaluation,
            "Зарегистрированный модуль должен сохранять результат run.",
        )
        self.assertTrue(callable(evaluate_run))
        self.assertTrue(callable(save_run_evaluation))
        for capability_name in (
                "acquire_run_lease",
                "heartbeat_run_lease",
                "release_run_lease",
                "classify_run_error",
        ):
            with self.subTest(capability=capability_name):
                capability = getattr(
                    definition,
                    capability_name,
                    None,
                )
                self.assertIsNotNone(
                    capability,
                    "Зарегистрированный модуль должен предоставлять "
                    "все заявленные capabilities.",
                )
                self.assertTrue(callable(capability))

    def test_registered_module_uses_real_avito_capabilities(self):
        registry_module = self.get_registry_module()
        definition = registry_module.get_module_definition(
            "avito_listings",
        )
        condition_tree = self.build_condition_tree()
        action_config = {}

        self.assertIs(
            definition.validate_condition_tree(condition_tree),
            condition_tree,
        )
        self.assertIs(
            definition.validate_action("pause", action_config),
            action_config,
        )

    def test_unknown_or_invalid_module_type_is_rejected_safely(self):
        registry_module = self.get_registry_module()

        for module_type in ("reports", [], None):
            with self.subTest(module_type=module_type):
                with self.assertRaises(
                        registry_module.UnknownAutomationModuleError,
                ) as caught:
                    registry_module.get_module_definition(module_type)

                self.assertEqual(
                    caught.exception.module_type,
                    module_type,
                )

    def test_registry_is_immutable_and_catalog_payload_is_safe_json(self):
        registry_module = self.get_registry_module()

        with self.assertRaises(TypeError):
            registry_module.MODULES_BY_TYPE["reports"] = object()

        payload = registry_module.build_modules_catalog_payload()
        serialized_payload = json.dumps(payload, ensure_ascii=False)

        self.assertEqual(len(payload), 1)
        self.assertEqual(payload[0]["module_type"], "avito_listings")
        self.assertNotIn("import_path", serialized_payload)
        self.assertNotIn("callable", serialized_payload)


class AutomationRunErrorClassificationTests(SimpleTestCase):
    core_module_path = "automations.error_policy"
    module_policy_path = (
        "automations.modules.avito_listings.error_policy"
    )

    def get_core_policy_module(self):
        try:
            return import_module(self.core_module_path)
        except ModuleNotFoundError as exc:
            if exc.name != self.core_module_path:
                raise

            self.fail(
                "Ядро automations должно предоставлять типизированную "
                "классификацию ошибок run.",
            )

    def get_module_policy(self):
        try:
            return import_module(self.module_policy_path)
        except ModuleNotFoundError as exc:
            if exc.name != self.module_policy_path:
                raise

            self.fail(
                "Модуль объявлений Avito должен классифицировать "
                "собственные ошибки run.",
            )

    def assert_safe_classification(
            self,
            classification,
            *,
            error_code,
            retryable,
            secret,
    ):
        self.assertIsNotNone(classification)
        self.assertEqual(classification.error_code, error_code)
        self.assertEqual(classification.retryable, retryable)
        self.assertTrue(classification.safe_message)
        self.assertNotIn(secret, classification.safe_message)

    def test_database_connection_errors_are_retryable_without_leak(self):
        policy_module = self.get_core_policy_module()
        from django.db import InterfaceError

        for error in (
                OperationalError("secret database DSN"),
                InterfaceError("secret database socket"),
        ):
            with self.subTest(error_type=type(error).__name__):
                classification = (
                    policy_module.classify_infrastructure_error(
                        error,
                    )
                )

                self.assert_safe_classification(
                    classification,
                    error_code="transient_database_error",
                    retryable=True,
                    secret="secret",
                )

    def test_timeouts_are_permanent_for_current_run(self):
        policy_module = self.get_core_policy_module()
        from billiard.exceptions import SoftTimeLimitExceeded

        for error in (
                TimeoutError("secret timeout detail"),
                SoftTimeLimitExceeded("secret celery detail"),
        ):
            with self.subTest(error_type=type(error).__name__):
                classification = (
                    policy_module.classify_infrastructure_error(
                        error,
                    )
                )

                self.assert_safe_classification(
                    classification,
                    error_code="time_limit",
                    retryable=False,
                    secret="secret",
                )

    def test_unknown_infrastructure_error_is_not_assumed_retryable(self):
        policy_module = self.get_core_policy_module()

        classification = (
            policy_module.classify_infrastructure_error(
                RuntimeError("unknown failure"),
            )
        )

        self.assertIsNone(classification)

    def test_avito_validation_and_configuration_errors_do_not_retry(self):
        policy_module = self.get_module_policy()
        evaluator_module = import_module(
            "automations.modules.avito_listings.evaluator",
        )
        readiness_module = import_module(
            "automations.modules.avito_listings.run_readiness",
        )
        lease_module = import_module(
            "automations.modules.avito_listings.run_lease",
        )
        cases = (
            (
                evaluator_module.ConditionPlanCompilationError(
                    code="invalid_root",
                    path="condition_tree",
                    message="secret invalid condition",
                ),
                "validation_error",
            ),
            (
                readiness_module.InvalidAvitoListingRunResultError(
                    run_id=123,
                ),
                "configuration_error",
            ),
            (
                lease_module.RunLeaseTargetError(
                    "secret lease target",
                ),
                "configuration_error",
            ),
        )

        for error, expected_code in cases:
            with self.subTest(error_type=type(error).__name__):
                classification = policy_module.classify_run_error(
                    error,
                )

                self.assert_safe_classification(
                    classification,
                    error_code=expected_code,
                    retryable=False,
                    secret="secret",
                )

    def test_changed_listing_selection_is_stale_without_retry(self):
        policy_module = self.get_module_policy()
        evaluation_module = import_module(
            "automations.modules.avito_listings.evaluation",
        )
        error = evaluation_module.ListingSelectionChangedError(
            checked=1,
            eligible=2,
        )

        classification = policy_module.classify_run_error(error)

        self.assert_safe_classification(
            classification,
            error_code="stale",
            retryable=False,
            secret="Количество eligible-объявлений",
        )

    def test_unknown_module_error_is_left_to_common_fallback(self):
        policy_module = self.get_module_policy()

        classification = policy_module.classify_run_error(
            RuntimeError("unknown module failure"),
        )

        self.assertIsNone(classification)


class AvitoListingEvaluatorTests(SimpleTestCase):
    module_path = "automations.modules.avito_listings.evaluator"

    def get_evaluator_module(self):
        try:
            return import_module(self.module_path)
        except ModuleNotFoundError as exc:
            if exc.name != self.module_path:
                raise

            self.fail(
                "Модуль объявлений Avito должен предоставлять evaluator.",
            )

    def build_condition(self, **overrides):
        condition = {
            "type": "condition",
            "metric": "contacts",
            "aggregation": "sum",
            "window_days": 10,
            "comparator": "lt",
            "value": 10,
        }
        condition.update(overrides)
        return condition

    def build_group(self, *conditions, operators=None):
        if operators is None:
            operators = ["and"] * max(0, len(conditions) - 1)

        return {
            "type": "group",
            "operators": operators,
            "children": list(conditions),
        }

    def build_tree(self, *groups, operators=None):
        if operators is None:
            operators = ["and"] * max(0, len(groups) - 1)

        return {
            "type": "group",
            "operators": operators,
            "children": list(groups),
        }

    def compile_tree(self, tree):
        evaluator_module = self.get_evaluator_module()
        try:
            return evaluator_module.compile_condition_plan(
                tree,
                as_of_date=date(2026, 7, 20),
            )
        except Exception as error:
            self.fail(
                "Валидное дерево нового контракта должно компилироваться: "
                f"{error!r}",
            )

    def test_compile_deduplicates_windows_and_excludes_as_of_date(self):
        tree = self.build_tree(
            self.build_group(
                self.build_condition(),
                self.build_condition(
                    comparator="eq",
                    value=0,
                ),
                self.build_condition(
                    metric="views",
                    window_days=4,
                    comparator="gt",
                    value=100,
                ),
                operators=["and", "or"],
            ),
        )
        original_tree = json.loads(json.dumps(tree))

        plan = self.compile_tree(tree)

        self.assertEqual(plan.as_of_date, date(2026, 7, 20))
        self.assertEqual(
            [
                (
                    window.metric,
                    window.aggregation,
                    window.window_days,
                    window.date_from,
                    window.date_to,
                )
                for window in plan.windows
            ],
            [
                (
                    "contacts",
                    "sum",
                    10,
                    date(2026, 7, 10),
                    date(2026, 7, 19),
                ),
                (
                    "views",
                    "sum",
                    4,
                    date(2026, 7, 16),
                    date(2026, 7, 19),
                ),
            ],
        )
        self.assertIs(
            plan.root.children[0].children[0].window,
            plan.root.children[0].children[1].window,
        )
        self.assertEqual(tree, original_tree)

    def test_compile_rejects_invalid_as_of_date(self):
        evaluator_module = self.get_evaluator_module()
        tree = self.build_tree(
            self.build_group(self.build_condition()),
        )

        for invalid_as_of_date in (None, "2026-07-20", True):
            with self.subTest(as_of_date=invalid_as_of_date):
                with self.assertRaises(
                        evaluator_module.ConditionPlanCompilationError,
                ) as caught:
                    evaluator_module.compile_condition_plan(
                        tree,
                        as_of_date=invalid_as_of_date,
                    )

                self.assertEqual(
                    caught.exception.code,
                    "invalid_as_of_date",
                )
                self.assertEqual(
                    caught.exception.path,
                    "as_of_date",
                )

    def test_evaluator_supports_every_registered_comparator(self):
        evaluator_module = self.get_evaluator_module()
        cases = (
            ("lt", 9, 10, True),
            ("lt", 10, 10, False),
            ("lte", 10, 10, True),
            ("lte", 11, 10, False),
            ("eq", 10, 10, True),
            ("eq", 9, 10, False),
            ("gte", 10, 10, True),
            ("gte", 9, 10, False),
            ("gt", 11, 10, True),
            ("gt", 10, 10, False),
        )

        for comparator, actual, expected, result in cases:
            with self.subTest(
                    comparator=comparator,
                    actual=actual,
                    expected=expected,
            ):
                plan = self.compile_tree(
                    self.build_tree(
                        self.build_group(
                            self.build_condition(
                                comparator=comparator,
                                value=expected,
                            ),
                        ),
                    ),
                )

                self.assertIs(
                    evaluator_module.evaluate_condition_plan(
                        plan,
                        {plan.windows[0]: actual},
                    ),
                    result,
                )

    def test_and_has_priority_over_or_inside_condition_group(self):
        evaluator_module = self.get_evaluator_module()
        plan = self.compile_tree(
            self.build_tree(
                self.build_group(
                    self.build_condition(
                        metric="contacts",
                        window_days=10,
                        comparator="gt",
                        value=0,
                    ),
                    self.build_condition(
                        metric="views",
                        window_days=4,
                        comparator="gt",
                        value=0,
                    ),
                    self.build_condition(
                        metric="contacts",
                        window_days=5,
                        comparator="gt",
                        value=0,
                    ),
                    operators=["or", "and"],
                ),
            ),
        )
        windows = {
            (window.metric, window.window_days): window
            for window in plan.windows
        }

        self.assertTrue(
            evaluator_module.evaluate_condition_plan(
                plan,
                {
                    windows[("contacts", 10)]: 1,
                    windows[("views", 4)]: 0,
                    windows[("contacts", 5)]: 0,
                },
            ),
        )

    def test_and_has_priority_over_or_between_groups(self):
        evaluator_module = self.get_evaluator_module()
        plan = self.compile_tree(
            self.build_tree(
                self.build_group(
                    self.build_condition(
                        metric="contacts",
                        window_days=10,
                        comparator="gt",
                        value=0,
                    ),
                ),
                self.build_group(
                    self.build_condition(
                        metric="views",
                        window_days=4,
                        comparator="gt",
                        value=0,
                    ),
                ),
                self.build_group(
                    self.build_condition(
                        metric="contacts",
                        window_days=5,
                        comparator="gt",
                        value=0,
                    ),
                ),
                operators=["or", "and"],
            ),
        )
        windows = {
            (window.metric, window.window_days): window
            for window in plan.windows
        }

        self.assertTrue(
            evaluator_module.evaluate_condition_plan(
                plan,
                {
                    windows[("contacts", 10)]: 1,
                    windows[("views", 4)]: 0,
                    windows[("contacts", 5)]: 0,
                },
            ),
        )

    def test_or_requires_values_for_every_window_before_evaluation(self):
        evaluator_module = self.get_evaluator_module()
        plan = self.compile_tree(
            self.build_tree(
                self.build_group(
                    self.build_condition(
                        metric="contacts",
                        comparator="gt",
                        value=0,
                    ),
                    self.build_condition(
                        metric="views",
                        comparator="eq",
                        value=0,
                    ),
                    operators=["or"],
                ),
            ),
        )

        with self.assertRaises(
                evaluator_module.MissingMetricValueError,
        ) as caught:
            evaluator_module.evaluate_condition_plan(
                plan,
                {plan.windows[0]: 10},
            )

        self.assertEqual(caught.exception.window, plan.windows[1])

    def test_evaluator_rejects_invalid_prepared_metric_values(self):
        evaluator_module = self.get_evaluator_module()
        plan = self.compile_tree(
            self.build_tree(
                self.build_group(self.build_condition()),
            ),
        )

        for invalid_value in (None, True, -1, 1.5, "10"):
            with self.subTest(value=invalid_value):
                with self.assertRaises(
                        evaluator_module.InvalidMetricValueError,
                ) as caught:
                    evaluator_module.evaluate_condition_plan(
                        plan,
                        {plan.windows[0]: invalid_value},
                    )

                self.assertEqual(
                    caught.exception.window,
                    plan.windows[0],
                )
                self.assertEqual(
                    caught.exception.value,
                    invalid_value,
                )


class AvitoListingSelectorTests(TestCase):
    module_path = "automations.modules.avito_listings.selectors"

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(
            email="automation-selector-owner@example.com",
            password="test-password",
        )
        cls.workspace = Workspace.objects.create(
            name="Automation selector workspace",
            slug="automation-selector-workspace",
            owner=cls.user,
        )
        cls.avito_account = AvitoAccount.objects.create(
            workspace=cls.workspace,
            name="Selector Avito account",
        )
        cls.other_avito_account = AvitoAccount.objects.create(
            workspace=cls.workspace,
            name="Other selector Avito account",
        )

        cls.other_user = get_user_model().objects.create_user(
            email="automation-selector-other@example.com",
            password="test-password",
        )
        cls.other_workspace = Workspace.objects.create(
            name="Other selector workspace",
            slug="other-selector-workspace",
            owner=cls.other_user,
        )
        cls.other_workspace_account = AvitoAccount.objects.create(
            workspace=cls.other_workspace,
            name="Other workspace Avito account",
        )

        evaluator_module = import_module(
            "automations.modules.avito_listings.evaluator",
        )
        cls.plan = evaluator_module.compile_condition_plan(
            build_condition_tree(
                {
                    "type": "condition",
                    "metric": "contacts",
                    "aggregation": "sum",
                    "window_days": 10,
                    "comparator": "lt",
                    "value": 10,
                },
                {
                    "type": "condition",
                    "metric": "views",
                    "aggregation": "sum",
                    "window_days": 4,
                    "comparator": "gt",
                    "value": 0,
                },
            ),
            as_of_date=date(2026, 7, 20),
        )

        automation_model = apps.get_model("automations", "Automation")
        cls.automation = automation_model.objects.create(
            workspace=cls.workspace,
            module_type="avito_listings",
            name="Selector automation",
            state="enabled",
            created_by=cls.user,
            updated_by=cls.user,
        )
        automation_run_model = apps.get_model(
            "automations",
            "AutomationRun",
        )
        cls.automation_run = automation_run_model.objects.create(
            automation=cls.automation,
            workspace=cls.workspace,
            run_kind="execute",
            trigger="manual",
            execution_mode_snapshot="manual",
            automation_version=1,
            automation_name_snapshot=cls.automation.name,
            module_type_snapshot=cls.automation.module_type,
            status="effect_pending",
            idempotency_key="selector-effects",
            created_by=cls.user,
        )

    def get_selectors_module(self):
        try:
            return import_module(self.module_path)
        except ModuleNotFoundError as exc:
            if exc.name != self.module_path:
                raise

            self.fail(
                "Модуль объявлений Avito должен предоставлять selectors.",
            )

    def local_datetime(self, year, month, day, hour=0, minute=0):
        return timezone.make_aware(
            datetime(year, month, day, hour, minute),
            timezone.get_current_timezone(),
        )

    def create_listing(self, **overrides):
        values = {
            "workspace": self.workspace,
            "avito_account": self.avito_account,
            "avito_id": f"selector-{uuid4()}",
            "management_status": (
                AvitoListing.ManagementStatus.MANAGED
            ),
            "desired_status": AvitoListing.DesiredStatus.PUBLISH,
            "active_since": self.local_datetime(2026, 7, 9, 10),
        }
        values.update(overrides)
        return AvitoListing.objects.create(**values)

    def create_decision(self, listing, *, status):
        decision_model = apps.get_model(
            "automations",
            "AvitoListingDecision",
        )
        return decision_model.objects.create(
            run=self.automation_run,
            automation=self.automation,
            workspace=self.workspace,
            avito_account=self.avito_account,
            listing=listing,
            listing_id_snapshot=listing.id,
            listing_snapshot={
                "id": listing.id,
                "avito_id": listing.avito_id,
            },
            status=status,
            automation_version=1,
            active_since_snapshot=listing.active_since,
            condition_snapshot={},
            metrics_snapshot={},
            action_snapshot={
                "type": "pause",
                "config": {},
            },
            expires_at=timezone.now() + timedelta(hours=24),
        )

    def test_missing_account_sync_state_is_not_ready(self):
        selectors_module = self.get_selectors_module()

        with self.assertNumQueries(1):
            readiness = selectors_module.get_account_stats_readiness(
                workspace=self.workspace,
                avito_account=self.avito_account,
                plan=self.plan,
            )

        self.assertFalse(readiness.is_ready)
        self.assertEqual(readiness.reason, "missing_sync_state")
        self.assertEqual(readiness.required_from, date(2026, 7, 10))
        self.assertEqual(readiness.required_to, date(2026, 7, 19))
        self.assertIsNone(readiness.sync_status)

    def test_confirmed_account_coverage_is_ready_despite_error_status(self):
        selectors_module = self.get_selectors_module()
        AvitoStatsSyncState.objects.create(
            workspace=self.workspace,
            avito_account=self.avito_account,
            status=AvitoStatsSyncState.Status.ERROR,
            coverage_from=date(2026, 7, 1),
            coverage_to=date(2026, 7, 19),
            error="A newer sync failed",
        )

        readiness = selectors_module.get_account_stats_readiness(
            workspace=self.workspace,
            avito_account=self.avito_account,
            plan=self.plan,
        )

        self.assertTrue(readiness.is_ready)
        self.assertIsNone(readiness.reason)
        self.assertEqual(
            readiness.sync_status,
            AvitoStatsSyncState.Status.ERROR,
        )

    def test_incomplete_account_coverage_is_not_ready(self):
        selectors_module = self.get_selectors_module()
        sync_state = AvitoStatsSyncState.objects.create(
            workspace=self.workspace,
            avito_account=self.avito_account,
            status=AvitoStatsSyncState.Status.SUCCESS,
            coverage_from=date(2026, 7, 10),
            coverage_to=date(2026, 7, 19),
        )
        incomplete_ranges = (
            (date(2026, 7, 11), date(2026, 7, 19)),
            (date(2026, 7, 10), date(2026, 7, 18)),
            (None, date(2026, 7, 19)),
            (date(2026, 7, 10), None),
        )

        for coverage_from, coverage_to in incomplete_ranges:
            sync_state.coverage_from = coverage_from
            sync_state.coverage_to = coverage_to
            sync_state.save(
                update_fields=["coverage_from", "coverage_to"],
            )

            with self.subTest(
                    coverage_from=coverage_from,
                    coverage_to=coverage_to,
            ):
                readiness = (
                    selectors_module.get_account_stats_readiness(
                        workspace=self.workspace,
                        avito_account=self.avito_account,
                        plan=self.plan,
                    )
                )

                self.assertFalse(readiness.is_ready)
                self.assertEqual(
                    readiness.reason,
                    "insufficient_account_coverage",
                )

    def test_eligible_rows_are_scoped_stable_and_lightweight(self):
        selectors_module = self.get_selectors_module()
        oldest = self.create_listing(
            active_since=self.local_datetime(2026, 7, 8, 12),
        )
        first_same_time = self.create_listing()
        second_same_time = self.create_listing()
        pending_listing = self.create_listing(
            active_since=self.local_datetime(2026, 7, 9, 11),
        )
        self.create_decision(
            pending_listing,
            status="pending_approval",
        )

        applying_listing = self.create_listing()
        self.create_decision(applying_listing, status="applying")
        effect_pending_listing = self.create_listing()
        self.create_decision(
            effect_pending_listing,
            status="effect_pending",
        )

        self.create_listing(
            management_status=AvitoListing.ManagementStatus.OBSERVED,
        )
        self.create_listing(
            desired_status=AvitoListing.DesiredStatus.PAUSE,
        )
        self.create_listing(active_since=None)
        self.create_listing(
            active_since=self.local_datetime(2026, 7, 10),
        )
        self.create_listing(
            workspace=self.workspace,
            avito_account=self.other_avito_account,
        )
        self.create_listing(
            workspace=self.other_workspace,
            avito_account=self.other_workspace_account,
        )

        target_max_id_snapshot = (
            AvitoListing.objects.order_by("-id").values_list(
                "id",
                flat=True,
            ).first()
        )
        self.create_listing(
            active_since=self.local_datetime(2026, 7, 8),
        )

        with self.assertNumQueries(1):
            rows = list(
                selectors_module.select_eligible_listing_rows(
                    workspace=self.workspace,
                    avito_account=self.avito_account,
                    plan=self.plan,
                    target_max_id_snapshot=target_max_id_snapshot,
                ),
            )

        self.assertEqual(
            [row["id"] for row in rows],
            [
                oldest.id,
                first_same_time.id,
                second_same_time.id,
                pending_listing.id,
            ],
        )
        self.assertTrue(
            all(set(row) == {"id", "active_since"} for row in rows),
        )

    def test_coverage_is_partitioned_in_one_scoped_query(self):
        selectors_module = self.get_selectors_module()
        complete = self.create_listing()
        incomplete = self.create_listing()
        missing = self.create_listing()
        other_account_listing = self.create_listing(
            workspace=self.workspace,
            avito_account=self.other_avito_account,
        )

        AvitoListingStatsCoverage.objects.create(
            workspace=self.workspace,
            listing=complete,
            coverage_from=date(2026, 7, 10),
            finalized_through=date(2026, 7, 19),
        )
        AvitoListingStatsCoverage.objects.create(
            workspace=self.workspace,
            listing=incomplete,
            coverage_from=date(2026, 7, 11),
            finalized_through=date(2026, 7, 19),
        )
        AvitoListingStatsCoverage.objects.create(
            workspace=self.workspace,
            listing=other_account_listing,
            coverage_from=date(2026, 7, 1),
            finalized_through=date(2026, 7, 19),
        )

        with self.assertNumQueries(1):
            partition = (
                selectors_module.partition_listing_ids_by_coverage(
                    workspace=self.workspace,
                    avito_account=self.avito_account,
                    listing_ids=[
                        incomplete.id,
                        complete.id,
                        missing.id,
                        other_account_listing.id,
                    ],
                    plan=self.plan,
                )
            )

        self.assertEqual(
            partition.covered_listing_ids,
            (complete.id,),
        )
        self.assertEqual(
            partition.insufficient_listing_ids,
            (
                incomplete.id,
                missing.id,
                other_account_listing.id,
            ),
        )

    def test_empty_coverage_partition_does_not_query_database(self):
        selectors_module = self.get_selectors_module()

        with self.assertNumQueries(0):
            partition = (
                selectors_module.partition_listing_ids_by_coverage(
                    workspace=self.workspace,
                    avito_account=self.avito_account,
                    listing_ids=[],
                    plan=self.plan,
                )
            )

        self.assertEqual(partition.covered_listing_ids, ())
        self.assertEqual(partition.insufficient_listing_ids, ())

    def test_eligible_selector_does_not_load_heavy_listing_fields(self):
        selectors_module = self.get_selectors_module()
        listing = self.create_listing(
            description="Large listing description",
            image_urls=["https://example.com/image.jpg"],
            base_data={"large": "base-data"},
            option_data={"large": "option-data"},
            raw_data={"large": "raw-data"},
            imported_payload={"large": "imported-payload"},
        )

        with CaptureQueriesContext(connection) as captured_queries:
            rows = list(
                selectors_module.select_eligible_listing_rows(
                    workspace=self.workspace,
                    avito_account=self.avito_account,
                    plan=self.plan,
                    target_max_id_snapshot=listing.id,
                ),
            )

        self.assertEqual(
            rows,
            [{"id": listing.id, "active_since": listing.active_since}],
        )
        self.assertEqual(len(captured_queries), 1)
        selection_sql = captured_queries[0]["sql"].lower()
        for heavy_field in (
            "description",
            "image_urls",
            "base_data",
            "option_data",
            "raw_data",
            "imported_payload",
        ):
            with self.subTest(field=heavy_field):
                self.assertNotIn(
                    f'"avitotask_avitolisting"."{heavy_field}"',
                    selection_sql,
                )


class AvitoListingMetricAggregationTests(TestCase):
    module_path = (
        "automations.modules.avito_listings.metric_aggregation"
    )

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(
            email="automation-aggregation-owner@example.com",
            password="test-password",
        )
        cls.workspace = Workspace.objects.create(
            name="Automation aggregation workspace",
            slug="automation-aggregation-workspace",
            owner=cls.user,
        )
        cls.avito_account = AvitoAccount.objects.create(
            workspace=cls.workspace,
            name="Aggregation Avito account",
        )

        cls.other_user = get_user_model().objects.create_user(
            email="automation-aggregation-other@example.com",
            password="test-password",
        )
        cls.other_workspace = Workspace.objects.create(
            name="Other aggregation workspace",
            slug="other-aggregation-workspace",
            owner=cls.other_user,
        )

        evaluator_module = import_module(
            "automations.modules.avito_listings.evaluator",
        )
        cls.plan = evaluator_module.compile_condition_plan(
            build_condition_tree(
                {
                    "type": "condition",
                    "metric": "contacts",
                    "aggregation": "sum",
                    "window_days": 10,
                    "comparator": "lt",
                    "value": 10,
                },
                {
                    "type": "condition",
                    "metric": "views",
                    "aggregation": "sum",
                    "window_days": 4,
                    "comparator": "gt",
                    "value": 0,
                },
            ),
            as_of_date=date(2026, 7, 20),
        )

    def get_aggregation_module(self):
        try:
            return import_module(self.module_path)
        except ModuleNotFoundError as exc:
            if exc.name != self.module_path:
                raise

            self.fail(
                "Модуль объявлений Avito должен предоставлять "
                "пакетную агрегацию метрик.",
            )

    def create_listing(self):
        return AvitoListing.objects.create(
            workspace=self.workspace,
            avito_account=self.avito_account,
            avito_id=f"aggregation-{uuid4()}",
        )

    def get_statement_timeout(self):
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT current_setting('statement_timeout')",
            )
            return cursor.fetchone()[0]

    def test_aggregates_one_stats_query_and_fills_confirmed_zero(self):
        aggregation_module = self.get_aggregation_module()
        without_stats = self.create_listing()
        with_stats = self.create_listing()
        outside_window = self.create_listing()

        AvitoListingDailyStats.objects.bulk_create([
            AvitoListingDailyStats(
                workspace=self.workspace,
                listing=with_stats,
                date=date(2026, 7, 10),
                views=100,
                contacts=3,
            ),
            AvitoListingDailyStats(
                workspace=self.workspace,
                listing=with_stats,
                date=date(2026, 7, 16),
                views=4,
                contacts=2,
            ),
            AvitoListingDailyStats(
                workspace=self.workspace,
                listing=with_stats,
                date=date(2026, 7, 19),
                views=6,
                contacts=1,
            ),
            AvitoListingDailyStats(
                workspace=self.workspace,
                listing=outside_window,
                date=date(2026, 7, 9),
                views=99,
                contacts=99,
            ),
            AvitoListingDailyStats(
                workspace=self.other_workspace,
                listing=without_stats,
                date=date(2026, 7, 19),
                views=999,
                contacts=999,
            ),
        ])

        timeout_before = self.get_statement_timeout()
        with CaptureQueriesContext(connection) as captured_queries:
            result = (
                aggregation_module.aggregate_listing_metric_windows(
                    workspace=self.workspace,
                    avito_account=self.avito_account,
                    listing_ids=[
                        without_stats.id,
                        with_stats.id,
                        outside_window.id,
                    ],
                    plan=self.plan,
                )
            )
        timeout_after = self.get_statement_timeout()

        stats_queries = [
            query["sql"].lower()
            for query in captured_queries.captured_queries
            if (
                "analytics_avitolistingdailystats"
                in query["sql"].lower()
            )
        ]
        self.assertEqual(len(stats_queries), 1)
        self.assertIn("group by", stats_queries[0])
        self.assertTrue(any(
            "set_config" in query["sql"].lower()
            and "statement_timeout" in query["sql"].lower()
            for query in captured_queries.captured_queries
        ))
        self.assertEqual(timeout_after, timeout_before)

        self.assertEqual(
            tuple(item.listing_id for item in result),
            (
                without_stats.id,
                with_stats.id,
                outside_window.id,
            ),
        )
        windows_by_metric = {
            window.metric: window
            for window in self.plan.windows
        }
        self.assertEqual(
            result[0].metrics_by_window,
            {
                windows_by_metric["contacts"]: 0,
                windows_by_metric["views"]: 0,
            },
        )
        self.assertEqual(
            result[1].metrics_by_window,
            {
                windows_by_metric["contacts"]: 6,
                windows_by_metric["views"]: 10,
            },
        )
        self.assertEqual(
            result[2].metrics_by_window,
            {
                windows_by_metric["contacts"]: 0,
                windows_by_metric["views"]: 0,
            },
        )
        with self.assertRaises(TypeError):
            result[0].metrics_by_window[
                windows_by_metric["contacts"]
            ] = 1

    def test_empty_chunk_does_not_query_and_ids_are_deduplicated(self):
        aggregation_module = self.get_aggregation_module()

        with self.assertNumQueries(0):
            empty_result = (
                aggregation_module.aggregate_listing_metric_windows(
                    workspace=self.workspace,
                    avito_account=self.avito_account,
                    listing_ids=[],
                    plan=self.plan,
                )
            )

        self.assertEqual(empty_result, ())

        listing = self.create_listing()
        result = aggregation_module.aggregate_listing_metric_windows(
            workspace=self.workspace,
            avito_account=self.avito_account,
            listing_ids=[listing.id, listing.id],
            plan=self.plan,
        )

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].listing_id, listing.id)

    def test_only_query_canceled_becomes_domain_timeout(self):
        aggregation_module = self.get_aggregation_module()
        listing = self.create_listing()

        class QueryCanceled(Exception):
            sqlstate = "57014"

        query_canceled = OperationalError("query canceled")
        query_canceled.__cause__ = QueryCanceled()

        with patch.object(
                aggregation_module,
                "_fetch_aggregated_rows",
                side_effect=query_canceled,
        ):
            with self.assertRaises(
                    aggregation_module.MetricAggregationTimeoutError,
            ) as caught:
                aggregation_module.aggregate_listing_metric_windows(
                    workspace=self.workspace,
                    avito_account=self.avito_account,
                    listing_ids=[listing.id],
                    plan=self.plan,
                )

        self.assertEqual(caught.exception.timeout_seconds, 180)

        unrelated_error = OperationalError("connection lost")
        with patch.object(
                aggregation_module,
                "_fetch_aggregated_rows",
                side_effect=unrelated_error,
        ):
            with self.assertRaises(OperationalError) as caught:
                aggregation_module.aggregate_listing_metric_windows(
                    workspace=self.workspace,
                    avito_account=self.avito_account,
                    listing_ids=[listing.id],
                    plan=self.plan,
                )

        self.assertIs(caught.exception, unrelated_error)


class AvitoListingEvaluationTests(TestCase):
    module_path = "automations.modules.avito_listings.evaluation"

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(
            email="automation-evaluation-owner@example.com",
            password="test-password",
        )
        cls.workspace = Workspace.objects.create(
            name="Automation evaluation workspace",
            slug="automation-evaluation-workspace",
            owner=cls.user,
        )
        cls.avito_account = AvitoAccount.objects.create(
            workspace=cls.workspace,
            name="Evaluation Avito account",
        )
        cls.other_avito_account = AvitoAccount.objects.create(
            workspace=cls.workspace,
            name="Other evaluation Avito account",
        )

        cls.other_user = get_user_model().objects.create_user(
            email="automation-evaluation-other@example.com",
            password="test-password",
        )
        cls.other_workspace = Workspace.objects.create(
            name="Other evaluation workspace",
            slug="other-evaluation-workspace",
            owner=cls.other_user,
        )
        cls.other_workspace_account = AvitoAccount.objects.create(
            workspace=cls.other_workspace,
            name="Other workspace evaluation account",
        )

        evaluator_module = import_module(
            "automations.modules.avito_listings.evaluator",
        )
        cls.plan = evaluator_module.compile_condition_plan(
            build_condition_tree({
                "type": "condition",
                "metric": "contacts",
                "aggregation": "sum",
                "window_days": 10,
                "comparator": "lt",
                "value": 10,
            }),
            as_of_date=date(2026, 7, 20),
        )

    def get_evaluation_module(self):
        try:
            return import_module(self.module_path)
        except ModuleNotFoundError as exc:
            if exc.name != self.module_path:
                raise

            self.fail(
                "Модуль объявлений Avito должен предоставлять "
                "пакетный evaluation service.",
            )

    def local_datetime(self, year, month, day, hour=0, minute=0):
        return timezone.make_aware(
            datetime(year, month, day, hour, minute),
            timezone.get_current_timezone(),
        )

    def create_listing(self, **overrides):
        values = {
            "workspace": self.workspace,
            "avito_account": self.avito_account,
            "avito_id": f"evaluation-{uuid4()}",
            "management_status": (
                AvitoListing.ManagementStatus.MANAGED
            ),
            "desired_status": AvitoListing.DesiredStatus.PUBLISH,
            "active_since": self.local_datetime(2026, 7, 9),
        }
        values.update(overrides)
        return AvitoListing.objects.create(**values)

    def confirm_coverage(
            self,
            listing,
            *,
            coverage_from=date(2026, 7, 10),
            finalized_through=date(2026, 7, 19),
    ):
        return AvitoListingStatsCoverage.objects.create(
            workspace=listing.workspace,
            listing=listing,
            coverage_from=coverage_from,
            finalized_through=finalized_through,
        )

    def create_covered_listings(self, count):
        active_since = self.local_datetime(2026, 7, 9)
        listings = AvitoListing.objects.bulk_create([
            AvitoListing(
                workspace=self.workspace,
                avito_account=self.avito_account,
                avito_id=f"evaluation-bulk-{uuid4()}",
                management_status=(
                    AvitoListing.ManagementStatus.MANAGED
                ),
                desired_status=AvitoListing.DesiredStatus.PUBLISH,
                active_since=active_since,
            )
            for _ in range(count)
        ])
        AvitoListingStatsCoverage.objects.bulk_create([
            AvitoListingStatsCoverage(
                workspace=self.workspace,
                listing=listing,
                coverage_from=date(2026, 7, 10),
                finalized_through=date(2026, 7, 19),
            )
            for listing in listings
        ])
        return listings

    def test_counts_orders_limits_and_isolates_evaluation(self):
        evaluation_module = self.get_evaluation_module()

        matched_oldest = self.create_listing(
            active_since=self.local_datetime(2026, 7, 5),
        )
        not_matched = self.create_listing(
            active_since=self.local_datetime(2026, 7, 6),
        )
        insufficient_coverage = self.create_listing(
            active_since=self.local_datetime(2026, 7, 7),
        )
        matched_second = self.create_listing(
            active_since=self.local_datetime(2026, 7, 8),
        )
        self.create_listing(
            active_since=self.local_datetime(2026, 7, 9),
        )

        self.create_listing(
            desired_status=AvitoListing.DesiredStatus.PAUSE,
            active_since=self.local_datetime(2026, 7, 5),
        )
        self.create_listing(
            active_since=self.local_datetime(2026, 7, 15),
        )
        self.create_listing(active_since=None)

        observed = self.create_listing(
            management_status=AvitoListing.ManagementStatus.OBSERVED,
        )
        self.create_listing(
            avito_account=self.other_avito_account,
        )
        self.create_listing(
            workspace=self.other_workspace,
            avito_account=self.other_workspace_account,
        )

        for listing in (
            matched_oldest,
            not_matched,
            matched_second,
        ):
            self.confirm_coverage(listing)
        self.confirm_coverage(
            insufficient_coverage,
            coverage_from=date(2026, 7, 11),
        )
        matched_deferred = (
            AvitoListing.objects
            .filter(
                workspace=self.workspace,
                avito_account=self.avito_account,
                management_status=(
                    AvitoListing.ManagementStatus.MANAGED
                ),
                desired_status=AvitoListing.DesiredStatus.PUBLISH,
                active_since=self.local_datetime(2026, 7, 9),
            )
            .order_by("id")
            .first()
        )
        self.confirm_coverage(matched_deferred)

        AvitoListingDailyStats.objects.bulk_create([
            AvitoListingDailyStats(
                workspace=self.workspace,
                listing=matched_oldest,
                date=date(2026, 7, 19),
                contacts=3,
            ),
            AvitoListingDailyStats(
                workspace=self.workspace,
                listing=not_matched,
                date=date(2026, 7, 19),
                contacts=12,
            ),
        ])

        result = evaluation_module.evaluate_listing_candidates(
            workspace=self.workspace,
            avito_account=self.avito_account,
            plan=self.plan,
            max_actions_per_run=2,
        )

        self.assertEqual(result.target_max_id_snapshot, observed.id)
        self.assertEqual(result.checked, 8)
        self.assertEqual(result.ineligible, 3)
        self.assertEqual(result.insufficient_coverage, 1)
        self.assertEqual(result.not_matched, 1)
        self.assertEqual(result.matched, 3)
        self.assertEqual(result.deferred_by_run_limit, 1)
        self.assertEqual(
            result.checked,
            (
                result.ineligible
                + result.insufficient_coverage
                + result.not_matched
                + result.matched
            ),
        )
        self.assertEqual(
            tuple(
                match.listing_id
                for match in result.selected_matches
            ),
            (matched_oldest.id, matched_second.id),
        )
        self.assertEqual(
            result.selected_matches[0].active_since,
            matched_oldest.active_since,
        )
        window = self.plan.windows[0]
        self.assertEqual(
            result.selected_matches[0].metrics_by_window,
            {window: 3},
        )
        self.assertEqual(
            result.selected_matches[1].metrics_by_window,
            {window: 0},
        )
        with self.assertRaises(TypeError):
            result.selected_matches[0].metrics_by_window[window] = 4
        with self.assertRaises(AttributeError):
            result.matched = 0

    def test_empty_account_and_invalid_action_limit(self):
        evaluation_module = self.get_evaluation_module()
        empty_account = AvitoAccount.objects.create(
            workspace=self.workspace,
            name="Empty evaluation account",
        )

        result = evaluation_module.evaluate_listing_candidates(
            workspace=self.workspace,
            avito_account=empty_account,
            plan=self.plan,
            max_actions_per_run=10,
        )

        self.assertEqual(result.target_max_id_snapshot, 0)
        self.assertEqual(result.checked, 0)
        self.assertEqual(result.ineligible, 0)
        self.assertEqual(result.insufficient_coverage, 0)
        self.assertEqual(result.not_matched, 0)
        self.assertEqual(result.matched, 0)
        self.assertEqual(result.deferred_by_run_limit, 0)
        self.assertEqual(result.selected_matches, ())

        for invalid_limit in (0, 101, True):
            with self.subTest(max_actions_per_run=invalid_limit):
                with self.assertNumQueries(0):
                    with self.assertRaises(
                            evaluation_module.InvalidEvaluationLimitError,
                    ) as caught:
                        evaluation_module.evaluate_listing_candidates(
                            workspace=self.workspace,
                            avito_account=empty_account,
                            plan=self.plan,
                            max_actions_per_run=invalid_limit,
                        )

                self.assertEqual(
                    caught.exception.max_actions_per_run,
                    invalid_limit,
                )

    def test_uses_two_chunks_for_501_eligible_listings(self):
        evaluation_module = self.get_evaluation_module()
        self.create_covered_listings(501)

        with CaptureQueriesContext(connection) as captured_queries:
            result = evaluation_module.evaluate_listing_candidates(
                workspace=self.workspace,
                avito_account=self.avito_account,
                plan=self.plan,
                max_actions_per_run=100,
            )

        sql_queries = [
            query["sql"].lower()
            for query in captured_queries.captured_queries
        ]
        coverage_queries = [
            sql
            for sql in sql_queries
            if "analytics_avitolistingstatscoverage" in sql
        ]
        stats_queries = [
            sql
            for sql in sql_queries
            if "analytics_avitolistingdailystats" in sql
            and "group by" in sql
        ]

        self.assertEqual(len(coverage_queries), 2)
        self.assertEqual(len(stats_queries), 2)
        self.assertEqual(result.checked, 501)
        self.assertEqual(result.ineligible, 0)
        self.assertEqual(result.insufficient_coverage, 0)
        self.assertEqual(result.not_matched, 0)
        self.assertEqual(result.matched, 501)
        self.assertEqual(result.deferred_by_run_limit, 401)
        self.assertEqual(len(result.selected_matches), 100)

    def test_fifty_unique_windows_use_one_stats_query(self):
        evaluation_module = self.get_evaluation_module()
        evaluator_module = import_module(
            "automations.modules.avito_listings.evaluator",
        )
        plan = evaluator_module.compile_condition_plan(
            build_condition_tree(*[
                {
                    "type": "condition",
                    "metric": "contacts",
                    "aggregation": "sum",
                    "window_days": window_days,
                    "comparator": "lt",
                    "value": 1,
                }
                for window_days in range(1, 51)
            ]),
            as_of_date=date(2026, 7, 20),
        )
        listing = self.create_listing(
            active_since=self.local_datetime(2026, 5, 30),
        )
        self.confirm_coverage(
            listing,
            coverage_from=date(2026, 5, 31),
        )

        with CaptureQueriesContext(connection) as captured_queries:
            result = evaluation_module.evaluate_listing_candidates(
                workspace=self.workspace,
                avito_account=self.avito_account,
                plan=plan,
                max_actions_per_run=10,
            )

        sql_queries = [
            query["sql"].lower()
            for query in captured_queries.captured_queries
        ]
        coverage_queries = [
            sql
            for sql in sql_queries
            if "analytics_avitolistingstatscoverage" in sql
        ]
        stats_queries = [
            sql
            for sql in sql_queries
            if "analytics_avitolistingdailystats" in sql
            and "group by" in sql
        ]

        self.assertEqual(len(plan.windows), 50)
        self.assertEqual(len(coverage_queries), 1)
        self.assertEqual(len(stats_queries), 1)
        self.assertEqual(result.checked, 1)
        self.assertEqual(result.matched, 1)
        self.assertEqual(
            tuple(
                match.listing_id
                for match in result.selected_matches
            ),
            (listing.id,),
        )

    def test_selection_growth_is_controlled_instead_of_negative_counter(self):
        evaluation_module = self.get_evaluation_module()
        selectors_module = import_module(
            "automations.modules.avito_listings.selectors",
        )
        listing = self.create_listing()
        self.confirm_coverage(listing)
        inconsistent_snapshot = (
            selectors_module.ListingSelectionSnapshot(
                target_max_id_snapshot=listing.id,
                checked=0,
            )
        )

        with patch.object(
                evaluation_module,
                "get_listing_selection_snapshot",
                return_value=inconsistent_snapshot,
        ):
            with self.assertRaises(
                    evaluation_module.ListingSelectionChangedError,
            ) as caught:
                evaluation_module.evaluate_listing_candidates(
                    workspace=self.workspace,
                    avito_account=self.avito_account,
                    plan=self.plan,
                    max_actions_per_run=10,
                )

        self.assertEqual(caught.exception.checked, 0)
        self.assertEqual(caught.exception.eligible, 1)

    def test_second_chunk_error_does_not_persist_partial_result(self):
        evaluation_module = self.get_evaluation_module()
        aggregation_module = import_module(
            "automations.modules.avito_listings.metric_aggregation",
        )
        self.create_covered_listings(501)
        real_aggregate = (
            aggregation_module.aggregate_listing_metric_windows
        )
        calls = 0

        def fail_second_chunk(**kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError("second chunk failed")
            return real_aggregate(**kwargs)

        decision_model = apps.get_model(
            "automations",
            "AvitoListingDecision",
        )
        result_model = apps.get_model(
            "automations",
            "AvitoListingRunResult",
        )
        decisions_before = decision_model.objects.count()
        results_before = result_model.objects.count()

        with patch.object(
                evaluation_module,
                "aggregate_listing_metric_windows",
                side_effect=fail_second_chunk,
        ):
            with self.assertRaisesRegex(
                    RuntimeError,
                    "second chunk failed",
            ):
                evaluation_module.evaluate_listing_candidates(
                    workspace=self.workspace,
                    avito_account=self.avito_account,
                    plan=self.plan,
                    max_actions_per_run=10,
                )

        self.assertEqual(calls, 2)
        self.assertEqual(
            decision_model.objects.count(),
            decisions_before,
        )
        self.assertEqual(
            result_model.objects.count(),
            results_before,
        )


class AvitoListingRunEvaluationTests(TestCase):
    module_path = (
        "automations.modules.avito_listings.run_evaluation"
    )

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(
            email="run-evaluation-owner@example.com",
            password="test-password",
        )
        cls.workspace = Workspace.objects.create(
            name="Run evaluation workspace",
            slug="run-evaluation-workspace",
            owner=cls.user,
        )
        cls.avito_account = AvitoAccount.objects.create(
            workspace=cls.workspace,
            name="Run evaluation Avito account",
        )
        automation_model = apps.get_model("automations", "Automation")
        cls.automation = automation_model.objects.create(
            workspace=cls.workspace,
            module_type="avito_listings",
            name="Run evaluation automation",
            state=automation_model.State.DRAFT,
            created_by=cls.user,
            updated_by=cls.user,
        )
        cls.condition_tree = build_condition_tree({
            "type": "condition",
            "metric": "contacts",
            "aggregation": "sum",
            "window_days": 10,
            "comparator": "lt",
            "value": 10,
        })
        cls.config = apps.get_model(
            "automations",
            "AvitoListingAutomationConfig",
        ).objects.create(
            automation=cls.automation,
            workspace=cls.workspace,
            avito_account=cls.avito_account,
            condition_tree=cls.condition_tree,
            action_type="pause",
            action_config={},
            max_actions_per_run=100,
            approval_ttl_minutes=1440,
        )

    def get_run_evaluation_module(self):
        try:
            return import_module(self.module_path)
        except ModuleNotFoundError as exc:
            if exc.name != self.module_path:
                raise

            self.fail(
                "Модуль объявлений Avito должен предоставлять "
                "run evaluation service.",
            )

    def local_datetime(self, year, month, day, hour=0):
        return timezone.make_aware(
            datetime(year, month, day, hour),
            timezone.get_current_timezone(),
        )

    def create_run(self, *, max_actions_per_run_snapshot):
        run = apps.get_model(
            "automations",
            "AutomationRun",
        ).objects.create(
            automation=self.automation,
            workspace=self.workspace,
            run_kind="preview",
            trigger="manual",
            execution_mode_snapshot="manual",
            automation_version=1,
            automation_name_snapshot=self.automation.name,
            module_type_snapshot="avito_listings",
            status="evaluating",
            idempotency_key=f"run-evaluation-{uuid4()}",
            run_token=uuid4(),
            heartbeat_at=timezone.now(),
            started_at=timezone.now(),
            created_by=self.user,
        )
        apps.get_model(
            "automations",
            "AvitoListingRunResult",
        ).objects.create(
            run=run,
            workspace=self.workspace,
            avito_account=self.avito_account,
            as_of_date=date(2026, 7, 20),
            max_actions_per_run_snapshot=(
                max_actions_per_run_snapshot
            ),
            condition_snapshot=self.condition_tree,
            action_snapshot={"type": "pause", "config": {}},
        )
        return run

    def create_listing(self, **overrides):
        values = {
            "workspace": self.workspace,
            "avito_account": self.avito_account,
            "avito_id": f"run-evaluation-{uuid4()}",
            "title": "Безопасное название",
            "description": "SECRET-DESCRIPTION",
            "image_urls": ["https://secret.example/image.jpg"],
            "raw_data": {"secret": "SECRET-RAW-DATA"},
            "management_status": (
                AvitoListing.ManagementStatus.MANAGED
            ),
            "desired_status": AvitoListing.DesiredStatus.PUBLISH,
            "active_since": self.local_datetime(2026, 7, 5),
        }
        values.update(overrides)
        return AvitoListing.objects.create(**values)

    def confirm_coverage(
            self,
            listing,
            *,
            coverage_from=date(2026, 7, 10),
    ):
        return AvitoListingStatsCoverage.objects.create(
            workspace=self.workspace,
            listing=listing,
            coverage_from=coverage_from,
            finalized_through=date(2026, 7, 19),
        )

    def create_counting_fixture(self):
        matched_oldest = self.create_listing(
            avito_id="matched-oldest",
            title="Первое совпадение",
            active_since=self.local_datetime(2026, 7, 5),
        )
        not_matched = self.create_listing(
            avito_id="not-matched",
            active_since=self.local_datetime(2026, 7, 6),
        )
        insufficient = self.create_listing(
            avito_id="insufficient",
            active_since=self.local_datetime(2026, 7, 7),
        )
        matched_second = self.create_listing(
            avito_id="matched-second",
            title="Второе совпадение",
            active_since=self.local_datetime(2026, 7, 8),
        )
        matched_deferred = self.create_listing(
            avito_id="matched-deferred",
            active_since=self.local_datetime(2026, 7, 9),
        )
        young = self.create_listing(
            avito_id="young-ineligible",
            active_since=self.local_datetime(2026, 7, 15),
        )

        for listing in (
            matched_oldest,
            not_matched,
            matched_second,
            matched_deferred,
        ):
            self.confirm_coverage(listing)
        self.confirm_coverage(
            insufficient,
            coverage_from=date(2026, 7, 11),
        )

        AvitoListingDailyStats.objects.bulk_create([
            AvitoListingDailyStats(
                workspace=self.workspace,
                listing=matched_oldest,
                date=date(2026, 7, 19),
                contacts=3,
            ),
            AvitoListingDailyStats(
                workspace=self.workspace,
                listing=not_matched,
                date=date(2026, 7, 19),
                contacts=12,
            ),
        ])

        return {
            "matched_oldest": matched_oldest,
            "matched_second": matched_second,
            "young": young,
        }

    def test_evaluates_frozen_snapshots_without_writing_partial_result(self):
        run_evaluation_module = self.get_run_evaluation_module()
        fixture = self.create_counting_fixture()
        run = self.create_run(max_actions_per_run_snapshot=2)

        self.config.condition_tree = build_condition_tree({
            "type": "condition",
            "metric": "views",
            "aggregation": "sum",
            "window_days": 30,
            "comparator": "gte",
            "value": 100,
        })
        self.config.max_actions_per_run = 100
        self.config.save(
            update_fields=[
                "condition_tree",
                "max_actions_per_run",
                "updated_at",
            ],
        )

        outcome = run_evaluation_module.evaluate_run(run=run)
        evaluation = outcome.evaluation

        self.assertEqual(
            evaluation.target_max_id_snapshot,
            fixture["young"].id,
        )
        self.assertEqual(evaluation.checked, 6)
        self.assertEqual(evaluation.ineligible, 1)
        self.assertEqual(evaluation.insufficient_coverage, 1)
        self.assertEqual(evaluation.not_matched, 1)
        self.assertEqual(evaluation.matched, 3)
        self.assertEqual(evaluation.deferred_by_run_limit, 1)
        self.assertEqual(
            tuple(
                match.listing_id
                for match in evaluation.selected_matches
            ),
            (
                fixture["matched_oldest"].id,
                fixture["matched_second"].id,
            ),
        )

        self.assertEqual(
            outcome.examples_snapshot,
            (
                {
                    "listing_id": fixture["matched_oldest"].id,
                    "avito_id": "matched-oldest",
                    "title": "Первое совпадение",
                    "active_since": (
                        fixture["matched_oldest"]
                        .active_since.isoformat()
                    ),
                    "metrics": [
                        {
                            "metric": "contacts",
                            "aggregation": "sum",
                            "window_days": 10,
                            "date_from": "2026-07-10",
                            "date_to": "2026-07-19",
                            "value": 3,
                        },
                    ],
                    "matched": True,
                },
                {
                    "listing_id": fixture["matched_second"].id,
                    "avito_id": "matched-second",
                    "title": "Второе совпадение",
                    "active_since": (
                        fixture["matched_second"]
                        .active_since.isoformat()
                    ),
                    "metrics": [
                        {
                            "metric": "contacts",
                            "aggregation": "sum",
                            "window_days": 10,
                            "date_from": "2026-07-10",
                            "date_to": "2026-07-19",
                            "value": 0,
                        },
                    ],
                    "matched": True,
                },
            ),
        )

        stored_result = run.avito_listing_result
        stored_result.refresh_from_db()
        self.assertEqual(stored_result.target_max_id_snapshot, 0)
        self.assertEqual(stored_result.checked, 0)
        self.assertEqual(stored_result.matched, 0)
        self.assertEqual(stored_result.examples_snapshot, [])

        serialized_examples = json.dumps(
            outcome.examples_snapshot,
            ensure_ascii=False,
        )
        self.assertNotIn("SECRET-DESCRIPTION", serialized_examples)
        self.assertNotIn("SECRET-RAW-DATA", serialized_examples)
        self.assertNotIn("secret.example", serialized_examples)

    def test_examples_are_limited_and_loaded_by_one_light_query(self):
        run_evaluation_module = self.get_run_evaluation_module()
        active_since = self.local_datetime(2026, 7, 5)
        listings = AvitoListing.objects.bulk_create([
            AvitoListing(
                workspace=self.workspace,
                avito_account=self.avito_account,
                avito_id=f"example-{index:02d}",
                title=f"Пример {index:02d}",
                description="SECRET-BULK-DESCRIPTION",
                raw_data={"secret": "SECRET-BULK-RAW"},
                management_status=(
                    AvitoListing.ManagementStatus.MANAGED
                ),
                desired_status=AvitoListing.DesiredStatus.PUBLISH,
                active_since=active_since,
            )
            for index in range(25)
        ])
        AvitoListingStatsCoverage.objects.bulk_create([
            AvitoListingStatsCoverage(
                workspace=self.workspace,
                listing=listing,
                coverage_from=date(2026, 7, 10),
                finalized_through=date(2026, 7, 19),
            )
            for listing in listings
        ])
        run = self.create_run(max_actions_per_run_snapshot=25)

        with CaptureQueriesContext(connection) as captured_queries:
            outcome = run_evaluation_module.evaluate_run(run=run)

        self.assertEqual(outcome.evaluation.matched, 25)
        self.assertEqual(len(outcome.examples_snapshot), 20)
        self.assertEqual(
            tuple(
                example["listing_id"]
                for example in outcome.examples_snapshot
            ),
            tuple(listing.id for listing in listings[:20]),
        )

        example_queries = [
            query["sql"].lower()
            for query in captured_queries.captured_queries
            if "avitotask_avitolisting" in query["sql"].lower()
            and '"title"' in query["sql"].lower()
            and '"avito_id"' in query["sql"].lower()
        ]
        self.assertEqual(len(example_queries), 1)
        for forbidden_column in (
            "description",
            "image_urls",
            "base_data",
            "raw_data",
            "imported_payload",
        ):
            with self.subTest(column=forbidden_column):
                self.assertNotIn(
                    f'"{forbidden_column}"',
                    example_queries[0],
                )

    def test_saves_complete_typed_result_without_decisions_or_lifecycle(self):
        run_evaluation_module = self.get_run_evaluation_module()
        fixture = self.create_counting_fixture()
        run = self.create_run(max_actions_per_run_snapshot=2)
        outcome = run_evaluation_module.evaluate_run(run=run)

        with transaction.atomic():
            run_evaluation_module.save_run_evaluation(
                run=run,
                outcome=outcome,
            )

        stored_result = run.avito_listing_result
        stored_result.refresh_from_db()
        self.assertEqual(
            stored_result.target_max_id_snapshot,
            fixture["young"].id,
        )
        self.assertEqual(stored_result.checked, 6)
        self.assertEqual(stored_result.ineligible, 1)
        self.assertEqual(stored_result.insufficient_coverage, 1)
        self.assertEqual(stored_result.not_matched, 1)
        self.assertEqual(stored_result.matched, 3)
        self.assertEqual(stored_result.deferred_by_run_limit, 1)
        self.assertEqual(
            stored_result.examples_snapshot,
            list(outcome.examples_snapshot),
        )

        run.refresh_from_db()
        self.assertEqual(run.status, "evaluating")
        self.assertEqual(
            apps.get_model(
                "automations",
                "AvitoListingDecision",
            ).objects.count(),
            0,
        )
        self.assertFalse(
            AvitoListing.objects
            .filter(
                workspace=self.workspace,
                avito_account=self.avito_account,
            )
            .exclude(
                desired_status=AvitoListing.DesiredStatus.PUBLISH,
            )
            .exists(),
        )


class AutomationRunExecutorTests(TestCase):
    module_path = "automations.services.run_executor"

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(
            email="run-executor-owner@example.com",
            password="test-password",
        )
        cls.workspace = Workspace.objects.create(
            name="Run executor workspace",
            slug="run-executor-workspace",
            owner=cls.user,
        )
        cls.avito_account = AvitoAccount.objects.create(
            workspace=cls.workspace,
            name="Run executor Avito account",
        )
        automation_model = apps.get_model("automations", "Automation")
        cls.automation = automation_model.objects.create(
            workspace=cls.workspace,
            module_type="avito_listings",
            name="Run executor automation",
            state=automation_model.State.ENABLED,
            created_by=cls.user,
            updated_by=cls.user,
        )
        cls.condition_tree = build_condition_tree({
            "type": "condition",
            "metric": "contacts",
            "aggregation": "sum",
            "window_days": 10,
            "comparator": "lt",
            "value": 10,
        })

    def get_executor_module(self):
        try:
            return import_module(self.module_path)
        except ModuleNotFoundError as exc:
            if exc.name not in {
                "automations.services",
                self.module_path,
            }:
                raise

            self.fail(
                "Ядро автоматизаций должно предоставлять общий "
                "run executor.",
            )

    def local_datetime(self, year, month, day, hour=0):
        return timezone.make_aware(
            datetime(year, month, day, hour),
            timezone.get_current_timezone(),
        )

    def create_run(
            self,
            *,
            run_kind="preview",
            approval_ttl_minutes=1440,
            max_actions_per_run=10,
    ):
        run = apps.get_model(
            "automations",
            "AutomationRun",
        ).objects.create(
            automation=self.automation,
            workspace=self.workspace,
            run_kind=run_kind,
            trigger="manual",
            execution_mode_snapshot="manual",
            automation_version=1,
            automation_name_snapshot=self.automation.name,
            module_type_snapshot="avito_listings",
            status="queued",
            idempotency_key=f"executor-{uuid4()}",
            created_by=self.user,
        )
        apps.get_model(
            "automations",
            "AvitoListingRunResult",
        ).objects.create(
            run=run,
            workspace=self.workspace,
            avito_account=self.avito_account,
            as_of_date=date(2026, 7, 20),
            max_actions_per_run_snapshot=max_actions_per_run,
            approval_ttl_minutes_snapshot=approval_ttl_minutes,
            condition_snapshot=self.condition_tree,
            action_snapshot={"type": "pause", "config": {}},
        )
        return run

    def create_ready_listing(self, *, contacts=3):
        listing = AvitoListing.objects.create(
            workspace=self.workspace,
            avito_account=self.avito_account,
            avito_id=f"executor-listing-{uuid4()}",
            title="Executor listing",
            management_status=(
                AvitoListing.ManagementStatus.MANAGED
            ),
            desired_status=AvitoListing.DesiredStatus.PUBLISH,
            active_since=self.local_datetime(2026, 7, 5),
        )
        AvitoListingStatsCoverage.objects.create(
            workspace=self.workspace,
            listing=listing,
            coverage_from=date(2026, 7, 10),
            finalized_through=date(2026, 7, 19),
        )
        AvitoListingDailyStats.objects.create(
            workspace=self.workspace,
            listing=listing,
            date=date(2026, 7, 19),
            contacts=contacts,
        )
        AvitoStatsSyncState.objects.update_or_create(
            workspace=self.workspace,
            avito_account=self.avito_account,
            defaults={
                "status": AvitoStatsSyncState.Status.SUCCESS,
                "coverage_from": date(2026, 7, 10),
                "coverage_to": date(2026, 7, 19),
            },
        )
        return listing

    def execute_without_unhandled_error(
            self,
            executor_module,
            *,
            run_id,
    ):
        try:
            with self.assertLogs(
                    "automations.services.run_executor",
                    level="ERROR",
            ):
                return executor_module.execute_run(run_id=run_id)
        except Exception as exc:
            self.fail(
                "Executor не должен оставлять классифицируемую ошибку "
                f"необработанной: {type(exc).__name__}.",
            )

    def assert_failed_run_without_partial_result(
            self,
            run,
            *,
            failed_at,
            error_code,
            secret,
    ):
        run.refresh_from_db()
        self.assertEqual(run.status, "failed")
        self.assertEqual(run.finished_at, failed_at)
        self.assertEqual(run.retry_count, 0)
        self.assertIsNone(run.next_attempt_at)
        self.assertIsNone(run.run_token)
        self.assertIsNone(run.heartbeat_at)
        self.assertEqual(run.error_code, error_code)
        self.assertTrue(run.error_message)
        self.assertNotIn(secret, run.error_message)
        result = run.avito_listing_result
        self.assertEqual(result.checked, 0)
        self.assertEqual(result.matched, 0)
        self.assertEqual(result.examples_snapshot, [])

    def test_ready_preview_is_claimed_evaluated_and_completed(self):
        executor_module = self.get_executor_module()
        listing = self.create_ready_listing()
        run = self.create_run()
        processed_at = self.local_datetime(2026, 8, 19, 12)

        with patch.object(
                executor_module.timezone,
                "now",
                return_value=processed_at,
        ):
            execution = executor_module.execute_run(run_id=run.id)

        self.assertEqual(execution.status, "completed")
        self.assertIsNone(execution.reason)

        run.refresh_from_db()
        self.assertEqual(run.status, "completed")
        self.assertEqual(run.started_at, processed_at)
        self.assertEqual(run.finished_at, processed_at)
        self.assertIsNone(run.run_token)
        self.assertIsNone(run.heartbeat_at)
        self.assertEqual(run.error_code, "")
        self.assertEqual(run.error_message, "")

        result = run.avito_listing_result
        self.assertEqual(result.checked, 1)
        self.assertEqual(result.matched, 1)
        self.assertEqual(result.deferred_by_run_limit, 0)
        self.assertEqual(
            result.examples_snapshot[0]["listing_id"],
            listing.id,
        )
        self.assertEqual(
            apps.get_model(
                "automations",
                "AvitoListingDecision",
            ).objects.count(),
            0,
        )
        account_state = apps.get_model(
            "automations",
            "AvitoAutomationAccountState",
        ).objects.filter(
            workspace=self.workspace,
            avito_account=self.avito_account,
        ).first()
        self.assertIsNotNone(
            account_state,
            "Executor должен захватить account lease до evaluator-а.",
        )
        self.assertEqual(account_state.status, "idle")
        self.assertIsNone(account_state.run_token)
        self.assertIsNone(account_state.heartbeat_at)
        self.assertIsNone(account_state.lease_expires_at)

    def test_ready_execute_creates_decision_and_waits_for_approval(self):
        executor_module = self.get_executor_module()
        listing = self.create_ready_listing()
        run = self.create_run(
            run_kind="execute",
            approval_ttl_minutes=180,
        )
        processed_at = self.local_datetime(2026, 8, 19, 12)

        with patch.object(
                executor_module.timezone,
                "now",
                return_value=processed_at,
        ):
            execution = executor_module.execute_run(run_id=run.id)

        self.assertEqual(execution.status, "waiting_approval")
        self.assertIsNone(execution.reason)

        run.refresh_from_db()
        self.assertEqual(run.status, "waiting_approval")
        self.assertEqual(run.started_at, processed_at)
        self.assertIsNone(run.finished_at)
        self.assertIsNone(run.run_token)
        self.assertIsNone(run.heartbeat_at)
        self.assertIsNone(run.next_attempt_at)

        result = run.avito_listing_result
        self.assertEqual(result.checked, 1)
        self.assertEqual(result.matched, 1)
        self.assertEqual(result.pending_approval, 1)
        self.assertEqual(result.completed_actions, 0)
        self.assertEqual(result.failed_actions, 0)

        decision = apps.get_model(
            "automations",
            "AvitoListingDecision",
        ).objects.get(run=run)
        self.assertEqual(decision.automation, self.automation)
        self.assertEqual(decision.workspace, self.workspace)
        self.assertEqual(decision.avito_account, self.avito_account)
        self.assertEqual(decision.listing, listing)
        self.assertEqual(decision.listing_id_snapshot, listing.id)
        self.assertEqual(
            decision.listing_snapshot,
            {
                "avito_id": listing.avito_id,
                "title": listing.title,
            },
        )
        self.assertEqual(decision.status, "pending_approval")
        self.assertEqual(decision.automation_version, 1)
        self.assertEqual(
            decision.active_since_snapshot,
            listing.active_since,
        )
        self.assertEqual(
            decision.condition_snapshot,
            self.condition_tree,
        )
        self.assertEqual(
            decision.metrics_snapshot,
            [
                {
                    "metric": "contacts",
                    "aggregation": "sum",
                    "window_days": 10,
                    "date_from": "2026-07-10",
                    "date_to": "2026-07-19",
                    "value": 3,
                },
            ],
        )
        self.assertEqual(
            decision.action_snapshot,
            {"type": "pause", "config": {}},
        )
        self.assertEqual(
            decision.expires_at,
            processed_at + timedelta(minutes=180),
        )

        listing.refresh_from_db()
        self.assertEqual(
            listing.desired_status,
            AvitoListing.DesiredStatus.PUBLISH,
        )
        self.assertIsNotNone(listing.active_since)

    def test_execute_without_matches_completes_without_decisions(self):
        executor_module = self.get_executor_module()
        self.create_ready_listing(contacts=12)
        run = self.create_run(run_kind="execute")
        processed_at = self.local_datetime(2026, 8, 19, 12)

        with patch.object(
                executor_module.timezone,
                "now",
                return_value=processed_at,
        ):
            execution = executor_module.execute_run(run_id=run.id)

        self.assertEqual(execution.status, "completed")
        run.refresh_from_db()
        self.assertEqual(run.status, "completed")
        self.assertEqual(run.finished_at, processed_at)
        self.assertEqual(run.avito_listing_result.matched, 0)
        self.assertEqual(
            run.avito_listing_result.pending_approval,
            0,
        )
        self.assertFalse(
            apps.get_model(
                "automations",
                "AvitoListingDecision",
            ).objects.filter(run=run).exists(),
        )

    def test_execute_creates_decisions_only_within_snapshot_limit(self):
        executor_module = self.get_executor_module()
        listings = [
            self.create_ready_listing()
            for _ in range(3)
        ]
        run = self.create_run(
            run_kind="execute",
            max_actions_per_run=2,
        )
        processed_at = self.local_datetime(2026, 8, 19, 12)

        with patch.object(
                executor_module.timezone,
                "now",
                return_value=processed_at,
        ):
            execution = executor_module.execute_run(run_id=run.id)

        self.assertEqual(execution.status, "waiting_approval")
        result = run.avito_listing_result
        result.refresh_from_db()
        self.assertEqual(result.matched, 3)
        self.assertEqual(result.deferred_by_run_limit, 1)
        self.assertEqual(result.pending_approval, 2)
        decision_listing_ids = tuple(
            apps.get_model(
                "automations",
                "AvitoListingDecision",
            ).objects
            .filter(run=run)
            .order_by("listing_id_snapshot")
            .values_list("listing_id_snapshot", flat=True)
        )
        self.assertEqual(
            decision_listing_ids,
            tuple(listing.id for listing in listings[:2]),
        )

    def test_invalid_final_status_rolls_back_execute_decisions(self):
        executor_module = self.get_executor_module()
        self.create_ready_listing()
        run = self.create_run(run_kind="execute")
        definition = import_module(
            "automations.registry",
        ).get_module_definition("avito_listings")

        def save_and_return_invalid_status(*, run, outcome):
            definition.save_run_evaluation(
                run=run,
                outcome=outcome,
            )
            return "queued"

        invalid_definition = replace(
            definition,
            save_run_evaluation=save_and_return_invalid_status,
        )
        failed_at = self.local_datetime(2026, 8, 19, 12)

        with patch.object(
                executor_module,
                "get_module_definition",
                return_value=invalid_definition,
        ):
            with patch.object(
                    executor_module.timezone,
                    "now",
                    return_value=failed_at,
            ):
                execution = self.execute_without_unhandled_error(
                    executor_module,
                    run_id=run.id,
                )

        self.assertEqual(execution.status, "failed")
        self.assertEqual(execution.reason, "internal_error")
        run.refresh_from_db()
        self.assertEqual(run.status, "failed")
        result = run.avito_listing_result
        result.refresh_from_db()
        self.assertEqual(result.checked, 0)
        self.assertEqual(result.matched, 0)
        self.assertEqual(result.pending_approval, 0)
        self.assertFalse(
            apps.get_model(
                "automations",
                "AvitoListingDecision",
            ).objects.filter(run=run).exists(),
        )

    def test_unready_preview_waits_without_claim_or_evaluation(self):
        executor_module = self.get_executor_module()
        run = self.create_run()
        checked_at = self.local_datetime(2026, 8, 19, 9)

        with patch.object(
                executor_module.timezone,
                "now",
                return_value=checked_at,
        ):
            execution = executor_module.execute_run(run_id=run.id)

        self.assertEqual(execution.status, "waiting_for_data")
        self.assertEqual(execution.reason, "missing_sync_state")
        run.refresh_from_db()
        self.assertEqual(run.status, "waiting_for_data")
        self.assertEqual(run.wait_started_at, checked_at)
        self.assertEqual(
            run.next_attempt_at,
            checked_at + timedelta(minutes=10),
        )
        self.assertEqual(run.data_wait_attempt_count, 1)
        self.assertIsNone(run.run_token)
        self.assertIsNone(run.heartbeat_at)
        self.assertIsNone(run.started_at)
        self.assertIsNone(run.finished_at)
        self.assertEqual(run.error_code, "insufficient_data")
        result = run.avito_listing_result
        self.assertEqual(result.checked, 0)
        self.assertEqual(result.matched, 0)
        self.assertEqual(result.examples_snapshot, [])

    def test_waiting_run_before_next_attempt_is_not_rechecked(self):
        executor_module = self.get_executor_module()
        run = self.create_run()
        first_check = self.local_datetime(2026, 8, 19, 9)

        with patch.object(
                executor_module.timezone,
                "now",
                return_value=first_check,
        ):
            executor_module.execute_run(run_id=run.id)

        run.refresh_from_db()
        scheduled_at = run.next_attempt_at

        with patch.object(
                executor_module.timezone,
                "now",
                return_value=first_check + timedelta(minutes=5),
        ):
            with CaptureQueriesContext(connection) as captured_queries:
                execution = executor_module.execute_run(run_id=run.id)

        self.assertEqual(execution.status, "waiting_for_data")
        self.assertEqual(execution.reason, "not_due")
        run.refresh_from_db()
        self.assertEqual(run.data_wait_attempt_count, 1)
        self.assertEqual(run.next_attempt_at, scheduled_at)
        sync_queries = [
            query["sql"]
            for query in captured_queries.captured_queries
            if "analytics_avitostatssyncstate" in query["sql"].lower()
        ]
        self.assertEqual(sync_queries, [])

    def test_queued_retry_before_next_attempt_is_not_executed(self):
        executor_module = self.get_executor_module()
        run = self.create_run()
        retry_at = self.local_datetime(2026, 8, 19, 9)
        run.retry_count = 1
        run.next_attempt_at = retry_at
        run.error_code = "account_busy"
        run.save(
            update_fields=[
                "retry_count",
                "next_attempt_at",
                "error_code",
                "updated_at",
            ],
        )

        with patch.object(
                executor_module.timezone,
                "now",
                return_value=retry_at - timedelta(seconds=1),
        ):
            with CaptureQueriesContext(connection) as captured_queries:
                execution = executor_module.execute_run(run_id=run.id)

        self.assertEqual(execution.status, "queued")
        self.assertEqual(execution.reason, "not_due")
        run.refresh_from_db()
        self.assertEqual(run.status, "queued")
        self.assertEqual(run.retry_count, 1)
        self.assertEqual(run.next_attempt_at, retry_at)
        self.assertEqual(run.error_code, "account_busy")
        sync_queries = [
            query["sql"]
            for query in captured_queries.captured_queries
            if "analytics_avitostatssyncstate" in query["sql"].lower()
        ]
        self.assertEqual(sync_queries, [])

    def test_busy_account_defers_run_without_evaluation(self):
        executor_module = self.get_executor_module()
        self.create_ready_listing()
        run = self.create_run()
        processed_at = self.local_datetime(2026, 8, 19, 12)
        lease_owner_token = uuid4()
        account_state = apps.get_model(
            "automations",
            "AvitoAutomationAccountState",
        ).objects.create(
            workspace=self.workspace,
            avito_account=self.avito_account,
            status="running",
            run_token=lease_owner_token,
            heartbeat_at=processed_at,
            lease_expires_at=(
                processed_at + timedelta(minutes=10)
            ),
        )

        with patch.object(
                executor_module.timezone,
                "now",
                return_value=processed_at,
        ):
            execution = executor_module.execute_run(run_id=run.id)

        self.assertEqual(execution.status, "queued")
        self.assertEqual(execution.reason, "account_busy")
        run.refresh_from_db()
        self.assertEqual(run.status, "queued")
        self.assertEqual(run.retry_count, 1)
        self.assertEqual(
            run.next_attempt_at,
            processed_at + timedelta(seconds=60),
        )
        self.assertIsNone(run.run_token)
        self.assertIsNone(run.heartbeat_at)
        self.assertEqual(run.error_code, "account_busy")
        self.assertTrue(run.error_message)
        result = run.avito_listing_result
        self.assertEqual(result.checked, 0)
        self.assertEqual(result.matched, 0)
        self.assertEqual(result.examples_snapshot, [])

        account_state.refresh_from_db()
        self.assertEqual(account_state.status, "running")
        self.assertEqual(account_state.run_token, lease_owner_token)
        self.assertEqual(account_state.heartbeat_at, processed_at)
        self.assertEqual(
            account_state.lease_expires_at,
            processed_at + timedelta(minutes=10),
        )

    def test_busy_account_fails_after_three_bounded_retries(self):
        executor_module = self.get_executor_module()
        self.create_ready_listing()
        run = self.create_run()
        first_attempt_at = self.local_datetime(2026, 8, 19, 12)
        lease_owner_token = uuid4()
        account_state = apps.get_model(
            "automations",
            "AvitoAutomationAccountState",
        ).objects.create(
            workspace=self.workspace,
            avito_account=self.avito_account,
            status="running",
            run_token=lease_owner_token,
            heartbeat_at=first_attempt_at,
            lease_expires_at=(
                first_attempt_at + timedelta(minutes=10)
            ),
        )
        attempts = (
            (
                first_attempt_at,
                "queued",
                1,
                first_attempt_at + timedelta(seconds=60),
            ),
            (
                first_attempt_at + timedelta(seconds=60),
                "queued",
                2,
                first_attempt_at + timedelta(seconds=180),
            ),
            (
                first_attempt_at + timedelta(seconds=180),
                "queued",
                3,
                first_attempt_at + timedelta(seconds=420),
            ),
            (
                first_attempt_at + timedelta(seconds=420),
                "failed",
                3,
                None,
            ),
        )

        for (
                attempted_at,
                expected_status,
                expected_retry_count,
                expected_next_attempt,
        ) in attempts:
            with self.subTest(retry_count=expected_retry_count):
                with patch.object(
                        executor_module.timezone,
                        "now",
                        return_value=attempted_at,
                ):
                    execution = executor_module.execute_run(
                        run_id=run.id,
                    )

                self.assertEqual(execution.status, expected_status)
                self.assertEqual(execution.reason, "account_busy")
                run.refresh_from_db()
                self.assertEqual(run.status, expected_status)
                self.assertEqual(
                    run.retry_count,
                    expected_retry_count,
                )
                self.assertEqual(
                    run.next_attempt_at,
                    expected_next_attempt,
                )
                self.assertIsNone(run.run_token)
                self.assertIsNone(run.heartbeat_at)
                self.assertEqual(run.error_code, "account_busy")
                self.assertTrue(run.error_message)

        self.assertEqual(
            run.finished_at,
            first_attempt_at + timedelta(seconds=420),
        )
        result = run.avito_listing_result
        self.assertEqual(result.checked, 0)
        self.assertEqual(result.matched, 0)
        self.assertEqual(result.examples_snapshot, [])
        account_state.refresh_from_db()
        self.assertEqual(account_state.status, "running")
        self.assertEqual(account_state.run_token, lease_owner_token)

    def test_due_waiting_run_completes_when_data_becomes_ready(self):
        executor_module = self.get_executor_module()
        run = self.create_run()
        first_check = self.local_datetime(2026, 8, 19, 9)

        with patch.object(
                executor_module.timezone,
                "now",
                return_value=first_check,
        ):
            executor_module.execute_run(run_id=run.id)

        self.create_ready_listing()
        resumed_at = first_check + timedelta(minutes=10)
        with patch.object(
                executor_module.timezone,
                "now",
                return_value=resumed_at,
        ):
            execution = executor_module.execute_run(run_id=run.id)

        self.assertEqual(execution.status, "completed")
        self.assertIsNone(execution.reason)
        run.refresh_from_db()
        self.assertEqual(run.status, "completed")
        self.assertEqual(run.wait_started_at, first_check)
        self.assertEqual(run.data_wait_attempt_count, 1)
        self.assertIsNone(run.next_attempt_at)
        self.assertEqual(run.error_code, "")
        self.assertEqual(run.error_message, "")

    def test_waiting_run_is_cancelled_after_24_hours(self):
        executor_module = self.get_executor_module()
        run = self.create_run()
        first_check = self.local_datetime(2026, 8, 19, 9)

        with patch.object(
                executor_module.timezone,
                "now",
                return_value=first_check,
        ):
            executor_module.execute_run(run_id=run.id)

        expired_at = first_check + timedelta(hours=24)
        with patch.object(
                executor_module.timezone,
                "now",
                return_value=expired_at,
        ):
            execution = executor_module.execute_run(run_id=run.id)

        self.assertEqual(execution.status, "cancelled")
        self.assertEqual(execution.reason, "data_wait_expired")
        run.refresh_from_db()
        self.assertEqual(run.status, "cancelled")
        self.assertEqual(run.finished_at, expired_at)
        self.assertEqual(run.wait_started_at, first_check)
        self.assertEqual(run.data_wait_attempt_count, 1)
        self.assertIsNone(run.next_attempt_at)
        self.assertIsNone(run.run_token)
        self.assertIsNone(run.heartbeat_at)
        self.assertEqual(run.error_code, "data_wait_expired")
        self.assertTrue(run.error_message)
        result = run.avito_listing_result
        self.assertEqual(result.checked, 0)
        self.assertEqual(result.matched, 0)
        self.assertEqual(result.examples_snapshot, [])
        self.assertEqual(
            apps.get_model(
                "automations",
                "AvitoListingDecision",
            ).objects.count(),
            0,
        )

    def test_duplicate_delivery_skips_completed_run_without_stats_query(self):
        executor_module = self.get_executor_module()
        self.create_ready_listing()
        run = self.create_run()
        first_execution = executor_module.execute_run(run_id=run.id)

        with CaptureQueriesContext(connection) as captured_queries:
            second_execution = executor_module.execute_run(run_id=run.id)

        self.assertEqual(first_execution.status, "completed")
        self.assertEqual(second_execution.status, "skipped")
        self.assertEqual(
            second_execution.reason,
            "run_not_runnable",
        )
        stats_queries = [
            query["sql"]
            for query in captured_queries.captured_queries
            if "analytics_avitolistingdailystats" in query["sql"].lower()
        ]
        self.assertEqual(stats_queries, [])

    def test_worker_with_replaced_token_cannot_save_result(self):
        executor_module = self.get_executor_module()
        self.create_ready_listing()
        run = self.create_run()
        registry_module = import_module("automations.registry")
        definition = registry_module.get_module_definition(
            "avito_listings",
        )
        replacement_token = uuid4()

        def evaluate_and_replace_token(*, run):
            outcome = definition.evaluate_run(run=run)
            apps.get_model(
                "automations",
                "AutomationRun",
            ).objects.filter(id=run.id).update(
                run_token=replacement_token,
            )
            return outcome

        stolen_definition = SimpleNamespace(
            evaluate_run=evaluate_and_replace_token,
            save_run_evaluation=definition.save_run_evaluation,
            acquire_run_lease=definition.acquire_run_lease,
            heartbeat_run_lease=definition.heartbeat_run_lease,
            release_run_lease=definition.release_run_lease,
        )

        with patch.object(
                executor_module,
                "get_module_definition",
                return_value=stolen_definition,
        ):
            execution = executor_module.execute_run(run_id=run.id)

        self.assertEqual(execution.status, "skipped")
        self.assertEqual(execution.reason, "lost_ownership")
        run.refresh_from_db()
        self.assertEqual(run.status, "evaluating")
        self.assertEqual(run.run_token, replacement_token)
        result = run.avito_listing_result
        self.assertEqual(result.checked, 0)
        self.assertEqual(result.matched, 0)
        self.assertEqual(result.examples_snapshot, [])
        account_state = apps.get_model(
            "automations",
            "AvitoAutomationAccountState",
        ).objects.filter(
            workspace=self.workspace,
            avito_account=self.avito_account,
        ).first()
        self.assertIsNotNone(
            account_state,
            "Executor должен освободить ранее захваченный lease.",
        )
        self.assertEqual(account_state.status, "idle")
        self.assertIsNone(account_state.run_token)

    def test_lost_account_lease_defers_run_without_saving_result(self):
        executor_module = self.get_executor_module()
        self.create_ready_listing()
        run = self.create_run()
        registry_module = import_module("automations.registry")
        definition = registry_module.get_module_definition(
            "avito_listings",
        )
        processed_at = self.local_datetime(2026, 8, 19, 12)
        replacement_token = uuid4()

        def evaluate_and_replace_lease(*, run):
            outcome = definition.evaluate_run(run=run)
            apps.get_model(
                "automations",
                "AvitoAutomationAccountState",
            ).objects.update_or_create(
                workspace=self.workspace,
                avito_account=self.avito_account,
                defaults={
                    "status": "running",
                    "run_token": replacement_token,
                    "heartbeat_at": processed_at,
                    "lease_expires_at": (
                        processed_at + timedelta(minutes=10)
                    ),
                },
            )
            return outcome

        replaced_definition = SimpleNamespace(
            evaluate_run=evaluate_and_replace_lease,
            save_run_evaluation=definition.save_run_evaluation,
            acquire_run_lease=definition.acquire_run_lease,
            heartbeat_run_lease=definition.heartbeat_run_lease,
            release_run_lease=definition.release_run_lease,
        )

        with patch.object(
                executor_module,
                "get_module_definition",
                return_value=replaced_definition,
        ):
            with patch.object(
                    executor_module.timezone,
                    "now",
                    return_value=processed_at,
            ):
                execution = executor_module.execute_run(run_id=run.id)

        self.assertEqual(execution.status, "queued")
        self.assertEqual(execution.reason, "lease_lost")
        run.refresh_from_db()
        self.assertEqual(run.status, "queued")
        self.assertEqual(run.retry_count, 1)
        self.assertEqual(
            run.next_attempt_at,
            processed_at + timedelta(seconds=60),
        )
        self.assertIsNone(run.run_token)
        self.assertIsNone(run.heartbeat_at)
        self.assertEqual(run.error_code, "lease_lost")
        self.assertTrue(run.error_message)
        result = run.avito_listing_result
        self.assertEqual(result.checked, 0)
        self.assertEqual(result.matched, 0)
        self.assertEqual(result.examples_snapshot, [])

        account_state = apps.get_model(
            "automations",
            "AvitoAutomationAccountState",
        ).objects.get(
            workspace=self.workspace,
            avito_account=self.avito_account,
        )
        self.assertEqual(account_state.status, "running")
        self.assertEqual(account_state.run_token, replacement_token)

    def test_invalid_snapshot_before_claim_fails_without_retry(self):
        executor_module = self.get_executor_module()
        run = self.create_run()
        result = run.avito_listing_result
        result.condition_snapshot = {
            "type": "secret invalid snapshot",
        }
        result.save(
            update_fields=["condition_snapshot", "updated_at"],
        )
        failed_at = self.local_datetime(2026, 8, 19, 12)

        with patch.object(
                executor_module.timezone,
                "now",
                return_value=failed_at,
        ):
            execution = self.execute_without_unhandled_error(
                executor_module,
                run_id=run.id,
            )

        self.assertEqual(execution.status, "failed")
        self.assertEqual(execution.reason, "validation_error")
        self.assert_failed_run_without_partial_result(
            run,
            failed_at=failed_at,
            error_code="validation_error",
            secret="secret invalid snapshot",
        )
        self.assertIsNone(run.started_at)
        self.assertFalse(
            apps.get_model(
                "automations",
                "AvitoAutomationAccountState",
            ).objects.filter(
                workspace=self.workspace,
                avito_account=self.avito_account,
            ).exists(),
        )

    def test_evaluator_validation_error_fails_and_releases_lease(self):
        executor_module = self.get_executor_module()
        self.create_ready_listing()
        run = self.create_run()
        definition = import_module(
            "automations.registry",
        ).get_module_definition("avito_listings")
        evaluator_module = import_module(
            "automations.modules.avito_listings.evaluator",
        )
        secret = "secret evaluator validation detail"

        def raise_validation_error(*, run):
            raise evaluator_module.ConditionPlanCompilationError(
                code="invalid_root",
                path="condition_tree",
                message=secret,
            )

        failing_definition = replace(
            definition,
            evaluate_run=raise_validation_error,
        )
        failed_at = self.local_datetime(2026, 8, 19, 12)

        with patch.object(
                executor_module,
                "get_module_definition",
                return_value=failing_definition,
        ):
            with patch.object(
                    executor_module.timezone,
                    "now",
                    return_value=failed_at,
            ):
                execution = self.execute_without_unhandled_error(
                    executor_module,
                    run_id=run.id,
                )

        self.assertEqual(execution.status, "failed")
        self.assertEqual(execution.reason, "validation_error")
        self.assert_failed_run_without_partial_result(
            run,
            failed_at=failed_at,
            error_code="validation_error",
            secret=secret,
        )
        account_state = apps.get_model(
            "automations",
            "AvitoAutomationAccountState",
        ).objects.get(
            workspace=self.workspace,
            avito_account=self.avito_account,
        )
        self.assertEqual(account_state.status, "idle")

    def test_evaluator_timeout_fails_without_retry(self):
        executor_module = self.get_executor_module()
        self.create_ready_listing()
        run = self.create_run()
        definition = import_module(
            "automations.registry",
        ).get_module_definition("avito_listings")
        secret = "secret evaluator timeout detail"

        def raise_timeout(*, run):
            raise TimeoutError(secret)

        failing_definition = replace(
            definition,
            evaluate_run=raise_timeout,
        )
        failed_at = self.local_datetime(2026, 8, 19, 12)

        with patch.object(
                executor_module,
                "get_module_definition",
                return_value=failing_definition,
        ):
            with patch.object(
                    executor_module.timezone,
                    "now",
                    return_value=failed_at,
            ):
                execution = self.execute_without_unhandled_error(
                    executor_module,
                    run_id=run.id,
                )

        self.assertEqual(execution.status, "failed")
        self.assertEqual(execution.reason, "time_limit")
        self.assert_failed_run_without_partial_result(
            run,
            failed_at=failed_at,
            error_code="time_limit",
            secret=secret,
        )

    def test_unknown_evaluator_error_fails_without_detail_leak(self):
        executor_module = self.get_executor_module()
        self.create_ready_listing()
        run = self.create_run()
        definition = import_module(
            "automations.registry",
        ).get_module_definition("avito_listings")
        secret = "secret unexpected evaluator detail"

        def raise_unknown_error(*, run):
            raise RuntimeError(secret)

        failing_definition = replace(
            definition,
            evaluate_run=raise_unknown_error,
        )
        failed_at = self.local_datetime(2026, 8, 19, 12)

        with patch.object(
                executor_module,
                "get_module_definition",
                return_value=failing_definition,
        ):
            with patch.object(
                    executor_module.timezone,
                    "now",
                    return_value=failed_at,
            ):
                execution = self.execute_without_unhandled_error(
                    executor_module,
                    run_id=run.id,
                )

        self.assertEqual(execution.status, "failed")
        self.assertEqual(execution.reason, "internal_error")
        self.assert_failed_run_without_partial_result(
            run,
            failed_at=failed_at,
            error_code="internal_error",
            secret=secret,
        )

    def test_transient_saver_error_retries_and_rolls_back_result(self):
        executor_module = self.get_executor_module()
        self.create_ready_listing()
        run = self.create_run()
        definition = import_module(
            "automations.registry",
        ).get_module_definition("avito_listings")
        secret = "secret saver database detail"

        def save_partial_result_and_fail(*, run, outcome):
            result = run.avito_listing_result
            result.checked = 999
            result.examples_snapshot = [{"secret": secret}]
            result.save(
                update_fields=[
                    "checked",
                    "examples_snapshot",
                    "updated_at",
                ],
            )
            raise OperationalError(secret)

        failing_definition = replace(
            definition,
            save_run_evaluation=save_partial_result_and_fail,
        )
        failed_at = self.local_datetime(2026, 8, 19, 12)

        with patch.object(
                executor_module,
                "get_module_definition",
                return_value=failing_definition,
        ):
            with patch.object(
                    executor_module.timezone,
                    "now",
                    return_value=failed_at,
            ):
                execution = self.execute_without_unhandled_error(
                    executor_module,
                    run_id=run.id,
                )

        self.assertEqual(execution.status, "queued")
        self.assertEqual(
            execution.reason,
            "transient_database_error",
        )
        run.refresh_from_db()
        self.assertEqual(run.status, "queued")
        self.assertEqual(run.retry_count, 1)
        self.assertEqual(
            run.next_attempt_at,
            failed_at + timedelta(seconds=60),
        )
        self.assertIsNone(run.finished_at)
        self.assertIsNone(run.run_token)
        self.assertIsNone(run.heartbeat_at)
        self.assertEqual(
            run.error_code,
            "transient_database_error",
        )
        self.assertTrue(run.error_message)
        self.assertNotIn(secret, run.error_message)
        result = run.avito_listing_result
        self.assertEqual(result.checked, 0)
        self.assertEqual(result.matched, 0)
        self.assertEqual(result.examples_snapshot, [])
        account_state = apps.get_model(
            "automations",
            "AvitoAutomationAccountState",
        ).objects.get(
            workspace=self.workspace,
            avito_account=self.avito_account,
        )
        self.assertEqual(account_state.status, "idle")

    def test_claim_and_heartbeat_keep_indexed_recovery_deadline(self):
        executor_module = self.get_executor_module()
        run = self.create_run()
        claimed_at = self.local_datetime(2026, 8, 24, 12)
        heartbeat_at = claimed_at + timedelta(minutes=3)

        with patch.object(
                executor_module.timezone,
                "now",
                return_value=claimed_at,
        ):
            claimed = executor_module._claim_run(run_id=run.id)

        self.assertIsNotNone(claimed)
        run.refresh_from_db()
        self.assertEqual(run.status, "evaluating")
        self.assertEqual(run.heartbeat_at, claimed_at)
        self.assertEqual(
            run.next_attempt_at,
            claimed_at + timedelta(minutes=10),
        )

        heartbeat_updated = executor_module._heartbeat_claimed_run(
            run_id=run.id,
            run_token=claimed.run_token,
            heartbeat_at=heartbeat_at,
        )

        self.assertTrue(heartbeat_updated)
        run.refresh_from_db()
        self.assertEqual(run.heartbeat_at, heartbeat_at)
        self.assertEqual(
            run.next_attempt_at,
            heartbeat_at + timedelta(minutes=10),
        )

    def test_celery_task_is_configured_and_calls_real_executor(self):
        try:
            tasks_module = import_module("automations.tasks")
        except ModuleNotFoundError as exc:
            if exc.name != "automations.tasks":
                raise
            self.fail(
                "Приложение automations должно предоставлять "
                "Celery evaluator task.",
            )

        task = tasks_module.evaluate_automation_run_task

        self.assertEqual(task.queue, "automations")
        self.assertTrue(task.acks_late)
        self.assertTrue(task.reject_on_worker_lost)
        self.assertTrue(task.ignore_result)
        self.assertEqual(task.soft_time_limit, 240)
        self.assertEqual(task.time_limit, 300)

        execution = task.run(999999999)

        self.assertEqual(execution.status, "skipped")
        self.assertEqual(execution.reason, "run_not_found")


class AutomationRunRecoveryServiceTests(TestCase):
    module_path = "automations.services.run_recovery"

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(
            email="run-recovery-owner@example.com",
            password="test-password",
        )
        cls.workspace = Workspace.objects.create(
            name="Run recovery workspace",
            slug="run-recovery-workspace",
            owner=cls.user,
        )

    def get_recovery_module(self):
        try:
            return import_module(self.module_path)
        except ModuleNotFoundError as exc:
            if exc.name not in {
                "automations.services",
                self.module_path,
            }:
                raise

            self.fail(
                "Ядро автоматизаций должно предоставлять ограниченный "
                "сервис восстановления run.",
            )

    def local_datetime(self, year, month, day, hour=0):
        return timezone.make_aware(
            datetime(year, month, day, hour),
            timezone.get_current_timezone(),
        )

    def create_run(
            self,
            *,
            status,
            next_attempt_at=None,
            heartbeat_at=None,
            run_token=None,
            retry_count=0,
    ):
        automation_model = apps.get_model("automations", "Automation")
        automation = automation_model.objects.create(
            workspace=self.workspace,
            module_type="avito_listings",
            name=f"Recovery automation {uuid4()}",
            state=automation_model.State.DRAFT,
            created_by=self.user,
            updated_by=self.user,
        )
        return apps.get_model(
            "automations",
            "AutomationRun",
        ).objects.create(
            automation=automation,
            workspace=self.workspace,
            run_kind="preview",
            trigger="manual",
            execution_mode_snapshot="manual",
            automation_version=1,
            automation_name_snapshot=automation.name,
            module_type_snapshot="avito_listings",
            status=status,
            idempotency_key=f"recovery-{uuid4()}",
            retry_count=retry_count,
            next_attempt_at=next_attempt_at,
            run_token=run_token,
            heartbeat_at=heartbeat_at,
            created_by=self.user,
        )

    def test_dispatches_only_due_and_stale_runs_after_commit(self):
        recovery_module = self.get_recovery_module()
        tasks_module = import_module("automations.tasks")
        recovered_at = self.local_datetime(2026, 8, 24, 12)
        due_queued = self.create_run(status="queued")
        due_waiting = self.create_run(
            status="waiting_for_data",
            next_attempt_at=recovered_at,
        )
        stale_token = uuid4()
        stale_evaluating = self.create_run(
            status="evaluating",
            next_attempt_at=recovered_at - timedelta(seconds=1),
            heartbeat_at=recovered_at - timedelta(minutes=11),
            run_token=stale_token,
        )
        future_queued = self.create_run(
            status="queued",
            next_attempt_at=recovered_at + timedelta(minutes=1),
        )
        fresh_evaluating = self.create_run(
            status="evaluating",
            next_attempt_at=recovered_at + timedelta(minutes=9),
            heartbeat_at=recovered_at - timedelta(minutes=1),
            run_token=uuid4(),
        )
        completed = self.create_run(status="completed")

        with patch.object(
                tasks_module.evaluate_automation_run_task,
                "delay",
        ) as delay:
            with self.captureOnCommitCallbacks(
                    execute=False,
            ) as callbacks:
                result = recovery_module.recover_automation_runs(
                    recovered_at=recovered_at,
                )

            self.assertEqual(result.selected, 3)
            self.assertEqual(result.dispatched, 3)
            self.assertEqual(result.failed, 0)
            self.assertEqual(len(callbacks), 1)
            delay.assert_not_called()

            callbacks[0]()

        self.assertEqual(
            [call.args[0] for call in delay.call_args_list],
            [due_queued.id, due_waiting.id, stale_evaluating.id],
        )

        stale_evaluating.refresh_from_db()
        self.assertEqual(stale_evaluating.status, "queued")
        self.assertEqual(stale_evaluating.retry_count, 1)
        self.assertIsNone(stale_evaluating.next_attempt_at)
        self.assertIsNone(stale_evaluating.run_token)
        self.assertIsNone(stale_evaluating.heartbeat_at)
        self.assertEqual(stale_evaluating.error_code, "worker_lost")
        self.assertTrue(stale_evaluating.error_message)

        future_queued.refresh_from_db()
        fresh_evaluating.refresh_from_db()
        completed.refresh_from_db()
        self.assertEqual(future_queued.status, "queued")
        self.assertEqual(fresh_evaluating.status, "evaluating")
        self.assertEqual(fresh_evaluating.retry_count, 0)
        self.assertEqual(completed.status, "completed")

    def test_stale_run_fails_after_three_bounded_retries(self):
        recovery_module = self.get_recovery_module()
        recovered_at = self.local_datetime(2026, 8, 24, 12)
        stale_run = self.create_run(
            status="evaluating",
            next_attempt_at=recovered_at,
            heartbeat_at=recovered_at - timedelta(minutes=11),
            run_token=uuid4(),
            retry_count=3,
        )

        with self.captureOnCommitCallbacks(
                execute=False,
        ) as callbacks:
            result = recovery_module.recover_automation_runs(
                recovered_at=recovered_at,
            )

        self.assertEqual(result.selected, 1)
        self.assertEqual(result.dispatched, 0)
        self.assertEqual(result.failed, 1)
        self.assertEqual(callbacks, [])

        stale_run.refresh_from_db()
        self.assertEqual(stale_run.status, "failed")
        self.assertEqual(stale_run.retry_count, 3)
        self.assertEqual(stale_run.finished_at, recovered_at)
        self.assertIsNone(stale_run.next_attempt_at)
        self.assertIsNone(stale_run.run_token)
        self.assertIsNone(stale_run.heartbeat_at)
        self.assertEqual(stale_run.error_code, "worker_lost")
        self.assertTrue(stale_run.error_message)

    def test_processes_at_most_one_hundred_rows_per_call(self):
        recovery_module = self.get_recovery_module()
        tasks_module = import_module("automations.tasks")
        recovered_at = self.local_datetime(2026, 8, 24, 12)

        for _ in range(101):
            self.create_run(status="queued")

        with patch.object(
                tasks_module.evaluate_automation_run_task,
                "delay",
        ) as delay:
            with self.captureOnCommitCallbacks(
                    execute=True,
            ):
                with CaptureQueriesContext(connection) as queries:
                    result = recovery_module.recover_automation_runs(
                        recovered_at=recovered_at,
                    )

        self.assertEqual(result.selected, 100)
        self.assertEqual(result.dispatched, 100)
        self.assertEqual(result.failed, 0)
        self.assertEqual(delay.call_count, 100)
        recovery_selects = [
            query["sql"].upper()
            for query in queries.captured_queries
            if "AUTOMATIONS_AUTOMATIONRUN" in query["sql"].upper()
            and "FOR UPDATE" in query["sql"].upper()
        ]
        self.assertTrue(
            recovery_selects,
            "Recovery должен блокировать только выбранный batch run.",
        )
        self.assertIn("SKIP LOCKED", recovery_selects[0])


class AutomationRecoveryCeleryTests(SimpleTestCase):
    def get_recovery_task(self):
        tasks_module = import_module("automations.tasks")
        task = getattr(
            tasks_module,
            "recover_automation_runs_task",
            None,
        )
        self.assertIsNotNone(
            task,
            "Приложение automations должно предоставлять recovery task.",
        )
        return tasks_module, task

    def test_recovery_task_has_bounded_worker_configuration(self):
        _, task = self.get_recovery_task()

        self.assertEqual(task.queue, "automations")
        self.assertTrue(task.acks_late)
        self.assertTrue(task.reject_on_worker_lost)
        self.assertTrue(task.ignore_result)
        self.assertEqual(task.soft_time_limit, 60)
        self.assertEqual(task.time_limit, 90)

    def test_recovery_task_delegates_one_pass_with_current_time(self):
        tasks_module, task = self.get_recovery_task()
        cleanup_service = getattr(
            tasks_module,
            "expire_pending_decisions",
            None,
        )
        self.assertIsNotNone(
            cleanup_service,
            (
                "Recovery task должна использовать bounded-сервис "
                "истечения ожидающих решений."
            ),
        )
        effect_recovery_service = getattr(
            tasks_module,
            "recover_pending_listing_effects",
            None,
        )
        self.assertIsNotNone(
            effect_recovery_service,
            (
                "Recovery task должна использовать bounded-сервис "
                "подтверждения внешних CSV-эффектов."
            ),
        )
        recovered_at = timezone.make_aware(
            datetime(2026, 8, 25, 12),
            timezone.get_current_timezone(),
        )
        expected_result = SimpleNamespace(
            selected=3,
            dispatched=2,
            failed=1,
        )
        expected_cleanup_result = SimpleNamespace(
            selected=4,
            expired=3,
            skipped=0,
            busy=1,
        )
        expected_effect_result = SimpleNamespace(
            selected=5,
            completed=2,
            superseded=1,
            failed=1,
            retries_scheduled=1,
            accounts_queued=1,
            busy=0,
        )

        with patch.object(
                tasks_module.timezone,
                "now",
                return_value=recovered_at,
        ):
            with patch.object(
                    tasks_module,
                    "recover_automation_runs",
                    return_value=expected_result,
            ) as recover:
                with patch.object(
                        tasks_module,
                        "expire_pending_decisions",
                        return_value=expected_cleanup_result,
                ) as cleanup:
                    with patch.object(
                            tasks_module,
                            "recover_pending_listing_effects",
                            return_value=expected_effect_result,
                    ) as recover_effects:
                        result = task.run()

        self.assertIs(result, expected_result)
        recover.assert_called_once_with(recovered_at=recovered_at)
        cleanup.assert_called_once_with(expired_at=recovered_at)
        recover_effects.assert_called_once_with(
            recovered_at=recovered_at,
        )

    def test_recovery_uses_existing_beat_schedule_every_ten_minutes(self):
        celery_app = import_module("system.celery").app
        schedule_name = (
            "recover_automation_runs_every_ten_minutes"
        )
        beat_schedule = celery_app.conf.beat_schedule

        self.assertIn(schedule_name, beat_schedule)
        entry = beat_schedule[schedule_name]
        self.assertEqual(
            entry["task"],
            "automations.tasks.recover_automation_runs_task",
        )
        self.assertEqual(
            entry["schedule"].minute,
            {5, 15, 25, 35, 45, 55},
        )
        matching_entries = [
            candidate
            for candidate in beat_schedule.values()
            if candidate["task"]
            == "automations.tasks.recover_automation_runs_task"
        ]
        self.assertEqual(len(matching_entries), 1)


class AutomationManagementServiceTests(TestCase):
    module_path = "automations.services.automation_management"

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(
            email="automation-management-owner@example.com",
            password="test-password",
        )
        cls.other_user = get_user_model().objects.create_user(
            email="automation-management-other@example.com",
            password="test-password",
        )
        cls.workspace = Workspace.objects.create(
            name="Automation management workspace",
            slug="automation-management-workspace",
            owner=cls.user,
        )
        cls.other_workspace = Workspace.objects.create(
            name="Other automation management workspace",
            slug="other-automation-management-workspace",
            owner=cls.other_user,
        )
        cls.first_account = AvitoAccount.objects.create(
            workspace=cls.workspace,
            name="First automation management account",
        )
        cls.second_account = AvitoAccount.objects.create(
            workspace=cls.workspace,
            name="Second automation management account",
        )
        cls.foreign_account = AvitoAccount.objects.create(
            workspace=cls.other_workspace,
            name="Foreign automation management account",
        )

    def get_management_service(self):
        try:
            return import_module(self.module_path)
        except ModuleNotFoundError as error:
            if error.name != self.module_path:
                raise

            self.fail(
                "Добавьте доменный сервис управления автоматизациями.",
            )

    def build_config(
            self,
            *,
            avito_account_id=None,
            action_type="pause",
            max_actions_per_run=10,
            approval_ttl_minutes=1440,
    ):
        return {
            "avito_account_id": (
                avito_account_id or self.first_account.id
            ),
            "condition_tree": build_condition_tree({
                "type": "condition",
                "metric": "contacts",
                "aggregation": "sum",
                "window_days": 10,
                "comparator": "lt",
                "value": 10,
            }),
            "action": {
                "type": action_type,
                "config": {},
            },
            "max_actions_per_run": max_actions_per_run,
            "approval_ttl_minutes": approval_ttl_minutes,
        }

    def create_automation(self, **overrides):
        values = {
            "workspace": self.workspace,
            "actor": self.user,
            "name": "Архивировать объявления без контактов",
            "module_type": "avito_listings",
            "config": self.build_config(),
        }
        values.update(overrides)
        return self.get_management_service().create_automation(**values)

    def create_run_context(
            self,
            *,
            automation,
            status,
            run_kind,
            automation_version=None,
    ):
        run_model = apps.get_model("automations", "AutomationRun")
        result_model = apps.get_model(
            "automations",
            "AvitoListingRunResult",
        )
        run = run_model.objects.create(
            automation=automation,
            workspace=self.workspace,
            run_kind=run_kind,
            trigger=run_model.Trigger.MANUAL,
            execution_mode_snapshot="manual",
            automation_version=(
                automation.version
                if automation_version is None
                else automation_version
            ),
            automation_name_snapshot=automation.name,
            module_type_snapshot=automation.module_type,
            status=status,
            idempotency_key=f"management-state-{uuid4()}",
            created_by=self.user,
        )
        result = result_model.objects.create(
            run=run,
            workspace=self.workspace,
            avito_account=self.first_account,
            as_of_date=date(2026, 8, 20),
            condition_snapshot=self.build_config()["condition_tree"],
            action_snapshot={"type": "pause", "config": {}},
        )
        return SimpleNamespace(run=run, result=result)

    def add_decision(self, context, *, status="pending_approval"):
        decision_model = apps.get_model(
            "automations",
            "AvitoListingDecision",
        )
        active_since = timezone.make_aware(
            datetime(2026, 8, 1, 9, 0),
            timezone.get_current_timezone(),
        )
        listing = AvitoListing.objects.create(
            workspace=self.workspace,
            avito_account=self.first_account,
            source=AvitoListing.Source.AVITO_EXCEL,
            management_status=AvitoListing.ManagementStatus.MANAGED,
            desired_status=(
                AvitoListing.DesiredStatus.PAUSE
                if status == "effect_pending"
                else AvitoListing.DesiredStatus.PUBLISH
            ),
            active_since=(
                None if status == "effect_pending" else active_since
            ),
            avito_id=f"management-decision-{uuid4()}",
            row_id=f"MANAGEMENT-DECISION-{uuid4()}",
            title="Решение старой версии",
        )
        decision = decision_model.objects.create(
            run=context.run,
            automation=context.run.automation,
            workspace=self.workspace,
            avito_account=self.first_account,
            listing=listing,
            listing_id_snapshot=listing.id,
            listing_snapshot={"id": listing.id},
            status=status,
            automation_version=context.run.automation_version,
            active_since_snapshot=active_since,
            condition_snapshot=self.build_config()["condition_tree"],
            metrics_snapshot=[],
            action_snapshot={"type": "pause", "config": {}},
            expires_at=timezone.now() + timedelta(hours=1),
            action_applied_at=(
                timezone.now()
                if status == "effect_pending"
                else None
            ),
            required_export_revision=(
                1 if status == "effect_pending" else None
            ),
        )
        if status == "pending_approval":
            context.result.pending_approval = 1
            context.result.save(
                update_fields=["pending_approval", "updated_at"],
            )
        return decision

    def test_create_saves_manual_draft_and_typed_config_atomically(self):
        automation = self.create_automation()

        automation.refresh_from_db()
        config = automation.avito_listing_config
        self.assertEqual(automation.workspace, self.workspace)
        self.assertEqual(automation.module_type, "avito_listings")
        self.assertEqual(
            automation.name,
            "Архивировать объявления без контактов",
        )
        self.assertEqual(automation.state, "draft")
        self.assertEqual(automation.execution_mode, "manual")
        self.assertEqual(automation.version, 1)
        self.assertEqual(automation.created_by, self.user)
        self.assertEqual(automation.updated_by, self.user)
        self.assertEqual(config.workspace, self.workspace)
        self.assertEqual(config.avito_account, self.first_account)
        self.assertEqual(config.action_type, "pause")
        self.assertEqual(config.action_config, {})
        self.assertEqual(config.max_actions_per_run, 10)
        self.assertEqual(config.approval_ttl_minutes, 1440)

    def test_invalid_or_foreign_config_does_not_save_partial_rows(self):
        service = self.get_management_service()
        automation_model = apps.get_model("automations", "Automation")
        config_model = apps.get_model(
            "automations",
            "AvitoListingAutomationConfig",
        )
        invalid_cases = []

        invalid_tree = self.build_config()
        invalid_tree["condition_tree"]["children"][0]["metric"] = (
            "expenses"
        )
        invalid_cases.append(
            (invalid_tree, "invalid_condition_tree"),
        )

        invalid_action = self.build_config(action_type="delete")
        invalid_cases.append((invalid_action, "invalid_action"))

        foreign_account = self.build_config(
            avito_account_id=self.foreign_account.id,
        )
        invalid_cases.append(
            (foreign_account, "avito_account_not_found"),
        )

        invalid_limit = self.build_config(max_actions_per_run=101)
        invalid_cases.append((invalid_limit, "invalid_run_limit"))

        invalid_ttl = self.build_config(approval_ttl_minutes=59)
        invalid_cases.append((invalid_ttl, "invalid_approval_ttl"))

        for config, expected_code in invalid_cases:
            with self.subTest(expected_code=expected_code):
                with self.assertRaises(
                    service.AutomationManagementError,
                ) as raised:
                    self.create_automation(config=config)

                self.assertEqual(raised.exception.code, expected_code)
                self.assertEqual(automation_model.objects.count(), 0)
                self.assertEqual(config_model.objects.count(), 0)

    def test_unknown_module_is_rejected_before_any_write(self):
        service = self.get_management_service()

        with self.assertRaises(
            service.AutomationManagementError,
        ) as raised:
            self.create_automation(module_type="messages")

        self.assertEqual(raised.exception.code, "unsupported_module")
        self.assertFalse(
            apps.get_model("automations", "Automation").objects.exists(),
        )

    def test_enable_requires_completed_preview_of_current_version(self):
        service = self.get_management_service()
        automation = self.create_automation()

        with self.assertRaises(
            service.AutomationManagementError,
        ) as missing_preview:
            service.update_automation(
                workspace=self.workspace,
                actor=self.other_user,
                automation_id=automation.id,
                state="enabled",
            )

        self.assertEqual(
            missing_preview.exception.code,
            "preview_required",
        )
        automation.refresh_from_db()
        self.assertEqual(automation.state, "draft")

        self.create_run_context(
            automation=automation,
            status="failed",
            run_kind="preview",
        )

        with self.assertRaises(
            service.AutomationManagementError,
        ) as failed_preview:
            service.update_automation(
                workspace=self.workspace,
                actor=self.other_user,
                automation_id=automation.id,
                state="enabled",
            )

        self.assertEqual(
            failed_preview.exception.code,
            "preview_required",
        )

        self.create_run_context(
            automation=automation,
            status="completed",
            run_kind="preview",
        )

        updated = service.update_automation(
            workspace=self.workspace,
            actor=self.other_user,
            automation_id=automation.id,
            state="enabled",
        )

        self.assertEqual(updated.state, "enabled")
        self.assertEqual(updated.version, 1)
        self.assertEqual(updated.updated_by, self.other_user)

    def test_name_change_keeps_current_preview_valid(self):
        service = self.get_management_service()
        automation = self.create_automation()
        self.create_run_context(
            automation=automation,
            status="completed",
            run_kind="preview",
        )
        service.update_automation(
            workspace=self.workspace,
            actor=self.user,
            automation_id=automation.id,
            state="enabled",
        )

        updated = service.update_automation(
            workspace=self.workspace,
            actor=self.other_user,
            automation_id=automation.id,
            name="Новое название",
        )

        self.assertEqual(updated.name, "Новое название")
        self.assertEqual(updated.state, "enabled")
        self.assertEqual(updated.version, 1)

        with self.assertRaises(
            service.AutomationManagementError,
        ) as raised:
            service.update_automation(
                workspace=self.workspace,
                actor=self.user,
                automation_id=automation.id,
                state="archived",
            )

        self.assertEqual(
            raised.exception.code,
            "invalid_state_transition",
        )

    def test_config_change_disables_rule_and_requires_new_preview(self):
        service = self.get_management_service()
        automation = self.create_automation()
        self.create_run_context(
            automation=automation,
            status="completed",
            run_kind="preview",
        )
        service.update_automation(
            workspace=self.workspace,
            actor=self.user,
            automation_id=automation.id,
            state="enabled",
        )

        updated = service.update_automation(
            workspace=self.workspace,
            actor=self.user,
            automation_id=automation.id,
            config=self.build_config(action_type="archive"),
        )

        self.assertEqual(updated.version, 2)
        self.assertEqual(updated.state, "disabled")

        with self.assertRaises(
            service.AutomationManagementError,
        ) as stale_preview:
            service.update_automation(
                workspace=self.workspace,
                actor=self.user,
                automation_id=automation.id,
                state="enabled",
            )

        self.assertEqual(
            stale_preview.exception.code,
            "preview_required",
        )

        self.create_run_context(
            automation=updated,
            status="completed",
            run_kind="preview",
        )
        enabled = service.update_automation(
            workspace=self.workspace,
            actor=self.user,
            automation_id=automation.id,
            state="enabled",
        )

        self.assertEqual(enabled.version, 2)
        self.assertEqual(enabled.state, "enabled")

    def test_config_change_cannot_enable_rule_in_same_update(self):
        service = self.get_management_service()
        automation = self.create_automation()
        self.create_run_context(
            automation=automation,
            status="completed",
            run_kind="preview",
        )
        original_config = automation.avito_listing_config

        with self.assertRaises(
            service.AutomationManagementError,
        ) as raised:
            service.update_automation(
                workspace=self.workspace,
                actor=self.user,
                automation_id=automation.id,
                state="enabled",
                config=self.build_config(action_type="archive"),
            )

        self.assertEqual(raised.exception.code, "preview_required")
        automation.refresh_from_db()
        original_config.refresh_from_db()
        self.assertEqual(automation.state, "draft")
        self.assertEqual(automation.version, 1)
        self.assertEqual(original_config.action_type, "pause")

    def test_config_change_increments_version_and_account_locks_after_run(self):
        service = self.get_management_service()
        automation = self.create_automation()
        changed_config = self.build_config(
            avito_account_id=self.second_account.id,
            action_type="archive",
            max_actions_per_run=20,
            approval_ttl_minutes=60,
        )

        updated = service.update_automation(
            workspace=self.workspace,
            actor=self.user,
            automation_id=automation.id,
            config=changed_config,
        )

        updated.refresh_from_db()
        config = updated.avito_listing_config
        self.assertEqual(updated.version, 2)
        self.assertEqual(config.avito_account, self.second_account)
        self.assertEqual(config.action_type, "archive")
        self.assertEqual(config.max_actions_per_run, 20)
        self.assertEqual(config.approval_ttl_minutes, 60)

        run_model = apps.get_model("automations", "AutomationRun")
        run_model.objects.create(
            automation=updated,
            workspace=self.workspace,
            run_kind=run_model.RunKind.PREVIEW,
            trigger=run_model.Trigger.MANUAL,
            execution_mode_snapshot="manual",
            automation_version=updated.version,
            automation_name_snapshot=updated.name,
            module_type_snapshot=updated.module_type,
            status=run_model.Status.COMPLETED,
            idempotency_key=f"management-{uuid4()}",
            created_by=self.user,
        )

        with self.assertRaises(
            service.AutomationManagementError,
        ) as raised:
            service.update_automation(
                workspace=self.workspace,
                actor=self.user,
                automation_id=updated.id,
                config=self.build_config(
                    avito_account_id=self.first_account.id,
                ),
            )

        self.assertEqual(
            raised.exception.code,
            "avito_account_immutable",
        )
        updated.refresh_from_db()
        config.refresh_from_db()
        self.assertEqual(updated.version, 2)
        self.assertEqual(config.avito_account, self.second_account)

    def test_archive_is_soft_idempotent_and_blocks_later_updates(self):
        service = self.get_management_service()
        automation = self.create_automation()
        archived_at = timezone.make_aware(
            datetime(2026, 8, 29, 14, 0),
            timezone.get_current_timezone(),
        )

        first = service.archive_automation(
            workspace=self.workspace,
            actor=self.user,
            automation_id=automation.id,
            archived_at=archived_at,
        )
        repeated = service.archive_automation(
            workspace=self.workspace,
            actor=self.other_user,
            automation_id=automation.id,
            archived_at=archived_at + timedelta(minutes=1),
        )

        self.assertEqual(first.state, "archived")
        self.assertEqual(first.archived_at, archived_at)
        self.assertEqual(repeated.state, "archived")
        self.assertEqual(repeated.archived_at, archived_at)

        with self.assertRaises(
            service.AutomationManagementError,
        ) as raised:
            service.update_automation(
                workspace=self.workspace,
                actor=self.user,
                automation_id=automation.id,
                name="Нельзя изменить",
            )

        self.assertEqual(raised.exception.code, "automation_archived")

    def test_foreign_workspace_cannot_update_or_archive(self):
        service = self.get_management_service()
        automation = self.create_automation()

        for operation in (
                lambda: service.update_automation(
                    workspace=self.other_workspace,
                    actor=self.other_user,
                    automation_id=automation.id,
                    name="Чужое изменение",
                ),
                lambda: service.archive_automation(
                    workspace=self.other_workspace,
                    actor=self.other_user,
                    automation_id=automation.id,
                ),
        ):
            with self.subTest(operation=operation):
                with self.assertRaises(
                    service.AutomationManagementError,
                ) as raised:
                    operation()

                self.assertEqual(
                    raised.exception.code,
                    "automation_not_found",
                )

    def test_config_change_closes_old_queued_run_and_pending_decision(self):
        service = self.get_management_service()
        automation = self.create_automation()
        self.create_run_context(
            automation=automation,
            status="completed",
            run_kind="preview",
        )
        service.update_automation(
            workspace=self.workspace,
            actor=self.user,
            automation_id=automation.id,
            state="enabled",
        )
        automation.refresh_from_db()
        queued_context = self.create_run_context(
            automation=automation,
            status="queued",
            run_kind="preview",
        )
        approval_context = self.create_run_context(
            automation=automation,
            status="waiting_approval",
            run_kind="execute",
        )
        decision = self.add_decision(approval_context)
        changed_at = timezone.make_aware(
            datetime(2026, 8, 29, 15, 0),
            timezone.get_current_timezone(),
        )

        with patch.object(
                service.timezone,
                "now",
                return_value=changed_at,
        ):
            updated = service.update_automation(
                workspace=self.workspace,
                actor=self.user,
                automation_id=automation.id,
                config=self.build_config(action_type="archive"),
            )

        queued_context.run.refresh_from_db()
        approval_context.run.refresh_from_db()
        approval_context.result.refresh_from_db()
        decision.refresh_from_db()
        self.assertEqual(updated.version, 2)
        self.assertEqual(queued_context.run.status, "cancelled")
        self.assertEqual(queued_context.run.finished_at, changed_at)
        self.assertEqual(
            queued_context.run.error_code,
            "automation_version_changed",
        )
        self.assertTrue(queued_context.run.error_message)
        self.assertEqual(decision.status, "stale")
        self.assertEqual(decision.terminal_at, changed_at)
        self.assertEqual(decision.error_code, "stale")
        self.assertEqual(approval_context.result.pending_approval, 0)
        self.assertEqual(approval_context.run.status, "completed")
        self.assertEqual(approval_context.run.finished_at, changed_at)

    def test_config_change_does_not_interrupt_started_or_applied_work(self):
        service = self.get_management_service()
        automation = self.create_automation()
        self.create_run_context(
            automation=automation,
            status="completed",
            run_kind="preview",
        )
        service.update_automation(
            workspace=self.workspace,
            actor=self.user,
            automation_id=automation.id,
            state="enabled",
        )
        automation.refresh_from_db()
        evaluating_context = self.create_run_context(
            automation=automation,
            status="evaluating",
            run_kind="preview",
        )
        effect_context = self.create_run_context(
            automation=automation,
            status="effect_pending",
            run_kind="execute",
        )
        effect_decision = self.add_decision(
            effect_context,
            status="effect_pending",
        )

        updated = service.update_automation(
            workspace=self.workspace,
            actor=self.user,
            automation_id=automation.id,
            config=self.build_config(action_type="archive"),
        )

        evaluating_context.run.refresh_from_db()
        effect_context.run.refresh_from_db()
        effect_decision.refresh_from_db()
        self.assertEqual(updated.version, 2)
        self.assertEqual(evaluating_context.run.status, "evaluating")
        self.assertEqual(effect_context.run.status, "effect_pending")
        self.assertEqual(effect_decision.status, "effect_pending")
        self.assertEqual(effect_decision.required_export_revision, 1)

    def test_disable_and_archive_close_unstarted_and_pending_work(self):
        service = self.get_management_service()
        transition_at = timezone.make_aware(
            datetime(2026, 8, 29, 16, 0),
            timezone.get_current_timezone(),
        )

        for transition in ("disable", "archive"):
            with self.subTest(transition=transition):
                automation = self.create_automation(
                    name=f"Automation for {transition}",
                )
                self.create_run_context(
                    automation=automation,
                    status="completed",
                    run_kind="preview",
                )
                service.update_automation(
                    workspace=self.workspace,
                    actor=self.user,
                    automation_id=automation.id,
                    state="enabled",
                )
                automation.refresh_from_db()
                waiting_context = self.create_run_context(
                    automation=automation,
                    status="waiting_for_data",
                    run_kind="preview",
                )
                approval_context = self.create_run_context(
                    automation=automation,
                    status="waiting_approval",
                    run_kind="execute",
                )
                decision = self.add_decision(approval_context)

                with patch.object(
                        service.timezone,
                        "now",
                        return_value=transition_at,
                ):
                    if transition == "disable":
                        service.update_automation(
                            workspace=self.workspace,
                            actor=self.user,
                            automation_id=automation.id,
                            state="disabled",
                        )
                    else:
                        service.archive_automation(
                            workspace=self.workspace,
                            actor=self.user,
                            automation_id=automation.id,
                            archived_at=transition_at,
                        )

                waiting_context.run.refresh_from_db()
                approval_context.run.refresh_from_db()
                approval_context.result.refresh_from_db()
                decision.refresh_from_db()
                self.assertEqual(waiting_context.run.status, "cancelled")
                self.assertEqual(
                    waiting_context.run.error_code,
                    "automation_not_enabled",
                )
                self.assertEqual(decision.status, "stale")
                self.assertEqual(decision.terminal_at, transition_at)
                self.assertEqual(approval_context.result.pending_approval, 0)
                self.assertEqual(approval_context.run.status, "completed")


class AutomationRunCreationServiceTests(TestCase):
    module_path = "automations.services.run_creation"

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(
            email="preview-run-owner@example.com",
            password="test-password",
        )
        cls.workspace = Workspace.objects.create(
            name="Preview run workspace",
            slug="preview-run-workspace",
            owner=cls.user,
        )
        cls.avito_account = AvitoAccount.objects.create(
            workspace=cls.workspace,
            name="Preview run Avito account",
        )

        cls.other_user = get_user_model().objects.create_user(
            email="preview-run-other@example.com",
            password="test-password",
        )
        cls.other_workspace = Workspace.objects.create(
            name="Other preview workspace",
            slug="other-preview-workspace",
            owner=cls.other_user,
        )
        cls.other_avito_account = AvitoAccount.objects.create(
            workspace=cls.other_workspace,
            name="Other preview Avito account",
        )

        automation_model = apps.get_model("automations", "Automation")
        cls.automation = automation_model.objects.create(
            workspace=cls.workspace,
            module_type="avito_listings",
            name="Preview automation",
            state=automation_model.State.DRAFT,
            created_by=cls.user,
            updated_by=cls.user,
        )
        config_model = apps.get_model(
            "automations",
            "AvitoListingAutomationConfig",
        )
        cls.condition_tree = build_condition_tree({
            "type": "condition",
            "metric": "contacts",
            "aggregation": "sum",
            "window_days": 10,
            "comparator": "lt",
            "value": 10,
        })
        cls.config = config_model.objects.create(
            automation=cls.automation,
            workspace=cls.workspace,
            avito_account=cls.avito_account,
            condition_tree=cls.condition_tree,
            action_type="pause",
            action_config={},
            max_actions_per_run=10,
            approval_ttl_minutes=1440,
        )

    def get_run_creation_module(self):
        try:
            return import_module(self.module_path)
        except ModuleNotFoundError as exc:
            if exc.name not in {
                "automations.services",
                self.module_path,
            }:
                raise

            self.fail(
                "Приложение automations должно предоставлять сервис "
                "создания automation run.",
            )

    def create_preview(self, preview_module, *, key, user=None):
        return preview_module.create_or_get_preview_run(
            workspace=self.workspace,
            automation_id=self.automation.id,
            created_by=user or self.user,
            idempotency_key=key,
        )

    def create_manual_run(self, run_creation_module, *, key, user=None):
        return run_creation_module.create_or_get_manual_run(
            workspace=self.workspace,
            automation_id=self.automation.id,
            created_by=user or self.user,
            idempotency_key=key,
        )

    def test_dispatches_new_and_repeated_queued_run_only_after_commit(self):
        preview_module = self.get_run_creation_module()
        try:
            tasks_module = import_module("automations.tasks")
        except ModuleNotFoundError as exc:
            if exc.name != "automations.tasks":
                raise
            self.fail(
                "Приложение automations должно предоставлять "
                "Celery evaluator task.",
            )

        with patch.object(
                tasks_module.evaluate_automation_run_task,
                "delay",
        ) as delay:
            with self.captureOnCommitCallbacks(
                    execute=False,
            ) as first_callbacks:
                first = self.create_preview(
                    preview_module,
                    key="dispatch-after-commit",
                )

            self.assertEqual(len(first_callbacks), 1)
            delay.assert_not_called()
            first_callbacks[0]()
            delay.assert_called_once_with(first.run.id)

            delay.reset_mock()
            with self.captureOnCommitCallbacks(
                    execute=False,
            ) as repeated_callbacks:
                repeated = self.create_preview(
                    preview_module,
                    key="dispatch-after-commit",
                )

            self.assertFalse(repeated.created)
            self.assertEqual(repeated.run.id, first.run.id)
            self.assertEqual(len(repeated_callbacks), 1)
            delay.assert_not_called()
            repeated_callbacks[0]()
            delay.assert_called_once_with(first.run.id)

            first.run.status = "completed"
            first.run.finished_at = timezone.now()
            first.run.save(
                update_fields=[
                    "status",
                    "finished_at",
                    "updated_at",
                ],
            )

            delay.reset_mock()
            with self.captureOnCommitCallbacks(
                    execute=False,
            ) as completed_callbacks:
                completed = self.create_preview(
                    preview_module,
                    key="dispatch-after-commit",
                )

            self.assertFalse(completed.created)
            self.assertEqual(completed_callbacks, [])
            delay.assert_not_called()

    def test_creates_run_and_typed_result_with_frozen_snapshots(self):
        preview_module = self.get_run_creation_module()
        as_of_date = date(2026, 8, 19)
        self.config.max_actions_per_run = 37
        self.config.approval_ttl_minutes = 180
        self.config.save(
            update_fields=[
                "max_actions_per_run",
                "approval_ttl_minutes",
                "updated_at",
            ],
        )

        with patch.object(
                preview_module.timezone,
                "localdate",
                return_value=as_of_date,
        ):
            creation = self.create_preview(
                preview_module,
                key="  preview-key  ",
            )

        run = creation.run
        result = run.avito_listing_result

        self.assertTrue(creation.created)
        self.assertEqual(run.workspace, self.workspace)
        self.assertEqual(run.automation, self.automation)
        self.assertEqual(run.run_kind, "preview")
        self.assertEqual(run.trigger, "manual")
        self.assertEqual(run.status, "queued")
        self.assertEqual(run.idempotency_key, "preview-key")
        self.assertEqual(run.execution_mode_snapshot, "manual")
        self.assertEqual(run.automation_version, 1)
        self.assertEqual(
            run.automation_name_snapshot,
            "Preview automation",
        )
        self.assertEqual(
            run.module_type_snapshot,
            "avito_listings",
        )
        self.assertEqual(run.created_by, self.user)

        self.assertEqual(result.workspace, self.workspace)
        self.assertEqual(result.avito_account, self.avito_account)
        self.assertEqual(result.as_of_date, as_of_date)
        self.assertEqual(result.condition_snapshot, self.condition_tree)
        self.assertEqual(
            result.action_snapshot,
            {"type": "pause", "config": {}},
        )
        self.assertEqual(
            getattr(result, "max_actions_per_run_snapshot", None),
            37,
        )
        self.assertEqual(
            getattr(result, "approval_ttl_minutes_snapshot", None),
            180,
        )
        self.assertEqual(result.target_max_id_snapshot, 0)
        self.assertEqual(result.checked, 0)
        self.assertEqual(result.examples_snapshot, [])
        self.assertEqual(
            apps.get_model(
                "automations",
                "AvitoListingDecision",
            ).objects.count(),
            0,
        )

    def test_preview_is_allowed_for_disabled_but_not_archived_rule(self):
        run_creation_module = self.get_run_creation_module()
        automation_model = apps.get_model("automations", "Automation")
        self.automation.state = automation_model.State.DISABLED
        self.automation.save(update_fields=["state", "updated_at"])

        try:
            disabled_preview = self.create_preview(
                run_creation_module,
                key="disabled-preview",
            )
        except run_creation_module.RunCreationError as error:
            self.fail(
                "Preview должен быть доступен для disabled правила, "
                f"но получена ошибка {error.code}.",
            )

        self.assertTrue(disabled_preview.created)
        self.assertEqual(disabled_preview.run.run_kind, "preview")
        self.assertEqual(disabled_preview.run.status, "queued")

        self.automation.state = automation_model.State.ARCHIVED
        self.automation.save(update_fields=["state", "updated_at"])

        with self.assertRaises(
            run_creation_module.RunCreationError,
        ) as archived:
            self.create_preview(
                run_creation_module,
                key="archived-preview",
            )

        self.assertEqual(
            archived.exception.code,
            "invalid_automation_state",
        )

    def test_manual_run_creates_execute_with_frozen_typed_result(self):
        run_creation_module = self.get_run_creation_module()
        automation_model = apps.get_model("automations", "Automation")
        self.automation.state = automation_model.State.ENABLED
        self.automation.save(update_fields=["state", "updated_at"])
        as_of_date = date(2026, 8, 20)

        with patch.object(
                run_creation_module.timezone,
                "localdate",
                return_value=as_of_date,
        ):
            creation = self.create_manual_run(
                run_creation_module,
                key="  manual-run-key  ",
            )

        run = creation.run
        result = run.avito_listing_result

        self.assertTrue(creation.created)
        self.assertEqual(run.run_kind, "execute")
        self.assertEqual(run.trigger, "manual")
        self.assertEqual(run.status, "queued")
        self.assertEqual(run.idempotency_key, "manual-run-key")
        self.assertEqual(run.execution_mode_snapshot, "manual")
        self.assertEqual(run.created_by, self.user)
        self.assertEqual(result.as_of_date, as_of_date)
        self.assertEqual(result.condition_snapshot, self.condition_tree)
        self.assertEqual(
            result.action_snapshot,
            {"type": "pause", "config": {}},
        )
        self.assertEqual(result.max_actions_per_run_snapshot, 10)
        self.assertEqual(result.approval_ttl_minutes_snapshot, 1440)

    def test_manual_run_requires_enabled_automation(self):
        run_creation_module = self.get_run_creation_module()
        automation_model = apps.get_model("automations", "Automation")

        for state in (
                automation_model.State.DRAFT,
                automation_model.State.DISABLED,
                automation_model.State.ARCHIVED,
        ):
            with self.subTest(state=state):
                self.automation.state = state
                self.automation.save(
                    update_fields=["state", "updated_at"],
                )

                with self.assertRaises(
                        run_creation_module.RunCreationError,
                ) as caught:
                    self.create_manual_run(
                        run_creation_module,
                        key=f"manual-{state}",
                    )

                self.assertEqual(
                    caught.exception.code,
                    "invalid_automation_state",
                )

        self.assertEqual(
            apps.get_model(
                "automations",
                "AutomationRun",
            ).objects.count(),
            0,
        )

    def test_open_preview_does_not_block_manual_run(self):
        run_creation_module = self.get_run_creation_module()
        preview = self.create_preview(
            run_creation_module,
            key="open-preview",
        )

        automation_model = apps.get_model("automations", "Automation")
        self.automation.state = automation_model.State.ENABLED
        self.automation.save(update_fields=["state", "updated_at"])

        manual = self.create_manual_run(
            run_creation_module,
            key="manual-alongside-preview",
        )

        self.assertTrue(manual.created)
        self.assertEqual(preview.run.run_kind, "preview")
        self.assertEqual(manual.run.run_kind, "execute")
        self.assertEqual(
            apps.get_model(
                "automations",
                "AutomationRun",
            ).objects.count(),
            2,
        )

    def test_manual_run_is_idempotent_and_rejects_second_open_run(self):
        run_creation_module = self.get_run_creation_module()
        automation_model = apps.get_model("automations", "Automation")
        self.automation.state = automation_model.State.ENABLED
        self.automation.save(update_fields=["state", "updated_at"])

        first = self.create_manual_run(
            run_creation_module,
            key="  repeat-manual  ",
        )
        repeated = self.create_manual_run(
            run_creation_module,
            key="repeat-manual",
        )

        self.assertFalse(repeated.created)
        self.assertEqual(repeated.run.id, first.run.id)

        with self.assertRaises(
                run_creation_module.RunCreationError,
        ) as caught:
            self.create_manual_run(
                run_creation_module,
                key="different-manual",
            )

        self.assertEqual(caught.exception.code, "open_execute_conflict")
        self.assertEqual(caught.exception.open_run_id, first.run.id)
        self.assertEqual(
            apps.get_model(
                "automations",
                "AutomationRun",
            ).objects.count(),
            1,
        )

    def test_same_normalized_key_returns_original_run_unchanged(self):
        preview_module = self.get_run_creation_module()
        first = self.create_preview(
            preview_module,
            key="  repeat-key  ",
        )
        original_condition_snapshot = (
            first.run.avito_listing_result.condition_snapshot
        )

        automation_model = apps.get_model("automations", "Automation")
        self.automation.name = "Changed automation"
        self.automation.version = 2
        self.automation.state = automation_model.State.ARCHIVED
        self.automation.save(
            update_fields=["name", "version", "state", "updated_at"],
        )
        self.config.condition_tree = build_condition_tree({
            "type": "condition",
            "metric": "views",
            "aggregation": "sum",
            "window_days": 1,
            "comparator": "eq",
            "value": 0,
        })
        self.config.save(
            update_fields=["condition_tree", "updated_at"],
        )

        second = self.create_preview(
            preview_module,
            key="repeat-key",
        )

        self.assertFalse(second.created)
        self.assertEqual(second.run.id, first.run.id)
        self.assertEqual(
            second.run.automation_name_snapshot,
            "Preview automation",
        )
        self.assertEqual(second.run.automation_version, 1)
        self.assertEqual(
            second.run.avito_listing_result.condition_snapshot,
            original_condition_snapshot,
        )
        self.assertEqual(
            apps.get_model(
                "automations",
                "AutomationRun",
            ).objects.count(),
            1,
        )
        self.assertEqual(
            apps.get_model(
                "automations",
                "AvitoListingRunResult",
            ).objects.count(),
            1,
        )

    def test_different_key_conflicts_only_while_preview_is_open(self):
        preview_module = self.get_run_creation_module()
        first = self.create_preview(preview_module, key="first-key")

        with self.assertRaises(
                preview_module.RunCreationError,
        ) as caught:
            self.create_preview(preview_module, key="second-key")

        self.assertEqual(caught.exception.code, "open_preview_conflict")
        self.assertEqual(caught.exception.open_run_id, first.run.id)

        first.run.status = "completed"
        first.run.finished_at = timezone.now()
        first.run.save(
            update_fields=["status", "finished_at", "updated_at"],
        )

        second = self.create_preview(preview_module, key="second-key")

        self.assertTrue(second.created)
        self.assertNotEqual(second.run.id, first.run.id)
        self.assertEqual(
            apps.get_model(
                "automations",
                "AutomationRun",
            ).objects.count(),
            2,
        )

    def test_rejects_invalid_key_scope_state_module_and_config(self):
        preview_module = self.get_run_creation_module()

        for invalid_key in (None, "", "   ", "x" * 129, 123):
            with self.subTest(idempotency_key=invalid_key):
                with self.assertNumQueries(0):
                    with self.assertRaises(
                            preview_module.RunCreationError,
                    ) as caught:
                        self.create_preview(
                            preview_module,
                            key=invalid_key,
                        )

                self.assertEqual(
                    caught.exception.code,
                    "invalid_idempotency_key",
                )

        with self.assertRaises(
                preview_module.RunCreationError,
        ) as caught:
            preview_module.create_or_get_preview_run(
                workspace=self.other_workspace,
                automation_id=self.automation.id,
                created_by=self.other_user,
                idempotency_key="foreign-workspace",
            )
        self.assertEqual(caught.exception.code, "automation_not_found")

        automation_model = apps.get_model("automations", "Automation")
        self.automation.state = automation_model.State.ARCHIVED
        self.automation.save(update_fields=["state", "updated_at"])
        with self.assertRaises(
                preview_module.RunCreationError,
        ) as caught:
            self.create_preview(preview_module, key="archived")
        self.assertEqual(
            caught.exception.code,
            "invalid_automation_state",
        )

        self.automation.state = automation_model.State.DRAFT
        self.automation.module_type = "reports"
        self.automation.save(
            update_fields=["state", "module_type", "updated_at"],
        )
        with self.assertRaises(
                preview_module.RunCreationError,
        ) as caught:
            self.create_preview(preview_module, key="unsupported-module")
        self.assertEqual(caught.exception.code, "unsupported_module")

        self.automation.module_type = "avito_listings"
        self.automation.save(
            update_fields=["module_type", "updated_at"],
        )
        self.config.workspace = self.other_workspace
        self.config.avito_account = self.other_avito_account
        self.config.save(
            update_fields=[
                "workspace",
                "avito_account",
                "updated_at",
            ],
        )
        with self.assertRaises(
                preview_module.RunCreationError,
        ) as caught:
            self.create_preview(preview_module, key="invalid-workspace")
        self.assertEqual(caught.exception.code, "invalid_configuration")

        self.assertEqual(
            apps.get_model(
                "automations",
                "AutomationRun",
            ).objects.count(),
            0,
        )

    def test_result_creation_failure_rolls_back_run(self):
        preview_module = self.get_run_creation_module()

        with patch.object(
                preview_module.AvitoListingRunResult.objects,
                "create",
                side_effect=RuntimeError("result write failed"),
        ):
            with self.assertRaisesRegex(
                    RuntimeError,
                    "result write failed",
            ):
                self.create_preview(preview_module, key="rollback-key")

        self.assertEqual(
            apps.get_model(
                "automations",
                "AutomationRun",
            ).objects.count(),
            0,
        )
        self.assertEqual(
            apps.get_model(
                "automations",
                "AvitoListingRunResult",
            ).objects.count(),
            0,
        )


class PreviewRunDataReadinessServiceTests(TestCase):
    service_module_path = "automations.services.run_readiness"

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(
            email="preview-readiness-owner@example.com",
            password="test-password",
        )
        cls.workspace = Workspace.objects.create(
            name="Preview readiness workspace",
            slug="preview-readiness-workspace",
            owner=cls.user,
        )
        cls.avito_account = AvitoAccount.objects.create(
            workspace=cls.workspace,
            name="Preview readiness Avito account",
        )

        automation_model = apps.get_model("automations", "Automation")
        cls.automation = automation_model.objects.create(
            workspace=cls.workspace,
            module_type="avito_listings",
            name="Preview readiness automation",
            state=automation_model.State.DRAFT,
            created_by=cls.user,
            updated_by=cls.user,
        )
        cls.condition_tree = build_condition_tree({
            "type": "condition",
            "metric": "contacts",
            "aggregation": "sum",
            "window_days": 10,
            "comparator": "lt",
            "value": 10,
        })
        cls.config = apps.get_model(
            "automations",
            "AvitoListingAutomationConfig",
        ).objects.create(
            automation=cls.automation,
            workspace=cls.workspace,
            avito_account=cls.avito_account,
            condition_tree=cls.condition_tree,
            action_type="pause",
            action_config={},
            max_actions_per_run=10,
            approval_ttl_minutes=1440,
        )

    def get_service_module(self):
        try:
            return import_module(self.service_module_path)
        except ModuleNotFoundError as exc:
            if exc.name not in {
                "automations.services",
                self.service_module_path,
            }:
                raise

            self.fail(
                "Ядро автоматизаций должно предоставлять сервис "
                "проверки готовности данных run.",
            )

    def create_preview_run(self, *, key):
        preview_module = import_module(
            "automations.services.run_creation",
        )

        with patch.object(
                preview_module.timezone,
                "localdate",
                return_value=date(2026, 8, 19),
        ):
            creation = preview_module.create_or_get_preview_run(
                workspace=self.workspace,
                automation_id=self.automation.id,
                created_by=self.user,
                idempotency_key=key,
            )

        return creation.run

    def test_ready_check_uses_frozen_condition_and_as_of_date(self):
        service_module = self.get_service_module()
        run = self.create_preview_run(key="ready-snapshot")

        self.config.condition_tree = build_condition_tree({
            "type": "condition",
            "metric": "views",
            "aggregation": "sum",
            "window_days": 30,
            "comparator": "gte",
            "value": 100,
        })
        self.config.save(
            update_fields=["condition_tree", "updated_at"],
        )
        AvitoStatsSyncState.objects.create(
            workspace=self.workspace,
            avito_account=self.avito_account,
            status=AvitoStatsSyncState.Status.SUCCESS,
            coverage_from=date(2026, 8, 9),
            coverage_to=date(2026, 8, 18),
        )

        readiness = service_module.check_run_data_readiness(
            run_id=run.id,
        )

        self.assertTrue(readiness.is_ready)
        self.assertIsNone(readiness.reason)
        self.assertEqual(readiness.required_from, date(2026, 8, 9))
        self.assertEqual(readiness.required_to, date(2026, 8, 18))

        run.refresh_from_db()
        self.assertEqual(run.status, "queued")
        self.assertIsNone(run.wait_started_at)
        self.assertEqual(run.error_code, "")
        self.assertEqual(
            run.avito_listing_result.condition_snapshot,
            self.condition_tree,
        )

    def test_missing_account_stats_moves_run_to_waiting(self):
        service_module = self.get_service_module()
        run = self.create_preview_run(key="missing-stats")
        checked_at = timezone.make_aware(
            datetime(2026, 8, 19, 9, 0),
            timezone.get_current_timezone(),
        )

        with patch.object(
                service_module.timezone,
                "now",
                return_value=checked_at,
        ):
            readiness = service_module.check_run_data_readiness(
                run_id=run.id,
            )

        self.assertFalse(readiness.is_ready)
        self.assertEqual(readiness.reason, "missing_sync_state")
        self.assertEqual(readiness.required_from, date(2026, 8, 9))
        self.assertEqual(readiness.required_to, date(2026, 8, 18))

        run.refresh_from_db()
        result = run.avito_listing_result
        self.assertEqual(run.status, "waiting_for_data")
        self.assertEqual(run.wait_started_at, checked_at)
        self.assertEqual(run.error_code, "insufficient_data")
        self.assertTrue(run.error_message)
        self.assertEqual(
            run.next_attempt_at,
            checked_at + timedelta(minutes=10),
        )
        self.assertEqual(run.data_wait_attempt_count, 1)
        self.assertEqual(result.target_max_id_snapshot, 0)
        self.assertEqual(result.checked, 0)
        self.assertEqual(result.matched, 0)
        self.assertEqual(result.examples_snapshot, [])
        self.assertEqual(
            apps.get_model(
                "automations",
                "AvitoListingDecision",
            ).objects.count(),
            0,
        )

    def test_rechecks_preserve_wait_start_and_follow_bounded_backoff(self):
        service_module = self.get_service_module()
        run = self.create_preview_run(key="preserve-wait-start")
        first_check = timezone.make_aware(
            datetime(2026, 8, 19, 9, 0),
            timezone.get_current_timezone(),
        )
        checks = (
            (first_check, first_check + timedelta(minutes=10), 1),
            (
                first_check + timedelta(minutes=10),
                first_check + timedelta(minutes=40),
                2,
            ),
            (
                first_check + timedelta(minutes=40),
                first_check + timedelta(hours=1, minutes=40),
                3,
            ),
            (
                first_check + timedelta(hours=1, minutes=40),
                first_check + timedelta(hours=3, minutes=40),
                4,
            ),
            (
                first_check + timedelta(hours=3, minutes=40),
                first_check + timedelta(hours=5, minutes=40),
                5,
            ),
        )

        for checked_at, expected_next_attempt, expected_count in checks:
            with self.subTest(attempt=expected_count):
                with patch.object(
                        service_module.timezone,
                        "now",
                        return_value=checked_at,
                ):
                    readiness = service_module.check_run_data_readiness(
                        run_id=run.id,
                    )

                run.refresh_from_db()
                self.assertFalse(readiness.is_ready)
                self.assertEqual(run.status, "waiting_for_data")
                self.assertEqual(run.wait_started_at, first_check)
                self.assertEqual(
                    run.next_attempt_at,
                    expected_next_attempt,
                )
                self.assertEqual(
                    run.data_wait_attempt_count,
                    expected_count,
                )
                self.assertEqual(run.error_code, "insufficient_data")

    def test_terminal_run_is_not_returned_to_waiting(self):
        service_module = self.get_service_module()
        run = self.create_preview_run(key="terminal-run")
        finished_at = timezone.now()
        run.status = "completed"
        run.finished_at = finished_at
        run.save(
            update_fields=["status", "finished_at", "updated_at"],
        )

        with self.assertRaises(
                service_module.RunDataReadinessError,
        ) as caught:
            service_module.check_run_data_readiness(run_id=run.id)

        self.assertEqual(caught.exception.code, "invalid_run_state")
        run.refresh_from_db()
        self.assertEqual(run.status, "completed")
        self.assertEqual(run.finished_at, finished_at)
        self.assertIsNone(run.wait_started_at)
        self.assertEqual(run.error_code, "")


class AutomationModelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(
            email="automation-owner@example.com",
            password="test-password",
        )
        cls.workspace = Workspace.objects.create(
            name="Automation workspace",
            slug="automation-workspace",
            owner=cls.user,
        )

    def get_automation_model(self):
        try:
            automation_model = apps.get_model("automations", "Automation")
        except LookupError:
            automation_model = None

        self.assertIsNotNone(
            automation_model,
            "The automations app must define the Automation model.",
        )
        return automation_model

    def test_new_automation_starts_as_versioned_manual_draft(self):
        automation_model = self.get_automation_model()

        automation = automation_model.objects.create(
            workspace=self.workspace,
            module_type="avito_listings",
            name="Pause ineffective listings",
            created_by=self.user,
            updated_by=self.user,
        )

        self.assertEqual(automation.state, "draft")
        self.assertEqual(automation.execution_mode, "manual")
        self.assertEqual(automation.version, 1)
        self.assertIsNone(automation.archived_at)
        self.assertEqual(automation.workspace, self.workspace)
        self.assertEqual(automation.created_by, self.user)
        self.assertEqual(automation.updated_by, self.user)
        self.assertIsNotNone(automation.created_at)
        self.assertIsNotNone(automation.updated_at)

    def test_automatic_execution_mode_is_rejected_in_mvp(self):
        automation_model = self.get_automation_model()
        automation = automation_model(
            workspace=self.workspace,
            module_type="avito_listings",
            name="Unsupported automatic rule",
            execution_mode="auto",
            created_by=self.user,
            updated_by=self.user,
        )

        with self.assertRaises(ValidationError):
            automation.full_clean()

    def test_version_must_be_greater_than_zero(self):
        automation_model = self.get_automation_model()

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                automation_model.objects.create(
                    workspace=self.workspace,
                    module_type="avito_listings",
                    name="Invalid version",
                    version=0,
                    created_by=self.user,
                    updated_by=self.user,
                )

    def test_workspace_state_index_is_declared(self):
        automation_model = self.get_automation_model()
        declared_indexes = {
            tuple(index.fields) for index in automation_model._meta.indexes
        }

        self.assertIn(("workspace", "state"), declared_indexes)


class AutomationRunModelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(
            email="automation-run-owner@example.com",
            password="test-password",
        )
        cls.workspace = Workspace.objects.create(
            name="Automation run workspace",
            slug="automation-run-workspace",
            owner=cls.user,
        )
        automation_model = apps.get_model("automations", "Automation")
        cls.automation = automation_model.objects.create(
            workspace=cls.workspace,
            module_type="avito_listings",
            name="Archive ineffective listings",
            created_by=cls.user,
            updated_by=cls.user,
        )

    def get_automation_run_model(self):
        try:
            automation_run_model = apps.get_model(
                "automations",
                "AutomationRun",
            )
        except LookupError:
            automation_run_model = None

        self.assertIsNotNone(
            automation_run_model,
            "The automations app must define the AutomationRun model.",
        )
        return automation_run_model

    def create_run(self, **overrides):
        automation_run_model = self.get_automation_run_model()
        values = {
            "automation": self.automation,
            "workspace": self.workspace,
            "run_kind": "preview",
            "trigger": "manual",
            "execution_mode_snapshot": "manual",
            "automation_version": 1,
            "automation_name_snapshot": self.automation.name,
            "module_type_snapshot": self.automation.module_type,
            "idempotency_key": "preview-request-1",
            "created_by": self.user,
        }
        values.update(overrides)
        return automation_run_model.objects.create(**values)

    def test_new_manual_run_starts_queued_and_captures_snapshots(self):
        run = self.create_run()

        self.assertEqual(run.status, "queued")
        self.assertEqual(run.retry_count, 0)
        self.assertEqual(run.data_wait_attempt_count, 0)
        self.assertEqual(run.automation_version, 1)
        self.assertEqual(
            run.automation_name_snapshot,
            "Archive ineffective listings",
        )
        self.assertEqual(run.module_type_snapshot, "avito_listings")
        self.assertIsNone(run.next_attempt_at)
        self.assertIsNone(run.wait_started_at)
        self.assertIsNone(run.run_token)
        self.assertIsNone(run.heartbeat_at)
        self.assertIsNone(run.started_at)
        self.assertIsNone(run.finished_at)
        self.assertEqual(run.error_code, "")
        self.assertEqual(run.error_message, "")
        self.assertIsNotNone(run.created_at)
        self.assertIsNotNone(run.updated_at)

    def test_production_only_run_modes_are_rejected_in_mvp(self):
        automation_run_model = self.get_automation_run_model()

        invalid_values = (
            ("trigger", "scheduled"),
            ("execution_mode_snapshot", "auto"),
            ("execution_mode_snapshot", "shadow"),
        )
        for field_name, invalid_value in invalid_values:
            with self.subTest(field=field_name, value=invalid_value):
                run = automation_run_model(
                    automation=self.automation,
                    workspace=self.workspace,
                    run_kind="preview",
                    trigger="manual",
                    execution_mode_snapshot="manual",
                    automation_version=1,
                    automation_name_snapshot=self.automation.name,
                    module_type_snapshot=self.automation.module_type,
                    idempotency_key=f"invalid-{field_name}-{invalid_value}",
                    created_by=self.user,
                )
                setattr(run, field_name, invalid_value)

                with self.assertRaises(ValidationError):
                    run.full_clean()

    def test_automation_version_must_be_greater_than_zero(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self.create_run(
                    automation_version=0,
                    idempotency_key="invalid-version",
                )

    def test_non_empty_client_key_is_unique_per_automation_and_run_kind(self):
        self.create_run(status="completed", idempotency_key="same-key")

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self.create_run(
                    status="completed",
                    idempotency_key="same-key",
                )

    def test_empty_client_keys_are_outside_database_deduplication(self):
        first_run = self.create_run(status="completed", idempotency_key=None)
        second_run = self.create_run(status="completed", idempotency_key=None)
        first_blank_run = self.create_run(status="completed", idempotency_key="")
        second_blank_run = self.create_run(status="completed", idempotency_key="")

        self.assertNotEqual(first_run.pk, second_run.pk)
        self.assertNotEqual(first_blank_run.pk, second_blank_run.pk)

    def test_only_one_non_terminal_run_of_each_kind_is_allowed(self):
        self.create_run(idempotency_key="first-open-preview")

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self.create_run(idempotency_key="second-open-preview")

    def test_preview_and_execute_can_be_open_at_the_same_time(self):
        preview_run = self.create_run(idempotency_key="shared-client-key")
        execute_run = self.create_run(
            run_kind="execute",
            idempotency_key="shared-client-key",
        )

        self.assertEqual(preview_run.status, "queued")
        self.assertEqual(execute_run.status, "queued")

    def test_terminal_run_does_not_block_next_run_of_the_same_kind(self):
        completed_run = self.create_run(
            status="completed",
            idempotency_key="completed-preview",
        )
        next_run = self.create_run(idempotency_key="next-preview")

        self.assertEqual(completed_run.status, "completed")
        self.assertEqual(next_run.status, "queued")

    def test_recovery_and_journal_indexes_are_declared(self):
        automation_run_model = self.get_automation_run_model()
        declared_indexes = {
            tuple(index.fields) for index in automation_run_model._meta.indexes
        }

        self.assertIn(("status", "next_attempt_at", "id"), declared_indexes)
        self.assertIn(("automation", "created_at"), declared_indexes)


class AvitoListingAutomationConfigModelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(
            email="automation-config-owner@example.com",
            password="test-password",
        )
        cls.workspace = Workspace.objects.create(
            name="Automation config workspace",
            slug="automation-config-workspace",
            owner=cls.user,
        )
        cls.avito_account = AvitoAccount.objects.create(
            workspace=cls.workspace,
            name="Primary Avito account",
        )
        automation_model = apps.get_model("automations", "Automation")
        cls.automation = automation_model.objects.create(
            workspace=cls.workspace,
            module_type="avito_listings",
            name="Pause listings with few contacts",
            created_by=cls.user,
            updated_by=cls.user,
        )

    def get_config_model(self):
        try:
            config_model = apps.get_model(
                "automations",
                "AvitoListingAutomationConfig",
            )
        except LookupError:
            config_model = None

        self.assertIsNotNone(
            config_model,
            (
                "The automations app must define the "
                "AvitoListingAutomationConfig model."
            ),
        )
        return config_model

    def create_config(self, **overrides):
        config_model = self.get_config_model()
        values = {
            "automation": self.automation,
            "workspace": self.workspace,
            "avito_account": self.avito_account,
            "condition_tree": {
                "type": "condition",
                "metric": "contacts",
                "aggregation": "sum",
                "window_days": 10,
                "comparator": "lt",
                "value": 10,
            },
            "action_type": "pause",
        }
        values.update(overrides)
        return config_model.objects.create(**values)

    def test_new_config_uses_safe_mvp_defaults(self):
        config = self.create_config()

        self.assertEqual(config.automation, self.automation)
        self.assertEqual(config.workspace, self.workspace)
        self.assertEqual(config.avito_account, self.avito_account)
        self.assertEqual(config.action_config, {})
        self.assertEqual(config.max_actions_per_run, 10)
        self.assertEqual(config.approval_ttl_minutes, 1440)
        self.assertIsNotNone(config.created_at)
        self.assertIsNotNone(config.updated_at)

    def test_only_one_avito_listing_config_is_allowed_per_automation(self):
        self.create_config()

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self.create_config()

    def test_action_limit_and_approval_ttl_are_enforced_by_database(self):
        invalid_values = (
            ("max_actions_per_run", 0),
            ("max_actions_per_run", 101),
            ("approval_ttl_minutes", 59),
            ("approval_ttl_minutes", 10081),
        )
        for field_name, invalid_value in invalid_values:
            with self.subTest(field=field_name, value=invalid_value):
                with self.assertRaises(IntegrityError):
                    with transaction.atomic():
                        self.create_config(**{field_name: invalid_value})

    def test_linked_avito_account_cannot_be_deleted_directly(self):
        self.create_config()

        with self.assertRaises(RestrictedError):
            self.avito_account.delete()


class AvitoListingRunResultModelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(
            email="automation-result-owner@example.com",
            password="test-password",
        )
        cls.workspace = Workspace.objects.create(
            name="Automation result workspace",
            slug="automation-result-workspace",
            owner=cls.user,
        )
        cls.avito_account = AvitoAccount.objects.create(
            workspace=cls.workspace,
            name="Result Avito account",
        )

        automation_model = apps.get_model("automations", "Automation")
        cls.automation = automation_model.objects.create(
            workspace=cls.workspace,
            module_type="avito_listings",
            name="Preview ineffective listings",
            created_by=cls.user,
            updated_by=cls.user,
        )

        automation_run_model = apps.get_model("automations", "AutomationRun")
        cls.automation_run = automation_run_model.objects.create(
            automation=cls.automation,
            workspace=cls.workspace,
            run_kind="preview",
            trigger="manual",
            execution_mode_snapshot="manual",
            automation_version=1,
            automation_name_snapshot=cls.automation.name,
            module_type_snapshot=cls.automation.module_type,
            status="completed",
            idempotency_key="result-preview-request",
            created_by=cls.user,
        )

    def get_result_model(self):
        try:
            result_model = apps.get_model(
                "automations",
                "AvitoListingRunResult",
            )
        except LookupError:
            result_model = None

        self.assertIsNotNone(
            result_model,
            (
                "The automations app must define the "
                "AvitoListingRunResult model."
            ),
        )
        return result_model

    def create_result(self, **overrides):
        result_model = self.get_result_model()
        values = {
            "run": self.automation_run,
            "workspace": self.workspace,
            "avito_account": self.avito_account,
            "as_of_date": date(2026, 8, 14),
            "condition_snapshot": {
                "type": "condition",
                "metric": "contacts",
                "window_days": 10,
                "comparator": "lt",
                "value": 10,
            },
            "action_snapshot": {
                "type": "pause",
                "config": {},
            },
        }
        values.update(overrides)
        return result_model.objects.create(**values)

    def test_new_result_uses_empty_bounded_defaults(self):
        result = self.create_result()

        self.assertEqual(
            getattr(result, "max_actions_per_run_snapshot", None),
            10,
        )
        self.assertEqual(
            getattr(result, "approval_ttl_minutes_snapshot", None),
            1440,
        )
        self.assertEqual(result.target_max_id_snapshot, 0)
        self.assertEqual(result.examples_snapshot, [])
        self.assertEqual(result.checked, 0)
        self.assertEqual(result.ineligible, 0)
        self.assertEqual(result.insufficient_coverage, 0)
        self.assertEqual(result.not_matched, 0)
        self.assertEqual(result.matched, 0)
        self.assertEqual(result.deferred_by_run_limit, 0)
        self.assertEqual(result.pending_approval, 0)
        self.assertEqual(result.completed_actions, 0)
        self.assertEqual(result.failed_actions, 0)
        self.assertIsNotNone(result.created_at)
        self.assertIsNotNone(result.updated_at)

    def test_run_limit_snapshot_is_enforced_by_database(self):
        result_model = self.get_result_model()
        field_names = {
            field.name
            for field in result_model._meta.fields
        }
        self.assertIn(
            "max_actions_per_run_snapshot",
            field_names,
            "Типизированный результат должен фиксировать лимит run.",
        )

        for invalid_value in (0, 101):
            with self.subTest(value=invalid_value):
                with self.assertRaises(IntegrityError):
                    with transaction.atomic():
                        self.create_result(
                            max_actions_per_run_snapshot=invalid_value,
                        )

    def test_approval_ttl_snapshot_is_enforced_by_database(self):
        result_model = self.get_result_model()
        field_names = {
            field.name
            for field in result_model._meta.fields
        }
        self.assertIn(
            "approval_ttl_minutes_snapshot",
            field_names,
            "Типизированный результат должен фиксировать TTL решения.",
        )

        for invalid_value in (59, 10081):
            with self.subTest(value=invalid_value):
                with self.assertRaises(IntegrityError):
                    with transaction.atomic():
                        self.create_result(
                            approval_ttl_minutes_snapshot=invalid_value,
                        )

    def test_only_one_avito_listing_result_is_allowed_per_run(self):
        self.create_result()

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self.create_result()

    def test_snapshot_boundary_and_counters_cannot_be_negative(self):
        non_negative_fields = (
            "target_max_id_snapshot",
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
        for field_name in non_negative_fields:
            with self.subTest(field=field_name):
                with self.assertRaises(IntegrityError):
                    with transaction.atomic():
                        self.create_result(**{field_name: -1})

    def test_result_history_prevents_direct_account_deletion(self):
        self.create_result()

        with self.assertRaises(RestrictedError):
            self.avito_account.delete()

    def test_account_date_journal_index_is_declared(self):
        result_model = self.get_result_model()
        declared_indexes = {
            tuple(index.fields) for index in result_model._meta.indexes
        }

        self.assertIn(("avito_account", "as_of_date"), declared_indexes)


class AvitoListingDecisionModelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(
            email="automation-decision-owner@example.com",
            password="test-password",
        )
        cls.workspace = Workspace.objects.create(
            name="Automation decision workspace",
            slug="automation-decision-workspace",
            owner=cls.user,
        )
        cls.avito_account = AvitoAccount.objects.create(
            workspace=cls.workspace,
            name="Decision Avito account",
        )
        cls.listing = AvitoListing.objects.create(
            workspace=cls.workspace,
            avito_account=cls.avito_account,
            avito_id="decision-listing-1",
            title="Listing safe title",
            management_status=AvitoListing.ManagementStatus.MANAGED,
        )
        cls.active_since = timezone.now() - timedelta(days=20)

        automation_model = apps.get_model("automations", "Automation")
        cls.automation = automation_model.objects.create(
            workspace=cls.workspace,
            module_type="avito_listings",
            name="Archive listing decision",
            state="enabled",
            created_by=cls.user,
            updated_by=cls.user,
        )

        automation_run_model = apps.get_model("automations", "AutomationRun")
        cls.automation_run = automation_run_model.objects.create(
            automation=cls.automation,
            workspace=cls.workspace,
            run_kind="execute",
            trigger="manual",
            execution_mode_snapshot="manual",
            automation_version=1,
            automation_name_snapshot=cls.automation.name,
            module_type_snapshot=cls.automation.module_type,
            status="waiting_approval",
            idempotency_key="decision-execute-request",
            created_by=cls.user,
        )

    def get_decision_model(self):
        try:
            decision_model = apps.get_model(
                "automations",
                "AvitoListingDecision",
            )
        except LookupError:
            decision_model = None

        self.assertIsNotNone(
            decision_model,
            (
                "The automations app must define the "
                "AvitoListingDecision model."
            ),
        )
        return decision_model

    def create_decision(self, **overrides):
        decision_model = self.get_decision_model()
        values = {
            "run": self.automation_run,
            "automation": self.automation,
            "workspace": self.workspace,
            "avito_account": self.avito_account,
            "listing": self.listing,
            "listing_id_snapshot": self.listing.id,
            "listing_snapshot": {
                "id": self.listing.id,
                "avito_id": self.listing.avito_id,
                "title": self.listing.title,
            },
            "automation_version": 1,
            "active_since_snapshot": self.active_since,
            "condition_snapshot": {
                "type": "condition",
                "metric": "contacts",
                "window_days": 10,
                "comparator": "lt",
                "value": 10,
            },
            "metrics_snapshot": {
                "contacts": {
                    "window_days": 10,
                    "value": 3,
                },
            },
            "action_snapshot": {
                "type": "archive",
                "config": {},
            },
            "expires_at": timezone.now() + timedelta(hours=24),
        }
        values.update(overrides)
        return decision_model.objects.create(**values)

    def test_new_decision_starts_pending_with_durable_snapshots(self):
        decision = self.create_decision()

        self.assertEqual(decision.status, "pending_approval")
        self.assertEqual(decision.run, self.automation_run)
        self.assertEqual(decision.automation, self.automation)
        self.assertEqual(decision.workspace, self.workspace)
        self.assertEqual(decision.avito_account, self.avito_account)
        self.assertEqual(decision.listing, self.listing)
        self.assertEqual(decision.listing_id_snapshot, self.listing.id)
        self.assertEqual(decision.automation_version, 1)
        self.assertEqual(decision.active_since_snapshot, self.active_since)
        self.assertEqual(decision.effect_attempts, 0)
        self.assertIsNone(decision.required_export_revision)
        self.assertIsNone(decision.next_effect_retry_at)
        self.assertIsNone(decision.approved_by)
        self.assertIsNone(decision.approved_at)
        self.assertIsNone(decision.rejected_by)
        self.assertIsNone(decision.rejected_at)
        self.assertIsNone(decision.action_applied_at)
        self.assertIsNone(decision.completed_at)
        self.assertIsNone(decision.terminal_at)
        self.assertEqual(decision.error_code, "")
        self.assertEqual(decision.error_message, "")
        self.assertIsNotNone(decision.created_at)
        self.assertIsNotNone(decision.updated_at)

    def test_listing_deletion_keeps_decision_snapshots(self):
        decision = self.create_decision()
        listing_id_snapshot = decision.listing_id_snapshot
        listing_snapshot = decision.listing_snapshot

        self.listing.delete()
        decision.refresh_from_db()

        self.assertIsNone(decision.listing)
        self.assertEqual(decision.listing_id_snapshot, listing_id_snapshot)
        self.assertEqual(decision.listing_snapshot, listing_snapshot)

    def test_run_and_listing_snapshot_pair_is_unique(self):
        self.create_decision()

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self.create_decision()

    def test_identity_version_and_export_revision_are_strictly_positive(self):
        invalid_values = (
            ("listing_id_snapshot", 0),
            ("automation_version", 0),
            ("required_export_revision", 0),
            ("effect_attempts", -1),
        )
        for field_name, invalid_value in invalid_values:
            with self.subTest(field=field_name, value=invalid_value):
                with self.assertRaises(IntegrityError):
                    with transaction.atomic():
                        self.create_decision(**{field_name: invalid_value})

    def test_decision_processing_and_retention_indexes_are_declared(self):
        decision_model = self.get_decision_model()
        declared_indexes = {
            tuple(index.fields) for index in decision_model._meta.indexes
        }

        self.assertIn(("run", "status"), declared_indexes)
        self.assertIn(("listing", "status"), declared_indexes)
        self.assertIn(("status", "expires_at"), declared_indexes)
        self.assertIn(("terminal_at", "id"), declared_indexes)


class AvitoListingRunLeaseTests(TestCase):
    module_path = "automations.modules.avito_listings.run_lease"

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(
            email="avito-run-lease-owner@example.com",
            password="test-password",
        )
        cls.workspace = Workspace.objects.create(
            name="Avito run lease workspace",
            slug="avito-run-lease-workspace",
            owner=cls.user,
        )
        cls.avito_account = AvitoAccount.objects.create(
            workspace=cls.workspace,
            name="Avito run lease account",
        )
        automation_model = apps.get_model(
            "automations",
            "Automation",
        )
        cls.automation = automation_model.objects.create(
            workspace=cls.workspace,
            module_type="avito_listings",
            name="Avito run lease automation",
            state=automation_model.State.DRAFT,
            created_by=cls.user,
            updated_by=cls.user,
        )

    def get_lease_module(self):
        try:
            return import_module(self.module_path)
        except ModuleNotFoundError as exc:
            if exc.name != self.module_path:
                raise

            self.fail(
                "Модуль объявлений Avito должен предоставлять "
                "сервис account lease.",
            )

    def create_automation(self):
        automation_model = apps.get_model(
            "automations",
            "Automation",
        )
        return automation_model.objects.create(
            workspace=self.workspace,
            module_type="avito_listings",
            name=f"Competing lease automation {uuid4()}",
            state=automation_model.State.DRAFT,
            created_by=self.user,
            updated_by=self.user,
        )

    def create_claimed_run(
            self,
            *,
            run_token=None,
            automation=None,
    ):
        effective_token = run_token or uuid4()
        effective_automation = automation or self.automation
        run = apps.get_model(
            "automations",
            "AutomationRun",
        ).objects.create(
            automation=effective_automation,
            workspace=self.workspace,
            run_kind="preview",
            trigger="manual",
            execution_mode_snapshot="manual",
            automation_version=1,
            automation_name_snapshot=effective_automation.name,
            module_type_snapshot="avito_listings",
            status="evaluating",
            idempotency_key=f"lease-{uuid4()}",
            run_token=effective_token,
            heartbeat_at=timezone.now(),
            created_by=self.user,
        )
        apps.get_model(
            "automations",
            "AvitoListingRunResult",
        ).objects.create(
            run=run,
            workspace=self.workspace,
            avito_account=self.avito_account,
            as_of_date=date(2026, 8, 18),
            max_actions_per_run_snapshot=10,
            condition_snapshot={},
            action_snapshot={},
        )
        return run, effective_token

    def get_account_state(self):
        return apps.get_model(
            "automations",
            "AvitoAutomationAccountState",
        ).objects.get(
            workspace=self.workspace,
            avito_account=self.avito_account,
        )

    def test_acquire_creates_ten_minute_lease_for_run_token(self):
        lease_module = self.get_lease_module()
        run, run_token = self.create_claimed_run()
        acquired_at = timezone.make_aware(
            datetime(2026, 8, 19, 9, 0),
            timezone.get_current_timezone(),
        )

        acquired = lease_module.acquire_run_lease(
            run=run,
            run_token=run_token,
            acquired_at=acquired_at,
        )

        self.assertTrue(acquired)
        state = self.get_account_state()
        self.assertEqual(state.status, "running")
        self.assertEqual(state.run_token, run_token)
        self.assertEqual(state.heartbeat_at, acquired_at)
        self.assertEqual(
            state.lease_expires_at,
            acquired_at + timedelta(minutes=10),
        )

    def test_active_lease_cannot_be_stolen_by_another_token(self):
        lease_module = self.get_lease_module()
        first_run, first_token = self.create_claimed_run()
        acquired_at = timezone.make_aware(
            datetime(2026, 8, 19, 9, 0),
            timezone.get_current_timezone(),
        )
        lease_module.acquire_run_lease(
            run=first_run,
            run_token=first_token,
            acquired_at=acquired_at,
        )
        second_run, second_token = self.create_claimed_run(
            automation=self.create_automation(),
        )

        acquired = lease_module.acquire_run_lease(
            run=second_run,
            run_token=second_token,
            acquired_at=acquired_at + timedelta(minutes=5),
        )

        self.assertFalse(acquired)
        state = self.get_account_state()
        self.assertEqual(state.status, "running")
        self.assertEqual(state.run_token, first_token)
        self.assertEqual(state.heartbeat_at, acquired_at)
        self.assertEqual(
            state.lease_expires_at,
            acquired_at + timedelta(minutes=10),
        )

    def test_expired_lease_can_be_acquired_by_another_token(self):
        lease_module = self.get_lease_module()
        first_run, first_token = self.create_claimed_run()
        acquired_at = timezone.make_aware(
            datetime(2026, 8, 19, 9, 0),
            timezone.get_current_timezone(),
        )
        lease_module.acquire_run_lease(
            run=first_run,
            run_token=first_token,
            acquired_at=acquired_at,
        )
        second_run, second_token = self.create_claimed_run(
            automation=self.create_automation(),
        )
        takeover_at = acquired_at + timedelta(minutes=10)

        acquired = lease_module.acquire_run_lease(
            run=second_run,
            run_token=second_token,
            acquired_at=takeover_at,
        )

        self.assertTrue(acquired)
        state = self.get_account_state()
        self.assertEqual(state.status, "running")
        self.assertEqual(state.run_token, second_token)
        self.assertEqual(state.heartbeat_at, takeover_at)
        self.assertEqual(
            state.lease_expires_at,
            takeover_at + timedelta(minutes=10),
        )

    def test_heartbeat_extends_only_live_lease_owned_by_token(self):
        lease_module = self.get_lease_module()
        run, run_token = self.create_claimed_run()
        acquired_at = timezone.make_aware(
            datetime(2026, 8, 19, 9, 0),
            timezone.get_current_timezone(),
        )
        lease_module.acquire_run_lease(
            run=run,
            run_token=run_token,
            acquired_at=acquired_at,
        )
        heartbeat_at = acquired_at + timedelta(minutes=5)

        refreshed = lease_module.heartbeat_run_lease(
            run=run,
            run_token=run_token,
            heartbeat_at=heartbeat_at,
        )

        self.assertTrue(refreshed)
        state = self.get_account_state()
        self.assertEqual(state.heartbeat_at, heartbeat_at)
        self.assertEqual(
            state.lease_expires_at,
            heartbeat_at + timedelta(minutes=10),
        )

        for invalid_token, invalid_time in (
                (uuid4(), heartbeat_at + timedelta(minutes=1)),
                (run_token, heartbeat_at + timedelta(minutes=10)),
        ):
            with self.subTest(
                    token=invalid_token,
                    heartbeat_at=invalid_time,
            ):
                self.assertFalse(
                    lease_module.heartbeat_run_lease(
                        run=run,
                        run_token=invalid_token,
                        heartbeat_at=invalid_time,
                    ),
                )

        state.refresh_from_db()
        self.assertEqual(state.heartbeat_at, heartbeat_at)
        self.assertEqual(
            state.lease_expires_at,
            heartbeat_at + timedelta(minutes=10),
        )

    def test_release_changes_only_lease_owned_by_token_to_idle(self):
        lease_module = self.get_lease_module()
        run, run_token = self.create_claimed_run()
        acquired_at = timezone.make_aware(
            datetime(2026, 8, 19, 9, 0),
            timezone.get_current_timezone(),
        )
        lease_module.acquire_run_lease(
            run=run,
            run_token=run_token,
            acquired_at=acquired_at,
        )

        self.assertFalse(
            lease_module.release_run_lease(
                run=run,
                run_token=uuid4(),
            ),
        )
        state = self.get_account_state()
        self.assertEqual(state.status, "running")
        self.assertEqual(state.run_token, run_token)

        self.assertTrue(
            lease_module.release_run_lease(
                run=run,
                run_token=run_token,
            ),
        )
        state.refresh_from_db()
        self.assertEqual(state.status, "idle")
        self.assertIsNone(state.run_token)
        self.assertIsNone(state.heartbeat_at)
        self.assertIsNone(state.lease_expires_at)


class AvitoListingDecisionLifecycleTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(
            email="decision-lifecycle-owner@example.com",
            password="test-password",
        )
        cls.other_user = get_user_model().objects.create_user(
            email="decision-lifecycle-admin@example.com",
            password="test-password",
        )
        cls.workspace = Workspace.objects.create(
            name="Decision lifecycle workspace",
            slug="decision-lifecycle-workspace",
            owner=cls.user,
        )
        cls.other_workspace = Workspace.objects.create(
            name="Other decision lifecycle workspace",
            slug="other-decision-lifecycle-workspace",
            owner=cls.other_user,
        )
        cls.avito_account = AvitoAccount.objects.create(
            workspace=cls.workspace,
            name="Decision lifecycle Avito account",
        )
        cls.active_since = timezone.make_aware(
            datetime(2026, 8, 1, 9, 0),
            timezone.get_current_timezone(),
        )
        cls.listing = AvitoListing.objects.create(
            workspace=cls.workspace,
            avito_account=cls.avito_account,
            avito_id="decision-lifecycle-listing-1",
            title="Первое объявление",
            management_status=AvitoListing.ManagementStatus.MANAGED,
            active_since=cls.active_since,
        )
        cls.second_listing = AvitoListing.objects.create(
            workspace=cls.workspace,
            avito_account=cls.avito_account,
            avito_id="decision-lifecycle-listing-2",
            title="Второе объявление",
            management_status=AvitoListing.ManagementStatus.MANAGED,
            active_since=cls.active_since,
        )
        cls.third_listing = AvitoListing.objects.create(
            workspace=cls.workspace,
            avito_account=cls.avito_account,
            avito_id="decision-lifecycle-listing-3",
            title="Третье объявление",
            management_status=AvitoListing.ManagementStatus.MANAGED,
            active_since=cls.active_since,
        )

        automation_model = apps.get_model("automations", "Automation")
        cls.automation = automation_model.objects.create(
            workspace=cls.workspace,
            module_type="avito_listings",
            name="Ручное отклонение действий",
            state="enabled",
            created_by=cls.user,
            updated_by=cls.user,
        )
        run_model = apps.get_model("automations", "AutomationRun")
        cls.automation_run = run_model.objects.create(
            automation=cls.automation,
            workspace=cls.workspace,
            run_kind=run_model.RunKind.EXECUTE,
            trigger=run_model.Trigger.MANUAL,
            execution_mode_snapshot="manual",
            automation_version=cls.automation.version,
            automation_name_snapshot=cls.automation.name,
            module_type_snapshot=cls.automation.module_type,
            status=run_model.Status.WAITING_APPROVAL,
            idempotency_key="decision-lifecycle-run",
            created_by=cls.user,
        )
        result_model = apps.get_model(
            "automations",
            "AvitoListingRunResult",
        )
        cls.result = result_model.objects.create(
            run=cls.automation_run,
            workspace=cls.workspace,
            avito_account=cls.avito_account,
            as_of_date=date(2026, 8, 20),
            condition_snapshot={
                "type": "condition",
                "metric": "contacts",
                "operator": "lt",
                "value": 10,
                "period_days": 10,
            },
            action_snapshot={"type": "pause", "config": {}},
        )

    def get_lifecycle_module(self):
        try:
            return import_module(
                "automations.modules.avito_listings.decision_lifecycle",
            )
        except ModuleNotFoundError as error:
            self.fail(
                "Добавьте модуль decision_lifecycle для переходов решений: "
                f"{error}",
            )

    def get_expire_decision(self):
        lifecycle = self.get_lifecycle_module()
        expire_decision = getattr(lifecycle, "expire_decision", None)
        self.assertIsNotNone(
            expire_decision,
            (
                "decision_lifecycle должен предоставлять публичный "
                "идемпотентный переход expire_decision."
            ),
        )
        return expire_decision

    def create_decision(self, *, listing=None, **overrides):
        decision_model = apps.get_model(
            "automations",
            "AvitoListingDecision",
        )
        listing = listing or self.listing
        values = {
            "run": self.automation_run,
            "automation": self.automation,
            "workspace": self.workspace,
            "avito_account": self.avito_account,
            "listing": listing,
            "listing_id_snapshot": listing.id,
            "listing_snapshot": {
                "id": listing.id,
                "avito_id": listing.avito_id,
                "title": listing.title,
            },
            "status": decision_model.Status.PENDING_APPROVAL,
            "automation_version": self.automation.version,
            "active_since_snapshot": self.active_since,
            "condition_snapshot": self.result.condition_snapshot,
            "metrics_snapshot": {"contacts": 3},
            "action_snapshot": self.result.action_snapshot,
            "expires_at": timezone.make_aware(
                datetime(2026, 8, 21, 9, 0),
                timezone.get_current_timezone(),
            ),
        }
        values.update(overrides)
        return decision_model.objects.create(**values)

    def set_pending_approval(self, value):
        self.result.pending_approval = value
        self.result.save(update_fields=["pending_approval", "updated_at"])

    def reject(self, decision, *, rejected_by=None, rejected_at=None):
        lifecycle = self.get_lifecycle_module()
        return lifecycle.reject_decision(
            workspace=self.workspace,
            run_id=self.automation_run.id,
            decision_id=decision.id,
            rejected_by=rejected_by or self.user,
            rejected_at=rejected_at,
        )

    def test_rejects_pending_decision_and_completes_run(self):
        rejected_at = timezone.make_aware(
            datetime(2026, 8, 20, 9, 0),
            timezone.get_current_timezone(),
        )
        self.set_pending_approval(1)
        decision = self.create_decision()
        listing_status = self.listing.management_status
        listing_active_since = self.listing.active_since

        transition = self.reject(decision, rejected_at=rejected_at)

        decision.refresh_from_db()
        self.result.refresh_from_db()
        self.automation_run.refresh_from_db()
        self.listing.refresh_from_db()
        self.assertTrue(transition.changed)
        self.assertEqual(transition.decision.pk, decision.pk)
        self.assertEqual(decision.status, decision.Status.REJECTED)
        self.assertEqual(decision.rejected_by, self.user)
        self.assertEqual(decision.rejected_at, rejected_at)
        self.assertEqual(decision.terminal_at, rejected_at)
        self.assertIsNone(decision.approved_by)
        self.assertIsNone(decision.approved_at)
        self.assertEqual(self.result.pending_approval, 0)
        self.assertEqual(
            self.automation_run.status,
            self.automation_run.Status.COMPLETED,
        )
        self.assertEqual(self.automation_run.finished_at, rejected_at)
        self.assertEqual(self.listing.management_status, listing_status)
        self.assertEqual(self.listing.active_since, listing_active_since)

    def test_rejecting_one_of_two_keeps_run_waiting_approval(self):
        rejected_at = timezone.make_aware(
            datetime(2026, 8, 20, 9, 0),
            timezone.get_current_timezone(),
        )
        self.set_pending_approval(2)
        decision = self.create_decision()
        second_decision = self.create_decision(listing=self.second_listing)

        self.reject(decision, rejected_at=rejected_at)

        second_decision.refresh_from_db()
        self.result.refresh_from_db()
        self.automation_run.refresh_from_db()
        self.assertEqual(self.result.pending_approval, 1)
        self.assertEqual(
            self.automation_run.status,
            self.automation_run.Status.WAITING_APPROVAL,
        )
        self.assertIsNone(self.automation_run.finished_at)
        self.assertEqual(
            second_decision.status,
            second_decision.Status.PENDING_APPROVAL,
        )

    def test_repeated_reject_preserves_original_audit(self):
        first_rejected_at = timezone.make_aware(
            datetime(2026, 8, 20, 9, 0),
            timezone.get_current_timezone(),
        )
        repeated_at = first_rejected_at + timedelta(hours=1)
        self.set_pending_approval(1)
        decision = self.create_decision()

        first_transition = self.reject(
            decision,
            rejected_at=first_rejected_at,
        )
        repeated_transition = self.reject(
            decision,
            rejected_by=self.other_user,
            rejected_at=repeated_at,
        )

        decision.refresh_from_db()
        self.result.refresh_from_db()
        self.automation_run.refresh_from_db()
        self.assertTrue(first_transition.changed)
        self.assertFalse(repeated_transition.changed)
        self.assertEqual(decision.rejected_by, self.user)
        self.assertEqual(decision.rejected_at, first_rejected_at)
        self.assertEqual(decision.terminal_at, first_rejected_at)
        self.assertEqual(self.result.pending_approval, 0)
        self.assertEqual(
            self.automation_run.finished_at,
            first_rejected_at,
        )

    def test_ttl_boundary_expires_decision_instead_of_rejecting_it(self):
        expires_at = timezone.make_aware(
            datetime(2026, 8, 20, 9, 0),
            timezone.get_current_timezone(),
        )
        self.set_pending_approval(1)
        decision = self.create_decision(expires_at=expires_at)

        transition = self.reject(decision, rejected_at=expires_at)

        decision.refresh_from_db()
        self.result.refresh_from_db()
        self.automation_run.refresh_from_db()
        self.assertTrue(transition.changed)
        self.assertEqual(decision.status, decision.Status.EXPIRED)
        self.assertIsNone(decision.rejected_by)
        self.assertIsNone(decision.rejected_at)
        self.assertEqual(decision.terminal_at, expires_at)
        self.assertEqual(self.result.pending_approval, 0)
        self.assertEqual(
            self.automation_run.status,
            self.automation_run.Status.COMPLETED,
        )
        self.assertEqual(self.automation_run.finished_at, expires_at)

    def test_expire_decision_closes_due_decision_idempotently(self):
        expire_decision = self.get_expire_decision()
        expires_at = timezone.make_aware(
            datetime(2026, 8, 20, 9, 0),
            timezone.get_current_timezone(),
        )
        processed_at = expires_at + timedelta(minutes=5)
        repeated_at = processed_at + timedelta(minutes=10)
        self.set_pending_approval(1)
        decision = self.create_decision(expires_at=expires_at)

        first_transition = expire_decision(
            workspace_id=self.workspace.id,
            run_id=self.automation_run.id,
            decision_id=decision.id,
            expired_at=processed_at,
        )
        repeated_transition = expire_decision(
            workspace_id=self.workspace.id,
            run_id=self.automation_run.id,
            decision_id=decision.id,
            expired_at=repeated_at,
        )

        decision.refresh_from_db()
        self.result.refresh_from_db()
        self.automation_run.refresh_from_db()
        self.assertTrue(first_transition.changed)
        self.assertFalse(repeated_transition.changed)
        self.assertEqual(decision.status, decision.Status.EXPIRED)
        self.assertEqual(decision.terminal_at, processed_at)
        self.assertIsNone(decision.rejected_by)
        self.assertIsNone(decision.rejected_at)
        self.assertEqual(self.result.pending_approval, 0)
        self.assertEqual(
            self.automation_run.status,
            self.automation_run.Status.COMPLETED,
        )
        self.assertEqual(self.automation_run.finished_at, processed_at)

    def test_expire_decision_leaves_future_decision_open(self):
        expire_decision = self.get_expire_decision()
        checked_at = timezone.make_aware(
            datetime(2026, 8, 20, 9, 0),
            timezone.get_current_timezone(),
        )
        self.set_pending_approval(1)
        decision = self.create_decision(
            expires_at=checked_at + timedelta(minutes=1),
        )

        transition = expire_decision(
            workspace_id=self.workspace.id,
            run_id=self.automation_run.id,
            decision_id=decision.id,
            expired_at=checked_at,
        )

        decision.refresh_from_db()
        self.result.refresh_from_db()
        self.automation_run.refresh_from_db()
        self.assertFalse(transition.changed)
        self.assertEqual(
            decision.status,
            decision.Status.PENDING_APPROVAL,
        )
        self.assertIsNone(decision.terminal_at)
        self.assertEqual(self.result.pending_approval, 1)
        self.assertEqual(
            self.automation_run.status,
            self.automation_run.Status.WAITING_APPROVAL,
        )

    def test_scope_mismatch_does_not_change_decision(self):
        lifecycle = self.get_lifecycle_module()
        self.set_pending_approval(1)
        decision = self.create_decision()
        rejected_at = timezone.make_aware(
            datetime(2026, 8, 20, 9, 0),
            timezone.get_current_timezone(),
        )
        invalid_scopes = (
            {
                "workspace": self.other_workspace,
                "run_id": self.automation_run.id,
            },
            {
                "workspace": self.workspace,
                "run_id": self.automation_run.id + 100_000,
            },
        )

        for invalid_scope in invalid_scopes:
            with self.subTest(**invalid_scope):
                with self.assertRaises(
                    lifecycle.DecisionTransitionError,
                ) as raised:
                    lifecycle.reject_decision(
                        **invalid_scope,
                        decision_id=decision.id,
                        rejected_by=self.user,
                        rejected_at=rejected_at,
                    )
                self.assertEqual(raised.exception.code, "decision_not_found")

        decision.refresh_from_db()
        self.result.refresh_from_db()
        self.automation_run.refresh_from_db()
        self.assertEqual(decision.status, decision.Status.PENDING_APPROVAL)
        self.assertEqual(self.result.pending_approval, 1)
        self.assertEqual(
            self.automation_run.status,
            self.automation_run.Status.WAITING_APPROVAL,
        )

    def test_non_pending_decision_is_rejected_safely(self):
        lifecycle = self.get_lifecycle_module()
        decision = self.create_decision(
            status=apps.get_model(
                "automations",
                "AvitoListingDecision",
            ).Status.COMPLETED,
        )
        rejected_at = timezone.make_aware(
            datetime(2026, 8, 20, 9, 0),
            timezone.get_current_timezone(),
        )

        with self.assertRaises(
            lifecycle.DecisionTransitionError,
        ) as raised:
            self.reject(decision, rejected_at=rejected_at)

        decision.refresh_from_db()
        self.result.refresh_from_db()
        self.automation_run.refresh_from_db()
        self.assertEqual(raised.exception.code, "invalid_decision_state")
        self.assertEqual(decision.status, decision.Status.COMPLETED)
        self.assertIsNone(decision.rejected_at)
        self.assertEqual(self.result.pending_approval, 0)
        self.assertEqual(
            self.automation_run.status,
            self.automation_run.Status.WAITING_APPROVAL,
        )

    def test_last_rejection_preserves_effect_pending_run(self):
        decision_model = apps.get_model(
            "automations",
            "AvitoListingDecision",
        )
        rejected_at = timezone.make_aware(
            datetime(2026, 8, 20, 9, 0),
            timezone.get_current_timezone(),
        )
        self.set_pending_approval(1)
        decision = self.create_decision()
        self.create_decision(
            listing=self.second_listing,
            status=decision_model.Status.EFFECT_PENDING,
        )

        self.reject(decision, rejected_at=rejected_at)

        self.result.refresh_from_db()
        self.automation_run.refresh_from_db()
        self.assertEqual(self.result.pending_approval, 0)
        self.assertEqual(
            self.automation_run.status,
            self.automation_run.Status.EFFECT_PENDING,
        )
        self.assertIsNone(self.automation_run.finished_at)

    def test_last_rejection_marks_run_partial_after_mixed_actions(self):
        decision_model = apps.get_model(
            "automations",
            "AvitoListingDecision",
        )
        rejected_at = timezone.make_aware(
            datetime(2026, 8, 20, 9, 0),
            timezone.get_current_timezone(),
        )
        self.set_pending_approval(1)
        decision = self.create_decision()
        self.create_decision(
            listing=self.second_listing,
            status=decision_model.Status.COMPLETED,
        )
        self.create_decision(
            listing=self.third_listing,
            status=decision_model.Status.FAILED,
        )

        self.reject(decision, rejected_at=rejected_at)

        self.automation_run.refresh_from_db()
        self.assertEqual(
            self.automation_run.status,
            self.automation_run.Status.PARTIAL,
        )
        self.assertEqual(self.automation_run.finished_at, rejected_at)

    def test_last_rejection_marks_run_failed_when_all_attempts_failed(self):
        decision_model = apps.get_model(
            "automations",
            "AvitoListingDecision",
        )
        rejected_at = timezone.make_aware(
            datetime(2026, 8, 20, 9, 0),
            timezone.get_current_timezone(),
        )
        self.set_pending_approval(1)
        decision = self.create_decision()
        self.create_decision(
            listing=self.second_listing,
            status=decision_model.Status.FAILED,
        )

        self.reject(decision, rejected_at=rejected_at)

        self.automation_run.refresh_from_db()
        self.assertEqual(
            self.automation_run.status,
            self.automation_run.Status.FAILED,
        )
        self.assertEqual(self.automation_run.finished_at, rejected_at)

    def test_lock_conflict_is_reported_as_resource_busy(self):
        lifecycle = self.get_lifecycle_module()
        self.set_pending_approval(1)
        decision = self.create_decision()

        with patch.object(
            lifecycle,
            "_get_locked_decision",
            side_effect=OperationalError("could not obtain lock"),
        ):
            with self.assertRaises(
                lifecycle.DecisionTransitionError,
            ) as raised:
                self.reject(decision)

        decision.refresh_from_db()
        self.assertEqual(raised.exception.code, "resource_busy")
        self.assertEqual(decision.status, decision.Status.PENDING_APPROVAL)


class AvitoListingDecisionCleanupTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(
            email="decision-cleanup-owner@example.com",
            password="test-password",
        )
        cls.workspace = Workspace.objects.create(
            name="Decision cleanup workspace",
            slug="decision-cleanup-workspace",
            owner=cls.user,
        )
        cls.avito_account = AvitoAccount.objects.create(
            workspace=cls.workspace,
            name="Decision cleanup Avito account",
        )
        cls.active_since = timezone.make_aware(
            datetime(2026, 8, 1, 9, 0),
            timezone.get_current_timezone(),
        )
        automation_model = apps.get_model("automations", "Automation")
        cls.automation = automation_model.objects.create(
            workspace=cls.workspace,
            module_type="avito_listings",
            name="Очистка истёкших решений",
            state=automation_model.State.ENABLED,
            created_by=cls.user,
            updated_by=cls.user,
        )

    def get_cleanup_module(self):
        try:
            return import_module(
                "automations.services.decision_cleanup",
            )
        except ModuleNotFoundError as error:
            self.fail(
                "Добавьте bounded-сервис очистки истёкших решений: "
                f"{error}",
            )

    def create_run_with_decisions(self, expires_at_values):
        run_model = apps.get_model("automations", "AutomationRun")
        result_model = apps.get_model(
            "automations",
            "AvitoListingRunResult",
        )
        decision_model = apps.get_model(
            "automations",
            "AvitoListingDecision",
        )
        automation_run = run_model.objects.create(
            automation=self.automation,
            workspace=self.workspace,
            run_kind=run_model.RunKind.EXECUTE,
            trigger=run_model.Trigger.MANUAL,
            execution_mode_snapshot="manual",
            automation_version=self.automation.version,
            automation_name_snapshot=self.automation.name,
            module_type_snapshot=self.automation.module_type,
            status=run_model.Status.WAITING_APPROVAL,
            idempotency_key=f"decision-cleanup-{uuid4()}",
            created_by=self.user,
        )
        condition_snapshot = {
            "type": "condition",
            "metric": "contacts",
            "operator": "lt",
            "value": 10,
            "period_days": 10,
        }
        action_snapshot = {"type": "pause", "config": {}}
        run_result = result_model.objects.create(
            run=automation_run,
            workspace=self.workspace,
            avito_account=self.avito_account,
            as_of_date=date(2026, 8, 20),
            condition_snapshot=condition_snapshot,
            action_snapshot=action_snapshot,
            pending_approval=len(expires_at_values),
        )
        listings = AvitoListing.objects.bulk_create(
            [
                AvitoListing(
                    workspace=self.workspace,
                    avito_account=self.avito_account,
                    avito_id=f"cleanup-listing-{uuid4()}",
                    title=f"Объявление {position}",
                    management_status=(
                        AvitoListing.ManagementStatus.MANAGED
                    ),
                    active_since=self.active_since,
                )
                for position, _ in enumerate(expires_at_values, start=1)
            ],
        )
        decisions = decision_model.objects.bulk_create(
            [
                decision_model(
                    run=automation_run,
                    automation=self.automation,
                    workspace=self.workspace,
                    avito_account=self.avito_account,
                    listing=listing,
                    listing_id_snapshot=listing.id,
                    listing_snapshot={
                        "id": listing.id,
                        "avito_id": listing.avito_id,
                        "title": listing.title,
                    },
                    automation_version=self.automation.version,
                    active_since_snapshot=self.active_since,
                    condition_snapshot=condition_snapshot,
                    metrics_snapshot={"contacts": 3},
                    action_snapshot=action_snapshot,
                    expires_at=expires_at,
                )
                for listing, expires_at in zip(
                    listings,
                    expires_at_values,
                    strict=True,
                )
            ],
        )
        return automation_run, run_result, decisions

    def test_cleanup_expires_due_boundary_and_leaves_future_open(self):
        cleanup = self.get_cleanup_module()
        processed_at = timezone.make_aware(
            datetime(2026, 8, 26, 12, 0),
            timezone.get_current_timezone(),
        )
        automation_run, run_result, decisions = (
            self.create_run_with_decisions(
                [
                    processed_at - timedelta(minutes=1),
                    processed_at,
                    processed_at + timedelta(minutes=1),
                ],
            )
        )

        cleanup_result = cleanup.expire_pending_decisions(
            expired_at=processed_at,
        )

        for decision in decisions:
            decision.refresh_from_db()
        run_result.refresh_from_db()
        automation_run.refresh_from_db()
        self.assertEqual(cleanup_result.selected, 2)
        self.assertEqual(cleanup_result.expired, 2)
        self.assertEqual(cleanup_result.skipped, 0)
        self.assertEqual(cleanup_result.busy, 0)
        self.assertEqual(
            [decision.status for decision in decisions],
            ["expired", "expired", "pending_approval"],
        )
        self.assertEqual(run_result.pending_approval, 1)
        self.assertEqual(automation_run.status, "waiting_approval")
        self.assertIsNone(automation_run.finished_at)

    def test_cleanup_processes_at_most_one_hundred_per_pass(self):
        cleanup = self.get_cleanup_module()
        processed_at = timezone.make_aware(
            datetime(2026, 8, 26, 12, 0),
            timezone.get_current_timezone(),
        )
        automation_run, run_result, _ = self.create_run_with_decisions(
            [processed_at] * 101,
        )

        first_result = cleanup.expire_pending_decisions(
            expired_at=processed_at,
        )

        run_result.refresh_from_db()
        automation_run.refresh_from_db()
        self.assertEqual(first_result.selected, 100)
        self.assertEqual(first_result.expired, 100)
        self.assertEqual(run_result.pending_approval, 1)
        self.assertEqual(automation_run.status, "waiting_approval")

        second_result = cleanup.expire_pending_decisions(
            expired_at=processed_at,
        )

        run_result.refresh_from_db()
        automation_run.refresh_from_db()
        self.assertEqual(second_result.selected, 1)
        self.assertEqual(second_result.expired, 1)
        self.assertEqual(run_result.pending_approval, 0)
        self.assertEqual(automation_run.status, "completed")
        self.assertEqual(automation_run.finished_at, processed_at)

        repeated_result = cleanup.expire_pending_decisions(
            expired_at=processed_at,
        )
        self.assertEqual(repeated_result.selected, 0)
        self.assertEqual(repeated_result.expired, 0)

    def test_cleanup_skips_busy_decision_and_continues_batch(self):
        cleanup = self.get_cleanup_module()
        lifecycle = import_module(
            "automations.modules.avito_listings.decision_lifecycle",
        )
        processed_at = timezone.make_aware(
            datetime(2026, 8, 26, 12, 0),
            timezone.get_current_timezone(),
        )
        _, run_result, decisions = self.create_run_with_decisions(
            [processed_at, processed_at],
        )
        busy_decision = decisions[0]
        real_expire_decision = lifecycle.expire_decision

        def expire_or_report_busy(**kwargs):
            if kwargs["decision_id"] == busy_decision.id:
                raise lifecycle.DecisionTransitionError(
                    code="resource_busy",
                    message="Решение занято.",
                )
            return real_expire_decision(**kwargs)

        with patch.object(
            cleanup,
            "expire_decision",
            side_effect=expire_or_report_busy,
        ):
            cleanup_result = cleanup.expire_pending_decisions(
                expired_at=processed_at,
            )

        for decision in decisions:
            decision.refresh_from_db()
        run_result.refresh_from_db()
        self.assertEqual(cleanup_result.selected, 2)
        self.assertEqual(cleanup_result.expired, 1)
        self.assertEqual(cleanup_result.busy, 1)
        self.assertEqual(cleanup_result.skipped, 0)
        self.assertEqual(
            [decision.status for decision in decisions],
            ["pending_approval", "expired"],
        )
        self.assertEqual(run_result.pending_approval, 1)

    def test_cleanup_does_not_hide_invalid_run_state(self):
        cleanup = self.get_cleanup_module()
        lifecycle = import_module(
            "automations.modules.avito_listings.decision_lifecycle",
        )
        processed_at = timezone.make_aware(
            datetime(2026, 8, 26, 12, 0),
            timezone.get_current_timezone(),
        )
        automation_run, _, decisions = self.create_run_with_decisions(
            [processed_at],
        )
        automation_run.status = automation_run.Status.COMPLETED
        automation_run.finished_at = processed_at - timedelta(minutes=1)
        automation_run.save(
            update_fields=["status", "finished_at", "updated_at"],
        )

        with self.assertRaises(
            lifecycle.DecisionTransitionError,
        ) as raised:
            cleanup.expire_pending_decisions(expired_at=processed_at)

        decisions[0].refresh_from_db()
        self.assertEqual(raised.exception.code, "invalid_run_state")
        self.assertEqual(decisions[0].status, "pending_approval")


class AvitoListingDecisionRecheckTests(TestCase):
    module_path = (
        "automations.modules.avito_listings.decision_recheck"
    )

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(
            email="decision-recheck-owner@example.com",
            password="test-password",
        )
        cls.other_user = get_user_model().objects.create_user(
            email="decision-recheck-other@example.com",
            password="test-password",
        )
        cls.workspace = Workspace.objects.create(
            name="Decision recheck workspace",
            slug="decision-recheck-workspace",
            owner=cls.user,
        )
        cls.other_workspace = Workspace.objects.create(
            name="Other decision recheck workspace",
            slug="other-decision-recheck-workspace",
            owner=cls.other_user,
        )
        cls.avito_account = AvitoAccount.objects.create(
            workspace=cls.workspace,
            name="Decision recheck Avito account",
        )
        cls.active_since = timezone.make_aware(
            datetime(2026, 8, 1, 9, 0),
            timezone.get_current_timezone(),
        )
        cls.checked_at = timezone.make_aware(
            datetime(2026, 8, 27, 12, 0),
            timezone.get_current_timezone(),
        )
        cls.condition_snapshot = build_condition_tree({
            "type": "condition",
            "metric": "contacts",
            "aggregation": "sum",
            "window_days": 10,
            "comparator": "lt",
            "value": 10,
        })
        cls.action_snapshot = {"type": "pause", "config": {}}

    def setUp(self):
        self.context = self.create_decision_context()

    def get_recheck_module(self):
        try:
            return import_module(self.module_path)
        except ModuleNotFoundError as error:
            if error.name != self.module_path:
                raise

            self.fail(
                "Добавьте read-only stale recheck перед подтверждением.",
            )

    def create_decision_context(self):
        automation_model = apps.get_model("automations", "Automation")
        run_model = apps.get_model("automations", "AutomationRun")
        result_model = apps.get_model(
            "automations",
            "AvitoListingRunResult",
        )
        decision_model = apps.get_model(
            "automations",
            "AvitoListingDecision",
        )
        automation = automation_model.objects.create(
            workspace=self.workspace,
            module_type="avito_listings",
            name=f"Decision recheck {uuid4()}",
            state=automation_model.State.ENABLED,
            created_by=self.user,
            updated_by=self.user,
        )
        listing = AvitoListing.objects.create(
            workspace=self.workspace,
            avito_account=self.avito_account,
            source=AvitoListing.Source.AVITO_EXCEL,
            avito_id=f"decision-recheck-{uuid4()}",
            title="Объявление для повторной проверки",
            management_status=AvitoListing.ManagementStatus.MANAGED,
            desired_status=AvitoListing.DesiredStatus.PUBLISH,
            active_since=self.active_since,
        )
        automation_run = run_model.objects.create(
            automation=automation,
            workspace=self.workspace,
            run_kind=run_model.RunKind.EXECUTE,
            trigger=run_model.Trigger.MANUAL,
            execution_mode_snapshot="manual",
            automation_version=automation.version,
            automation_name_snapshot=automation.name,
            module_type_snapshot=automation.module_type,
            status=run_model.Status.WAITING_APPROVAL,
            idempotency_key=f"decision-recheck-{uuid4()}",
            created_by=self.user,
        )
        run_result = result_model.objects.create(
            run=automation_run,
            workspace=self.workspace,
            avito_account=self.avito_account,
            as_of_date=date(2026, 8, 20),
            condition_snapshot=self.condition_snapshot,
            action_snapshot=self.action_snapshot,
            pending_approval=1,
        )
        decision = decision_model.objects.create(
            run=automation_run,
            automation=automation,
            workspace=self.workspace,
            avito_account=self.avito_account,
            listing=listing,
            listing_id_snapshot=listing.id,
            listing_snapshot={
                "id": listing.id,
                "avito_id": listing.avito_id,
                "title": listing.title,
            },
            automation_version=automation.version,
            active_since_snapshot=self.active_since,
            condition_snapshot=self.condition_snapshot,
            metrics_snapshot=[
                {
                    "metric": "contacts",
                    "aggregation": "sum",
                    "window_days": 10,
                    "date_from": "2026-08-11",
                    "date_to": "2026-08-20",
                    "value": 3,
                },
            ],
            action_snapshot=self.action_snapshot,
            expires_at=self.checked_at + timedelta(hours=1),
        )
        return SimpleNamespace(
            automation=automation,
            listing=listing,
            automation_run=automation_run,
            run_result=run_result,
            decision=decision,
        )

    def confirm_ready_statistics(self, context, *, contacts=3):
        AvitoStatsSyncState.objects.update_or_create(
            workspace=self.workspace,
            avito_account=self.avito_account,
            defaults={
                "status": AvitoStatsSyncState.Status.SUCCESS,
                "coverage_from": date(2026, 8, 17),
                "coverage_to": date(2026, 8, 26),
            },
        )
        AvitoListingStatsCoverage.objects.create(
            workspace=self.workspace,
            listing=context.listing,
            coverage_from=date(2026, 8, 17),
            finalized_through=date(2026, 8, 26),
        )
        AvitoListingDailyStats.objects.create(
            workspace=self.workspace,
            listing=context.listing,
            date=date(2026, 8, 26),
            contacts=contacts,
        )

    def recheck(self, *, context=None, workspace=None):
        recheck_module = self.get_recheck_module()
        context = context or self.context
        return recheck_module.recheck_decision_before_approval(
            workspace=workspace or self.workspace,
            run_id=context.automation_run.id,
            decision_id=context.decision.id,
            checked_at=self.checked_at,
        )

    def assert_stale_context(self, context, *, reason):
        context.decision.refresh_from_db()
        context.run_result.refresh_from_db()
        context.automation_run.refresh_from_db()
        self.assertEqual(context.decision.status, "stale")
        self.assertEqual(context.decision.terminal_at, self.checked_at)
        self.assertEqual(context.decision.error_code, "stale")
        self.assertTrue(context.decision.error_message)
        self.assertEqual(context.run_result.pending_approval, 0)
        self.assertEqual(context.automation_run.status, "completed")
        self.assertEqual(
            context.automation_run.finished_at,
            self.checked_at,
        )

    def test_ready_recheck_uses_fresh_window_ending_yesterday(self):
        self.confirm_ready_statistics(self.context, contacts=3)

        recheck_result = self.recheck()

        self.context.decision.refresh_from_db()
        self.assertEqual(recheck_result.outcome, "ready")
        self.assertIsNone(recheck_result.reason)
        self.assertFalse(recheck_result.changed)
        self.assertEqual(recheck_result.as_of_date, date(2026, 8, 27))
        self.assertEqual(
            recheck_result.metrics_snapshot,
            (
                {
                    "metric": "contacts",
                    "aggregation": "sum",
                    "window_days": 10,
                    "date_from": "2026-08-17",
                    "date_to": "2026-08-26",
                    "value": 3,
                },
            ),
        )
        self.assertEqual(
            self.context.decision.status,
            "pending_approval",
        )
        self.assertEqual(
            self.context.decision.metrics_snapshot[0]["date_to"],
            "2026-08-20",
            "Исходный audit snapshot нельзя перезаписывать recheck-ом.",
        )

    def test_ready_recheck_does_not_hold_row_locks_while_reading(self):
        self.confirm_ready_statistics(self.context)

        with CaptureQueriesContext(connection) as queries:
            recheck_result = self.recheck()

        self.assertEqual(recheck_result.outcome, "ready")
        locking_queries = [
            query["sql"]
            for query in queries.captured_queries
            if "FOR UPDATE" in query["sql"].upper()
        ]
        self.assertEqual(locking_queries, [])

    def test_missing_account_coverage_leaves_decision_open(self):
        recheck_result = self.recheck()

        self.context.decision.refresh_from_db()
        self.context.run_result.refresh_from_db()
        self.assertEqual(recheck_result.outcome, "insufficient_data")
        self.assertEqual(
            recheck_result.reason,
            "insufficient_account_coverage",
        )
        self.assertFalse(recheck_result.changed)
        self.assertEqual(
            self.context.decision.status,
            "pending_approval",
        )
        self.assertEqual(self.context.run_result.pending_approval, 1)

    def test_missing_listing_coverage_leaves_decision_open(self):
        AvitoStatsSyncState.objects.create(
            workspace=self.workspace,
            avito_account=self.avito_account,
            status=AvitoStatsSyncState.Status.SUCCESS,
            coverage_from=date(2026, 8, 17),
            coverage_to=date(2026, 8, 26),
        )

        recheck_result = self.recheck()

        self.context.decision.refresh_from_db()
        self.assertEqual(recheck_result.outcome, "insufficient_data")
        self.assertEqual(
            recheck_result.reason,
            "insufficient_listing_coverage",
        )
        self.assertFalse(recheck_result.changed)
        self.assertEqual(
            self.context.decision.status,
            "pending_approval",
        )

    def test_condition_change_marks_decision_stale_idempotently(self):
        self.confirm_ready_statistics(self.context, contacts=12)

        first_result = self.recheck()
        repeated_result = self.recheck()

        self.assertEqual(first_result.outcome, "stale")
        self.assertEqual(first_result.reason, "condition_not_matched")
        self.assertTrue(first_result.changed)
        self.assertEqual(repeated_result.outcome, "unchanged")
        self.assertFalse(repeated_result.changed)
        self.assert_stale_context(
            self.context,
            reason="condition_not_matched",
        )

    def test_hard_state_changes_mark_decisions_stale(self):
        scenarios = []

        disabled = self.create_decision_context()
        disabled.automation.state = disabled.automation.State.DISABLED
        disabled.automation.save(
            update_fields=["state", "updated_at"],
        )
        scenarios.append(
            (disabled, "automation_not_enabled"),
        )

        changed_version = self.create_decision_context()
        changed_version.automation.version += 1
        changed_version.automation.save(
            update_fields=["version", "updated_at"],
        )
        scenarios.append(
            (changed_version, "automation_version_changed"),
        )

        changed_period = self.create_decision_context()
        changed_period.listing.active_since += timedelta(days=1)
        changed_period.listing.save(
            update_fields=["active_since", "updated_at"],
        )
        scenarios.append(
            (changed_period, "active_period_changed"),
        )

        missing_listing = self.create_decision_context()
        missing_listing.listing.delete()
        scenarios.append(
            (missing_listing, "listing_missing"),
        )

        for context, expected_reason in scenarios:
            with self.subTest(reason=expected_reason):
                recheck_result = self.recheck(context=context)

                self.assertEqual(recheck_result.outcome, "stale")
                self.assertEqual(
                    recheck_result.reason,
                    expected_reason,
                )
                self.assertTrue(recheck_result.changed)
                self.assert_stale_context(
                    context,
                    reason=expected_reason,
                )

    def test_ttl_boundary_expires_before_reading_statistics(self):
        self.context.decision.expires_at = self.checked_at
        self.context.decision.save(
            update_fields=["expires_at", "updated_at"],
        )

        with CaptureQueriesContext(connection) as queries:
            recheck_result = self.recheck()

        self.context.decision.refresh_from_db()
        self.assertEqual(recheck_result.outcome, "expired")
        self.assertTrue(recheck_result.changed)
        self.assertEqual(self.context.decision.status, "expired")
        statistics_queries = [
            query["sql"]
            for query in queries.captured_queries
            if "ANALYTICS_" in query["sql"].upper()
        ]
        self.assertEqual(statistics_queries, [])

    def test_workspace_mismatch_cannot_recheck_decision(self):
        recheck_module = self.get_recheck_module()

        with self.assertRaises(
            recheck_module.DecisionRecheckError,
        ) as raised:
            self.recheck(workspace=self.other_workspace)

        self.context.decision.refresh_from_db()
        self.assertEqual(raised.exception.code, "decision_not_found")
        self.assertEqual(
            self.context.decision.status,
            "pending_approval",
        )


class AvitoListingDecisionApprovalTests(TestCase):
    module_path = (
        "automations.modules.avito_listings.decision_approval"
    )

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(
            email="decision-approval-owner@example.com",
            password="test-password",
        )
        cls.other_user = get_user_model().objects.create_user(
            email="decision-approval-other@example.com",
            password="test-password",
        )
        cls.workspace = Workspace.objects.create(
            name="Decision approval workspace",
            slug="decision-approval-workspace",
            owner=cls.user,
        )
        cls.other_workspace = Workspace.objects.create(
            name="Other decision approval workspace",
            slug="other-decision-approval-workspace",
            owner=cls.other_user,
        )
        cls.avito_account = AvitoAccount.objects.create(
            workspace=cls.workspace,
            name="Decision approval Avito account",
        )
        cls.active_since = timezone.make_aware(
            datetime(2026, 8, 1, 9, 0),
            timezone.get_current_timezone(),
        )
        cls.approved_at = timezone.make_aware(
            datetime(2026, 8, 27, 12, 0),
            timezone.get_current_timezone(),
        )
        cls.condition_snapshot = build_condition_tree({
            "type": "condition",
            "metric": "contacts",
            "aggregation": "sum",
            "window_days": 10,
            "comparator": "lt",
            "value": 10,
        })

    def setUp(self):
        self.context = self.create_decision_context()

    def get_approval_module(self):
        try:
            return import_module(self.module_path)
        except ModuleNotFoundError as error:
            if error.name != self.module_path:
                raise

            self.fail(
                "Добавьте транзакционное подтверждение решения.",
            )

    def create_decision_context(
            self,
            *,
            action_type="pause",
            source=AvitoListing.Source.AVITO_EXCEL,
    ):
        automation_model = apps.get_model("automations", "Automation")
        run_model = apps.get_model("automations", "AutomationRun")
        result_model = apps.get_model(
            "automations",
            "AvitoListingRunResult",
        )
        decision_model = apps.get_model(
            "automations",
            "AvitoListingDecision",
        )
        automation = automation_model.objects.create(
            workspace=self.workspace,
            module_type="avito_listings",
            name=f"Decision approval {uuid4()}",
            state=automation_model.State.ENABLED,
            created_by=self.user,
            updated_by=self.user,
        )
        publication = None
        if source == AvitoListing.Source.SERVICE:
            creative = AdCreative.objects.create(
                workspace=self.workspace,
                source=AdCreative.Source.MANUAL,
                title=f"Decision approval creative {uuid4()}",
                description="Описание",
                base_data={},
            )
            publication = AdPublication.objects.create(
                workspace=self.workspace,
                avito_account=self.avito_account,
                creative=creative,
                source=AdPublication.Source.MANUAL,
                status=AdPublication.Status.ACTIVE,
                row_id=f"APPROVAL-{uuid4()}",
                address="Москва",
            )
        listing = AvitoListing.objects.create(
            workspace=self.workspace,
            avito_account=self.avito_account,
            publication=publication,
            source=source,
            management_status=AvitoListing.ManagementStatus.MANAGED,
            desired_status=AvitoListing.DesiredStatus.PUBLISH,
            active_since=self.active_since,
            avito_id=f"decision-approval-{uuid4()}",
            row_id=f"DECISION-APPROVAL-{uuid4()}",
            title="Объявление для подтверждения",
        )
        automation_run = run_model.objects.create(
            automation=automation,
            workspace=self.workspace,
            run_kind=run_model.RunKind.EXECUTE,
            trigger=run_model.Trigger.MANUAL,
            execution_mode_snapshot="manual",
            automation_version=automation.version,
            automation_name_snapshot=automation.name,
            module_type_snapshot=automation.module_type,
            status=run_model.Status.WAITING_APPROVAL,
            idempotency_key=f"decision-approval-{uuid4()}",
            created_by=self.user,
        )
        action_snapshot = {
            "type": action_type,
            "config": {},
        }
        run_result = result_model.objects.create(
            run=automation_run,
            workspace=self.workspace,
            avito_account=self.avito_account,
            as_of_date=date(2026, 8, 20),
            condition_snapshot=self.condition_snapshot,
            action_snapshot=action_snapshot,
            pending_approval=1,
        )
        decision = decision_model.objects.create(
            run=automation_run,
            automation=automation,
            workspace=self.workspace,
            avito_account=self.avito_account,
            listing=listing,
            listing_id_snapshot=listing.id,
            listing_snapshot={
                "id": listing.id,
                "avito_id": listing.avito_id,
                "title": listing.title,
            },
            automation_version=automation.version,
            active_since_snapshot=self.active_since,
            condition_snapshot=self.condition_snapshot,
            metrics_snapshot=[
                {
                    "metric": "contacts",
                    "aggregation": "sum",
                    "window_days": 10,
                    "date_from": "2026-08-11",
                    "date_to": "2026-08-20",
                    "value": 3,
                },
            ],
            action_snapshot=action_snapshot,
            expires_at=self.approved_at + timedelta(hours=1),
        )
        return SimpleNamespace(
            automation=automation,
            listing=listing,
            publication=publication,
            automation_run=automation_run,
            run_result=run_result,
            decision=decision,
        )

    def confirm_ready_statistics(self, context, *, contacts=3):
        AvitoStatsSyncState.objects.update_or_create(
            workspace=self.workspace,
            avito_account=self.avito_account,
            defaults={
                "status": AvitoStatsSyncState.Status.SUCCESS,
                "coverage_from": date(2026, 8, 17),
                "coverage_to": date(2026, 8, 26),
            },
        )
        AvitoListingStatsCoverage.objects.create(
            workspace=self.workspace,
            listing=context.listing,
            coverage_from=date(2026, 8, 17),
            finalized_through=date(2026, 8, 26),
        )
        AvitoListingDailyStats.objects.create(
            workspace=self.workspace,
            listing=context.listing,
            date=date(2026, 8, 26),
            contacts=contacts,
        )

    def approve(
            self,
            *,
            context=None,
            workspace=None,
            approved_by=None,
            approved_at=None,
    ):
        context = context or self.context
        return self.get_approval_module().approve_decision(
            workspace=workspace or self.workspace,
            run_id=context.automation_run.id,
            decision_id=context.decision.id,
            approved_by=approved_by or self.user,
            approved_at=approved_at or self.approved_at,
        )

    def add_pending_decision(self, context):
        decision_model = apps.get_model(
            "automations",
            "AvitoListingDecision",
        )
        listing = AvitoListing.objects.create(
            workspace=self.workspace,
            avito_account=self.avito_account,
            source=AvitoListing.Source.AVITO_EXCEL,
            management_status=AvitoListing.ManagementStatus.MANAGED,
            desired_status=AvitoListing.DesiredStatus.PUBLISH,
            active_since=self.active_since,
            avito_id=f"second-approval-{uuid4()}",
            row_id=f"SECOND-APPROVAL-{uuid4()}",
            title="Второе решение",
        )
        decision = decision_model.objects.create(
            run=context.automation_run,
            automation=context.automation,
            workspace=self.workspace,
            avito_account=self.avito_account,
            listing=listing,
            listing_id_snapshot=listing.id,
            listing_snapshot={"id": listing.id},
            automation_version=context.automation.version,
            active_since_snapshot=self.active_since,
            condition_snapshot=self.condition_snapshot,
            metrics_snapshot=[],
            action_snapshot={"type": "pause", "config": {}},
            expires_at=self.approved_at + timedelta(hours=1),
        )
        context.run_result.pending_approval = 2
        context.run_result.save(
            update_fields=["pending_approval", "updated_at"],
        )
        return decision

    def test_ready_pause_moves_decision_and_run_to_effect_pending(self):
        self.confirm_ready_statistics(self.context)

        approval_result = self.approve()

        self.context.decision.refresh_from_db()
        self.context.listing.refresh_from_db()
        self.context.run_result.refresh_from_db()
        self.context.automation_run.refresh_from_db()
        self.avito_account.refresh_from_db()
        self.assertEqual(approval_result.outcome, "effect_pending")
        self.assertTrue(approval_result.changed)
        self.assertEqual(approval_result.required_export_revision, 1)
        self.assertEqual(self.context.decision.status, "effect_pending")
        self.assertEqual(self.context.decision.approved_by, self.user)
        self.assertEqual(
            self.context.decision.approved_at,
            self.approved_at,
        )
        self.assertEqual(
            self.context.decision.action_applied_at,
            self.approved_at,
        )
        self.assertEqual(
            self.context.decision.required_export_revision,
            1,
        )
        self.assertIsNone(self.context.decision.terminal_at)
        self.assertEqual(
            self.context.decision.metrics_snapshot[0]["date_to"],
            "2026-08-20",
        )
        self.assertEqual(
            self.context.listing.desired_status,
            AvitoListing.DesiredStatus.PAUSE,
        )
        self.assertIsNone(self.context.listing.active_since)
        self.assertEqual(self.avito_account.export_revision, 1)
        self.assertEqual(self.context.run_result.pending_approval, 0)
        self.assertEqual(self.context.run_result.completed_actions, 0)
        self.assertEqual(self.context.run_result.failed_actions, 0)
        self.assertEqual(
            self.context.automation_run.status,
            self.context.automation_run.Status.EFFECT_PENDING,
        )
        self.assertIsNone(self.context.automation_run.finished_at)

    def test_archive_service_listing_routes_to_publication(self):
        context = self.create_decision_context(
            action_type="archive",
            source=AvitoListing.Source.SERVICE,
        )
        self.confirm_ready_statistics(context)

        approval_result = self.approve(context=context)

        context.publication.refresh_from_db()
        context.listing.refresh_from_db()
        context.decision.refresh_from_db()
        self.assertEqual(approval_result.outcome, "effect_pending")
        self.assertEqual(
            context.publication.status,
            AdPublication.Status.ARCHIVED,
        )
        self.assertIsNone(context.listing.active_since)
        self.assertEqual(context.decision.required_export_revision, 1)

    def test_duplicate_approve_does_not_repeat_action_or_revision(self):
        self.confirm_ready_statistics(self.context)
        first_result = self.approve()

        repeated_result = self.approve(
            approved_by=self.other_user,
            approved_at=self.approved_at + timedelta(minutes=1),
        )

        self.context.decision.refresh_from_db()
        self.avito_account.refresh_from_db()
        self.assertEqual(first_result.outcome, "effect_pending")
        self.assertEqual(repeated_result.outcome, "unchanged")
        self.assertFalse(repeated_result.changed)
        self.assertEqual(repeated_result.required_export_revision, 1)
        self.assertEqual(self.avito_account.export_revision, 1)
        self.assertEqual(self.context.decision.approved_by, self.user)
        self.assertEqual(
            self.context.decision.approved_at,
            self.approved_at,
        )

    def test_insufficient_data_leaves_decision_open(self):
        approval_result = self.approve()

        self.context.decision.refresh_from_db()
        self.context.listing.refresh_from_db()
        self.context.run_result.refresh_from_db()
        self.context.automation_run.refresh_from_db()
        self.avito_account.refresh_from_db()
        self.assertEqual(approval_result.outcome, "insufficient_data")
        self.assertEqual(
            approval_result.reason,
            "insufficient_account_coverage",
        )
        self.assertFalse(approval_result.changed)
        self.assertIsNone(approval_result.required_export_revision)
        self.assertEqual(
            self.context.decision.status,
            "pending_approval",
        )
        self.assertEqual(
            self.context.listing.desired_status,
            AvitoListing.DesiredStatus.PUBLISH,
        )
        self.assertEqual(self.context.run_result.pending_approval, 1)
        self.assertEqual(
            self.context.automation_run.status,
            self.context.automation_run.Status.WAITING_APPROVAL,
        )
        self.assertEqual(self.avito_account.export_revision, 0)

    def test_state_change_after_recheck_becomes_stale_without_action(self):
        recheck_module = import_module(
            "automations.modules.avito_listings.decision_recheck",
        )
        self.confirm_ready_statistics(self.context)
        ready_result = recheck_module.recheck_decision_before_approval(
            workspace=self.workspace,
            run_id=self.context.automation_run.id,
            decision_id=self.context.decision.id,
            checked_at=self.approved_at,
        )
        self.assertEqual(ready_result.outcome, "ready")
        self.context.listing.active_since += timedelta(days=1)
        self.context.listing.save(
            update_fields=["active_since", "updated_at"],
        )
        approval_module = self.get_approval_module()

        with patch.object(
            approval_module,
            "recheck_decision_before_approval",
            return_value=ready_result,
        ):
            approval_result = self.approve()

        self.context.decision.refresh_from_db()
        self.context.listing.refresh_from_db()
        self.avito_account.refresh_from_db()
        self.assertEqual(approval_result.outcome, "stale")
        self.assertEqual(
            approval_result.reason,
            "active_period_changed",
        )
        self.assertTrue(approval_result.changed)
        self.assertEqual(self.context.decision.status, "stale")
        self.assertEqual(
            self.context.listing.desired_status,
            AvitoListing.DesiredStatus.PUBLISH,
        )
        self.assertEqual(self.avito_account.export_revision, 0)

    def test_permanent_action_error_rolls_back_and_fails_decision(self):
        self.confirm_ready_statistics(self.context)
        self.context.decision.action_snapshot = {
            "type": "publish",
            "config": {},
        }
        self.context.decision.save(
            update_fields=["action_snapshot", "updated_at"],
        )

        approval_result = self.approve()

        self.context.decision.refresh_from_db()
        self.context.listing.refresh_from_db()
        self.context.run_result.refresh_from_db()
        self.context.automation_run.refresh_from_db()
        self.avito_account.refresh_from_db()
        self.assertEqual(approval_result.outcome, "failed")
        self.assertEqual(approval_result.reason, "unsupported_action")
        self.assertTrue(approval_result.changed)
        self.assertEqual(self.context.decision.status, "failed")
        self.assertEqual(self.context.decision.approved_by, self.user)
        self.assertEqual(
            self.context.decision.approved_at,
            self.approved_at,
        )
        self.assertIsNone(self.context.decision.action_applied_at)
        self.assertIsNone(
            self.context.decision.required_export_revision,
        )
        self.assertEqual(
            self.context.decision.terminal_at,
            self.approved_at,
        )
        self.assertEqual(
            self.context.decision.error_code,
            "action_failed",
        )
        self.assertTrue(self.context.decision.error_message)
        self.assertEqual(
            self.context.listing.desired_status,
            AvitoListing.DesiredStatus.PUBLISH,
        )
        self.assertEqual(self.context.listing.active_since, self.active_since)
        self.assertEqual(self.avito_account.export_revision, 0)
        self.assertEqual(self.context.run_result.pending_approval, 0)
        self.assertEqual(self.context.run_result.failed_actions, 1)
        self.assertEqual(
            self.context.automation_run.status,
            self.context.automation_run.Status.FAILED,
        )
        self.assertEqual(
            self.context.automation_run.finished_at,
            self.approved_at,
        )

    def test_run_waits_while_another_decision_needs_approval(self):
        self.confirm_ready_statistics(self.context)
        self.add_pending_decision(self.context)

        approval_result = self.approve()

        self.context.run_result.refresh_from_db()
        self.context.automation_run.refresh_from_db()
        self.assertEqual(approval_result.outcome, "effect_pending")
        self.assertEqual(self.context.run_result.pending_approval, 1)
        self.assertEqual(
            self.context.automation_run.status,
            self.context.automation_run.Status.WAITING_APPROVAL,
        )
        self.assertIsNone(self.context.automation_run.finished_at)

    def test_workspace_mismatch_cannot_approve_decision(self):
        approval_module = self.get_approval_module()

        with self.assertRaises(
            approval_module.DecisionApprovalError,
        ) as raised:
            self.approve(workspace=self.other_workspace)

        self.context.decision.refresh_from_db()
        self.context.listing.refresh_from_db()
        self.avito_account.refresh_from_db()
        self.assertEqual(raised.exception.code, "decision_not_found")
        self.assertEqual(
            self.context.decision.status,
            "pending_approval",
        )
        self.assertEqual(
            self.context.listing.desired_status,
            AvitoListing.DesiredStatus.PUBLISH,
        )
        self.assertEqual(self.avito_account.export_revision, 0)


class AvitoListingApprovalConcurrencyTests(TransactionTestCase):
    """Реальная PostgreSQL-проверка двух одновременных approve."""

    def setUp(self):
        if connection.vendor != "postgresql":
            self.fail(
                "Concurrency-контракт MVP должен проверяться на PostgreSQL.",
            )

        self.user = get_user_model().objects.create_user(
            email="approval-concurrency-owner@example.com",
            password="test-password",
        )
        self.workspace = Workspace.objects.create(
            name="Approval concurrency workspace",
            slug="approval-concurrency-workspace",
            owner=self.user,
        )
        self.avito_account = AvitoAccount.objects.create(
            workspace=self.workspace,
            name="Approval concurrency account",
        )
        self.approved_at = timezone.make_aware(
            datetime(2026, 8, 29, 12, 0),
            timezone.get_current_timezone(),
        )
        active_since = timezone.make_aware(
            datetime(2026, 8, 1, 9, 0),
            timezone.get_current_timezone(),
        )
        automation_model = apps.get_model("automations", "Automation")
        run_model = apps.get_model("automations", "AutomationRun")
        result_model = apps.get_model(
            "automations",
            "AvitoListingRunResult",
        )
        decision_model = apps.get_model(
            "automations",
            "AvitoListingDecision",
        )
        self.automation = automation_model.objects.create(
            workspace=self.workspace,
            module_type="avito_listings",
            name="Approval concurrency automation",
            state=automation_model.State.ENABLED,
            created_by=self.user,
            updated_by=self.user,
        )
        self.listing = AvitoListing.objects.create(
            workspace=self.workspace,
            avito_account=self.avito_account,
            source=AvitoListing.Source.AVITO_EXCEL,
            management_status=AvitoListing.ManagementStatus.MANAGED,
            desired_status=AvitoListing.DesiredStatus.PUBLISH,
            active_since=active_since,
            avito_id=f"approval-concurrency-{uuid4()}",
            row_id=f"APPROVAL-CONCURRENCY-{uuid4()}",
            title="Объявление для конкурентного подтверждения",
        )
        self.automation_run = run_model.objects.create(
            automation=self.automation,
            workspace=self.workspace,
            run_kind=run_model.RunKind.EXECUTE,
            trigger=run_model.Trigger.MANUAL,
            execution_mode_snapshot="manual",
            automation_version=self.automation.version,
            automation_name_snapshot=self.automation.name,
            module_type_snapshot=self.automation.module_type,
            status=run_model.Status.WAITING_APPROVAL,
            idempotency_key=f"approval-concurrency-{uuid4()}",
            created_by=self.user,
        )
        action_snapshot = {
            "type": "pause",
            "config": {},
        }
        self.run_result = result_model.objects.create(
            run=self.automation_run,
            workspace=self.workspace,
            avito_account=self.avito_account,
            as_of_date=date(2026, 8, 20),
            condition_snapshot={},
            action_snapshot=action_snapshot,
            pending_approval=1,
        )
        self.decision = decision_model.objects.create(
            run=self.automation_run,
            automation=self.automation,
            workspace=self.workspace,
            avito_account=self.avito_account,
            listing=self.listing,
            listing_id_snapshot=self.listing.id,
            listing_snapshot={"id": self.listing.id},
            automation_version=self.automation.version,
            active_since_snapshot=active_since,
            condition_snapshot={},
            metrics_snapshot=[],
            action_snapshot=action_snapshot,
            expires_at=self.approved_at + timedelta(hours=1),
        )

    def test_second_approve_is_busy_and_action_runs_once(self):
        approval_module = import_module(
            "automations.modules.avito_listings.decision_approval",
        )
        original_apply_action = approval_module.apply_listing_action
        action_started = Event()
        release_action = Event()
        thread_results = Queue()
        action_calls = []
        ready_result = SimpleNamespace(
            decision=self.decision,
            outcome="ready",
            reason=None,
            changed=False,
            as_of_date=date(2026, 8, 28),
            metrics_snapshot=(),
        )

        def blocking_apply_action(**kwargs):
            action_calls.append(kwargs["listing"].id)
            action_started.set()
            if not release_action.wait(timeout=5):
                raise AssertionError(
                    "Первый approve не получил сигнал продолжения.",
                )
            return original_apply_action(**kwargs)

        def approve_in_thread(label):
            close_old_connections()
            try:
                workspace = Workspace.objects.get(id=self.workspace.id)
                user = get_user_model().objects.get(id=self.user.id)
                result = approval_module.approve_decision(
                    workspace=workspace,
                    run_id=self.automation_run.id,
                    decision_id=self.decision.id,
                    approved_by=user,
                    approved_at=self.approved_at,
                )
            except Exception as error:
                thread_results.put((label, "error", error))
            else:
                thread_results.put((label, "result", result))
            finally:
                close_old_connections()

        first_thread = Thread(
            target=approve_in_thread,
            args=("first",),
            daemon=True,
        )
        second_thread = Thread(
            target=approve_in_thread,
            args=("second",),
            daemon=True,
        )

        with patch.object(
                approval_module,
                "recheck_decision_before_approval",
                return_value=ready_result,
        ):
            with patch.object(
                    approval_module,
                    "apply_listing_action",
                    side_effect=blocking_apply_action,
            ):
                first_thread.start()
                try:
                    self.assertTrue(
                        action_started.wait(timeout=5),
                        "Первый approve не дошёл до действия.",
                    )
                    second_thread.start()
                    second_thread.join(timeout=5)
                    self.assertFalse(
                        second_thread.is_alive(),
                        "Второй approve ожидал row lock вместо nowait.",
                    )
                finally:
                    release_action.set()

                first_thread.join(timeout=5)

        self.assertFalse(
            first_thread.is_alive(),
            "Первый approve не завершился после освобождения действия.",
        )
        results_by_label = {
            label: (kind, value)
            for label, kind, value in (
                thread_results.get_nowait(),
                thread_results.get_nowait(),
            )
        }
        first_kind, first_value = results_by_label["first"]
        second_kind, second_value = results_by_label["second"]
        self.assertEqual(first_kind, "result")
        self.assertEqual(first_value.outcome, "effect_pending")
        self.assertEqual(second_kind, "error")
        self.assertIsInstance(
            second_value,
            approval_module.DecisionApprovalError,
        )
        self.assertEqual(second_value.code, "resource_busy")
        self.assertEqual(action_calls, [self.listing.id])

        self.decision.refresh_from_db()
        self.listing.refresh_from_db()
        self.avito_account.refresh_from_db()
        self.assertEqual(self.decision.status, "effect_pending")
        self.assertEqual(
            self.listing.desired_status,
            AvitoListing.DesiredStatus.PAUSE,
        )
        self.assertEqual(self.avito_account.export_revision, 1)


class AvitoListingEffectRecoveryTests(TestCase):
    module_path = (
        "automations.modules.avito_listings.effect_recovery"
    )

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(
            email="effect-recovery-owner@example.com",
            password="test-password",
        )
        cls.workspace = Workspace.objects.create(
            name="Effect recovery workspace",
            slug="effect-recovery-workspace",
            owner=cls.user,
        )
        cls.avito_account = AvitoAccount.objects.create(
            workspace=cls.workspace,
            name="Effect recovery Avito account",
        )
        cls.recovered_at = timezone.make_aware(
            datetime(2026, 8, 28, 12, 0),
            timezone.get_current_timezone(),
        )
        cls.active_since_snapshot = timezone.make_aware(
            datetime(2026, 8, 1, 9, 0),
            timezone.get_current_timezone(),
        )

    def get_recovery_module(self):
        try:
            return import_module(self.module_path)
        except ModuleNotFoundError as error:
            if error.name != self.module_path:
                raise

            self.fail(
                "Добавьте bounded recovery внешнего CSV-эффекта.",
            )

    def set_account_export_state(
            self,
            *,
            export_revision,
            last_exported_revision,
            export_status,
            exporting_revision=None,
            export_error="",
    ):
        self.avito_account.export_revision = export_revision
        self.avito_account.last_exported_revision = (
            last_exported_revision
        )
        self.avito_account.export_status = export_status
        self.avito_account.exporting_revision = exporting_revision
        self.avito_account.export_error = export_error
        self.avito_account.save(
            update_fields=[
                "export_revision",
                "last_exported_revision",
                "export_status",
                "exporting_revision",
                "export_error",
                "updated_at",
            ],
        )

    def create_effect_context(
            self,
            *,
            action_type="pause",
            source=AvitoListing.Source.AVITO_EXCEL,
            required_export_revision=1,
            effect_attempts=0,
            next_effect_retry_at=None,
            target_matches=True,
            run_context=None,
    ):
        automation_model = apps.get_model("automations", "Automation")
        run_model = apps.get_model("automations", "AutomationRun")
        result_model = apps.get_model(
            "automations",
            "AvitoListingRunResult",
        )
        decision_model = apps.get_model(
            "automations",
            "AvitoListingDecision",
        )

        if run_context is None:
            automation = automation_model.objects.create(
                workspace=self.workspace,
                module_type="avito_listings",
                name=f"Effect recovery {uuid4()}",
                state=automation_model.State.ENABLED,
                created_by=self.user,
                updated_by=self.user,
            )
            automation_run = run_model.objects.create(
                automation=automation,
                workspace=self.workspace,
                run_kind=run_model.RunKind.EXECUTE,
                trigger=run_model.Trigger.MANUAL,
                execution_mode_snapshot="manual",
                automation_version=automation.version,
                automation_name_snapshot=automation.name,
                module_type_snapshot=automation.module_type,
                status=run_model.Status.EFFECT_PENDING,
                idempotency_key=f"effect-recovery-{uuid4()}",
                created_by=self.user,
            )
            run_result = result_model.objects.create(
                run=automation_run,
                workspace=self.workspace,
                avito_account=self.avito_account,
                as_of_date=date(2026, 8, 20),
                condition_snapshot={},
                action_snapshot={
                    "type": action_type,
                    "config": {},
                },
            )
        else:
            automation = run_context.automation
            automation_run = run_context.automation_run
            run_result = run_context.run_result

        publication = None
        if source == AvitoListing.Source.SERVICE:
            creative = AdCreative.objects.create(
                workspace=self.workspace,
                source=AdCreative.Source.MANUAL,
                title=f"Effect recovery creative {uuid4()}",
                description="Описание",
                base_data={},
            )
            matching_status = {
                "pause": AdPublication.Status.PAUSED,
                "archive": AdPublication.Status.ARCHIVED,
            }[action_type]
            publication = AdPublication.objects.create(
                workspace=self.workspace,
                avito_account=self.avito_account,
                creative=creative,
                source=AdPublication.Source.MANUAL,
                status=(
                    matching_status
                    if target_matches
                    else AdPublication.Status.ACTIVE
                ),
                row_id=f"EFFECT-{uuid4()}",
                address="Москва",
            )

        desired_status = AvitoListing.DesiredStatus.PUBLISH
        if source == AvitoListing.Source.AVITO_EXCEL and target_matches:
            desired_status = {
                "pause": AvitoListing.DesiredStatus.PAUSE,
                "archive": AvitoListing.DesiredStatus.ARCHIVE,
            }[action_type]

        listing = AvitoListing.objects.create(
            workspace=self.workspace,
            avito_account=self.avito_account,
            publication=publication,
            source=source,
            management_status=AvitoListing.ManagementStatus.MANAGED,
            desired_status=desired_status,
            active_since=None,
            avito_id=f"effect-recovery-{uuid4()}",
            row_id=f"EFFECT-RECOVERY-{uuid4()}",
            title="Объявление с ожидающим CSV-эффектом",
        )
        action_snapshot = {
            "type": action_type,
            "config": {},
        }
        decision = decision_model.objects.create(
            run=automation_run,
            automation=automation,
            workspace=self.workspace,
            avito_account=self.avito_account,
            listing=listing,
            listing_id_snapshot=listing.id,
            listing_snapshot={
                "id": listing.id,
                "avito_id": listing.avito_id,
                "title": listing.title,
            },
            status=decision_model.Status.EFFECT_PENDING,
            automation_version=automation.version,
            active_since_snapshot=self.active_since_snapshot,
            condition_snapshot={},
            metrics_snapshot=[],
            action_snapshot=action_snapshot,
            expires_at=self.recovered_at,
            approved_by=self.user,
            approved_at=self.recovered_at - timedelta(hours=1),
            action_applied_at=self.recovered_at - timedelta(hours=1),
            required_export_revision=required_export_revision,
            effect_attempts=effect_attempts,
            next_effect_retry_at=next_effect_retry_at,
        )
        return SimpleNamespace(
            automation=automation,
            automation_run=automation_run,
            run_result=run_result,
            publication=publication,
            listing=listing,
            decision=decision,
        )

    def recover(self, *, limit=100):
        return self.get_recovery_module().recover_pending_listing_effects(
            recovered_at=self.recovered_at,
            limit=limit,
        )

    def test_completed_revision_finishes_excel_and_service_effects(self):
        excel_context = self.create_effect_context(
            action_type="pause",
            required_export_revision=1,
        )
        service_context = self.create_effect_context(
            action_type="archive",
            source=AvitoListing.Source.SERVICE,
            required_export_revision=2,
        )
        self.set_account_export_state(
            export_revision=2,
            last_exported_revision=2,
            export_status=AvitoAccount.ExportStatus.CLEAN,
        )

        first_result = self.recover()
        repeated_result = self.recover()

        self.assertEqual(first_result.selected, 2)
        self.assertEqual(first_result.completed, 2)
        self.assertEqual(first_result.superseded, 0)
        self.assertEqual(repeated_result.selected, 0)
        for context in (excel_context, service_context):
            with self.subTest(source=context.listing.source):
                context.decision.refresh_from_db()
                context.run_result.refresh_from_db()
                context.automation_run.refresh_from_db()
                self.assertEqual(context.decision.status, "completed")
                self.assertEqual(
                    context.decision.completed_at,
                    self.recovered_at,
                )
                self.assertEqual(
                    context.decision.terminal_at,
                    self.recovered_at,
                )
                self.assertEqual(context.run_result.completed_actions, 1)
                self.assertEqual(
                    context.automation_run.status,
                    context.automation_run.Status.COMPLETED,
                )
                self.assertEqual(
                    context.automation_run.finished_at,
                    self.recovered_at,
                )

    def test_unfinished_export_leaves_effect_pending_without_retry(self):
        context = self.create_effect_context(
            required_export_revision=2,
        )
        self.set_account_export_state(
            export_revision=2,
            last_exported_revision=1,
            exporting_revision=2,
            export_status=AvitoAccount.ExportStatus.EXPORTING,
        )
        recovery_module = self.get_recovery_module()

        with patch.object(
                recovery_module,
                "queue_avito_account_csv_exports",
        ) as queue_exports:
            result = self.recover()

        context.decision.refresh_from_db()
        context.automation_run.refresh_from_db()
        self.assertEqual(result.selected, 1)
        self.assertEqual(result.completed, 0)
        self.assertEqual(result.retries_scheduled, 0)
        self.assertEqual(context.decision.status, "effect_pending")
        self.assertEqual(context.decision.effect_attempts, 0)
        self.assertIsNone(context.decision.next_effect_retry_at)
        self.assertEqual(
            context.automation_run.status,
            context.automation_run.Status.EFFECT_PENDING,
        )
        queue_exports.assert_not_called()

    def test_changed_target_state_marks_effect_superseded(self):
        excel_context = self.create_effect_context(
            action_type="pause",
            required_export_revision=1,
            target_matches=False,
        )
        service_context = self.create_effect_context(
            action_type="archive",
            source=AvitoListing.Source.SERVICE,
            required_export_revision=1,
            target_matches=False,
        )
        self.set_account_export_state(
            export_revision=1,
            last_exported_revision=1,
            export_status=AvitoAccount.ExportStatus.CLEAN,
        )

        result = self.recover()

        self.assertEqual(result.superseded, 2)
        for context in (excel_context, service_context):
            with self.subTest(source=context.listing.source):
                context.decision.refresh_from_db()
                context.run_result.refresh_from_db()
                context.automation_run.refresh_from_db()
                self.assertEqual(context.decision.status, "superseded")
                self.assertEqual(
                    context.decision.terminal_at,
                    self.recovered_at,
                )
                self.assertEqual(context.run_result.completed_actions, 0)
                self.assertEqual(context.run_result.failed_actions, 0)
                self.assertEqual(
                    context.automation_run.status,
                    context.automation_run.Status.COMPLETED,
                )

    def test_failed_export_queues_one_retry_per_account(self):
        first_context = self.create_effect_context(
            required_export_revision=3,
        )
        second_context = self.create_effect_context(
            required_export_revision=4,
        )
        self.set_account_export_state(
            export_revision=4,
            last_exported_revision=2,
            export_status=AvitoAccount.ExportStatus.ERROR,
            export_error="Тестовая ошибка CSV",
        )
        recovery_module = self.get_recovery_module()

        with patch.object(
                recovery_module,
                "queue_avito_account_csv_exports",
                return_value="queued",
        ) as queue_exports:
            result = self.recover()

        self.assertEqual(result.retries_scheduled, 2)
        self.assertEqual(result.accounts_queued, 1)
        queue_exports.assert_called_once()
        queued_account_ids = queue_exports.call_args.args[0]
        self.assertEqual(set(queued_account_ids), {self.avito_account.id})
        for context in (first_context, second_context):
            context.decision.refresh_from_db()
            context.listing.refresh_from_db()
            self.assertEqual(context.decision.status, "effect_pending")
            self.assertEqual(context.decision.effect_attempts, 1)
            self.assertEqual(
                context.decision.next_effect_retry_at,
                self.recovered_at + timedelta(minutes=10),
            )
            self.assertEqual(
                context.listing.desired_status,
                AvitoListing.DesiredStatus.PAUSE,
            )
        self.avito_account.refresh_from_db()
        self.assertEqual(self.avito_account.export_revision, 4)

    def test_third_failed_retry_finishes_mixed_run_as_partial(self):
        completed_context = self.create_effect_context(
            required_export_revision=2,
        )
        failed_context = self.create_effect_context(
            required_export_revision=3,
            effect_attempts=3,
            run_context=completed_context,
        )
        self.set_account_export_state(
            export_revision=3,
            last_exported_revision=2,
            export_status=AvitoAccount.ExportStatus.ERROR,
            export_error="Третья ошибка CSV",
        )
        recovery_module = self.get_recovery_module()

        with patch.object(
                recovery_module,
                "queue_avito_account_csv_exports",
        ) as queue_exports:
            result = self.recover()

        completed_context.decision.refresh_from_db()
        failed_context.decision.refresh_from_db()
        completed_context.run_result.refresh_from_db()
        completed_context.automation_run.refresh_from_db()
        self.assertEqual(result.completed, 1)
        self.assertEqual(result.failed, 1)
        self.assertEqual(
            completed_context.decision.status,
            "completed",
        )
        self.assertEqual(failed_context.decision.status, "failed")
        self.assertEqual(
            failed_context.decision.error_code,
            "export_failed",
        )
        self.assertNotIn(
            "Третья ошибка CSV",
            failed_context.decision.error_message,
        )
        self.assertEqual(
            failed_context.decision.terminal_at,
            self.recovered_at,
        )
        self.assertEqual(
            completed_context.run_result.completed_actions,
            1,
        )
        self.assertEqual(completed_context.run_result.failed_actions, 1)
        self.assertEqual(
            completed_context.automation_run.status,
            completed_context.automation_run.Status.PARTIAL,
        )
        self.assertEqual(
            completed_context.automation_run.finished_at,
            self.recovered_at,
        )
        queue_exports.assert_not_called()

    def test_invalid_required_revision_fails_without_stopping_batch(self):
        invalid_context = self.create_effect_context(
            required_export_revision=None,
        )
        valid_context = self.create_effect_context(
            required_export_revision=1,
        )
        self.set_account_export_state(
            export_revision=1,
            last_exported_revision=1,
            export_status=AvitoAccount.ExportStatus.CLEAN,
        )

        result = self.recover()

        invalid_context.decision.refresh_from_db()
        valid_context.decision.refresh_from_db()
        self.assertEqual(result.selected, 2)
        self.assertEqual(result.failed, 1)
        self.assertEqual(result.completed, 1)
        self.assertEqual(invalid_context.decision.status, "failed")
        self.assertEqual(
            invalid_context.decision.error_code,
            "invalid_effect_state",
        )
        self.assertTrue(invalid_context.decision.error_message)
        self.assertEqual(valid_context.decision.status, "completed")

    def test_recovery_processes_only_requested_bounded_batch(self):
        contexts = [
            self.create_effect_context(required_export_revision=1)
            for _ in range(3)
        ]
        self.set_account_export_state(
            export_revision=1,
            last_exported_revision=1,
            export_status=AvitoAccount.ExportStatus.CLEAN,
        )

        result = self.recover(limit=2)

        self.assertEqual(result.selected, 2)
        statuses = []
        for context in contexts:
            context.decision.refresh_from_db()
            statuses.append(context.decision.status)
        self.assertEqual(statuses.count("completed"), 2)
        self.assertEqual(statuses.count("effect_pending"), 1)


class AvitoListingActionAdapterTests(TestCase):
    module_path = "automations.modules.avito_listings.actions"

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(
            email="listing-action-adapter@example.com",
            password="test-password",
        )
        cls.workspace = Workspace.objects.create(
            name="Listing action adapter workspace",
            slug="listing-action-adapter-workspace",
            owner=cls.user,
        )
        cls.avito_account = AvitoAccount.objects.create(
            workspace=cls.workspace,
            name="Listing action adapter account",
        )
        cls.active_since = timezone.make_aware(
            datetime(2026, 8, 1, 9, 0),
            timezone.get_current_timezone(),
        )

    def get_actions_module(self):
        try:
            return import_module(self.module_path)
        except ModuleNotFoundError as error:
            if error.name != self.module_path:
                raise

            self.fail(
                "Добавьте адаптер pause/archive для объявлений Avito.",
            )

    def create_service_listing(self):
        suffix = uuid4()
        creative = AdCreative.objects.create(
            workspace=self.workspace,
            source=AdCreative.Source.MANUAL,
            title=f"Service creative {suffix}",
            description="Описание",
            base_data={},
        )
        publication = AdPublication.objects.create(
            workspace=self.workspace,
            avito_account=self.avito_account,
            creative=creative,
            source=AdPublication.Source.MANUAL,
            status=AdPublication.Status.ACTIVE,
            row_id=f"ACTION-{suffix}",
            address="Москва",
        )
        listing = AvitoListing.objects.create(
            workspace=self.workspace,
            avito_account=self.avito_account,
            publication=publication,
            source=AvitoListing.Source.SERVICE,
            management_status=AvitoListing.ManagementStatus.MANAGED,
            desired_status=AvitoListing.DesiredStatus.PUBLISH,
            active_since=self.active_since,
            avito_id=f"service-action-{suffix}",
            title="Service listing",
        )
        return publication, listing

    def create_excel_listing(
            self,
            *,
            management_status=AvitoListing.ManagementStatus.MANAGED,
    ):
        suffix = uuid4()
        return AvitoListing.objects.create(
            workspace=self.workspace,
            avito_account=self.avito_account,
            source=AvitoListing.Source.AVITO_EXCEL,
            management_status=management_status,
            desired_status=AvitoListing.DesiredStatus.PUBLISH,
            active_since=self.active_since,
            avito_id=f"excel-action-{suffix}",
            row_id=f"EXCEL-ACTION-{suffix}",
            title="Excel listing",
        )

    def apply_action(self, *, listing, action_type):
        return self.get_actions_module().apply_listing_action(
            workspace=self.workspace,
            avito_account=self.avito_account,
            listing=listing,
            action_type=action_type,
        )

    def assert_account_export_revision_advanced(self, previous_revision):
        self.avito_account.refresh_from_db()
        self.assertEqual(
            self.avito_account.export_status,
            AvitoAccount.ExportStatus.DIRTY,
        )
        self.assertEqual(
            self.avito_account.export_revision,
            previous_revision + 1,
        )

    def test_pause_and_archive_service_listing_through_publication(self):
        cases = (
            ("pause", AdPublication.Status.PAUSED),
            ("archive", AdPublication.Status.ARCHIVED),
        )

        for action_type, expected_status in cases:
            with self.subTest(action_type=action_type):
                publication, listing = self.create_service_listing()
                self.avito_account.refresh_from_db()
                previous_revision = self.avito_account.export_revision

                result = self.apply_action(
                    listing=listing,
                    action_type=action_type,
                )

                publication.refresh_from_db()
                listing.refresh_from_db()
                self.assertEqual(result.listing_id, listing.id)
                self.assertEqual(result.action_type, action_type)
                self.assertTrue(result.updated)
                self.assertEqual(
                    result.required_export_revision,
                    previous_revision + 1,
                )
                self.assertEqual(publication.status, expected_status)
                self.assertIsNone(listing.active_since)
                self.assert_account_export_revision_advanced(
                    previous_revision,
                )

    def test_pause_and_archive_managed_excel_listing(self):
        cases = (
            ("pause", AvitoListing.DesiredStatus.PAUSE),
            ("archive", AvitoListing.DesiredStatus.ARCHIVE),
        )

        for action_type, expected_status in cases:
            with self.subTest(action_type=action_type):
                listing = self.create_excel_listing()
                self.avito_account.refresh_from_db()
                previous_revision = self.avito_account.export_revision

                result = self.apply_action(
                    listing=listing,
                    action_type=action_type,
                )

                listing.refresh_from_db()
                self.assertEqual(result.listing_id, listing.id)
                self.assertEqual(result.action_type, action_type)
                self.assertTrue(result.updated)
                self.assertEqual(
                    result.required_export_revision,
                    previous_revision + 1,
                )
                self.assertEqual(listing.desired_status, expected_status)
                self.assertIsNone(listing.active_since)
                self.assert_account_export_revision_advanced(
                    previous_revision,
                )

    def test_unknown_action_is_rejected_without_side_effects(self):
        actions_module = self.get_actions_module()
        listing = self.create_excel_listing()
        self.avito_account.refresh_from_db()
        previous_revision = self.avito_account.export_revision
        previous_export_status = self.avito_account.export_status

        with self.assertRaises(
            actions_module.AvitoListingActionError,
        ) as raised:
            self.apply_action(listing=listing, action_type="publish")

        listing.refresh_from_db()
        self.avito_account.refresh_from_db()
        self.assertEqual(raised.exception.code, "unsupported_action")
        self.assertEqual(
            listing.desired_status,
            AvitoListing.DesiredStatus.PUBLISH,
        )
        self.assertEqual(listing.active_since, self.active_since)
        self.assertEqual(
            self.avito_account.export_revision,
            previous_revision,
        )
        self.assertEqual(
            self.avito_account.export_status,
            previous_export_status,
        )

    def test_unmanaged_excel_listing_is_rejected_without_side_effects(self):
        actions_module = self.get_actions_module()
        listing = self.create_excel_listing(
            management_status=AvitoListing.ManagementStatus.OBSERVED,
        )
        self.avito_account.refresh_from_db()
        previous_revision = self.avito_account.export_revision
        previous_export_status = self.avito_account.export_status

        with self.assertRaises(
            actions_module.AvitoListingActionError,
        ) as raised:
            self.apply_action(listing=listing, action_type="pause")

        listing.refresh_from_db()
        self.avito_account.refresh_from_db()
        self.assertEqual(raised.exception.code, "listing_not_actionable")
        self.assertEqual(
            listing.desired_status,
            AvitoListing.DesiredStatus.PUBLISH,
        )
        self.assertEqual(listing.active_since, self.active_since)
        self.assertEqual(
            self.avito_account.export_revision,
            previous_revision,
        )
        self.assertEqual(
            self.avito_account.export_status,
            previous_export_status,
        )

    def test_api_listing_is_rejected_without_side_effects(self):
        actions_module = self.get_actions_module()
        suffix = uuid4()
        listing = AvitoListing.objects.create(
            workspace=self.workspace,
            avito_account=self.avito_account,
            source=AvitoListing.Source.API,
            management_status=AvitoListing.ManagementStatus.MANAGED,
            desired_status=AvitoListing.DesiredStatus.PUBLISH,
            active_since=self.active_since,
            avito_id=f"api-action-{suffix}",
            title="API listing",
        )
        self.avito_account.refresh_from_db()
        previous_revision = self.avito_account.export_revision

        with self.assertRaises(
            actions_module.AvitoListingActionError,
        ) as raised:
            self.apply_action(listing=listing, action_type="archive")

        listing.refresh_from_db()
        self.avito_account.refresh_from_db()
        self.assertEqual(raised.exception.code, "listing_not_actionable")
        self.assertEqual(listing.active_since, self.active_since)
        self.assertEqual(
            self.avito_account.export_revision,
            previous_revision,
        )

    def test_foreign_listing_is_rejected_without_side_effects(self):
        actions_module = self.get_actions_module()
        other_user = get_user_model().objects.create_user(
            email=f"listing-action-other-{uuid4()}@example.com",
            password="test-password",
        )
        other_workspace = Workspace.objects.create(
            name="Other listing action workspace",
            slug=f"other-listing-action-{uuid4()}",
            owner=other_user,
        )
        other_account = AvitoAccount.objects.create(
            workspace=other_workspace,
            name="Other listing action account",
        )
        foreign_listing = AvitoListing.objects.create(
            workspace=other_workspace,
            avito_account=other_account,
            source=AvitoListing.Source.AVITO_EXCEL,
            management_status=AvitoListing.ManagementStatus.MANAGED,
            desired_status=AvitoListing.DesiredStatus.PUBLISH,
            active_since=self.active_since,
            avito_id=f"foreign-action-{uuid4()}",
            title="Foreign listing",
        )

        with self.assertRaises(
            actions_module.AvitoListingActionError,
        ) as raised:
            self.apply_action(
                listing=foreign_listing,
                action_type="pause",
            )

        foreign_listing.refresh_from_db()
        other_account.refresh_from_db()
        self.avito_account.refresh_from_db()
        self.assertEqual(raised.exception.code, "listing_scope_mismatch")
        self.assertEqual(
            foreign_listing.desired_status,
            AvitoListing.DesiredStatus.PUBLISH,
        )
        self.assertEqual(foreign_listing.active_since, self.active_since)
        self.assertEqual(other_account.export_revision, 0)
        self.assertEqual(self.avito_account.export_revision, 0)


class AvitoAutomationAccountStateModelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(
            email="automation-state-owner@example.com",
            password="test-password",
        )
        cls.workspace = Workspace.objects.create(
            name="Automation state workspace",
            slug="automation-state-workspace",
            owner=cls.user,
        )
        cls.avito_account = AvitoAccount.objects.create(
            workspace=cls.workspace,
            name="State Avito account",
        )

    def get_account_state_model(self):
        try:
            account_state_model = apps.get_model(
                "automations",
                "AvitoAutomationAccountState",
            )
        except LookupError:
            account_state_model = None

        self.assertIsNotNone(
            account_state_model,
            (
                "The automations app must define the "
                "AvitoAutomationAccountState model."
            ),
        )
        return account_state_model

    def create_account_state(self, **overrides):
        account_state_model = self.get_account_state_model()
        values = {
            "workspace": self.workspace,
            "avito_account": self.avito_account,
        }
        values.update(overrides)
        return account_state_model.objects.create(**values)

    def test_new_account_state_starts_idle_without_lease(self):
        account_state = self.create_account_state()

        self.assertEqual(account_state.status, "idle")
        self.assertIsNone(account_state.run_token)
        self.assertIsNone(account_state.heartbeat_at)
        self.assertIsNone(account_state.lease_expires_at)
        self.assertIsNotNone(account_state.created_at)
        self.assertIsNotNone(account_state.updated_at)

    def test_running_state_requires_complete_finite_lease(self):
        heartbeat_at = timezone.now()
        lease_expires_at = heartbeat_at + timedelta(minutes=10)
        run_token = uuid4()

        account_state = self.create_account_state(
            status="running",
            run_token=run_token,
            heartbeat_at=heartbeat_at,
            lease_expires_at=lease_expires_at,
        )

        self.assertEqual(account_state.run_token, run_token)
        self.assertEqual(account_state.heartbeat_at, heartbeat_at)
        self.assertEqual(account_state.lease_expires_at, lease_expires_at)

    def test_only_one_automation_state_is_allowed_per_account(self):
        self.create_account_state()

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self.create_account_state()

    def test_incomplete_or_non_forward_lease_state_is_rejected_by_database(self):
        heartbeat_at = timezone.now()
        lease_expires_at = heartbeat_at + timedelta(minutes=10)
        run_token = uuid4()
        invalid_states = (
            {"status": "idle", "run_token": run_token},
            {"status": "idle", "heartbeat_at": heartbeat_at},
            {"status": "idle", "lease_expires_at": lease_expires_at},
            {
                "status": "running",
                "heartbeat_at": heartbeat_at,
                "lease_expires_at": lease_expires_at,
            },
            {
                "status": "running",
                "run_token": run_token,
                "lease_expires_at": lease_expires_at,
            },
            {
                "status": "running",
                "run_token": run_token,
                "heartbeat_at": heartbeat_at,
            },
            {
                "status": "running",
                "run_token": run_token,
                "heartbeat_at": heartbeat_at,
                "lease_expires_at": heartbeat_at,
            },
        )
        for invalid_state in invalid_states:
            with self.subTest(state=invalid_state):
                with self.assertRaises(IntegrityError):
                    with transaction.atomic():
                        self.create_account_state(**invalid_state)

    def test_account_deletion_cascades_ephemeral_lease_state(self):
        account_state = self.create_account_state()
        account_state_id = account_state.id
        account_state_model = self.get_account_state_model()

        self.avito_account.delete()

        self.assertFalse(
            account_state_model.objects.filter(id=account_state_id).exists()
        )

    def test_expired_lease_recovery_index_is_declared(self):
        account_state_model = self.get_account_state_model()
        declared_indexes = {
            tuple(index.fields) for index in account_state_model._meta.indexes
        }

        self.assertIn(("status", "lease_expires_at", "id"), declared_indexes)


class AutomationCrudApiTests(TestCase):
    list_url = "/api/automations/"
    catalog_url = "/api/automations/catalog/"

    @classmethod
    def setUpTestData(cls):
        user_model = get_user_model()
        cls.owner = user_model.objects.create_user(
            email="automation-api-owner@example.com",
            password="test-password",
        )
        cls.admin = user_model.objects.create_user(
            email="automation-api-admin@example.com",
            password="test-password",
        )
        cls.manager = user_model.objects.create_user(
            email="automation-api-manager@example.com",
            password="test-password",
        )
        cls.foreign_owner = user_model.objects.create_user(
            email="automation-api-foreign-owner@example.com",
            password="test-password",
        )
        cls.workspace = Workspace.objects.create(
            name="Automation API workspace",
            slug="automation-api-workspace",
            owner=cls.owner,
        )
        cls.foreign_workspace = Workspace.objects.create(
            name="Foreign automation API workspace",
            slug="foreign-automation-api-workspace",
            owner=cls.foreign_owner,
        )
        memberships = (
            (
                cls.workspace,
                cls.owner,
                WorkspaceMembership.Role.OWNER,
            ),
            (
                cls.workspace,
                cls.admin,
                WorkspaceMembership.Role.ADMIN,
            ),
            (
                cls.workspace,
                cls.manager,
                WorkspaceMembership.Role.MANAGER,
            ),
            (
                cls.foreign_workspace,
                cls.foreign_owner,
                WorkspaceMembership.Role.OWNER,
            ),
            (
                cls.foreign_workspace,
                cls.owner,
                WorkspaceMembership.Role.VIEWER,
            ),
        )
        for workspace, user, role in memberships:
            WorkspaceMembership.objects.create(
                workspace=workspace,
                user=user,
                role=role,
                status=WorkspaceMembership.Status.ACTIVE,
            )

        cls.avito_account = AvitoAccount.objects.create(
            workspace=cls.workspace,
            name="Automation API account",
        )
        cls.foreign_account = AvitoAccount.objects.create(
            workspace=cls.foreign_workspace,
            name="Foreign automation API account",
        )

    def build_config(
            self,
            *,
            avito_account_id=None,
            action_type="pause",
    ):
        return {
            "avito_account_id": (
                avito_account_id or self.avito_account.id
            ),
            "condition_tree": build_condition_tree({
                "type": "condition",
                "metric": "contacts",
                "aggregation": "sum",
                "window_days": 10,
                "comparator": "lt",
                "value": 10,
            }),
            "action": {
                "type": action_type,
                "config": {},
            },
            "max_actions_per_run": 10,
            "approval_ttl_minutes": 1440,
        }

    def build_payload(self, **overrides):
        payload = {
            "name": "Приостановить объявления без контактов",
            "module_type": "avito_listings",
            "config": self.build_config(),
        }
        payload.update(overrides)
        return payload

    def client_for(self, user):
        client = APIClient()
        client.force_authenticate(user)
        return client

    def workspace_headers(self):
        return {
            "HTTP_X_WORKSPACE_ID": str(self.workspace.id),
        }

    def create_automation(
            self,
            *,
            workspace=None,
            actor=None,
            name="Тестовая автоматизация",
            config=None,
    ):
        service = import_module(
            "automations.services.automation_management",
        )
        target_workspace = workspace or self.workspace
        target_actor = actor or self.owner
        return service.create_automation(
            workspace=target_workspace,
            actor=target_actor,
            name=name,
            module_type="avito_listings",
            config=config or self.build_config(),
        )

    def create_completed_preview(self, automation):
        run_model = apps.get_model("automations", "AutomationRun")
        result_model = apps.get_model(
            "automations",
            "AvitoListingRunResult",
        )
        run = run_model.objects.create(
            automation=automation,
            workspace=automation.workspace,
            run_kind=run_model.RunKind.PREVIEW,
            trigger=run_model.Trigger.MANUAL,
            execution_mode_snapshot="manual",
            automation_version=automation.version,
            automation_name_snapshot=automation.name,
            module_type_snapshot=automation.module_type,
            status=run_model.Status.COMPLETED,
            idempotency_key=f"api-preview-{uuid4()}",
            created_by=self.owner,
        )
        result_model.objects.create(
            run=run,
            workspace=automation.workspace,
            avito_account=automation.avito_listing_config.avito_account,
            as_of_date=date(2026, 8, 30),
            condition_snapshot=(
                automation.avito_listing_config.condition_tree
            ),
            action_snapshot={
                "type": automation.avito_listing_config.action_type,
                "config": automation.avito_listing_config.action_config,
            },
        )
        return run

    def test_owner_creates_and_reads_automation_and_admin_updates_it(self):
        owner_client = self.client_for(self.owner)

        create_response = owner_client.post(
            self.list_url,
            data=self.build_payload(),
            format="json",
            **self.workspace_headers(),
        )

        self.assertEqual(create_response.status_code, 201)
        automation_id = create_response.data["id"]
        self.assertEqual(create_response.data["state"], "draft")
        self.assertEqual(create_response.data["execution_mode"], "manual")
        self.assertEqual(create_response.data["version"], 1)
        self.assertEqual(
            create_response.data["created_by"],
            self.owner.id,
        )
        self.assertEqual(
            create_response.data["updated_by"],
            self.owner.id,
        )
        self.assertEqual(
            create_response.data["config"],
            self.build_config(),
        )
        self.assertIn("created_at", create_response.data)
        self.assertIn("updated_at", create_response.data)

        detail_response = owner_client.get(
            f"{self.list_url}{automation_id}/",
            **self.workspace_headers(),
        )
        self.assertEqual(detail_response.status_code, 200)
        self.assertEqual(detail_response.data, create_response.data)

        changed_config = self.build_config(action_type="archive")
        admin_client = self.client_for(self.admin)
        update_response = admin_client.patch(
            f"{self.list_url}{automation_id}/",
            data={
                "config": changed_config,
            },
            format="json",
            **self.workspace_headers(),
        )

        self.assertEqual(update_response.status_code, 200)
        self.assertEqual(update_response.data["state"], "draft")
        self.assertEqual(update_response.data["version"], 2)
        self.assertEqual(update_response.data["config"], changed_config)
        self.assertEqual(update_response.data["updated_by"], self.admin.id)

        automation = apps.get_model(
            "automations",
            "Automation",
        ).objects.get(id=automation_id)
        self.create_completed_preview(automation)

        enable_response = admin_client.patch(
            f"{self.list_url}{automation_id}/",
            data={
                "name": "Архивировать объявления без контактов",
                "state": "enabled",
            },
            format="json",
            **self.workspace_headers(),
        )

        self.assertEqual(enable_response.status_code, 200)
        self.assertEqual(enable_response.data["state"], "enabled")
        self.assertEqual(enable_response.data["version"], 2)

    def test_enable_requires_completed_preview_of_current_version(self):
        automation = self.create_automation()
        client = self.client_for(self.admin)

        blocked_response = client.patch(
            f"{self.list_url}{automation.id}/",
            data={"state": "enabled"},
            format="json",
            **self.workspace_headers(),
        )

        self.assertEqual(blocked_response.status_code, 409)
        self.assertEqual(
            blocked_response.data["code"],
            "preview_required",
        )
        automation.refresh_from_db()
        self.assertEqual(automation.state, "draft")

        self.create_completed_preview(automation)
        enabled_response = client.patch(
            f"{self.list_url}{automation.id}/",
            data={"state": "enabled"},
            format="json",
            **self.workspace_headers(),
        )

        self.assertEqual(enabled_response.status_code, 200)
        self.assertEqual(enabled_response.data["state"], "enabled")

    def test_delete_soft_archives_and_hides_automation(self):
        automation = self.create_automation()
        client = self.client_for(self.admin)

        response = client.delete(
            f"{self.list_url}{automation.id}/",
            **self.workspace_headers(),
        )

        self.assertEqual(response.status_code, 204)
        automation.refresh_from_db()
        self.assertEqual(automation.state, "archived")
        self.assertIsNotNone(automation.archived_at)
        self.assertEqual(automation.updated_by, self.admin)
        self.assertEqual(
            client.get(
                f"{self.list_url}{automation.id}/",
                **self.workspace_headers(),
            ).status_code,
            404,
        )

    def test_catalog_exposes_only_safe_registered_module_payloads(self):
        response = self.client_for(self.owner).get(
            self.catalog_url,
            **self.workspace_headers(),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data["modules"]), 1)
        module = response.data["modules"][0]
        self.assertEqual(module["module_type"], "avito_listings")
        self.assertEqual(
            {action["code"] for action in module["actions"]},
            {"pause", "archive"},
        )
        serialized = json.dumps(response.data, ensure_ascii=False)
        self.assertNotIn("import_path", serialized)
        self.assertNotIn("callable", serialized)

    def test_write_api_rejects_unknown_read_only_and_invalid_fields(self):
        client = self.client_for(self.owner)
        invalid_payload = self.build_payload(extra="unexpected")

        unknown_response = client.post(
            self.list_url,
            data=invalid_payload,
            format="json",
            **self.workspace_headers(),
        )

        self.assertEqual(unknown_response.status_code, 400)
        self.assertIn("extra", unknown_response.data)

        invalid_action = self.build_payload(
            config=self.build_config(action_type="delete"),
        )
        action_response = client.post(
            self.list_url,
            data=invalid_action,
            format="json",
            **self.workspace_headers(),
        )
        self.assertEqual(action_response.status_code, 400)
        self.assertEqual(action_response.data["code"], "invalid_action")

        automation = self.create_automation()
        read_only_response = client.patch(
            f"{self.list_url}{automation.id}/",
            data={"module_type": "messages"},
            format="json",
            **self.workspace_headers(),
        )
        self.assertEqual(read_only_response.status_code, 400)
        self.assertIn("module_type", read_only_response.data)

    def test_api_requires_authentication_and_manage_permission(self):
        unauthenticated_response = APIClient().get(
            self.list_url,
            **self.workspace_headers(),
        )
        self.assertEqual(unauthenticated_response.status_code, 401)

        manager_response = self.client_for(self.manager).get(
            self.list_url,
            **self.workspace_headers(),
        )
        self.assertEqual(manager_response.status_code, 403)

    def test_api_enforces_workspace_scope_and_explicit_workspace_header(self):
        local_automation = self.create_automation(name="Local")
        foreign_automation = self.create_automation(
            workspace=self.foreign_workspace,
            actor=self.foreign_owner,
            name="Foreign",
            config=self.build_config(
                avito_account_id=self.foreign_account.id,
            ),
        )
        client = self.client_for(self.owner)

        list_response = client.get(
            self.list_url,
            **self.workspace_headers(),
        )
        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(list_response.data["count"], 1)
        self.assertEqual(
            [item["id"] for item in list_response.data["results"]],
            [local_automation.id],
        )

        foreign_detail = client.get(
            f"{self.list_url}{foreign_automation.id}/",
            **self.workspace_headers(),
        )
        self.assertEqual(foreign_detail.status_code, 404)

        foreign_account_response = client.post(
            self.list_url,
            data=self.build_payload(
                config=self.build_config(
                    avito_account_id=self.foreign_account.id,
                ),
            ),
            format="json",
            **self.workspace_headers(),
        )
        self.assertEqual(foreign_account_response.status_code, 400)
        self.assertEqual(
            foreign_account_response.data["code"],
            "avito_account_not_found",
        )

        missing_header = client.get(self.list_url)
        self.assertEqual(missing_header.status_code, 400)
        self.assertIn("workspace", missing_header.data)

    def test_list_is_paginated_with_bounded_default_page_size(self):
        for index in range(21):
            self.create_automation(name=f"Automation {index:02d}")

        response = self.client_for(self.owner).get(
            self.list_url,
            **self.workspace_headers(),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 21)
        self.assertEqual(len(response.data["results"]), 20)
        self.assertIsNotNone(response.data["next"])
        self.assertIsNone(response.data["previous"])


class AutomationRunApiTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        user_model = get_user_model()
        cls.owner = user_model.objects.create_user(
            email="automation-run-api-owner@example.com",
            password="test-password",
        )
        cls.admin = user_model.objects.create_user(
            email="automation-run-api-admin@example.com",
            password="test-password",
        )
        cls.manager = user_model.objects.create_user(
            email="automation-run-api-manager@example.com",
            password="test-password",
        )
        cls.foreign_owner = user_model.objects.create_user(
            email="automation-run-api-foreign@example.com",
            password="test-password",
        )
        cls.workspace = Workspace.objects.create(
            name="Automation run API workspace",
            slug="automation-run-api-workspace",
            owner=cls.owner,
        )
        cls.foreign_workspace = Workspace.objects.create(
            name="Foreign automation run API workspace",
            slug="foreign-automation-run-api-workspace",
            owner=cls.foreign_owner,
        )
        memberships = (
            (
                cls.workspace,
                cls.owner,
                WorkspaceMembership.Role.OWNER,
            ),
            (
                cls.workspace,
                cls.admin,
                WorkspaceMembership.Role.ADMIN,
            ),
            (
                cls.workspace,
                cls.manager,
                WorkspaceMembership.Role.MANAGER,
            ),
            (
                cls.foreign_workspace,
                cls.foreign_owner,
                WorkspaceMembership.Role.OWNER,
            ),
        )
        for workspace, user, role in memberships:
            WorkspaceMembership.objects.create(
                workspace=workspace,
                user=user,
                role=role,
                status=WorkspaceMembership.Status.ACTIVE,
            )

        cls.avito_account = AvitoAccount.objects.create(
            workspace=cls.workspace,
            name="Automation run API account",
        )
        cls.foreign_account = AvitoAccount.objects.create(
            workspace=cls.foreign_workspace,
            name="Foreign automation run API account",
        )

    def build_config(self, *, avito_account_id=None):
        return {
            "avito_account_id": (
                avito_account_id or self.avito_account.id
            ),
            "condition_tree": build_condition_tree({
                "type": "condition",
                "metric": "contacts",
                "aggregation": "sum",
                "window_days": 10,
                "comparator": "lt",
                "value": 10,
            }),
            "action": {
                "type": "pause",
                "config": {},
            },
            "max_actions_per_run": 10,
            "approval_ttl_minutes": 1440,
        }

    def create_automation(
            self,
            *,
            workspace=None,
            actor=None,
            config=None,
    ):
        service = import_module(
            "automations.services.automation_management",
        )
        return service.create_automation(
            workspace=workspace or self.workspace,
            actor=actor or self.owner,
            name="Automation run API rule",
            module_type="avito_listings",
            config=config or self.build_config(),
        )

    def client_for(self, user):
        client = APIClient()
        client.force_authenticate(user)
        return client

    def headers(self, *, key=None):
        headers = {
            "HTTP_X_WORKSPACE_ID": str(self.workspace.id),
        }
        if key is not None:
            headers["HTTP_IDEMPOTENCY_KEY"] = key
        return headers

    @staticmethod
    def preview_url(automation):
        return f"/api/automations/{automation.id}/preview/"

    @staticmethod
    def run_url(automation):
        return f"/api/automations/{automation.id}/run/"

    def test_preview_returns_accepted_run_and_dispatches_after_commit(self):
        automation = self.create_automation()
        client = self.client_for(self.owner)
        tasks_module = import_module("automations.tasks")

        with patch.object(
                tasks_module.evaluate_automation_run_task,
                "delay",
        ) as delay:
            with self.captureOnCommitCallbacks(execute=True) as callbacks:
                response = client.post(
                    self.preview_url(automation),
                    data={},
                    format="json",
                    **self.headers(key="preview-api-key"),
                )

        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.data["status"], "queued")
        self.assertTrue(response.data["created"])
        self.assertEqual(len(callbacks), 1)

        run = apps.get_model(
            "automations",
            "AutomationRun",
        ).objects.get(id=response.data["run_id"])
        self.assertEqual(run.workspace, self.workspace)
        self.assertEqual(run.automation, automation)
        self.assertEqual(run.run_kind, "preview")
        self.assertEqual(run.created_by, self.owner)
        self.assertEqual(run.idempotency_key, "preview-api-key")
        self.assertTrue(hasattr(run, "avito_listing_result"))
        delay.assert_called_once_with(run.id)

    def test_repeated_normalized_key_returns_same_run(self):
        automation = self.create_automation()
        client = self.client_for(self.owner)

        first = client.post(
            self.preview_url(automation),
            data={},
            format="json",
            **self.headers(key="  repeated-api-key  "),
        )
        repeated = client.post(
            self.preview_url(automation),
            data={},
            format="json",
            **self.headers(key="repeated-api-key"),
        )

        self.assertEqual(first.status_code, 202)
        self.assertEqual(repeated.status_code, 202)
        self.assertTrue(first.data["created"])
        self.assertFalse(repeated.data["created"])
        self.assertEqual(repeated.data["run_id"], first.data["run_id"])
        self.assertEqual(
            apps.get_model(
                "automations",
                "AutomationRun",
            ).objects.count(),
            1,
        )

    def test_admin_starts_manual_execute_only_for_enabled_automation(self):
        automation = self.create_automation()
        automation.state = "enabled"
        automation.save(update_fields=["state", "updated_at"])

        response = self.client_for(self.admin).post(
            self.run_url(automation),
            data={},
            format="json",
            **self.headers(key="manual-api-key"),
        )

        self.assertEqual(response.status_code, 202)
        self.assertTrue(response.data["created"])
        run = apps.get_model(
            "automations",
            "AutomationRun",
        ).objects.get(id=response.data["run_id"])
        self.assertEqual(run.run_kind, "execute")
        self.assertEqual(run.status, "queued")
        self.assertEqual(run.created_by, self.admin)

    def test_run_api_maps_invalid_key_state_and_open_run_conflict(self):
        automation = self.create_automation()
        client = self.client_for(self.owner)

        for key in (None, "   ", "x" * 129):
            with self.subTest(key=key):
                response = client.post(
                    self.preview_url(automation),
                    data={},
                    format="json",
                    **self.headers(key=key),
                )
                self.assertEqual(response.status_code, 400)
                self.assertEqual(
                    response.data["code"],
                    "invalid_idempotency_key",
                )

        disabled_execute = client.post(
            self.run_url(automation),
            data={},
            format="json",
            **self.headers(key="disabled-execute"),
        )
        self.assertEqual(disabled_execute.status_code, 409)
        self.assertEqual(
            disabled_execute.data["code"],
            "invalid_automation_state",
        )

        first = client.post(
            self.preview_url(automation),
            data={},
            format="json",
            **self.headers(key="first-open-preview"),
        )
        conflict = client.post(
            self.preview_url(automation),
            data={},
            format="json",
            **self.headers(key="second-open-preview"),
        )

        self.assertEqual(first.status_code, 202)
        self.assertEqual(conflict.status_code, 409)
        self.assertEqual(
            conflict.data["code"],
            "open_preview_conflict",
        )
        self.assertEqual(
            conflict.data["open_run_id"],
            first.data["run_id"],
        )

    def test_run_api_rejects_request_body_fields(self):
        automation = self.create_automation()

        response = self.client_for(self.owner).post(
            self.preview_url(automation),
            data={"force": True},
            format="json",
            **self.headers(key="unexpected-body"),
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("force", response.data)
        self.assertFalse(
            apps.get_model(
                "automations",
                "AutomationRun",
            ).objects.exists(),
        )

    def test_run_api_enforces_permission_and_workspace_scope(self):
        automation = self.create_automation()
        foreign_automation = self.create_automation(
            workspace=self.foreign_workspace,
            actor=self.foreign_owner,
            config=self.build_config(
                avito_account_id=self.foreign_account.id,
            ),
        )

        forbidden = self.client_for(self.manager).post(
            self.preview_url(automation),
            data={},
            format="json",
            **self.headers(key="manager-preview"),
        )
        self.assertEqual(forbidden.status_code, 403)

        foreign = self.client_for(self.owner).post(
            self.preview_url(foreign_automation),
            data={},
            format="json",
            **self.headers(key="foreign-preview"),
        )
        self.assertEqual(foreign.status_code, 404)
        self.assertEqual(foreign.data["code"], "automation_not_found")


class AutomationRunJournalApiTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        user_model = get_user_model()
        cls.owner = user_model.objects.create_user(
            email="automation-journal-owner@example.com",
            password="test-password",
        )
        cls.manager = user_model.objects.create_user(
            email="automation-journal-manager@example.com",
            password="test-password",
        )
        cls.foreign_owner = user_model.objects.create_user(
            email="automation-journal-foreign@example.com",
            password="test-password",
        )
        cls.workspace = Workspace.objects.create(
            name="Automation journal workspace",
            slug="automation-journal-workspace",
            owner=cls.owner,
        )
        cls.foreign_workspace = Workspace.objects.create(
            name="Foreign automation journal workspace",
            slug="foreign-automation-journal-workspace",
            owner=cls.foreign_owner,
        )
        memberships = (
            (
                cls.workspace,
                cls.owner,
                WorkspaceMembership.Role.OWNER,
            ),
            (
                cls.workspace,
                cls.manager,
                WorkspaceMembership.Role.MANAGER,
            ),
            (
                cls.foreign_workspace,
                cls.foreign_owner,
                WorkspaceMembership.Role.OWNER,
            ),
        )
        for workspace, user, role in memberships:
            WorkspaceMembership.objects.create(
                workspace=workspace,
                user=user,
                role=role,
                status=WorkspaceMembership.Status.ACTIVE,
            )

        cls.avito_account = AvitoAccount.objects.create(
            workspace=cls.workspace,
            name="Automation journal account",
        )
        cls.foreign_account = AvitoAccount.objects.create(
            workspace=cls.foreign_workspace,
            name="Foreign automation journal account",
        )

    def build_config(self, *, avito_account_id=None):
        return {
            "avito_account_id": (
                avito_account_id or self.avito_account.id
            ),
            "condition_tree": build_condition_tree({
                "type": "condition",
                "metric": "contacts",
                "aggregation": "sum",
                "window_days": 10,
                "comparator": "lt",
                "value": 10,
            }),
            "action": {
                "type": "pause",
                "config": {},
            },
            "max_actions_per_run": 10,
            "approval_ttl_minutes": 1440,
        }

    def create_automation(
            self,
            *,
            workspace=None,
            actor=None,
            config=None,
            name="Automation journal rule",
    ):
        service = import_module(
            "automations.services.automation_management",
        )
        return service.create_automation(
            workspace=workspace or self.workspace,
            actor=actor or self.owner,
            name=name,
            module_type="avito_listings",
            config=config or self.build_config(),
        )

    def create_run(
            self,
            *,
            automation,
            workspace=None,
            avito_account=None,
            actor=None,
            status="completed",
            run_kind="preview",
            error_code="",
            error_message="",
            retry_count=0,
            checked=12,
    ):
        run_model = apps.get_model("automations", "AutomationRun")
        result_model = apps.get_model(
            "automations",
            "AvitoListingRunResult",
        )
        target_workspace = workspace or self.workspace
        target_account = avito_account or self.avito_account
        finished_at = (
            timezone.now()
            if status in {
                "completed",
                "partial",
                "failed",
                "cancelled",
            }
            else None
        )
        run = run_model.objects.create(
            automation=automation,
            workspace=target_workspace,
            run_kind=run_kind,
            trigger="manual",
            execution_mode_snapshot="manual",
            automation_version=automation.version,
            automation_name_snapshot=automation.name,
            module_type_snapshot=automation.module_type,
            status=status,
            idempotency_key=f"journal-{uuid4()}",
            retry_count=retry_count,
            started_at=timezone.now(),
            finished_at=finished_at,
            error_code=error_code,
            error_message=error_message,
            created_by=actor or self.owner,
        )
        result_model.objects.create(
            run=run,
            workspace=target_workspace,
            avito_account=target_account,
            as_of_date=date(2026, 8, 28),
            max_actions_per_run_snapshot=10,
            approval_ttl_minutes_snapshot=1440,
            target_max_id_snapshot=500,
            condition_snapshot=self.build_config()["condition_tree"],
            action_snapshot={"type": "pause", "config": {}},
            examples_snapshot=[
                {
                    "listing_id": 101,
                    "title": "Безопасный пример",
                    "metrics": [],
                    "matched": True,
                },
            ],
            checked=checked,
            ineligible=2,
            insufficient_coverage=3,
            not_matched=4,
            matched=3,
            deferred_by_run_limit=1,
            pending_approval=0,
            completed_actions=2,
            failed_actions=1,
        )
        return run

    def client_for(self, user):
        client = APIClient()
        client.force_authenticate(user)
        return client

    def headers(self):
        return {
            "HTTP_X_WORKSPACE_ID": str(self.workspace.id),
        }

    @staticmethod
    def list_url(automation):
        return f"/api/automations/{automation.id}/runs/"

    @staticmethod
    def detail_url(run):
        return f"/api/automation-runs/{run.id}/"

    @staticmethod
    def decisions_url(run):
        return f"/api/automation-runs/{run.id}/decisions/"

    def create_decision(
            self,
            *,
            run,
            index,
            status="pending_approval",
            error_code="",
            error_message="",
            required_export_revision=None,
    ):
        decision_model = apps.get_model(
            "automations",
            "AvitoListingDecision",
        )
        run_result = run.avito_listing_result
        return decision_model.objects.create(
            run=run,
            automation=run.automation,
            workspace=run.workspace,
            avito_account=run_result.avito_account,
            listing=None,
            listing_id_snapshot=1000 + index,
            listing_snapshot={
                "avito_id": f"journal-avito-{index}",
                "title": f"Journal listing {index}",
            },
            status=status,
            automation_version=run.automation_version,
            active_since_snapshot=(
                timezone.now() - timedelta(days=20)
            ),
            condition_snapshot=self.build_config()["condition_tree"],
            metrics_snapshot=[
                {
                    "metric": "contacts",
                    "aggregation": "sum",
                    "window_days": 10,
                    "date_from": "2026-08-18",
                    "date_to": "2026-08-27",
                    "value": index,
                },
            ],
            action_snapshot={"type": "pause", "config": {}},
            expires_at=timezone.now() + timedelta(hours=24),
            required_export_revision=required_export_revision,
            error_code=error_code,
            error_message=error_message,
        )

    def test_run_list_is_paginated_lightweight_and_has_no_n_plus_one(self):
        automation = self.create_automation()
        runs = [
            self.create_run(
                automation=automation,
                checked=index,
            )
            for index in range(21)
        ]
        client = self.client_for(self.owner)

        with CaptureQueriesContext(connection) as queries:
            response = client.get(
                self.list_url(automation),
                **self.headers(),
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 21)
        self.assertEqual(len(response.data["results"]), 20)
        self.assertEqual(response.data["results"][0]["id"], runs[-1].id)
        self.assertLessEqual(len(queries), 5)

        item = response.data["results"][0]
        self.assertEqual(item["kind"], "preview")
        self.assertEqual(item["automation_id"], automation.id)
        self.assertEqual(item["result"]["checked"], 20)
        self.assertNotIn("condition_snapshot", item["result"])
        self.assertNotIn("action_snapshot", item["result"])
        self.assertNotIn("examples_snapshot", item["result"])
        self.assertNotIn("idempotency_key", item)
        self.assertNotIn("run_token", item)
        self.assertNotIn("heartbeat_at", item)

    def test_run_detail_returns_safe_snapshots_counters_and_error(self):
        automation = self.create_automation()
        run = self.create_run(
            automation=automation,
            status="failed",
            error_code="internal_error",
            error_message="Безопасное сообщение об ошибке.",
            retry_count=2,
        )

        response = self.client_for(self.owner).get(
            self.detail_url(run),
            **self.headers(),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["id"], run.id)
        self.assertEqual(response.data["status"], "failed")
        self.assertEqual(response.data["retry_count"], 2)
        self.assertEqual(
            response.data["error"],
            {
                "code": "internal_error",
                "message": "Безопасное сообщение об ошибке.",
            },
        )
        result = response.data["result"]
        self.assertEqual(result["avito_account_id"], self.avito_account.id)
        self.assertEqual(result["as_of_date"], "2026-08-28")
        self.assertEqual(result["checked"], 12)
        self.assertEqual(
            result["condition_snapshot"],
            self.build_config()["condition_tree"],
        )
        self.assertEqual(
            result["action_snapshot"],
            {"type": "pause", "config": {}},
        )
        self.assertEqual(len(result["examples_snapshot"]), 1)
        self.assertNotIn("idempotency_key", response.data)
        self.assertNotIn("run_token", response.data)
        self.assertNotIn("heartbeat_at", response.data)

    def test_decision_list_is_paginated_snapshot_based_and_has_no_n_plus_one(
            self,
    ):
        automation = self.create_automation()
        run = self.create_run(
            automation=automation,
            run_kind="execute",
        )
        decisions = [
            self.create_decision(
                run=run,
                index=index,
            )
            for index in range(21)
        ]

        with CaptureQueriesContext(connection) as queries:
            response = self.client_for(self.owner).get(
                self.decisions_url(run),
                **self.headers(),
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 21)
        self.assertEqual(len(response.data["results"]), 20)
        self.assertEqual(
            response.data["results"][0]["id"],
            decisions[-1].id,
        )
        self.assertLessEqual(len(queries), 5)

        item = response.data["results"][0]
        self.assertEqual(item["run_id"], run.id)
        self.assertEqual(item["automation_id"], automation.id)
        self.assertEqual(item["avito_account_id"], self.avito_account.id)
        self.assertEqual(item["listing_id"], 1020)
        self.assertEqual(
            item["listing"],
            {
                "avito_id": "journal-avito-20",
                "title": "Journal listing 20",
            },
        )
        self.assertEqual(item["metrics"][0]["value"], 20)
        self.assertEqual(
            item["action"],
            {"type": "pause", "config": {}},
        )
        self.assertIsNone(item["error"])
        self.assertNotIn("condition_snapshot", item)
        self.assertNotIn("workspace", item)

    def test_decision_list_keeps_terminal_audit_after_listing_deletion(self):
        automation = self.create_automation()
        run = self.create_run(
            automation=automation,
            run_kind="execute",
        )
        decision = self.create_decision(
            run=run,
            index=1,
            status="failed",
            error_code="export_failed",
            error_message="Не удалось подтвердить CSV revision.",
            required_export_revision=7,
        )
        decision.effect_attempts = 3
        decision.terminal_at = timezone.now()
        decision.save(
            update_fields=[
                "effect_attempts",
                "terminal_at",
                "updated_at",
            ],
        )

        response = self.client_for(self.owner).get(
            self.decisions_url(run),
            **self.headers(),
        )

        self.assertEqual(response.status_code, 200)
        item = response.data["results"][0]
        self.assertEqual(item["status"], "failed")
        self.assertEqual(item["listing_id"], 1001)
        self.assertEqual(item["listing"]["title"], "Journal listing 1")
        self.assertEqual(item["required_export_revision"], 7)
        self.assertEqual(item["effect_attempts"], 3)
        self.assertIsNotNone(item["terminal_at"])
        self.assertEqual(
            item["error"],
            {
                "code": "export_failed",
                "message": "Не удалось подтвердить CSV revision.",
            },
        )

    def test_run_journal_enforces_permission_and_workspace_scope(self):
        automation = self.create_automation()
        run = self.create_run(automation=automation)
        foreign_automation = self.create_automation(
            workspace=self.foreign_workspace,
            actor=self.foreign_owner,
            config=self.build_config(
                avito_account_id=self.foreign_account.id,
            ),
            name="Foreign automation journal rule",
        )
        foreign_run = self.create_run(
            automation=foreign_automation,
            workspace=self.foreign_workspace,
            avito_account=self.foreign_account,
            actor=self.foreign_owner,
        )

        manager_client = self.client_for(self.manager)
        self.assertEqual(
            manager_client.get(
                self.list_url(automation),
                **self.headers(),
            ).status_code,
            403,
        )
        self.assertEqual(
            manager_client.get(
                self.detail_url(run),
                **self.headers(),
            ).status_code,
            403,
        )
        self.assertEqual(
            manager_client.get(
                self.decisions_url(run),
                **self.headers(),
            ).status_code,
            403,
        )

        owner_client = self.client_for(self.owner)
        self.assertEqual(
            owner_client.get(
                self.list_url(foreign_automation),
                **self.headers(),
            ).status_code,
            404,
        )
        self.assertEqual(
            owner_client.get(
                self.detail_url(foreign_run),
                **self.headers(),
            ).status_code,
            404,
        )
        self.assertEqual(
            owner_client.get(
                self.decisions_url(foreign_run),
                **self.headers(),
            ).status_code,
            404,
        )


class AutomationDecisionCommandApiTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        user_model = get_user_model()
        cls.owner = user_model.objects.create_user(
            email="automation-command-owner@example.com",
            password="test-password",
        )
        cls.admin = user_model.objects.create_user(
            email="automation-command-admin@example.com",
            password="test-password",
        )
        cls.manager = user_model.objects.create_user(
            email="automation-command-manager@example.com",
            password="test-password",
        )
        cls.foreign_owner = user_model.objects.create_user(
            email="automation-command-foreign@example.com",
            password="test-password",
        )
        cls.workspace = Workspace.objects.create(
            name="Automation command workspace",
            slug="automation-command-workspace",
            owner=cls.owner,
        )
        cls.foreign_workspace = Workspace.objects.create(
            name="Foreign automation command workspace",
            slug="foreign-automation-command-workspace",
            owner=cls.foreign_owner,
        )
        memberships = (
            (
                cls.workspace,
                cls.owner,
                WorkspaceMembership.Role.OWNER,
            ),
            (
                cls.workspace,
                cls.admin,
                WorkspaceMembership.Role.ADMIN,
            ),
            (
                cls.workspace,
                cls.manager,
                WorkspaceMembership.Role.MANAGER,
            ),
            (
                cls.foreign_workspace,
                cls.foreign_owner,
                WorkspaceMembership.Role.OWNER,
            ),
        )
        for workspace, user, role in memberships:
            WorkspaceMembership.objects.create(
                workspace=workspace,
                user=user,
                role=role,
                status=WorkspaceMembership.Status.ACTIVE,
            )

        cls.avito_account = AvitoAccount.objects.create(
            workspace=cls.workspace,
            name="Automation command account",
        )
        cls.foreign_account = AvitoAccount.objects.create(
            workspace=cls.foreign_workspace,
            name="Foreign automation command account",
        )
        cls.condition_snapshot = build_condition_tree({
            "type": "condition",
            "metric": "contacts",
            "aggregation": "sum",
            "window_days": 10,
            "comparator": "lt",
            "value": 10,
        })

    def create_context(
            self,
            *,
            workspace=None,
            avito_account=None,
            actor=None,
    ):
        automation_model = apps.get_model("automations", "Automation")
        run_model = apps.get_model("automations", "AutomationRun")
        result_model = apps.get_model(
            "automations",
            "AvitoListingRunResult",
        )
        decision_model = apps.get_model(
            "automations",
            "AvitoListingDecision",
        )
        target_workspace = workspace or self.workspace
        target_account = avito_account or self.avito_account
        target_actor = actor or self.owner
        active_since = timezone.now() - timedelta(days=20)
        automation = automation_model.objects.create(
            workspace=target_workspace,
            module_type="avito_listings",
            name=f"Automation command {uuid4()}",
            state=automation_model.State.ENABLED,
            created_by=target_actor,
            updated_by=target_actor,
        )
        listing = AvitoListing.objects.create(
            workspace=target_workspace,
            avito_account=target_account,
            source=AvitoListing.Source.AVITO_EXCEL,
            management_status=AvitoListing.ManagementStatus.MANAGED,
            desired_status=AvitoListing.DesiredStatus.PUBLISH,
            active_since=active_since,
            avito_id=f"automation-command-{uuid4()}",
            row_id=f"AUTOMATION-COMMAND-{uuid4()}",
            title="Объявление для API-команды",
        )
        automation_run = run_model.objects.create(
            automation=automation,
            workspace=target_workspace,
            run_kind=run_model.RunKind.EXECUTE,
            trigger=run_model.Trigger.MANUAL,
            execution_mode_snapshot="manual",
            automation_version=automation.version,
            automation_name_snapshot=automation.name,
            module_type_snapshot=automation.module_type,
            status=run_model.Status.WAITING_APPROVAL,
            idempotency_key=f"automation-command-{uuid4()}",
            created_by=target_actor,
        )
        action_snapshot = {"type": "pause", "config": {}}
        run_result = result_model.objects.create(
            run=automation_run,
            workspace=target_workspace,
            avito_account=target_account,
            as_of_date=timezone.localdate(),
            condition_snapshot=self.condition_snapshot,
            action_snapshot=action_snapshot,
            pending_approval=1,
        )
        decision = decision_model.objects.create(
            run=automation_run,
            automation=automation,
            workspace=target_workspace,
            avito_account=target_account,
            listing=listing,
            listing_id_snapshot=listing.id,
            listing_snapshot={
                "avito_id": listing.avito_id,
                "title": listing.title,
            },
            automation_version=automation.version,
            active_since_snapshot=active_since,
            condition_snapshot=self.condition_snapshot,
            metrics_snapshot=[],
            action_snapshot=action_snapshot,
            expires_at=timezone.now() + timedelta(hours=24),
        )
        return SimpleNamespace(
            automation=automation,
            listing=listing,
            automation_run=automation_run,
            run_result=run_result,
            decision=decision,
            workspace=target_workspace,
            avito_account=target_account,
        )

    def confirm_ready_statistics(self, context):
        as_of_date = timezone.localdate()
        date_from = as_of_date - timedelta(days=10)
        date_to = as_of_date - timedelta(days=1)
        AvitoStatsSyncState.objects.create(
            workspace=context.workspace,
            avito_account=context.avito_account,
            status=AvitoStatsSyncState.Status.SUCCESS,
            coverage_from=date_from,
            coverage_to=date_to,
        )
        AvitoListingStatsCoverage.objects.create(
            workspace=context.workspace,
            listing=context.listing,
            coverage_from=date_from,
            finalized_through=date_to,
        )
        AvitoListingDailyStats.objects.create(
            workspace=context.workspace,
            listing=context.listing,
            date=date_to,
            contacts=3,
        )

    def client_for(self, user):
        client = APIClient()
        client.force_authenticate(user)
        return client

    def headers(self):
        return {
            "HTTP_X_WORKSPACE_ID": str(self.workspace.id),
        }

    @staticmethod
    def approve_url(context):
        return (
            f"/api/automation-runs/{context.automation_run.id}/"
            f"decisions/{context.decision.id}/approve/"
        )

    @staticmethod
    def reject_url(context):
        return (
            f"/api/automation-runs/{context.automation_run.id}/"
            f"decisions/{context.decision.id}/reject/"
        )

    def test_approve_applies_action_and_repeated_request_is_idempotent(self):
        context = self.create_context()
        self.confirm_ready_statistics(context)

        first = self.client_for(self.owner).post(
            self.approve_url(context),
            data={},
            format="json",
            **self.headers(),
        )
        repeated = self.client_for(self.admin).post(
            self.approve_url(context),
            data={},
            format="json",
            **self.headers(),
        )

        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.data["decision_id"], context.decision.id)
        self.assertEqual(first.data["status"], "effect_pending")
        self.assertEqual(first.data["outcome"], "effect_pending")
        self.assertTrue(first.data["changed"])
        self.assertEqual(first.data["required_export_revision"], 1)
        self.assertIsNone(first.data["reason"])

        self.assertEqual(repeated.status_code, 200)
        self.assertEqual(repeated.data["status"], "effect_pending")
        self.assertEqual(repeated.data["outcome"], "unchanged")
        self.assertFalse(repeated.data["changed"])
        self.assertEqual(repeated.data["required_export_revision"], 1)

        context.decision.refresh_from_db()
        context.avito_account.refresh_from_db()
        self.assertEqual(context.decision.approved_by, self.owner)
        self.assertEqual(context.avito_account.export_revision, 1)

    def test_approve_insufficient_data_leaves_decision_open(self):
        context = self.create_context()

        response = self.client_for(self.owner).post(
            self.approve_url(context),
            data={},
            format="json",
            **self.headers(),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], "pending_approval")
        self.assertEqual(response.data["outcome"], "insufficient_data")
        self.assertEqual(
            response.data["reason"],
            "insufficient_account_coverage",
        )
        self.assertFalse(response.data["changed"])
        context.decision.refresh_from_db()
        self.assertEqual(context.decision.status, "pending_approval")

    def test_reject_is_idempotent_and_never_changes_listing(self):
        context = self.create_context()
        original_active_since = context.listing.active_since

        first = self.client_for(self.owner).post(
            self.reject_url(context),
            data={},
            format="json",
            **self.headers(),
        )
        repeated = self.client_for(self.admin).post(
            self.reject_url(context),
            data={},
            format="json",
            **self.headers(),
        )

        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.data["status"], "rejected")
        self.assertEqual(first.data["outcome"], "rejected")
        self.assertTrue(first.data["changed"])
        self.assertEqual(repeated.status_code, 200)
        self.assertEqual(repeated.data["outcome"], "unchanged")
        self.assertFalse(repeated.data["changed"])

        context.decision.refresh_from_db()
        context.listing.refresh_from_db()
        context.avito_account.refresh_from_db()
        self.assertEqual(context.decision.rejected_by, self.owner)
        self.assertEqual(context.listing.active_since, original_active_since)
        self.assertEqual(context.avito_account.export_revision, 0)

    def test_decision_commands_reject_body_fields_and_invalid_state(self):
        context = self.create_context()
        client = self.client_for(self.owner)

        invalid_body = client.post(
            self.reject_url(context),
            data={"reason": "manual"},
            format="json",
            **self.headers(),
        )
        self.assertEqual(invalid_body.status_code, 400)
        self.assertIn("reason", invalid_body.data)

        context.decision.status = "effect_pending"
        context.decision.save(update_fields=["status", "updated_at"])
        invalid_state = client.post(
            self.reject_url(context),
            data={},
            format="json",
            **self.headers(),
        )
        self.assertEqual(invalid_state.status_code, 409)
        self.assertEqual(
            invalid_state.data["code"],
            "invalid_decision_state",
        )

    def test_decision_commands_enforce_scope_permission_and_busy_mapping(self):
        context = self.create_context()
        foreign_context = self.create_context(
            workspace=self.foreign_workspace,
            avito_account=self.foreign_account,
            actor=self.foreign_owner,
        )

        forbidden = self.client_for(self.manager).post(
            self.reject_url(context),
            data={},
            format="json",
            **self.headers(),
        )
        self.assertEqual(forbidden.status_code, 403)

        foreign = self.client_for(self.owner).post(
            self.reject_url(foreign_context),
            data={},
            format="json",
            **self.headers(),
        )
        self.assertEqual(foreign.status_code, 404)
        self.assertEqual(foreign.data["code"], "decision_not_found")

        approval_module = import_module(
            "automations.modules.avito_listings.decision_approval",
        )
        with patch(
                "automations.api_views.approve_listing_decision",
                side_effect=approval_module.DecisionApprovalError(
                    code="resource_busy",
                    message="Решение сейчас обрабатывается.",
                ),
                create=True,
        ):
            busy = self.client_for(self.owner).post(
                self.approve_url(context),
                data={},
                format="json",
                **self.headers(),
            )

        self.assertEqual(busy.status_code, 409)
        self.assertEqual(busy.data["code"], "resource_busy")


class AutomationInboxSummaryApiTests(TestCase):
    url = "/api/automations/inbox-summary/"

    @classmethod
    def setUpTestData(cls):
        user_model = get_user_model()
        cls.owner = user_model.objects.create_user(
            email="automation-inbox-owner@example.com",
            password="test-password",
        )
        cls.admin = user_model.objects.create_user(
            email="automation-inbox-admin@example.com",
            password="test-password",
        )
        cls.manager = user_model.objects.create_user(
            email="automation-inbox-manager@example.com",
            password="test-password",
        )
        cls.foreign_owner = user_model.objects.create_user(
            email="automation-inbox-foreign@example.com",
            password="test-password",
        )
        cls.workspace = Workspace.objects.create(
            name="Automation inbox workspace",
            slug="automation-inbox-workspace",
            owner=cls.owner,
        )
        cls.foreign_workspace = Workspace.objects.create(
            name="Foreign automation inbox workspace",
            slug="foreign-automation-inbox-workspace",
            owner=cls.foreign_owner,
        )
        for workspace, user, role in (
            (
                cls.workspace,
                cls.owner,
                WorkspaceMembership.Role.OWNER,
            ),
            (
                cls.workspace,
                cls.admin,
                WorkspaceMembership.Role.ADMIN,
            ),
            (
                cls.workspace,
                cls.manager,
                WorkspaceMembership.Role.MANAGER,
            ),
            (
                cls.foreign_workspace,
                cls.foreign_owner,
                WorkspaceMembership.Role.OWNER,
            ),
        ):
            WorkspaceMembership.objects.create(
                workspace=workspace,
                user=user,
                role=role,
                status=WorkspaceMembership.Status.ACTIVE,
            )

        cls.avito_account = AvitoAccount.objects.create(
            workspace=cls.workspace,
            name="Automation inbox account",
        )
        cls.foreign_account = AvitoAccount.objects.create(
            workspace=cls.foreign_workspace,
            name="Foreign automation inbox account",
        )
        cls.automation, cls.automation_run = cls.create_run(
            workspace=cls.workspace,
            actor=cls.owner,
            name="Automation inbox",
        )
        foreign_automation, foreign_run = cls.create_run(
            workspace=cls.foreign_workspace,
            actor=cls.foreign_owner,
            name="Foreign automation inbox",
        )

        now = timezone.now()
        cls.create_decision(
            automation=cls.automation,
            automation_run=cls.automation_run,
            workspace=cls.workspace,
            avito_account=cls.avito_account,
            listing_id=1,
            status="pending_approval",
            expires_at=now + timedelta(hours=1),
        )
        cls.create_decision(
            automation=cls.automation,
            automation_run=cls.automation_run,
            workspace=cls.workspace,
            avito_account=cls.avito_account,
            listing_id=2,
            status="pending_approval",
            expires_at=now + timedelta(hours=2),
        )
        cls.create_decision(
            automation=cls.automation,
            automation_run=cls.automation_run,
            workspace=cls.workspace,
            avito_account=cls.avito_account,
            listing_id=3,
            status="pending_approval",
            expires_at=now - timedelta(minutes=1),
        )
        cls.create_decision(
            automation=cls.automation,
            automation_run=cls.automation_run,
            workspace=cls.workspace,
            avito_account=cls.avito_account,
            listing_id=4,
            status="effect_pending",
            expires_at=now + timedelta(hours=1),
        )
        cls.create_decision(
            automation=foreign_automation,
            automation_run=foreign_run,
            workspace=cls.foreign_workspace,
            avito_account=cls.foreign_account,
            listing_id=1,
            status="pending_approval",
            expires_at=now + timedelta(hours=1),
        )

    @classmethod
    def create_run(cls, *, workspace, actor, name):
        automation_model = apps.get_model("automations", "Automation")
        run_model = apps.get_model("automations", "AutomationRun")
        automation = automation_model.objects.create(
            workspace=workspace,
            module_type="avito_listings",
            name=name,
            state=automation_model.State.ENABLED,
            created_by=actor,
            updated_by=actor,
        )
        automation_run = run_model.objects.create(
            automation=automation,
            workspace=workspace,
            run_kind=run_model.RunKind.EXECUTE,
            trigger=run_model.Trigger.MANUAL,
            execution_mode_snapshot="manual",
            automation_version=automation.version,
            automation_name_snapshot=automation.name,
            module_type_snapshot=automation.module_type,
            status=run_model.Status.WAITING_APPROVAL,
            created_by=actor,
        )
        return automation, automation_run

    @classmethod
    def create_decision(
            cls,
            *,
            automation,
            automation_run,
            workspace,
            avito_account,
            listing_id,
            status,
            expires_at,
    ):
        decision_model = apps.get_model(
            "automations",
            "AvitoListingDecision",
        )
        return decision_model.objects.create(
            run=automation_run,
            automation=automation,
            workspace=workspace,
            avito_account=avito_account,
            listing_id_snapshot=listing_id,
            listing_snapshot={"title": f"Объявление {listing_id}"},
            status=status,
            automation_version=automation.version,
            active_since_snapshot=(
                timezone.now() - timedelta(days=20)
            ),
            condition_snapshot={},
            metrics_snapshot=[],
            action_snapshot={"type": "pause", "config": {}},
            expires_at=expires_at,
        )

    def client_for(self, user=None):
        client = APIClient()
        if user is not None:
            client.force_authenticate(user)
        return client

    def headers(self):
        return {
            "HTTP_X_WORKSPACE_ID": str(self.workspace.id),
        }

    def test_summary_counts_only_actionable_decisions_in_workspace(self):
        client = self.client_for(self.owner)

        with CaptureQueriesContext(connection) as queries:
            response = client.get(self.url, **self.headers())

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.data,
            {"pending_approval_count": 2},
        )
        decision_queries = [
            query["sql"]
            for query in queries.captured_queries
            if "automations_avitolistingdecision" in query["sql"]
        ]
        self.assertEqual(len(decision_queries), 1)
        self.assertIn("COUNT(", decision_queries[0].upper())

    def test_admin_can_read_summary(self):
        response = self.client_for(self.admin).get(
            self.url,
            **self.headers(),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.data,
            {"pending_approval_count": 2},
        )

    def test_manager_and_anonymous_cannot_read_summary(self):
        manager_response = self.client_for(self.manager).get(
            self.url,
            **self.headers(),
        )
        anonymous_response = self.client_for().get(
            self.url,
            **self.headers(),
        )

        self.assertEqual(manager_response.status_code, 403)
        self.assertEqual(anonymous_response.status_code, 401)
