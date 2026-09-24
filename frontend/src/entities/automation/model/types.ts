export type AutomationState =
    | "draft"
    | "enabled"
    | "disabled"
    | "archived";

export type EditableAutomationState =
    | "draft"
    | "enabled"
    | "disabled";

export type AutomationExecutionMode = "manual";

export type AutomationRunKind = "preview" | "execute";

export type AutomationRunTrigger = "manual";

export type AutomationRunStatus =
    | "queued"
    | "waiting_for_data"
    | "evaluating"
    | "waiting_approval"
    | "effect_pending"
    | "completed"
    | "partial"
    | "failed"
    | "cancelled";

export type AutomationDecisionStatus =
    | "pending_approval"
    | "applying"
    | "effect_pending"
    | "completed"
    | "rejected"
    | "expired"
    | "stale"
    | "superseded"
    | "failed";

export type AutomationConditionOperator =
    | "and"
    | "or";

export interface AutomationConditionLeaf {
    type: "condition";
    metric: string;
    aggregation: string;
    window_days: number;
    comparator: string;
    value: number;
}


export interface AutomationConditionGroup {
    type: "group";
    operators: AutomationConditionOperator[];
    children: AutomationConditionLeaf[];
}

export interface AutomationConditionRoot {
    type: "group";
    operators: AutomationConditionOperator[];
    children: AutomationConditionGroup[];
}

export interface AutomationAction {
    type: string;
    config: Record<string, unknown>;
}

export interface AutomationConfig {
    avito_account_id: number;
    condition_tree: AutomationConditionRoot;
    action: AutomationAction;
    max_actions_per_run: number;
    approval_ttl_minutes: number;
}

export interface Automation {
    id: number;
    name: string;
    module_type: string;
    state: AutomationState;
    execution_mode: AutomationExecutionMode;
    version: number;
    config: AutomationConfig;
    created_by: number | null;
    updated_by: number | null;
    created_at: string;
    updated_at: string;
}

export interface CreateAutomationRequest {
    name: string;
    module_type: string;
    config: AutomationConfig;
}

export interface UpdateAutomationRequest {
    name?: string;
    state?: EditableAutomationState;
    config?: AutomationConfig;
}

export interface AutomationMetricDefinition {
    code: string;
    label: string;
    description: string;
    value_type: string;
    allowed_aggregations: string[];
}

export interface AutomationAggregationDefinition {
    code: string;
    label: string;
}

export interface AutomationComparatorDefinition {
    code: string;
    symbol: string;
    label: string;
}

export interface AutomationActionConfigSchema {
    type: "object";
    properties: Record<string, unknown>;
    additionalProperties: boolean;
}

export interface AutomationActionDefinition {
    code: string;
    label: string;
    description: string;
    config_schema: AutomationActionConfigSchema;
}

export interface AutomationConditionLimits {
    min_window_days: number;
    max_window_days: number;
    max_conditions: number;
}

export interface AutomationModuleCatalog {
    module_type: string;
    label: string;
    metrics: AutomationMetricDefinition[];
    aggregations: AutomationAggregationDefinition[];
    comparators: AutomationComparatorDefinition[];
    actions: AutomationActionDefinition[];
    condition_limits: AutomationConditionLimits;
}

export interface AutomationCatalogResponse {
    modules: AutomationModuleCatalog[];
}

export interface AutomationError {
    code: string;
    message: string;
}

export interface AvitoListingMetricSnapshot {
    metric: string;
    aggregation: string;
    window_days: number;
    date_from: string;
    date_to: string;
    value: number;
}

export interface AvitoListingExampleSnapshot {
    listing_id: number;
    avito_id: string;
    title: string | null;
    active_since: string;
    metrics: AvitoListingMetricSnapshot[];
}

export interface AvitoListingRunResultSummary {
    avito_account_id: number;
    as_of_date: string;
    checked: number;
    ineligible: number;
    insufficient_coverage: number;
    not_matched: number;
    matched: number;
    deferred_by_run_limit: number;
    pending_approval: number;
    completed_actions: number;
    failed_actions: number;
}

export interface AvitoListingRunResultDetail
    extends AvitoListingRunResultSummary {
    max_actions_per_run_snapshot: number;
    approval_ttl_minutes_snapshot: number;
    target_max_id_snapshot: number;
    condition_snapshot: AutomationConditionRoot;
    action_snapshot: AutomationAction;
    examples_snapshot: AvitoListingExampleSnapshot[];
}

export interface AutomationRunSummary {
    id: number;
    automation_id: number;
    kind: AutomationRunKind;
    trigger: AutomationRunTrigger;
    execution_mode: AutomationExecutionMode;
    automation_version: number;
    automation_name: string;
    module_type: string;
    status: AutomationRunStatus;
    error: AutomationError | null;
    result: AvitoListingRunResultSummary;
    created_by: number | null;
    started_at: string | null;
    finished_at: string | null;
    created_at: string;
}

export interface AutomationRunDetail
    extends Omit<AutomationRunSummary, "result"> {
    result: AvitoListingRunResultDetail;
    retry_count: number;
    data_wait_attempt_count: number;
    next_attempt_at: string | null;
    wait_started_at: string | null;
    updated_at: string;
}

export interface AutomationListingSnapshot {
    avito_id?: string | null;
    title?: string | null;

    [key: string]: unknown;
}

export interface AutomationDecision {
    id: number;
    run_id: number;
    automation_id: number;
    avito_account_id: number;
    listing_id: number;
    listing: AutomationListingSnapshot;
    status: AutomationDecisionStatus;
    automation_version: number;
    active_since: string;
    metrics: AvitoListingMetricSnapshot[];
    action: AutomationAction;
    expires_at: string;
    approved_by: number | null;
    approved_at: string | null;
    rejected_by: number | null;
    rejected_at: string | null;
    action_applied_at: string | null;
    completed_at: string | null;
    terminal_at: string | null;
    required_export_revision: number | null;
    effect_attempts: number;
    next_effect_retry_at: string | null;
    error: AutomationError | null;
    created_at: string;
    updated_at: string;
}

export interface CreateRunResponse {
    run_id: number;
    status: AutomationRunStatus;
    created: boolean;
}

export interface DecisionCommandResponse {
    decision_id: number;
    status: AutomationDecisionStatus;
    outcome: string;
    reason: string | null;
    changed: boolean;
    required_export_revision: number | null;
}

export interface AutomationInboxSummary {
    pending_approval_count: number;
}

export interface AutomationApiError {
    status: number | null;
    code: string | null;
    message: string;
    openRunId: number | null;
    fields: Record<string, string[]>;
}