-- Local deterministic seed data for DB-backed tests and demos.
-- Safe to run repeatedly against the local Docker database.

begin;

truncate table
    core.loan_overdue_ledger,
    core.principal_repayment_ledger,
    core.credit_usage_ledger,
    core.orders,
    core.interest_ledger,
    core.bss_scores,
    core.farmer_documents,
    core.ass_scores,
    core.credit_limits,
    core.credit_limit_applications,
    core.farmer_profiles,
    core.users,
    catalog.products,
    catalog.categories,
    ai.mcp_tool_calls,
    ai.chat_messages,
    ai.job_runs,
    ai.chat_sessions,
    ai.mcp_tools,
    ai.mcp_servers,
    ai.scaling_events,
    ai.prediction_error_metrics,
    ai.prediction_metrics,
    ai.actual_metrics,
    ai.prediction_runs,
    ai.model_versions
restart identity cascade;

insert into core.users (
    public_id,
    name,
    phone,
    resident_id_hash,
    resident_id_enc,
    address,
    address_detail,
    zip_code,
    status,
    created_at,
    updated_at
) values
    (
        '00000001-0000-0000-0000-000000000001',
        'Sample farmer',
        '010-1111-2222',
        'seed-hash-001',
        null,
        'jeonbuk',
        null,
        '55000',
        'ACTIVE',
        timestamp '2026-05-30 00:00:00',
        timestamp '2026-06-05 00:00:00'
    ),
    (
        '00000001-0000-0000-0000-000000000002',
        'Pepper grower',
        '010-3333-4444',
        'seed-hash-002',
        null,
        'gyeongbuk',
        null,
        '39000',
        'ACTIVE',
        timestamp '2026-05-30 00:00:00',
        timestamp '2026-06-05 00:00:00'
    ),
    (
        '00000001-0000-0000-0000-000000000003',
        'Cabbage farm',
        '010-5555-6666',
        'seed-hash-003',
        null,
        'gangwon',
        null,
        '24000',
        'ACTIVE',
        timestamp '2026-05-30 00:00:00',
        timestamp '2026-06-05 00:00:00'
    )
on conflict (public_id) do update set
    name = excluded.name,
    phone = excluded.phone,
    resident_id_hash = excluded.resident_id_hash,
    resident_id_enc = excluded.resident_id_enc,
    address = excluded.address,
    address_detail = excluded.address_detail,
    zip_code = excluded.zip_code,
    status = excluded.status,
    updated_at = excluded.updated_at;

insert into core.farmer_profiles (
    user_id,
    farming_since,
    field_aream2,
    has_crop_insurance,
    farm_address,
    main_crop,
    created_at,
    updated_at
)
select u.id, seed.farming_since, seed.field_aream2, seed.has_crop_insurance,
       seed.farm_address, seed.main_crop, timestamp '2026-05-30 00:00:00',
       timestamp '2026-06-05 00:00:00'
from (
    values
        ('00000001-0000-0000-0000-000000000001'::uuid, date '2020-01-01', 10000.00, true, 'jeonbuk', 'RICE'),
        ('00000001-0000-0000-0000-000000000002'::uuid, date '2019-01-01', 12000.00, false, 'gyeongbuk', 'PEPPER'),
        ('00000001-0000-0000-0000-000000000003'::uuid, date '2018-01-01', 8000.00, false, 'gangwon', 'CUSTOM')
) as seed(user_public_id, farming_since, field_aream2, has_crop_insurance, farm_address, main_crop)
join core.users u on u.public_id = seed.user_public_id
on conflict (user_id) do update set
    farming_since = excluded.farming_since,
    field_aream2 = excluded.field_aream2,
    has_crop_insurance = excluded.has_crop_insurance,
    farm_address = excluded.farm_address,
    main_crop = excluded.main_crop,
    updated_at = excluded.updated_at;

insert into core.credit_limit_applications (
    public_id,
    user_id,
    status,
    applied_at,
    created_at,
    updated_at
)
select seed.public_id, u.id, seed.status, seed.applied_at, seed.created_at, seed.updated_at
from (
    values
        ('a0000001-0000-0000-0000-000000000001'::uuid, '00000001-0000-0000-0000-000000000001'::uuid, 'APPROVED', timestamp '2026-06-02 09:00:00', timestamp '2026-06-02 09:00:00', timestamp '2026-06-05 00:00:00'),
        ('a0000001-0000-0000-0000-000000000002'::uuid, '00000001-0000-0000-0000-000000000002'::uuid, 'PENDING', timestamp '2026-06-04 09:00:00', timestamp '2026-06-04 09:00:00', timestamp '2026-06-05 00:00:00'),
        ('a0000001-0000-0000-0000-000000000003'::uuid, '00000001-0000-0000-0000-000000000003'::uuid, 'PENDING', timestamp '2026-06-03 14:30:00', timestamp '2026-06-03 14:30:00', timestamp '2026-06-05 00:00:00')
) as seed(public_id, user_public_id, status, applied_at, created_at, updated_at)
join core.users u on u.public_id = seed.user_public_id
on conflict (public_id) do update set
    user_id = excluded.user_id,
    status = excluded.status,
    applied_at = excluded.applied_at,
    updated_at = excluded.updated_at;

insert into core.credit_limits (
    public_id,
    user_public_id,
    application_public_id,
    crop_type_snapshot,
    total_limit,
    used_amount,
    interest_rate,
    interest_due_day,
    principal_due_date,
    expires_at,
    status,
    created_at,
    updated_at
) values
    (
        'c0000001-0000-0000-0000-000000000001',
        '00000001-0000-0000-0000-000000000001',
        'a0000001-0000-0000-0000-000000000001',
        'RICE',
        3000000.00,
        450000.00,
        0.0325,
        15,
        date '2026-08-15',
        date '2026-12-31',
        'ACTIVE',
        timestamp '2026-06-02 09:00:00',
        timestamp '2026-06-05 00:00:00'
    ),
    (
        'c0000001-0000-0000-0000-000000000002',
        '00000001-0000-0000-0000-000000000002',
        'a0000001-0000-0000-0000-000000000002',
        'PEPPER',
        5000000.00,
        3200000.00,
        0.0350,
        20,
        date '2026-08-20',
        date '2026-12-31',
        'ACTIVE',
        timestamp '2026-06-04 09:00:00',
        timestamp '2026-06-05 00:00:00'
    ),
    (
        'c0000001-0000-0000-0000-000000000003',
        '00000001-0000-0000-0000-000000000003',
        'a0000001-0000-0000-0000-000000000003',
        'GARLIC',
        4000000.00,
        3700000.00,
        0.0400,
        10,
        date '2026-08-10',
        date '2026-12-31',
        'SUSPENDED',
        timestamp '2026-06-03 14:30:00',
        timestamp '2026-06-05 00:00:00'
    )
on conflict (public_id) do update set
    user_public_id = excluded.user_public_id,
    application_public_id = excluded.application_public_id,
    crop_type_snapshot = excluded.crop_type_snapshot,
    total_limit = excluded.total_limit,
    used_amount = excluded.used_amount,
    interest_rate = excluded.interest_rate,
    interest_due_day = excluded.interest_due_day,
    principal_due_date = excluded.principal_due_date,
    expires_at = excluded.expires_at,
    status = excluded.status,
    updated_at = excluded.updated_at;

insert into core.bss_scores (
    public_id,
    user_public_id,
    application_public_id,
    period_type,
    period_year,
    period_month,
    monthly_score,
    annual_score,
    total_score,
    calculated_at,
    created_at
) values
    ('f0000001-0000-0000-0000-000000000001', '00000001-0000-0000-0000-000000000001', 'a0000001-0000-0000-0000-000000000001', 'MONTHLY', 2026, 5, 820, null, 820, timestamp '2026-05-01 00:00:00', timestamp '2026-05-01 00:00:00'),
    ('f0000001-0000-0000-0000-000000000002', '00000001-0000-0000-0000-000000000002', 'a0000001-0000-0000-0000-000000000002', 'MONTHLY', 2026, 5, 720, null, 720, timestamp '2026-05-01 00:00:00', timestamp '2026-05-01 00:00:00'),
    ('f0000001-0000-0000-0000-000000000003', '00000001-0000-0000-0000-000000000003', 'a0000001-0000-0000-0000-000000000003', 'MONTHLY', 2026, 5, 610, null, 610, timestamp '2026-05-01 00:00:00', timestamp '2026-05-01 00:00:00')
on conflict (public_id) do update set
    user_public_id = excluded.user_public_id,
    application_public_id = excluded.application_public_id,
    period_type = excluded.period_type,
    period_year = excluded.period_year,
    period_month = excluded.period_month,
    monthly_score = excluded.monthly_score,
    annual_score = excluded.annual_score,
    total_score = excluded.total_score,
    calculated_at = excluded.calculated_at;

insert into core.interest_ledger (
    public_id,
    credit_limit_public_id,
    base_principal,
    due_date,
    interest_amount,
    amount_paid,
    paid_at,
    status,
    created_at,
    updated_at
) values
    ('e0000001-0000-0000-0000-000000000001', 'c0000001-0000-0000-0000-000000000001', 450000.00, date '2026-06-15', 12000.00, 0.00, null, 'UPCOMING', timestamp '2026-06-01 00:00:00', timestamp '2026-06-05 00:00:00'),
    ('e0000001-0000-0000-0000-000000000002', 'c0000001-0000-0000-0000-000000000002', 3200000.00, date '2026-05-29', 120000.00, 0.00, null, 'OVERDUE', timestamp '2026-05-29 00:00:00', timestamp '2026-06-05 00:00:00'),
    ('e0000001-0000-0000-0000-000000000003', 'c0000001-0000-0000-0000-000000000003', 3700000.00, date '2026-05-15', 550000.00, 0.00, null, 'OVERDUE', timestamp '2026-05-15 00:00:00', timestamp '2026-06-05 00:00:00')
on conflict (public_id) do update set
    credit_limit_public_id = excluded.credit_limit_public_id,
    base_principal = excluded.base_principal,
    due_date = excluded.due_date,
    interest_amount = excluded.interest_amount,
    amount_paid = excluded.amount_paid,
    paid_at = excluded.paid_at,
    status = excluded.status,
    updated_at = excluded.updated_at;

insert into core.loan_overdue_ledger (
    public_id,
    user_public_id,
    credit_limit_public_id,
    interest_ledger_public_id,
    principal_repayment_public_id,
    overdue_type,
    overdue_amount,
    overdue_days,
    stage,
    penalty_rate,
    penalty_amount,
    action_taken,
    resolved_at,
    created_at,
    updated_at
) values
    ('d0000001-0000-0000-0000-000000000001', '00000001-0000-0000-0000-000000000002', 'c0000001-0000-0000-0000-000000000002', 'e0000001-0000-0000-0000-000000000002', null, 'INTEREST', 120000.00, 7, 'NOTICE', 0.0100, 0.00, null, null, timestamp '2026-05-29 00:00:00', timestamp '2026-06-05 00:00:00'),
    ('d0000001-0000-0000-0000-000000000002', '00000001-0000-0000-0000-000000000003', 'c0000001-0000-0000-0000-000000000003', 'e0000001-0000-0000-0000-000000000003', null, 'INTEREST', 550000.00, 21, 'COLLECTION', 0.0150, 0.00, null, null, timestamp '2026-05-15 00:00:00', timestamp '2026-06-05 00:00:00')
on conflict (public_id) do update set
    user_public_id = excluded.user_public_id,
    credit_limit_public_id = excluded.credit_limit_public_id,
    interest_ledger_public_id = excluded.interest_ledger_public_id,
    principal_repayment_public_id = excluded.principal_repayment_public_id,
    overdue_type = excluded.overdue_type,
    overdue_amount = excluded.overdue_amount,
    overdue_days = excluded.overdue_days,
    stage = excluded.stage,
    penalty_rate = excluded.penalty_rate,
    penalty_amount = excluded.penalty_amount,
    action_taken = excluded.action_taken,
    resolved_at = excluded.resolved_at,
    updated_at = excluded.updated_at;

insert into catalog.categories (public_id, name, status, created_at, updated_at) values
    ('20000000-0000-0000-0000-000000000001', 'fertilizer', 'ACTIVE', timestamp '2026-06-05 00:00:00', timestamp '2026-06-05 00:00:00'),
    ('20000000-0000-0000-0000-000000000002', 'seed', 'ACTIVE', timestamp '2026-06-05 00:00:00', timestamp '2026-06-05 00:00:00'),
    ('20000000-0000-0000-0000-000000000003', 'pesticide', 'ACTIVE', timestamp '2026-06-05 00:00:00', timestamp '2026-06-05 00:00:00')
on conflict (name) do update set
    status = excluded.status,
    updated_at = excluded.updated_at;

insert into catalog.products (
    public_id,
    category_public_id,
    name,
    description,
    price,
    stock_quantity,
    unit,
    image_url,
    status,
    created_at,
    updated_at
)
select
    seed.public_id,
    c.public_id as category_public_id,
    seed.name,
    seed.description,
    seed.price,
    seed.stock_quantity,
    seed.unit,
    seed.image_url,
    seed.status,
    seed.created_at,
    seed.updated_at
from (
    values
        ('10000000-0000-0000-0000-000000000001'::uuid, 'fertilizer', 'NPK 20kg fertilizer', 'Balanced NPK fertilizer for base application.', 28000.00, 100, 'bag', null, 'ON_SALE', timestamp '2026-06-05 00:00:00', timestamp '2026-06-05 00:00:00'),
        ('10000000-0000-0000-0000-000000000002'::uuid, 'fertilizer', 'Organic 20kg fertilizer', 'Organic fertilizer for soil preparation.', 24000.00, 100, 'bag', null, 'ON_SALE', timestamp '2026-06-05 00:00:00', timestamp '2026-06-05 00:00:00'),
        ('10000000-0000-0000-0000-000000000003'::uuid, 'seed', 'Rice seed 10kg', 'Rice seed pack for spring planting.', 36000.00, 8, 'pack', null, 'ON_SALE', timestamp '2026-06-05 00:00:00', timestamp '2026-06-05 00:00:00'),
        ('10000000-0000-0000-0000-000000000004'::uuid, 'pesticide', 'Low-toxicity pesticide 1L', 'Crop care pesticide bottle.', 18000.00, 100, 'bottle', null, 'ON_SALE', timestamp '2026-06-05 00:00:00', timestamp '2026-06-05 00:00:00')
) as seed(
    public_id,
    category_name,
    name,
    description,
    price,
    stock_quantity,
    unit,
    image_url,
    status,
    created_at,
    updated_at
)
join catalog.categories c on c.name = seed.category_name
on conflict (public_id) do update set
    category_public_id = excluded.category_public_id,
    name = excluded.name,
    description = excluded.description,
    price = excluded.price,
    stock_quantity = excluded.stock_quantity,
    unit = excluded.unit,
    image_url = excluded.image_url,
    status = excluded.status,
    updated_at = excluded.updated_at;

insert into ai.model_versions (
    public_id,
    model_name,
    model_version,
    model_type,
    artifact_path,
    target_metric,
    model_status,
    created_at
) values
    ('30000000-0000-0000-0000-000000000001', 'api', '2.0.0', 'GRU', 'models/api/gru-traffic-forecast/2.0.0', 'http_requests_per_second', 'ACTIVE', timestamp '2026-06-04 12:00:00'),
    ('30000000-0000-0000-0000-000000000002', 'api', '1.0.0', 'LSTM', 'models/api/lstm-traffic-forecast/1.0.0', 'http_requests_per_second', 'INACTIVE', timestamp '2026-05-10 12:00:00'),
    ('30000000-0000-0000-0000-000000000003', 'batch-worker', '1.0.0', 'REGRESSION', 'models/batch/runtime/1.0.0', 'job_runtime_seconds', 'INACTIVE', timestamp '2026-06-01 12:00:00')
on conflict (model_name, model_version) do update set
    public_id = excluded.public_id,
    model_type = excluded.model_type,
    artifact_path = excluded.artifact_path,
    target_metric = excluded.target_metric,
    model_status = excluded.model_status;

insert into ai.prediction_runs (
    public_id,
    model_version_public_id,
    target_namespace,
    target_service,
    target_metric,
    input_window_start,
    input_window_end,
    prediction_horizon_minutes,
    run_status,
    started_at,
    finished_at,
    last_error
) values
    ('40000000-0000-0000-0000-000000000001', '30000000-0000-0000-0000-000000000001', 'default', 'api', 'http_requests_per_second', timestamp '2026-06-04 23:30:00', timestamp '2026-06-05 00:00:00', 30, 'SUCCEEDED', timestamp '2026-06-05 00:00:00', timestamp '2026-06-05 00:01:00', null),
    ('40000000-0000-0000-0000-000000000002', '30000000-0000-0000-0000-000000000003', 'jobs', 'settlement-worker', 'job_runtime_seconds', timestamp '2026-06-05 00:00:00', timestamp '2026-06-05 00:02:00', 60, 'RUNNING', timestamp '2026-06-05 00:02:00', null, null)
on conflict (public_id) do update set
    model_version_public_id = excluded.model_version_public_id,
    target_namespace = excluded.target_namespace,
    target_service = excluded.target_service,
    target_metric = excluded.target_metric,
    input_window_start = excluded.input_window_start,
    input_window_end = excluded.input_window_end,
    prediction_horizon_minutes = excluded.prediction_horizon_minutes,
    run_status = excluded.run_status,
    started_at = excluded.started_at,
    finished_at = excluded.finished_at,
    last_error = excluded.last_error;

insert into ai.prediction_metrics (
    public_id,
    prediction_run_public_id,
    metric_name,
    namespace,
    service_name,
    predicted_value,
    target_time,
    model_version,
    created_at
) values
    ('41000000-0000-0000-0000-000000000001', '40000000-0000-0000-0000-000000000001', 'http_requests_per_second', 'default', 'api', 100.0, timestamp '2026-06-05 00:05:00', '2.0.0', timestamp '2026-06-05 00:01:00'),
    ('41000000-0000-0000-0000-000000000002', '40000000-0000-0000-0000-000000000001', 'http_requests_per_second', 'default', 'api', 120.0, timestamp '2026-06-05 00:10:00', '2.0.0', timestamp '2026-06-05 00:01:00'),
    ('41000000-0000-0000-0000-000000000003', '40000000-0000-0000-0000-000000000001', 'http_requests_per_second', 'default', 'api', 150.0, timestamp '2026-06-05 00:15:00', '2.0.0', timestamp '2026-06-05 00:01:00'),
    ('41000000-0000-0000-0000-000000000004', '40000000-0000-0000-0000-000000000002', 'job_runtime_seconds', 'jobs', 'settlement-worker', 780.0, timestamp '2026-06-05 01:00:00', '1.0.0', timestamp '2026-06-05 00:03:00')
on conflict (public_id) do update set
    prediction_run_public_id = excluded.prediction_run_public_id,
    metric_name = excluded.metric_name,
    namespace = excluded.namespace,
    service_name = excluded.service_name,
    predicted_value = excluded.predicted_value,
    target_time = excluded.target_time,
    model_version = excluded.model_version;

insert into ai.actual_metrics (
    public_id,
    metric_name,
    namespace,
    service_name,
    actual_value,
    measured_at,
    source_type,
    created_at
) values
    ('42000000-0000-0000-0000-000000000001', 'http_requests_per_second', 'default', 'api', 96.0, timestamp '2026-06-05 00:05:00', 'PROMETHEUS', timestamp '2026-06-05 00:05:30'),
    ('42000000-0000-0000-0000-000000000002', 'http_requests_per_second', 'default', 'api', 130.0, timestamp '2026-06-05 00:10:00', 'PROMETHEUS', timestamp '2026-06-05 00:10:30'),
    ('42000000-0000-0000-0000-000000000003', 'http_requests_per_second', 'default', 'api', 144.0, timestamp '2026-06-05 00:15:00', 'PROMETHEUS', timestamp '2026-06-05 00:15:30'),
    ('42000000-0000-0000-0000-000000000004', 'job_runtime_seconds', 'jobs', 'settlement-worker', 760.0, timestamp '2026-06-05 01:00:00', 'PROMETHEUS', timestamp '2026-06-05 01:00:30')
on conflict (public_id) do update set
    metric_name = excluded.metric_name,
    namespace = excluded.namespace,
    service_name = excluded.service_name,
    actual_value = excluded.actual_value,
    measured_at = excluded.measured_at,
    source_type = excluded.source_type;

insert into ai.scaling_events (
    public_id,
    prediction_metric_public_id,
    namespace,
    service_name,
    workload,
    source_type,
    previous_replicas,
    new_replicas,
    reason,
    metric_name,
    metric_value,
    threshold,
    event_time,
    created_at
) values
    ('50000000-0000-0000-0000-000000000001', '41000000-0000-0000-0000-000000000003', 'default', 'api', 'api', 'KEDA', 2, 4, 'Prediction forecasted API traffic increase.', 'http_requests_per_second', 150.0, 120.0, timestamp '2026-06-05 00:12:00', timestamp '2026-06-05 00:12:00'),
    ('50000000-0000-0000-0000-000000000002', null, 'default', 'api', 'api', 'HPA', 4, 3, 'Observed utilization normalized after peak.', 'http_requests_per_second', 90.0, 120.0, timestamp '2026-06-05 00:25:00', timestamp '2026-06-05 00:25:00')
on conflict (public_id) do update set
    prediction_metric_public_id = excluded.prediction_metric_public_id,
    namespace = excluded.namespace,
    service_name = excluded.service_name,
    workload = excluded.workload,
    source_type = excluded.source_type,
    previous_replicas = excluded.previous_replicas,
    new_replicas = excluded.new_replicas,
    reason = excluded.reason,
    metric_name = excluded.metric_name,
    metric_value = excluded.metric_value,
    threshold = excluded.threshold,
    event_time = excluded.event_time;

commit;
