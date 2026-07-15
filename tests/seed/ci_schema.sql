--
-- PostgreSQL database dump
--



SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: ai; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA ai;


--
-- Name: catalog; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA catalog;


--
-- Name: core; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA core;


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: actual_metrics; Type: TABLE; Schema: ai; Owner: -
--

CREATE TABLE ai.actual_metrics (
    id bigint NOT NULL,
    public_id uuid DEFAULT gen_random_uuid() NOT NULL,
    metric_name character varying(100) NOT NULL,
    namespace character varying(100) NOT NULL,
    service_name character varying(150) NOT NULL,
    actual_value numeric(18,6) NOT NULL,
    measured_at timestamp without time zone NOT NULL,
    source_type character varying(50) NOT NULL,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);


--
-- Name: actual_metrics_id_seq; Type: SEQUENCE; Schema: ai; Owner: -
--

CREATE SEQUENCE ai.actual_metrics_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: actual_metrics_id_seq; Type: SEQUENCE OWNED BY; Schema: ai; Owner: -
--

ALTER SEQUENCE ai.actual_metrics_id_seq OWNED BY ai.actual_metrics.id;


--
-- Name: approval_actions; Type: TABLE; Schema: ai; Owner: -
--

CREATE TABLE ai.approval_actions (
    id bigint NOT NULL,
    public_id uuid DEFAULT gen_random_uuid() NOT NULL,
    approval_request_public_id uuid NOT NULL,
    actor_user_public_id uuid,
    action_type character varying(30) NOT NULL,
    comment text,
    action_metadata jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT approval_actions_action_type_check CHECK (((action_type)::text = ANY ((ARRAY['REQUESTED'::character varying, 'APPROVED'::character varying, 'REJECTED'::character varying, 'EXPIRED'::character varying, 'CANCELED'::character varying])::text[])))
);


--
-- Name: approval_actions_id_seq; Type: SEQUENCE; Schema: ai; Owner: -
--

CREATE SEQUENCE ai.approval_actions_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: approval_actions_id_seq; Type: SEQUENCE OWNED BY; Schema: ai; Owner: -
--

ALTER SEQUENCE ai.approval_actions_id_seq OWNED BY ai.approval_actions.id;


--
-- Name: approval_requests; Type: TABLE; Schema: ai; Owner: -
--

CREATE TABLE ai.approval_requests (
    id bigint NOT NULL,
    public_id uuid DEFAULT gen_random_uuid() NOT NULL,
    requester_user_public_id uuid,
    approver_user_public_id uuid,
    mcp_tool_call_public_id uuid,
    approval_type character varying(40) NOT NULL,
    target_table character varying(100) NOT NULL,
    target_public_id uuid,
    approval_status character varying(30) DEFAULT 'PENDING'::character varying NOT NULL,
    request_payload jsonb DEFAULT '{}'::jsonb NOT NULL,
    expires_at timestamp without time zone,
    resolved_at timestamp without time zone,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT approval_requests_approval_status_check CHECK (((approval_status)::text = ANY ((ARRAY['PENDING'::character varying, 'APPROVED'::character varying, 'REJECTED'::character varying, 'EXPIRED'::character varying, 'CANCELED'::character varying])::text[]))),
    CONSTRAINT approval_requests_approval_type_check CHECK (((approval_type)::text = ANY ((ARRAY['USER_CONFIRMATION'::character varying, 'ADMIN_APPROVAL'::character varying, 'OPS_APPROVAL'::character varying])::text[])))
);


--
-- Name: approval_requests_id_seq; Type: SEQUENCE; Schema: ai; Owner: -
--

CREATE SEQUENCE ai.approval_requests_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: approval_requests_id_seq; Type: SEQUENCE OWNED BY; Schema: ai; Owner: -
--

ALTER SEQUENCE ai.approval_requests_id_seq OWNED BY ai.approval_requests.id;


--
-- Name: bnpl_payment_draft_items; Type: TABLE; Schema: ai; Owner: -
--

CREATE TABLE ai.bnpl_payment_draft_items (
    id bigint NOT NULL,
    public_id uuid DEFAULT gen_random_uuid() NOT NULL,
    draft_public_id uuid NOT NULL,
    product_public_id uuid NOT NULL,
    product_name_snapshot character varying(100) NOT NULL,
    unit_price_snapshot numeric(15,2) NOT NULL,
    quantity integer NOT NULL,
    shipping_fee numeric(15,2) DEFAULT 0 NOT NULL,
    total_price numeric(15,2) NOT NULL,
    bnpl_available boolean DEFAULT false NOT NULL,
    agronomic_fit character varying(30) NOT NULL,
    recommendation_reason text,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT bnpl_payment_draft_items_agronomic_fit_check CHECK (((agronomic_fit)::text = ANY ((ARRAY['HIGH'::character varying, 'MEDIUM'::character varying, 'LOW'::character varying])::text[]))),
    CONSTRAINT bnpl_payment_draft_items_quantity_check CHECK ((quantity > 0)),
    CONSTRAINT bnpl_payment_draft_items_shipping_fee_check CHECK ((shipping_fee >= (0)::numeric)),
    CONSTRAINT bnpl_payment_draft_items_total_price_check CHECK ((total_price >= (0)::numeric)),
    CONSTRAINT bnpl_payment_draft_items_unit_price_snapshot_check CHECK ((unit_price_snapshot >= (0)::numeric))
);


--
-- Name: bnpl_payment_draft_items_id_seq; Type: SEQUENCE; Schema: ai; Owner: -
--

CREATE SEQUENCE ai.bnpl_payment_draft_items_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: bnpl_payment_draft_items_id_seq; Type: SEQUENCE OWNED BY; Schema: ai; Owner: -
--

ALTER SEQUENCE ai.bnpl_payment_draft_items_id_seq OWNED BY ai.bnpl_payment_draft_items.id;


--
-- Name: bnpl_payment_drafts; Type: TABLE; Schema: ai; Owner: -
--

CREATE TABLE ai.bnpl_payment_drafts (
    id bigint NOT NULL,
    public_id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_public_id uuid NOT NULL,
    session_public_id uuid,
    llm_run_public_id uuid,
    credit_limit_public_id uuid,
    application_public_id uuid,
    draft_status character varying(30) DEFAULT 'PENDING'::character varying NOT NULL,
    remaining_credit_limit numeric(15,2) NOT NULL,
    total_amount numeric(15,2) NOT NULL,
    currency character varying(10) DEFAULT 'KRW'::character varying NOT NULL,
    expires_at timestamp without time zone NOT NULL,
    confirmed_at timestamp without time zone,
    submitted_at timestamp without time zone,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT bnpl_payment_drafts_draft_status_check CHECK (((draft_status)::text = ANY ((ARRAY['PENDING'::character varying, 'CONFIRMED'::character varying, 'SUBMITTED'::character varying, 'CANCELED'::character varying, 'EXPIRED'::character varying, 'FAILED'::character varying])::text[]))),
    CONSTRAINT bnpl_payment_drafts_remaining_credit_limit_check CHECK ((remaining_credit_limit >= (0)::numeric)),
    CONSTRAINT bnpl_payment_drafts_total_amount_check CHECK ((total_amount >= (0)::numeric))
);


--
-- Name: bnpl_payment_drafts_id_seq; Type: SEQUENCE; Schema: ai; Owner: -
--

CREATE SEQUENCE ai.bnpl_payment_drafts_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: bnpl_payment_drafts_id_seq; Type: SEQUENCE OWNED BY; Schema: ai; Owner: -
--

ALTER SEQUENCE ai.bnpl_payment_drafts_id_seq OWNED BY ai.bnpl_payment_drafts.id;


--
-- Name: business_entity_refs; Type: TABLE; Schema: ai; Owner: -
--

CREATE TABLE ai.business_entity_refs (
    id bigint NOT NULL,
    public_id uuid DEFAULT gen_random_uuid() NOT NULL,
    source_system character varying(80) NOT NULL,
    target_table character varying(100) NOT NULL,
    target_public_id uuid NOT NULL,
    display_name character varying(255),
    reference_metadata jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);


--
-- Name: business_entity_refs_id_seq; Type: SEQUENCE; Schema: ai; Owner: -
--

CREATE SEQUENCE ai.business_entity_refs_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: business_entity_refs_id_seq; Type: SEQUENCE OWNED BY; Schema: ai; Owner: -
--

ALTER SEQUENCE ai.business_entity_refs_id_seq OWNED BY ai.business_entity_refs.id;


--
-- Name: chat_messages; Type: TABLE; Schema: ai; Owner: -
--

CREATE TABLE ai.chat_messages (
    id bigint NOT NULL,
    public_id uuid DEFAULT gen_random_uuid() NOT NULL,
    session_public_id uuid NOT NULL,
    user_public_id uuid,
    llm_run_public_id uuid,
    mcp_tool_call_public_id uuid,
    role character varying(30) NOT NULL,
    content text NOT NULL,
    masked_content text,
    message_metadata jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT chat_messages_role_check CHECK (((role)::text = ANY ((ARRAY['USER'::character varying, 'ASSISTANT'::character varying, 'SYSTEM'::character varying, 'TOOL'::character varying])::text[])))
);


--
-- Name: chat_messages_id_seq; Type: SEQUENCE; Schema: ai; Owner: -
--

CREATE SEQUENCE ai.chat_messages_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: chat_messages_id_seq; Type: SEQUENCE OWNED BY; Schema: ai; Owner: -
--

ALTER SEQUENCE ai.chat_messages_id_seq OWNED BY ai.chat_messages.id;


--
-- Name: chat_sessions; Type: TABLE; Schema: ai; Owner: -
--

CREATE TABLE ai.chat_sessions (
    id bigint NOT NULL,
    public_id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_public_id uuid,
    session_type character varying(50) NOT NULL,
    source_type character varying(30) DEFAULT 'API'::character varying NOT NULL,
    session_status character varying(30) DEFAULT 'OPEN'::character varying NOT NULL,
    context jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT chat_sessions_session_status_check CHECK (((session_status)::text = ANY ((ARRAY['OPEN'::character varying, 'CLOSED'::character varying])::text[]))),
    CONSTRAINT chat_sessions_session_type_check CHECK (((session_type)::text = ANY ((ARRAY['FARMER_BNPL'::character varying, 'FARM_ADVISORY'::character varying, 'FARMER_CHECKOUT'::character varying, 'ADMIN_RISKOPS'::character varying, 'ADMIN_INFRAOPS'::character varying, 'ONCALL'::character varying])::text[]))),
    CONSTRAINT chat_sessions_source_type_check CHECK (((source_type)::text = ANY ((ARRAY['API'::character varying, 'SLACK'::character varying, 'WEB'::character varying, 'SYSTEM'::character varying])::text[])))
);


--
-- Name: chat_sessions_id_seq; Type: SEQUENCE; Schema: ai; Owner: -
--

CREATE SEQUENCE ai.chat_sessions_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: chat_sessions_id_seq; Type: SEQUENCE OWNED BY; Schema: ai; Owner: -
--

ALTER SEQUENCE ai.chat_sessions_id_seq OWNED BY ai.chat_sessions.id;


--
-- Name: disaster_risk_simulations; Type: TABLE; Schema: ai; Owner: -
--

CREATE TABLE ai.disaster_risk_simulations (
    id bigint NOT NULL,
    public_id uuid DEFAULT gen_random_uuid() NOT NULL,
    created_by_admin_public_id uuid,
    event_type character varying(80) NOT NULL,
    region character varying(100) NOT NULL,
    crop_type character varying(30),
    scenario_params jsonb DEFAULT '{}'::jsonb NOT NULL,
    result_summary text,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);


--
-- Name: disaster_risk_simulations_id_seq; Type: SEQUENCE; Schema: ai; Owner: -
--

CREATE SEQUENCE ai.disaster_risk_simulations_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: disaster_risk_simulations_id_seq; Type: SEQUENCE OWNED BY; Schema: ai; Owner: -
--

ALTER SEQUENCE ai.disaster_risk_simulations_id_seq OWNED BY ai.disaster_risk_simulations.id;


--
-- Name: farm_advisory_cases; Type: TABLE; Schema: ai; Owner: -
--

CREATE TABLE ai.farm_advisory_cases (
    id bigint NOT NULL,
    public_id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_public_id uuid NOT NULL,
    session_public_id uuid,
    advisory_type character varying(50) NOT NULL,
    crop_type character varying(30),
    field_area_m2 numeric(12,2),
    region character varying(100),
    input_context jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT farm_advisory_cases_advisory_type_check CHECK (((advisory_type)::text = ANY ((ARRAY['MATERIAL_RECOMMENDATION'::character varying, 'FERTILIZER_REQUIREMENT'::character varying, 'DISEASE_TRIAGE'::character varying, 'WEATHER_RISK'::character varying, 'CASHFLOW'::character varying])::text[]))),
    CONSTRAINT farm_advisory_cases_field_area_m2_check CHECK (((field_area_m2 IS NULL) OR (field_area_m2 > (0)::numeric)))
);


--
-- Name: farm_advisory_cases_id_seq; Type: SEQUENCE; Schema: ai; Owner: -
--

CREATE SEQUENCE ai.farm_advisory_cases_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: farm_advisory_cases_id_seq; Type: SEQUENCE OWNED BY; Schema: ai; Owner: -
--

ALTER SEQUENCE ai.farm_advisory_cases_id_seq OWNED BY ai.farm_advisory_cases.id;


--
-- Name: farm_advisory_results; Type: TABLE; Schema: ai; Owner: -
--

CREATE TABLE ai.farm_advisory_results (
    id bigint NOT NULL,
    public_id uuid DEFAULT gen_random_uuid() NOT NULL,
    advisory_case_public_id uuid NOT NULL,
    llm_run_public_id uuid,
    result_type character varying(40) NOT NULL,
    result_payload jsonb DEFAULT '{}'::jsonb NOT NULL,
    confidence numeric(4,3),
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT farm_advisory_results_confidence_check CHECK (((confidence IS NULL) OR ((confidence >= (0)::numeric) AND (confidence <= (1)::numeric)))),
    CONSTRAINT farm_advisory_results_result_type_check CHECK (((result_type)::text = ANY ((ARRAY['RECOMMENDATION'::character varying, 'RANKING'::character varying, 'SIMULATION'::character varying, 'TRIAGE'::character varying])::text[])))
);


--
-- Name: farm_advisory_results_id_seq; Type: SEQUENCE; Schema: ai; Owner: -
--

CREATE SEQUENCE ai.farm_advisory_results_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: farm_advisory_results_id_seq; Type: SEQUENCE OWNED BY; Schema: ai; Owner: -
--

ALTER SEQUENCE ai.farm_advisory_results_id_seq OWNED BY ai.farm_advisory_results.id;


--
-- Name: incident_alerts; Type: TABLE; Schema: ai; Owner: -
--

CREATE TABLE ai.incident_alerts (
    id bigint NOT NULL,
    public_id uuid DEFAULT gen_random_uuid() NOT NULL,
    incident_public_id uuid NOT NULL,
    fingerprint character varying(255) NOT NULL,
    alert_status character varying(30) NOT NULL,
    event_payload jsonb NOT NULL,
    labels jsonb DEFAULT '{}'::jsonb NOT NULL,
    annotations jsonb DEFAULT '{}'::jsonb NOT NULL,
    starts_at timestamp without time zone,
    ends_at timestamp without time zone,
    received_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT incident_alerts_alert_status_check CHECK (((alert_status)::text = ANY ((ARRAY['FIRING'::character varying, 'RESOLVED'::character varying])::text[])))
);


--
-- Name: incident_alerts_id_seq; Type: SEQUENCE; Schema: ai; Owner: -
--

CREATE SEQUENCE ai.incident_alerts_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: incident_alerts_id_seq; Type: SEQUENCE OWNED BY; Schema: ai; Owner: -
--

ALTER SEQUENCE ai.incident_alerts_id_seq OWNED BY ai.incident_alerts.id;


--
-- Name: incidents; Type: TABLE; Schema: ai; Owner: -
--

CREATE TABLE ai.incidents (
    id bigint NOT NULL,
    public_id uuid DEFAULT gen_random_uuid() NOT NULL,
    dedup_key character varying(255) NOT NULL,
    source_type character varying(50) NOT NULL,
    incident_status character varying(30) NOT NULL,
    severity character varying(30) NOT NULL,
    alert_name character varying(150),
    namespace character varying(100),
    workload character varying(150),
    service_name character varying(150),
    summary text,
    labels jsonb DEFAULT '{}'::jsonb NOT NULL,
    annotations jsonb DEFAULT '{}'::jsonb NOT NULL,
    starts_at timestamp without time zone,
    ends_at timestamp without time zone,
    first_seen_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    last_seen_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT incidents_incident_status_check CHECK (((incident_status)::text = ANY ((ARRAY['FIRING'::character varying, 'INVESTIGATING'::character varying, 'ANALYZED'::character varying, 'RESOLVED'::character varying, 'CLOSED'::character varying])::text[]))),
    CONSTRAINT incidents_severity_check CHECK (((severity)::text = ANY ((ARRAY['INFO'::character varying, 'WARNING'::character varying, 'CRITICAL'::character varying])::text[])))
);


--
-- Name: incidents_id_seq; Type: SEQUENCE; Schema: ai; Owner: -
--

CREATE SEQUENCE ai.incidents_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: incidents_id_seq; Type: SEQUENCE OWNED BY; Schema: ai; Owner: -
--

ALTER SEQUENCE ai.incidents_id_seq OWNED BY ai.incidents.id;


--
-- Name: job_runs; Type: TABLE; Schema: ai; Owner: -
--

CREATE TABLE ai.job_runs (
    id bigint NOT NULL,
    public_id uuid DEFAULT gen_random_uuid() NOT NULL,
    job_type character varying(50) NOT NULL,
    run_status character varying(30) DEFAULT 'QUEUED'::character varying NOT NULL,
    target_table character varying(100),
    target_public_id uuid,
    idempotency_key character varying(255),
    retry_count integer DEFAULT 0 NOT NULL,
    max_retry_count integer DEFAULT 3 NOT NULL,
    started_at timestamp without time zone,
    finished_at timestamp without time zone,
    last_error text,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    scheduled_at timestamp without time zone,
    job_context jsonb DEFAULT '{}'::jsonb NOT NULL,
    CONSTRAINT job_runs_job_type_check CHECK (((job_type)::text = ANY ((ARRAY['RCA'::character varying, 'DAILY_REPORT'::character varying, 'DAILY_REPORT_PREPROCESS'::character varying, 'WEEKLY_REPORT'::character varying, 'SCALING_REPORT'::character varying, 'ONCALL'::character varying, 'NOTIFICATION'::character varying, 'FARMER_CHAT'::character varying, 'BNPL_PAYMENT_DRAFT'::character varying, 'PAYMENT_REQUEST_PUBLISH'::character varying, 'FARM_ADVISORY'::character varying, 'RISK_ANALYSIS'::character varying, 'DISASTER_SIMULATION'::character varying, 'PREDICTION_RUN'::character varying, 'PREDICTION_ERROR_CALCULATION'::character varying, 'SCALING_EVENT_COLLECTION'::character varying, 'APPROVAL_EXECUTION'::character varying])::text[]))),
    CONSTRAINT job_runs_max_retry_count_check CHECK ((max_retry_count >= 0)),
    CONSTRAINT job_runs_retry_count_check CHECK ((retry_count >= 0)),
    CONSTRAINT job_runs_run_status_check CHECK (((run_status)::text = ANY ((ARRAY['QUEUED'::character varying, 'RUNNING'::character varying, 'SUCCEEDED'::character varying, 'FAILED'::character varying, 'RETRYING'::character varying, 'CANCELED'::character varying])::text[])))
);


--
-- Name: job_runs_id_seq; Type: SEQUENCE; Schema: ai; Owner: -
--

CREATE SEQUENCE ai.job_runs_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: job_runs_id_seq; Type: SEQUENCE OWNED BY; Schema: ai; Owner: -
--

ALTER SEQUENCE ai.job_runs_id_seq OWNED BY ai.job_runs.id;


--
-- Name: llm_runs; Type: TABLE; Schema: ai; Owner: -
--

CREATE TABLE ai.llm_runs (
    id bigint NOT NULL,
    public_id uuid DEFAULT gen_random_uuid() NOT NULL,
    job_run_public_id uuid,
    session_public_id uuid,
    user_public_id uuid,
    prompt_version_public_id uuid,
    domain character varying(50) NOT NULL,
    purpose character varying(80) NOT NULL,
    provider character varying(50) NOT NULL,
    model character varying(100) NOT NULL,
    temperature numeric(4,3),
    input_tokens integer,
    output_tokens integer,
    latency_ms integer,
    input_hash character varying(255),
    masked_input jsonb,
    raw_output jsonb,
    parsed_output jsonb,
    run_status character varying(30) NOT NULL,
    last_error text,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT llm_runs_domain_check CHECK (((domain)::text = ANY ((ARRAY['INFRAOPS'::character varying, 'RISKOPS'::character varying, 'FARMER_BNPL'::character varying, 'FARMER_CHECKOUT'::character varying, 'FARM_ADVISORY'::character varying, 'REPORT'::character varying, 'ONCALL'::character varying, 'PREDICTION_SCALING'::character varying])::text[]))),
    CONSTRAINT llm_runs_purpose_check CHECK (((purpose)::text = ANY ((ARRAY['RCA'::character varying, 'DAILY_REPORT'::character varying, 'WEEKLY_REPORT'::character varying, 'SCALING_REPORT'::character varying, 'ONCALL'::character varying, 'FARMER_CHAT'::character varying, 'FARMER_CHECKOUT_RECOMMENDATION'::character varying, 'RISK_ANALYSIS'::character varying, 'FARM_ADVISORY'::character varying])::text[]))),
    CONSTRAINT llm_runs_run_status_check CHECK (((run_status)::text = ANY ((ARRAY['SUCCESS'::character varying, 'FAILED'::character varying, 'VALIDATION_FAILED'::character varying])::text[])))
);


--
-- Name: llm_runs_id_seq; Type: SEQUENCE; Schema: ai; Owner: -
--

CREATE SEQUENCE ai.llm_runs_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: llm_runs_id_seq; Type: SEQUENCE OWNED BY; Schema: ai; Owner: -
--

ALTER SEQUENCE ai.llm_runs_id_seq OWNED BY ai.llm_runs.id;


--
-- Name: mcp_servers; Type: TABLE; Schema: ai; Owner: -
--

CREATE TABLE ai.mcp_servers (
    id bigint NOT NULL,
    public_id uuid DEFAULT gen_random_uuid() NOT NULL,
    server_name character varying(100) NOT NULL,
    display_name character varying(100) NOT NULL,
    description text,
    base_url text,
    server_status character varying(30) DEFAULT 'ACTIVE'::character varying NOT NULL,
    server_metadata jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT mcp_servers_server_status_check CHECK (((server_status)::text = ANY ((ARRAY['ACTIVE'::character varying, 'INACTIVE'::character varying, 'DEPRECATED'::character varying])::text[])))
);


--
-- Name: mcp_servers_id_seq; Type: SEQUENCE; Schema: ai; Owner: -
--

CREATE SEQUENCE ai.mcp_servers_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: mcp_servers_id_seq; Type: SEQUENCE OWNED BY; Schema: ai; Owner: -
--

ALTER SEQUENCE ai.mcp_servers_id_seq OWNED BY ai.mcp_servers.id;


--
-- Name: mcp_tool_calls; Type: TABLE; Schema: ai; Owner: -
--

CREATE TABLE ai.mcp_tool_calls (
    id bigint NOT NULL,
    public_id uuid DEFAULT gen_random_uuid() NOT NULL,
    job_run_public_id uuid,
    llm_run_public_id uuid,
    session_public_id uuid,
    user_public_id uuid,
    mcp_server_public_id uuid NOT NULL,
    mcp_tool_public_id uuid NOT NULL,
    tool_name character varying(120) NOT NULL,
    tool_permission character varying(40) NOT NULL,
    confirmation_policy character varying(40) DEFAULT 'NONE'::character varying NOT NULL,
    request_payload jsonb,
    masked_request_payload jsonb,
    response_ref text,
    masked_response_payload jsonb,
    call_status character varying(30) NOT NULL,
    latency_ms integer,
    approval_request_public_id uuid,
    business_ref_public_id uuid,
    last_error text,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT mcp_tool_calls_call_status_check CHECK (((call_status)::text = ANY ((ARRAY['SUCCESS'::character varying, 'FAILED'::character varying, 'TIMEOUT'::character varying, 'BLOCKED'::character varying, 'APPROVAL_REQUIRED'::character varying])::text[]))),
    CONSTRAINT mcp_tool_calls_confirmation_policy_check CHECK (((confirmation_policy)::text = ANY ((ARRAY['NONE'::character varying, 'USER_CONFIRMATION'::character varying, 'ADMIN_APPROVAL'::character varying, 'BLOCKED'::character varying])::text[]))),
    CONSTRAINT mcp_tool_calls_tool_permission_check CHECK (((tool_permission)::text = ANY ((ARRAY['READ'::character varying, 'WRITE'::character varying, 'USER_CONFIRMED_WRITE'::character varying, 'OPS_WRITE'::character varying, 'DESTRUCTIVE'::character varying])::text[])))
);


--
-- Name: mcp_tool_calls_id_seq; Type: SEQUENCE; Schema: ai; Owner: -
--

CREATE SEQUENCE ai.mcp_tool_calls_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: mcp_tool_calls_id_seq; Type: SEQUENCE OWNED BY; Schema: ai; Owner: -
--

ALTER SEQUENCE ai.mcp_tool_calls_id_seq OWNED BY ai.mcp_tool_calls.id;


--
-- Name: mcp_tools; Type: TABLE; Schema: ai; Owner: -
--

CREATE TABLE ai.mcp_tools (
    id bigint NOT NULL,
    public_id uuid DEFAULT gen_random_uuid() NOT NULL,
    mcp_server_public_id uuid NOT NULL,
    tool_name character varying(120) NOT NULL,
    display_name character varying(120),
    description text,
    tool_permission character varying(40) NOT NULL,
    input_schema jsonb DEFAULT '{}'::jsonb NOT NULL,
    output_schema jsonb DEFAULT '{}'::jsonb NOT NULL,
    tool_status character varying(30) DEFAULT 'ACTIVE'::character varying NOT NULL,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT mcp_tools_tool_permission_check CHECK (((tool_permission)::text = ANY ((ARRAY['READ'::character varying, 'WRITE'::character varying, 'USER_CONFIRMED_WRITE'::character varying, 'OPS_WRITE'::character varying, 'DESTRUCTIVE'::character varying])::text[]))),
    CONSTRAINT mcp_tools_tool_status_check CHECK (((tool_status)::text = ANY ((ARRAY['ACTIVE'::character varying, 'INACTIVE'::character varying, 'DEPRECATED'::character varying])::text[])))
);


--
-- Name: mcp_tools_id_seq; Type: SEQUENCE; Schema: ai; Owner: -
--

CREATE SEQUENCE ai.mcp_tools_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: mcp_tools_id_seq; Type: SEQUENCE OWNED BY; Schema: ai; Owner: -
--

ALTER SEQUENCE ai.mcp_tools_id_seq OWNED BY ai.mcp_tools.id;


--
-- Name: model_versions; Type: TABLE; Schema: ai; Owner: -
--

CREATE TABLE ai.model_versions (
    id bigint NOT NULL,
    public_id uuid DEFAULT gen_random_uuid() NOT NULL,
    model_name character varying(100) NOT NULL,
    model_version character varying(80) NOT NULL,
    model_type character varying(50) NOT NULL,
    artifact_path text NOT NULL,
    target_metric character varying(100) NOT NULL,
    model_status character varying(30) NOT NULL,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT model_versions_model_status_check CHECK (((model_status)::text = ANY ((ARRAY['ACTIVE'::character varying, 'INACTIVE'::character varying, 'DEPRECATED'::character varying])::text[])))
);


--
-- Name: model_versions_id_seq; Type: SEQUENCE; Schema: ai; Owner: -
--

CREATE SEQUENCE ai.model_versions_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: model_versions_id_seq; Type: SEQUENCE OWNED BY; Schema: ai; Owner: -
--

ALTER SEQUENCE ai.model_versions_id_seq OWNED BY ai.model_versions.id;


--
-- Name: notification_outbox; Type: TABLE; Schema: ai; Owner: -
--

CREATE TABLE ai.notification_outbox (
    id bigint NOT NULL,
    public_id uuid DEFAULT gen_random_uuid() NOT NULL,
    notification_channel character varying(30) NOT NULL,
    user_public_id uuid,
    target_recipient character varying(255),
    title character varying(255),
    content text NOT NULL,
    message_payload jsonb DEFAULT '{}'::jsonb NOT NULL,
    send_status character varying(30) DEFAULT 'PENDING'::character varying NOT NULL,
    related_table character varying(100),
    related_public_id uuid,
    idempotency_key character varying(255),
    retry_count integer DEFAULT 0 NOT NULL,
    max_retry_count integer DEFAULT 5 NOT NULL,
    scheduled_at timestamp without time zone,
    sent_at timestamp without time zone,
    last_error text,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT notification_outbox_max_retry_count_check CHECK ((max_retry_count >= 0)),
    CONSTRAINT notification_outbox_notification_channel_check CHECK (((notification_channel)::text = ANY ((ARRAY['SLACK'::character varying, 'EMAIL'::character varying, 'WEBHOOK'::character varying, 'DASHBOARD'::character varying])::text[]))),
    CONSTRAINT notification_outbox_retry_count_check CHECK ((retry_count >= 0)),
    CONSTRAINT notification_outbox_send_status_check CHECK (((send_status)::text = ANY ((ARRAY['PENDING'::character varying, 'SENT'::character varying, 'FAILED'::character varying, 'RETRYING'::character varying, 'CANCELED'::character varying])::text[])))
);


--
-- Name: notification_outbox_id_seq; Type: SEQUENCE; Schema: ai; Owner: -
--

CREATE SEQUENCE ai.notification_outbox_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: notification_outbox_id_seq; Type: SEQUENCE OWNED BY; Schema: ai; Owner: -
--

ALTER SEQUENCE ai.notification_outbox_id_seq OWNED BY ai.notification_outbox.id;


--
-- Name: observability_snapshots; Type: TABLE; Schema: ai; Owner: -
--

CREATE TABLE ai.observability_snapshots (
    id bigint NOT NULL,
    public_id uuid DEFAULT gen_random_uuid() NOT NULL,
    incident_public_id uuid,
    snapshot_type character varying(50) NOT NULL,
    time_start timestamp without time zone NOT NULL,
    time_end timestamp without time zone NOT NULL,
    snapshot_status character varying(30) NOT NULL,
    masked boolean DEFAULT true NOT NULL,
    summary text,
    created_by_job_public_id uuid,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    session_public_id uuid,
    llm_run_public_id uuid,
    snapshot_payload jsonb DEFAULT '{}'::jsonb NOT NULL,
    CONSTRAINT observability_snapshots_snapshot_status_check CHECK (((snapshot_status)::text = ANY ((ARRAY['COLLECTING'::character varying, 'COMPLETED'::character varying, 'FAILED'::character varying])::text[]))),
    CONSTRAINT observability_snapshots_snapshot_type_check CHECK (((snapshot_type)::text = ANY ((ARRAY['RCA'::character varying, 'REPORT'::character varying, 'ONCALL'::character varying, 'RISKOPS'::character varying, 'FARM_ADVISORY'::character varying, 'PREDICTION_SCALING'::character varying, 'BUSINESS'::character varying])::text[])))
);


--
-- Name: observability_snapshots_id_seq; Type: SEQUENCE; Schema: ai; Owner: -
--

CREATE SEQUENCE ai.observability_snapshots_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: observability_snapshots_id_seq; Type: SEQUENCE OWNED BY; Schema: ai; Owner: -
--

ALTER SEQUENCE ai.observability_snapshots_id_seq OWNED BY ai.observability_snapshots.id;


--
-- Name: ops_report_rca_refs; Type: TABLE; Schema: ai; Owner: -
--

CREATE TABLE ai.ops_report_rca_refs (
    id bigint NOT NULL,
    public_id uuid DEFAULT gen_random_uuid() NOT NULL,
    report_public_id uuid NOT NULL,
    rca_report_public_id uuid NOT NULL,
    incident_public_id uuid NOT NULL,
    included_reason text,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);


--
-- Name: ops_report_rca_refs_id_seq; Type: SEQUENCE; Schema: ai; Owner: -
--

CREATE SEQUENCE ai.ops_report_rca_refs_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: ops_report_rca_refs_id_seq; Type: SEQUENCE OWNED BY; Schema: ai; Owner: -
--

ALTER SEQUENCE ai.ops_report_rca_refs_id_seq OWNED BY ai.ops_report_rca_refs.id;


--
-- Name: ops_reports; Type: TABLE; Schema: ai; Owner: -
--

CREATE TABLE ai.ops_reports (
    id bigint NOT NULL,
    public_id uuid DEFAULT gen_random_uuid() NOT NULL,
    report_type character varying(40) NOT NULL,
    period_start timestamp without time zone NOT NULL,
    period_end timestamp without time zone NOT NULL,
    timezone character varying(50) DEFAULT 'Asia/Seoul'::character varying NOT NULL,
    title character varying(255) NOT NULL,
    summary text,
    sections jsonb DEFAULT '[]'::jsonb NOT NULL,
    metrics jsonb DEFAULT '{}'::jsonb NOT NULL,
    llm_run_public_id uuid,
    report_status character varying(30) NOT NULL,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT ops_reports_report_status_check CHECK (((report_status)::text = ANY ((ARRAY['DRAFT'::character varying, 'COMPLETED'::character varying, 'SENT'::character varying, 'FAILED'::character varying])::text[]))),
    CONSTRAINT ops_reports_report_type_check CHECK (((report_type)::text = ANY ((ARRAY['DAILY'::character varying, 'WEEKLY'::character varying, 'SCALING'::character varying, 'RISKOPS'::character varying])::text[])))
);


--
-- Name: ops_reports_id_seq; Type: SEQUENCE; Schema: ai; Owner: -
--

CREATE SEQUENCE ai.ops_reports_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: ops_reports_id_seq; Type: SEQUENCE OWNED BY; Schema: ai; Owner: -
--

ALTER SEQUENCE ai.ops_reports_id_seq OWNED BY ai.ops_reports.id;


--
-- Name: payment_request_publish_events; Type: TABLE; Schema: ai; Owner: -
--

CREATE TABLE ai.payment_request_publish_events (
    id bigint NOT NULL,
    public_id uuid DEFAULT gen_random_uuid() NOT NULL,
    draft_public_id uuid NOT NULL,
    payment_request_public_id uuid,
    event_type character varying(50) NOT NULL,
    kafka_topic character varying(150),
    message_key character varying(255),
    payload_ref text,
    publish_status character varying(30) NOT NULL,
    last_error text,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT payment_request_publish_events_event_type_check CHECK (((event_type)::text = ANY ((ARRAY['PAYMENT_REQUESTED'::character varying, 'PAYMENT_PUBLISH_FAILED'::character varying, 'PAYMENT_ACKNOWLEDGED'::character varying])::text[]))),
    CONSTRAINT payment_request_publish_events_publish_status_check CHECK (((publish_status)::text = ANY ((ARRAY['PENDING'::character varying, 'PUBLISHED'::character varying, 'FAILED'::character varying, 'ACKNOWLEDGED'::character varying])::text[])))
);


--
-- Name: payment_request_publish_events_id_seq; Type: SEQUENCE; Schema: ai; Owner: -
--

CREATE SEQUENCE ai.payment_request_publish_events_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: payment_request_publish_events_id_seq; Type: SEQUENCE OWNED BY; Schema: ai; Owner: -
--

ALTER SEQUENCE ai.payment_request_publish_events_id_seq OWNED BY ai.payment_request_publish_events.id;


--
-- Name: prediction_error_metrics; Type: TABLE; Schema: ai; Owner: -
--

CREATE TABLE ai.prediction_error_metrics (
    id bigint NOT NULL,
    public_id uuid DEFAULT gen_random_uuid() NOT NULL,
    prediction_metric_public_id uuid NOT NULL,
    actual_metric_public_id uuid NOT NULL,
    error_value numeric(18,6) NOT NULL,
    absolute_error numeric(18,6) NOT NULL,
    error_rate numeric(18,6),
    mape numeric(18,6),
    measured_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);


--
-- Name: prediction_error_metrics_id_seq; Type: SEQUENCE; Schema: ai; Owner: -
--

CREATE SEQUENCE ai.prediction_error_metrics_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: prediction_error_metrics_id_seq; Type: SEQUENCE OWNED BY; Schema: ai; Owner: -
--

ALTER SEQUENCE ai.prediction_error_metrics_id_seq OWNED BY ai.prediction_error_metrics.id;


--
-- Name: prediction_metrics; Type: TABLE; Schema: ai; Owner: -
--

CREATE TABLE ai.prediction_metrics (
    id bigint NOT NULL,
    public_id uuid DEFAULT gen_random_uuid() NOT NULL,
    prediction_run_public_id uuid NOT NULL,
    metric_name character varying(100) NOT NULL,
    namespace character varying(100) NOT NULL,
    service_name character varying(150) NOT NULL,
    predicted_value numeric(18,6) NOT NULL,
    target_time timestamp without time zone NOT NULL,
    model_version character varying(80) NOT NULL,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);


--
-- Name: prediction_metrics_id_seq; Type: SEQUENCE; Schema: ai; Owner: -
--

CREATE SEQUENCE ai.prediction_metrics_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: prediction_metrics_id_seq; Type: SEQUENCE OWNED BY; Schema: ai; Owner: -
--

ALTER SEQUENCE ai.prediction_metrics_id_seq OWNED BY ai.prediction_metrics.id;


--
-- Name: prediction_runs; Type: TABLE; Schema: ai; Owner: -
--

CREATE TABLE ai.prediction_runs (
    id bigint NOT NULL,
    public_id uuid DEFAULT gen_random_uuid() NOT NULL,
    model_version_public_id uuid NOT NULL,
    target_namespace character varying(100) NOT NULL,
    target_service character varying(150) NOT NULL,
    target_metric character varying(100) NOT NULL,
    input_window_start timestamp without time zone NOT NULL,
    input_window_end timestamp without time zone NOT NULL,
    prediction_horizon_minutes integer NOT NULL,
    run_status character varying(30) NOT NULL,
    started_at timestamp without time zone,
    finished_at timestamp without time zone,
    last_error text,
    CONSTRAINT prediction_runs_prediction_horizon_minutes_check CHECK ((prediction_horizon_minutes > 0)),
    CONSTRAINT prediction_runs_run_status_check CHECK (((run_status)::text = ANY ((ARRAY['QUEUED'::character varying, 'RUNNING'::character varying, 'SUCCEEDED'::character varying, 'FAILED'::character varying])::text[])))
);


--
-- Name: prediction_runs_id_seq; Type: SEQUENCE; Schema: ai; Owner: -
--

CREATE SEQUENCE ai.prediction_runs_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: prediction_runs_id_seq; Type: SEQUENCE OWNED BY; Schema: ai; Owner: -
--

ALTER SEQUENCE ai.prediction_runs_id_seq OWNED BY ai.prediction_runs.id;


--
-- Name: prompt_versions; Type: TABLE; Schema: ai; Owner: -
--

CREATE TABLE ai.prompt_versions (
    id bigint NOT NULL,
    public_id uuid DEFAULT gen_random_uuid() NOT NULL,
    prompt_key character varying(100) NOT NULL,
    prompt_version character varying(50) NOT NULL,
    domain character varying(50) NOT NULL,
    template text NOT NULL,
    prompt_metadata jsonb DEFAULT '{}'::jsonb NOT NULL,
    prompt_status character varying(30) DEFAULT 'ACTIVE'::character varying NOT NULL,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT prompt_versions_prompt_status_check CHECK (((prompt_status)::text = ANY ((ARRAY['ACTIVE'::character varying, 'INACTIVE'::character varying, 'DEPRECATED'::character varying])::text[])))
);


--
-- Name: prompt_versions_id_seq; Type: SEQUENCE; Schema: ai; Owner: -
--

CREATE SEQUENCE ai.prompt_versions_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: prompt_versions_id_seq; Type: SEQUENCE OWNED BY; Schema: ai; Owner: -
--

ALTER SEQUENCE ai.prompt_versions_id_seq OWNED BY ai.prompt_versions.id;


--
-- Name: rca_feedback; Type: TABLE; Schema: ai; Owner: -
--

CREATE TABLE ai.rca_feedback (
    id bigint NOT NULL,
    public_id uuid DEFAULT gen_random_uuid() NOT NULL,
    rca_report_public_id uuid NOT NULL,
    user_public_id uuid,
    rating integer,
    feedback text,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT rca_feedback_rating_check CHECK (((rating IS NULL) OR ((rating >= 1) AND (rating <= 5))))
);


--
-- Name: rca_feedback_id_seq; Type: SEQUENCE; Schema: ai; Owner: -
--

CREATE SEQUENCE ai.rca_feedback_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: rca_feedback_id_seq; Type: SEQUENCE OWNED BY; Schema: ai; Owner: -
--

ALTER SEQUENCE ai.rca_feedback_id_seq OWNED BY ai.rca_feedback.id;


--
-- Name: rca_reports; Type: TABLE; Schema: ai; Owner: -
--

CREATE TABLE ai.rca_reports (
    id bigint NOT NULL,
    public_id uuid DEFAULT gen_random_uuid() NOT NULL,
    incident_public_id uuid NOT NULL,
    llm_run_public_id uuid,
    snapshot_public_id uuid,
    report_status character varying(30) NOT NULL,
    summary text,
    probable_root_cause text,
    impact text,
    timeline jsonb DEFAULT '[]'::jsonb NOT NULL,
    evidence jsonb DEFAULT '[]'::jsonb NOT NULL,
    recommended_actions jsonb DEFAULT '[]'::jsonb NOT NULL,
    confidence numeric(4,3),
    prompt_version character varying(50),
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT rca_reports_confidence_check CHECK (((confidence IS NULL) OR ((confidence >= (0)::numeric) AND (confidence <= (1)::numeric)))),
    CONSTRAINT rca_reports_report_status_check CHECK (((report_status)::text = ANY ((ARRAY['DRAFT'::character varying, 'COMPLETED'::character varying, 'FAILED'::character varying, 'SUPERSEDED'::character varying])::text[])))
);


--
-- Name: rca_reports_id_seq; Type: SEQUENCE; Schema: ai; Owner: -
--

CREATE SEQUENCE ai.rca_reports_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: rca_reports_id_seq; Type: SEQUENCE OWNED BY; Schema: ai; Owner: -
--

ALTER SEQUENCE ai.rca_reports_id_seq OWNED BY ai.rca_reports.id;


--
-- Name: report_incidents; Type: TABLE; Schema: ai; Owner: -
--

CREATE TABLE ai.report_incidents (
    id bigint NOT NULL,
    public_id uuid DEFAULT gen_random_uuid() NOT NULL,
    report_public_id uuid NOT NULL,
    incident_public_id uuid NOT NULL,
    summary text,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);


--
-- Name: report_incidents_id_seq; Type: SEQUENCE; Schema: ai; Owner: -
--

CREATE SEQUENCE ai.report_incidents_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: report_incidents_id_seq; Type: SEQUENCE OWNED BY; Schema: ai; Owner: -
--

ALTER SEQUENCE ai.report_incidents_id_seq OWNED BY ai.report_incidents.id;


--
-- Name: report_metric_summaries; Type: TABLE; Schema: ai; Owner: -
--

CREATE TABLE ai.report_metric_summaries (
    id bigint NOT NULL,
    public_id uuid DEFAULT gen_random_uuid() NOT NULL,
    report_public_id uuid,
    snapshot_public_id uuid,
    source_type character varying(50) NOT NULL,
    namespace character varying(100),
    service_name character varying(150),
    metric_name character varying(150) NOT NULL,
    period_start timestamp without time zone NOT NULL,
    period_end timestamp without time zone NOT NULL,
    summary_values jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT report_metric_summaries_source_type_check CHECK (((source_type)::text = ANY ((ARRAY['ONPREM_PROMETHEUS'::character varying, 'AWS_PROMETHEUS'::character varying, 'ONPREM_LOKI'::character varying, 'AWS_LOKI'::character varying, 'ONPREM_ELASTICSEARCH'::character varying, 'AWS_ELASTICSEARCH'::character varying, 'DATABASE'::character varying, 'PREDICTION'::character varying, 'PREDICTION_ERROR'::character varying, 'KEDA'::character varying, 'HPA'::character varying, 'SCALING'::character varying])::text[])))
);


--
-- Name: report_metric_summaries_id_seq; Type: SEQUENCE; Schema: ai; Owner: -
--

CREATE SEQUENCE ai.report_metric_summaries_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: report_metric_summaries_id_seq; Type: SEQUENCE OWNED BY; Schema: ai; Owner: -
--

ALTER SEQUENCE ai.report_metric_summaries_id_seq OWNED BY ai.report_metric_summaries.id;


--
-- Name: risk_analysis_reports; Type: TABLE; Schema: ai; Owner: -
--

CREATE TABLE ai.risk_analysis_reports (
    id bigint NOT NULL,
    public_id uuid DEFAULT gen_random_uuid() NOT NULL,
    llm_run_public_id uuid,
    created_by_admin_public_id uuid,
    user_public_id uuid,
    application_public_id uuid,
    credit_limit_public_id uuid,
    disaster_simulation_public_id uuid,
    report_type character varying(40) NOT NULL,
    title character varying(255) NOT NULL,
    summary text,
    risk_level character varying(30) NOT NULL,
    metrics jsonb DEFAULT '{}'::jsonb NOT NULL,
    findings jsonb DEFAULT '[]'::jsonb NOT NULL,
    recommended_actions jsonb DEFAULT '[]'::jsonb NOT NULL,
    report_status character varying(30) NOT NULL,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT risk_analysis_reports_report_status_check CHECK (((report_status)::text = ANY ((ARRAY['DRAFT'::character varying, 'COMPLETED'::character varying, 'SENT'::character varying, 'FAILED'::character varying])::text[]))),
    CONSTRAINT risk_analysis_reports_report_type_check CHECK (((report_type)::text = ANY ((ARRAY['CREDIT_REVIEW'::character varying, 'OVERDUE'::character varying, 'DISASTER'::character varying, 'PORTFOLIO'::character varying])::text[]))),
    CONSTRAINT risk_analysis_reports_risk_level_check CHECK (((risk_level)::text = ANY ((ARRAY['LOW'::character varying, 'MEDIUM'::character varying, 'HIGH'::character varying, 'CRITICAL'::character varying])::text[])))
);


--
-- Name: risk_analysis_reports_id_seq; Type: SEQUENCE; Schema: ai; Owner: -
--

CREATE SEQUENCE ai.risk_analysis_reports_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: risk_analysis_reports_id_seq; Type: SEQUENCE OWNED BY; Schema: ai; Owner: -
--

ALTER SEQUENCE ai.risk_analysis_reports_id_seq OWNED BY ai.risk_analysis_reports.id;


--
-- Name: risk_analysis_targets; Type: TABLE; Schema: ai; Owner: -
--

CREATE TABLE ai.risk_analysis_targets (
    id bigint NOT NULL,
    public_id uuid DEFAULT gen_random_uuid() NOT NULL,
    risk_analysis_report_public_id uuid NOT NULL,
    target_table character varying(100) NOT NULL,
    target_public_id uuid NOT NULL,
    target_type character varying(80) NOT NULL,
    risk_score numeric(8,4),
    included_reason text,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);


--
-- Name: risk_analysis_targets_id_seq; Type: SEQUENCE; Schema: ai; Owner: -
--

CREATE SEQUENCE ai.risk_analysis_targets_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: risk_analysis_targets_id_seq; Type: SEQUENCE OWNED BY; Schema: ai; Owner: -
--

ALTER SEQUENCE ai.risk_analysis_targets_id_seq OWNED BY ai.risk_analysis_targets.id;


--
-- Name: scaling_events; Type: TABLE; Schema: ai; Owner: -
--

CREATE TABLE ai.scaling_events (
    id bigint NOT NULL,
    public_id uuid DEFAULT gen_random_uuid() NOT NULL,
    prediction_metric_public_id uuid,
    namespace character varying(100) NOT NULL,
    service_name character varying(150) NOT NULL,
    workload character varying(150) NOT NULL,
    source_type character varying(30) NOT NULL,
    previous_replicas integer,
    new_replicas integer,
    reason text,
    metric_name character varying(100),
    metric_value numeric(18,6),
    threshold numeric(18,6),
    event_time timestamp without time zone NOT NULL,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT scaling_events_source_type_check CHECK (((source_type)::text = ANY ((ARRAY['KEDA'::character varying, 'HPA'::character varying, 'MANUAL'::character varying, 'SYSTEM'::character varying])::text[])))
);


--
-- Name: scaling_events_id_seq; Type: SEQUENCE; Schema: ai; Owner: -
--

CREATE SEQUENCE ai.scaling_events_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: scaling_events_id_seq; Type: SEQUENCE OWNED BY; Schema: ai; Owner: -
--

ALTER SEQUENCE ai.scaling_events_id_seq OWNED BY ai.scaling_events.id;


--
-- Name: snapshot_items; Type: TABLE; Schema: ai; Owner: -
--

CREATE TABLE ai.snapshot_items (
    id bigint NOT NULL,
    public_id uuid DEFAULT gen_random_uuid() NOT NULL,
    snapshot_public_id uuid NOT NULL,
    source_type character varying(50) NOT NULL,
    tool_name character varying(120),
    query_text text,
    query_params jsonb DEFAULT '{}'::jsonb NOT NULL,
    raw_data jsonb,
    masked_data jsonb,
    summary text,
    data_hash character varying(255),
    last_error text,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT snapshot_items_source_type_check CHECK (((source_type)::text = ANY ((ARRAY['PROMETHEUS'::character varying, 'LOKI'::character varying, 'ELASTICSEARCH'::character varying, 'KIBANA'::character varying, 'LOGSTASH'::character varying, 'KUBERNETES'::character varying, 'DATABASE'::character varying, 'SPRING_API'::character varying, 'WEATHER'::character varying, 'PREDICTION'::character varying, 'KEDA'::character varying])::text[])))
);


--
-- Name: snapshot_items_id_seq; Type: SEQUENCE; Schema: ai; Owner: -
--

CREATE SEQUENCE ai.snapshot_items_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: snapshot_items_id_seq; Type: SEQUENCE OWNED BY; Schema: ai; Owner: -
--

ALTER SEQUENCE ai.snapshot_items_id_seq OWNED BY ai.snapshot_items.id;


--
-- Name: bnpl_payment_request_items; Type: TABLE; Schema: catalog; Owner: -
--

CREATE TABLE catalog.bnpl_payment_request_items (
    id bigint NOT NULL,
    payment_request_public_id uuid NOT NULL,
    product_public_id uuid NOT NULL,
    product_name_snapshot character varying(100) NOT NULL,
    unit_price_snapshot numeric(15,2) NOT NULL,
    quantity integer NOT NULL,
    total_price numeric(15,2) NOT NULL,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT bnpl_payment_request_items_quantity_check CHECK ((quantity > 0)),
    CONSTRAINT bnpl_payment_request_items_total_price_check CHECK ((total_price >= (0)::numeric)),
    CONSTRAINT bnpl_payment_request_items_unit_price_snapshot_check CHECK ((unit_price_snapshot >= (0)::numeric))
);


--
-- Name: bnpl_payment_request_items_id_seq; Type: SEQUENCE; Schema: catalog; Owner: -
--

CREATE SEQUENCE catalog.bnpl_payment_request_items_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: bnpl_payment_request_items_id_seq; Type: SEQUENCE OWNED BY; Schema: catalog; Owner: -
--

ALTER SEQUENCE catalog.bnpl_payment_request_items_id_seq OWNED BY catalog.bnpl_payment_request_items.id;


--
-- Name: bnpl_payment_requests; Type: TABLE; Schema: catalog; Owner: -
--

CREATE TABLE catalog.bnpl_payment_requests (
    id bigint NOT NULL,
    public_id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_public_id uuid NOT NULL,
    total_amount numeric(15,2) NOT NULL,
    request_status character varying(20) DEFAULT 'REQUESTED'::character varying NOT NULL,
    requested_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    processed_at timestamp without time zone,
    rejection_reason text,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT bnpl_payment_requests_request_status_check CHECK (((request_status)::text = ANY ((ARRAY['REQUESTED'::character varying, 'APPROVED'::character varying, 'REJECTED'::character varying, 'CANCELLED'::character varying])::text[]))),
    CONSTRAINT bnpl_payment_requests_total_amount_check CHECK ((total_amount > (0)::numeric))
);


--
-- Name: bnpl_payment_requests_id_seq; Type: SEQUENCE; Schema: catalog; Owner: -
--

CREATE SEQUENCE catalog.bnpl_payment_requests_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: bnpl_payment_requests_id_seq; Type: SEQUENCE OWNED BY; Schema: catalog; Owner: -
--

ALTER SEQUENCE catalog.bnpl_payment_requests_id_seq OWNED BY catalog.bnpl_payment_requests.id;


--
-- Name: cart_items; Type: TABLE; Schema: catalog; Owner: -
--

CREATE TABLE catalog.cart_items (
    id bigint NOT NULL,
    public_id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_public_id uuid NOT NULL,
    product_public_id uuid NOT NULL,
    quantity integer NOT NULL,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT cart_items_quantity_check CHECK ((quantity > 0))
);


--
-- Name: cart_items_id_seq; Type: SEQUENCE; Schema: catalog; Owner: -
--

CREATE SEQUENCE catalog.cart_items_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: cart_items_id_seq; Type: SEQUENCE OWNED BY; Schema: catalog; Owner: -
--

ALTER SEQUENCE catalog.cart_items_id_seq OWNED BY catalog.cart_items.id;


--
-- Name: categories; Type: TABLE; Schema: catalog; Owner: -
--

CREATE TABLE catalog.categories (
    id bigint NOT NULL,
    public_id uuid DEFAULT gen_random_uuid() NOT NULL,
    name character varying(100) NOT NULL,
    status character varying(20) DEFAULT 'ACTIVE'::character varying NOT NULL,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT categories_status_check CHECK (((status)::text = ANY ((ARRAY['ACTIVE'::character varying, 'INACTIVE'::character varying])::text[])))
);


--
-- Name: categories_id_seq; Type: SEQUENCE; Schema: catalog; Owner: -
--

CREATE SEQUENCE catalog.categories_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: categories_id_seq; Type: SEQUENCE OWNED BY; Schema: catalog; Owner: -
--

ALTER SEQUENCE catalog.categories_id_seq OWNED BY catalog.categories.id;


--
-- Name: products; Type: TABLE; Schema: catalog; Owner: -
--

CREATE TABLE catalog.products (
    id bigint NOT NULL,
    public_id uuid DEFAULT gen_random_uuid() NOT NULL,
    category_public_id uuid NOT NULL,
    name character varying(100) NOT NULL,
    description text,
    price numeric(15,2) NOT NULL,
    stock_quantity integer DEFAULT 0 NOT NULL,
    unit character varying(20) NOT NULL,
    image_url text,
    status character varying(20) DEFAULT 'ON_SALE'::character varying NOT NULL,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT products_price_check CHECK ((price >= (0)::numeric)),
    CONSTRAINT products_status_check CHECK (((status)::text = ANY ((ARRAY['ON_SALE'::character varying, 'SOLD_OUT'::character varying, 'HIDDEN'::character varying])::text[]))),
    CONSTRAINT products_stock_quantity_check CHECK ((stock_quantity >= 0))
);


--
-- Name: products_id_seq; Type: SEQUENCE; Schema: catalog; Owner: -
--

CREATE SEQUENCE catalog.products_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: products_id_seq; Type: SEQUENCE OWNED BY; Schema: catalog; Owner: -
--

ALTER SEQUENCE catalog.products_id_seq OWNED BY catalog.products.id;


--
-- Name: admin_users; Type: TABLE; Schema: core; Owner: -
--

CREATE TABLE core.admin_users (
    id bigint NOT NULL,
    public_id uuid DEFAULT gen_random_uuid() NOT NULL,
    email character varying(100) NOT NULL,
    password_hash character varying(255) NOT NULL,
    name character varying(100) NOT NULL,
    role character varying(30) NOT NULL,
    status character varying(20) DEFAULT 'ACTIVE'::character varying NOT NULL,
    last_login_at timestamp without time zone,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);


--
-- Name: admin_users_id_seq; Type: SEQUENCE; Schema: core; Owner: -
--

CREATE SEQUENCE core.admin_users_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: admin_users_id_seq; Type: SEQUENCE OWNED BY; Schema: core; Owner: -
--

ALTER SEQUENCE core.admin_users_id_seq OWNED BY core.admin_users.id;


--
-- Name: ass_scores; Type: TABLE; Schema: core; Owner: -
--

CREATE TABLE core.ass_scores (
    crop_score integer NOT NULL,
    farming_career_score integer NOT NULL,
    field_area_score integer NOT NULL,
    insurance_score integer NOT NULL,
    total_score integer NOT NULL,
    application_id bigint NOT NULL,
    created_at timestamp(6) without time zone NOT NULL,
    id bigint NOT NULL
);


--
-- Name: ass_scores_id_seq; Type: SEQUENCE; Schema: core; Owner: -
--

ALTER TABLE core.ass_scores ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME core.ass_scores_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: audit_logs; Type: TABLE; Schema: core; Owner: -
--

CREATE TABLE core.audit_logs (
    id bigint NOT NULL,
    public_id uuid DEFAULT gen_random_uuid() NOT NULL,
    admin_user_public_id uuid NOT NULL,
    user_public_id uuid,
    action character varying(50) NOT NULL,
    target_table character varying(100) NOT NULL,
    target_public_id uuid,
    before_data jsonb,
    after_data jsonb,
    ip_address character varying(50),
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);


--
-- Name: audit_logs_id_seq; Type: SEQUENCE; Schema: core; Owner: -
--

CREATE SEQUENCE core.audit_logs_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: audit_logs_id_seq; Type: SEQUENCE OWNED BY; Schema: core; Owner: -
--

ALTER SEQUENCE core.audit_logs_id_seq OWNED BY core.audit_logs.id;


--
-- Name: bss_scores; Type: TABLE; Schema: core; Owner: -
--

CREATE TABLE core.bss_scores (
    id bigint NOT NULL,
    public_id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_public_id uuid NOT NULL,
    application_public_id uuid,
    period_type character varying(20) NOT NULL,
    period_year integer NOT NULL,
    period_month integer,
    monthly_score integer,
    annual_score integer,
    total_score integer NOT NULL,
    calculated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT bss_scores_check CHECK (((((period_type)::text = 'MONTHLY'::text) AND (period_month IS NOT NULL)) OR (((period_type)::text = 'ANNUAL'::text) AND (period_month IS NULL)))),
    CONSTRAINT bss_scores_period_month_check CHECK (((period_month >= 1) AND (period_month <= 12))),
    CONSTRAINT bss_scores_period_type_check CHECK (((period_type)::text = ANY ((ARRAY['MONTHLY'::character varying, 'ANNUAL'::character varying])::text[])))
);


--
-- Name: bss_scores_id_seq; Type: SEQUENCE; Schema: core; Owner: -
--

CREATE SEQUENCE core.bss_scores_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: bss_scores_id_seq; Type: SEQUENCE OWNED BY; Schema: core; Owner: -
--

ALTER SEQUENCE core.bss_scores_id_seq OWNED BY core.bss_scores.id;


--
-- Name: credit_limit_applications; Type: TABLE; Schema: core; Owner: -
--

CREATE TABLE core.credit_limit_applications (
    applied_at timestamp(6) without time zone NOT NULL,
    created_at timestamp(6) without time zone NOT NULL,
    id bigint NOT NULL,
    updated_at timestamp(6) without time zone NOT NULL,
    user_id bigint NOT NULL,
    public_id uuid NOT NULL,
    status character varying(255) NOT NULL,
    CONSTRAINT credit_limit_applications_status_check CHECK (((status)::text = ANY ((ARRAY['PENDING'::character varying, 'APPROVED'::character varying, 'REJECTED'::character varying])::text[])))
);


--
-- Name: credit_limit_applications_id_seq; Type: SEQUENCE; Schema: core; Owner: -
--

ALTER TABLE core.credit_limit_applications ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME core.credit_limit_applications_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: credit_limits; Type: TABLE; Schema: core; Owner: -
--

CREATE TABLE core.credit_limits (
    id bigint NOT NULL,
    public_id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_public_id uuid NOT NULL,
    application_public_id uuid NOT NULL,
    crop_type_snapshot character varying(30) NOT NULL,
    total_limit numeric(15,2) NOT NULL,
    used_amount numeric(15,2) DEFAULT 0 NOT NULL,
    interest_rate numeric(6,4) NOT NULL,
    interest_due_day integer NOT NULL,
    principal_due_date date NOT NULL,
    expires_at date,
    status character varying(20) DEFAULT 'ACTIVE'::character varying NOT NULL,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT credit_limits_check CHECK ((used_amount <= total_limit)),
    CONSTRAINT credit_limits_crop_type_snapshot_check CHECK (((crop_type_snapshot)::text = ANY ((ARRAY['RICE'::character varying, 'PEPPER'::character varying, 'SOYBEAN'::character varying, 'GARLIC'::character varying, 'ONION'::character varying])::text[]))),
    CONSTRAINT credit_limits_interest_due_day_check CHECK (((interest_due_day >= 1) AND (interest_due_day <= 28))),
    CONSTRAINT credit_limits_interest_rate_check CHECK ((interest_rate >= (0)::numeric)),
    CONSTRAINT credit_limits_status_check CHECK (((status)::text = ANY ((ARRAY['ACTIVE'::character varying, 'SUSPENDED'::character varying, 'REPAID'::character varying, 'EXPIRED'::character varying])::text[]))),
    CONSTRAINT credit_limits_total_limit_check CHECK ((total_limit > (0)::numeric)),
    CONSTRAINT credit_limits_used_amount_check CHECK ((used_amount >= (0)::numeric))
);


--
-- Name: credit_limits_id_seq; Type: SEQUENCE; Schema: core; Owner: -
--

CREATE SEQUENCE core.credit_limits_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: credit_limits_id_seq; Type: SEQUENCE OWNED BY; Schema: core; Owner: -
--

ALTER SEQUENCE core.credit_limits_id_seq OWNED BY core.credit_limits.id;


--
-- Name: credit_usage_ledger; Type: TABLE; Schema: core; Owner: -
--

CREATE TABLE core.credit_usage_ledger (
    id bigint NOT NULL,
    public_id uuid DEFAULT gen_random_uuid() NOT NULL,
    credit_limit_public_id uuid NOT NULL,
    payment_request_public_id uuid,
    order_public_id uuid,
    amount numeric(15,2) NOT NULL,
    usage_type character varying(20) NOT NULL,
    used_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT credit_usage_ledger_amount_check CHECK ((amount > (0)::numeric)),
    CONSTRAINT credit_usage_ledger_check CHECK (((((usage_type)::text = 'PURCHASE'::text) AND (payment_request_public_id IS NOT NULL) AND (order_public_id IS NOT NULL)) OR ((usage_type)::text <> 'PURCHASE'::text))),
    CONSTRAINT credit_usage_ledger_usage_type_check CHECK (((usage_type)::text = ANY ((ARRAY['PURCHASE'::character varying, 'CANCEL'::character varying, 'ADJUSTMENT'::character varying])::text[])))
);


--
-- Name: credit_usage_ledger_id_seq; Type: SEQUENCE; Schema: core; Owner: -
--

CREATE SEQUENCE core.credit_usage_ledger_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: credit_usage_ledger_id_seq; Type: SEQUENCE OWNED BY; Schema: core; Owner: -
--

ALTER SEQUENCE core.credit_usage_ledger_id_seq OWNED BY core.credit_usage_ledger.id;


--
-- Name: crop_repayment_policies; Type: TABLE; Schema: core; Owner: -
--

CREATE TABLE core.crop_repayment_policies (
    id bigint NOT NULL,
    public_id uuid DEFAULT gen_random_uuid() NOT NULL,
    crop_type character varying(30) NOT NULL,
    crop_name character varying(50) NOT NULL,
    harvest_start_month integer NOT NULL,
    harvest_end_month integer NOT NULL,
    sales_start_month integer NOT NULL,
    sales_end_month integer NOT NULL,
    repayment_due_month integer NOT NULL,
    repayment_due_day integer NOT NULL,
    description text,
    status character varying(20) DEFAULT 'ACTIVE'::character varying NOT NULL,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT crop_repayment_policies_crop_type_check CHECK (((crop_type)::text = ANY ((ARRAY['RICE'::character varying, 'PEPPER'::character varying, 'SOYBEAN'::character varying, 'GARLIC'::character varying, 'ONION'::character varying])::text[]))),
    CONSTRAINT crop_repayment_policies_harvest_end_month_check CHECK (((harvest_end_month >= 1) AND (harvest_end_month <= 12))),
    CONSTRAINT crop_repayment_policies_harvest_start_month_check CHECK (((harvest_start_month >= 1) AND (harvest_start_month <= 12))),
    CONSTRAINT crop_repayment_policies_repayment_due_day_check CHECK (((repayment_due_day >= 1) AND (repayment_due_day <= 31))),
    CONSTRAINT crop_repayment_policies_repayment_due_month_check CHECK (((repayment_due_month >= 1) AND (repayment_due_month <= 12))),
    CONSTRAINT crop_repayment_policies_sales_end_month_check CHECK (((sales_end_month >= 1) AND (sales_end_month <= 12))),
    CONSTRAINT crop_repayment_policies_sales_start_month_check CHECK (((sales_start_month >= 1) AND (sales_start_month <= 12))),
    CONSTRAINT crop_repayment_policies_status_check CHECK (((status)::text = ANY ((ARRAY['ACTIVE'::character varying, 'INACTIVE'::character varying])::text[])))
);


--
-- Name: crop_repayment_policies_id_seq; Type: SEQUENCE; Schema: core; Owner: -
--

CREATE SEQUENCE core.crop_repayment_policies_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: crop_repayment_policies_id_seq; Type: SEQUENCE OWNED BY; Schema: core; Owner: -
--

ALTER SEQUENCE core.crop_repayment_policies_id_seq OWNED BY core.crop_repayment_policies.id;


--
-- Name: farmer_documents; Type: TABLE; Schema: core; Owner: -
--

CREATE TABLE core.farmer_documents (
    application_id bigint NOT NULL,
    created_at timestamp(6) without time zone NOT NULL,
    id bigint NOT NULL,
    updated_at timestamp(6) without time zone NOT NULL,
    document_type character varying(255) NOT NULL,
    file_url character varying(255) NOT NULL,
    CONSTRAINT farmer_documents_document_type_check CHECK (((document_type)::text = ANY ((ARRAY['AGRI_MANAGEMENT_REGISTRATION'::character varying, 'CROP_DISASTER_INSURANCE'::character varying])::text[])))
);


--
-- Name: farmer_documents_id_seq; Type: SEQUENCE; Schema: core; Owner: -
--

ALTER TABLE core.farmer_documents ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME core.farmer_documents_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: farmer_profiles; Type: TABLE; Schema: core; Owner: -
--

CREATE TABLE core.farmer_profiles (
    farming_since date,
    field_aream2 numeric(38,2) NOT NULL,
    has_crop_insurance boolean NOT NULL,
    created_at timestamp(6) without time zone NOT NULL,
    id bigint NOT NULL,
    updated_at timestamp(6) without time zone NOT NULL,
    user_id bigint NOT NULL,
    farm_address character varying(255) NOT NULL,
    main_crop character varying(255) NOT NULL,
    CONSTRAINT farmer_profiles_main_crop_check CHECK (((main_crop)::text = ANY ((ARRAY['RICE'::character varying, 'BEAN'::character varying, 'PEPPER'::character varying, 'ONION'::character varying, 'GARLIC'::character varying, 'CUSTOM'::character varying])::text[])))
);


--
-- Name: farmer_profiles_id_seq; Type: SEQUENCE; Schema: core; Owner: -
--

ALTER TABLE core.farmer_profiles ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME core.farmer_profiles_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: interest_ledger; Type: TABLE; Schema: core; Owner: -
--

CREATE TABLE core.interest_ledger (
    id bigint NOT NULL,
    public_id uuid DEFAULT gen_random_uuid() NOT NULL,
    credit_limit_public_id uuid NOT NULL,
    base_principal numeric(15,2) NOT NULL,
    due_date date NOT NULL,
    interest_amount numeric(15,2) NOT NULL,
    amount_paid numeric(15,2) DEFAULT 0 NOT NULL,
    paid_at timestamp without time zone,
    status character varying(20) DEFAULT 'UPCOMING'::character varying NOT NULL,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT interest_ledger_amount_paid_check CHECK ((amount_paid >= (0)::numeric)),
    CONSTRAINT interest_ledger_base_principal_check CHECK ((base_principal >= (0)::numeric)),
    CONSTRAINT interest_ledger_check CHECK ((amount_paid <= interest_amount)),
    CONSTRAINT interest_ledger_interest_amount_check CHECK ((interest_amount >= (0)::numeric)),
    CONSTRAINT interest_ledger_status_check CHECK (((status)::text = ANY ((ARRAY['UPCOMING'::character varying, 'PARTIAL'::character varying, 'PAID'::character varying, 'OVERDUE'::character varying])::text[])))
);


--
-- Name: interest_ledger_id_seq; Type: SEQUENCE; Schema: core; Owner: -
--

CREATE SEQUENCE core.interest_ledger_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: interest_ledger_id_seq; Type: SEQUENCE OWNED BY; Schema: core; Owner: -
--

ALTER SEQUENCE core.interest_ledger_id_seq OWNED BY core.interest_ledger.id;


--
-- Name: loan_overdue_ledger; Type: TABLE; Schema: core; Owner: -
--

CREATE TABLE core.loan_overdue_ledger (
    id bigint NOT NULL,
    public_id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_public_id uuid NOT NULL,
    credit_limit_public_id uuid NOT NULL,
    interest_ledger_public_id uuid,
    principal_repayment_public_id uuid,
    overdue_type character varying(20) NOT NULL,
    overdue_amount numeric(15,2) NOT NULL,
    overdue_days integer NOT NULL,
    stage character varying(20) NOT NULL,
    penalty_rate numeric(6,4) NOT NULL,
    penalty_amount numeric(15,2) DEFAULT 0 NOT NULL,
    action_taken text,
    resolved_at timestamp without time zone,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT loan_overdue_ledger_check CHECK (((((overdue_type)::text = 'INTEREST'::text) AND (interest_ledger_public_id IS NOT NULL) AND (principal_repayment_public_id IS NULL)) OR (((overdue_type)::text = 'PRINCIPAL'::text) AND (principal_repayment_public_id IS NOT NULL) AND (interest_ledger_public_id IS NULL)))),
    CONSTRAINT loan_overdue_ledger_overdue_amount_check CHECK ((overdue_amount > (0)::numeric)),
    CONSTRAINT loan_overdue_ledger_overdue_days_check CHECK ((overdue_days >= 0)),
    CONSTRAINT loan_overdue_ledger_overdue_type_check CHECK (((overdue_type)::text = ANY ((ARRAY['INTEREST'::character varying, 'PRINCIPAL'::character varying])::text[]))),
    CONSTRAINT loan_overdue_ledger_penalty_amount_check CHECK ((penalty_amount >= (0)::numeric)),
    CONSTRAINT loan_overdue_ledger_penalty_rate_check CHECK ((penalty_rate >= (0)::numeric))
);


--
-- Name: loan_overdue_ledger_id_seq; Type: SEQUENCE; Schema: core; Owner: -
--

CREATE SEQUENCE core.loan_overdue_ledger_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: loan_overdue_ledger_id_seq; Type: SEQUENCE OWNED BY; Schema: core; Owner: -
--

ALTER SEQUENCE core.loan_overdue_ledger_id_seq OWNED BY core.loan_overdue_ledger.id;


--
-- Name: notifications; Type: TABLE; Schema: core; Owner: -
--

CREATE TABLE core.notifications (
    id bigint NOT NULL,
    public_id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_public_id uuid NOT NULL,
    title character varying(100) NOT NULL,
    content text NOT NULL,
    notification_type character varying(30) NOT NULL,
    is_read boolean DEFAULT false NOT NULL,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    read_at timestamp without time zone
);


--
-- Name: notifications_id_seq; Type: SEQUENCE; Schema: core; Owner: -
--

CREATE SEQUENCE core.notifications_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: notifications_id_seq; Type: SEQUENCE OWNED BY; Schema: core; Owner: -
--

ALTER SEQUENCE core.notifications_id_seq OWNED BY core.notifications.id;


--
-- Name: order_items; Type: TABLE; Schema: core; Owner: -
--

CREATE TABLE core.order_items (
    id bigint NOT NULL,
    order_public_id uuid NOT NULL,
    product_public_id uuid NOT NULL,
    product_name_snapshot character varying(100) NOT NULL,
    unit_price_snapshot numeric(15,2) NOT NULL,
    quantity integer NOT NULL,
    total_price numeric(15,2) NOT NULL,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT order_items_quantity_check CHECK ((quantity > 0)),
    CONSTRAINT order_items_total_price_check CHECK ((total_price >= (0)::numeric)),
    CONSTRAINT order_items_unit_price_snapshot_check CHECK ((unit_price_snapshot >= (0)::numeric))
);


--
-- Name: order_items_id_seq; Type: SEQUENCE; Schema: core; Owner: -
--

CREATE SEQUENCE core.order_items_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: order_items_id_seq; Type: SEQUENCE OWNED BY; Schema: core; Owner: -
--

ALTER SEQUENCE core.order_items_id_seq OWNED BY core.order_items.id;


--
-- Name: orders; Type: TABLE; Schema: core; Owner: -
--

CREATE TABLE core.orders (
    id bigint NOT NULL,
    public_id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_public_id uuid NOT NULL,
    payment_request_public_id uuid NOT NULL,
    total_amount numeric(15,2) NOT NULL,
    order_status character varying(20) DEFAULT 'CONFIRMED'::character varying NOT NULL,
    delivery_status character varying(20) DEFAULT 'PREPARING'::character varying NOT NULL,
    recipient_name character varying(100) NOT NULL,
    recipient_phone character varying(30) NOT NULL,
    delivery_address character varying(255) NOT NULL,
    delivery_address_detail character varying(255),
    delivery_zip_code character varying(20) NOT NULL,
    ordered_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    cancelled_at timestamp without time zone,
    cancel_reason text,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT orders_delivery_status_check CHECK (((delivery_status)::text = ANY ((ARRAY['PREPARING'::character varying, 'SHIPPING'::character varying, 'DELIVERED'::character varying, 'CANCELLED'::character varying])::text[]))),
    CONSTRAINT orders_order_status_check CHECK (((order_status)::text = ANY ((ARRAY['CONFIRMED'::character varying, 'CANCELLED'::character varying])::text[]))),
    CONSTRAINT orders_total_amount_check CHECK ((total_amount >= (0)::numeric))
);


--
-- Name: orders_id_seq; Type: SEQUENCE; Schema: core; Owner: -
--

CREATE SEQUENCE core.orders_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: orders_id_seq; Type: SEQUENCE OWNED BY; Schema: core; Owner: -
--

ALTER SEQUENCE core.orders_id_seq OWNED BY core.orders.id;


--
-- Name: payment_event_process_logs; Type: TABLE; Schema: core; Owner: -
--

CREATE TABLE core.payment_event_process_logs (
    id bigint NOT NULL,
    event_id uuid NOT NULL,
    payment_request_public_id uuid NOT NULL,
    idempotency_key character varying(120) NOT NULL,
    status character varying(20) NOT NULL,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT payment_event_process_logs_status_check CHECK (((status)::text = ANY ((ARRAY['PROCESSED'::character varying, 'FAILED'::character varying])::text[])))
);


--
-- Name: payment_event_process_logs_id_seq; Type: SEQUENCE; Schema: core; Owner: -
--

CREATE SEQUENCE core.payment_event_process_logs_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: payment_event_process_logs_id_seq; Type: SEQUENCE OWNED BY; Schema: core; Owner: -
--

ALTER SEQUENCE core.payment_event_process_logs_id_seq OWNED BY core.payment_event_process_logs.id;


--
-- Name: principal_repayment_ledger; Type: TABLE; Schema: core; Owner: -
--

CREATE TABLE core.principal_repayment_ledger (
    id bigint NOT NULL,
    public_id uuid DEFAULT gen_random_uuid() NOT NULL,
    credit_limit_public_id uuid NOT NULL,
    order_public_id uuid NOT NULL,
    payment_request_public_id uuid,
    due_date date NOT NULL,
    principal_amount numeric(15,2) NOT NULL,
    amount_paid numeric(15,2) DEFAULT 0 NOT NULL,
    paid_at timestamp without time zone,
    status character varying(20) DEFAULT 'UPCOMING'::character varying NOT NULL,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT principal_repayment_ledger_amount_paid_check CHECK ((amount_paid >= (0)::numeric)),
    CONSTRAINT principal_repayment_ledger_check CHECK ((amount_paid <= principal_amount)),
    CONSTRAINT principal_repayment_ledger_principal_amount_check CHECK ((principal_amount >= (0)::numeric)),
    CONSTRAINT principal_repayment_ledger_status_check CHECK (((status)::text = ANY ((ARRAY['UPCOMING'::character varying, 'PARTIAL'::character varying, 'PAID'::character varying, 'OVERDUE'::character varying])::text[])))
);


--
-- Name: principal_repayment_ledger_id_seq; Type: SEQUENCE; Schema: core; Owner: -
--

CREATE SEQUENCE core.principal_repayment_ledger_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: principal_repayment_ledger_id_seq; Type: SEQUENCE OWNED BY; Schema: core; Owner: -
--

ALTER SEQUENCE core.principal_repayment_ledger_id_seq OWNED BY core.principal_repayment_ledger.id;


--
-- Name: user_auth; Type: TABLE; Schema: core; Owner: -
--

CREATE TABLE core.user_auth (
    id bigint NOT NULL,
    user_public_id uuid NOT NULL,
    pin_hash character varying(255),
    password_hash character varying(255),
    refresh_token text,
    pin_changed_at timestamp without time zone,
    last_login_at timestamp without time zone,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);


--
-- Name: user_auth_id_seq; Type: SEQUENCE; Schema: core; Owner: -
--

CREATE SEQUENCE core.user_auth_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: user_auth_id_seq; Type: SEQUENCE OWNED BY; Schema: core; Owner: -
--

ALTER SEQUENCE core.user_auth_id_seq OWNED BY core.user_auth.id;


--
-- Name: users; Type: TABLE; Schema: core; Owner: -
--

CREATE TABLE core.users (
    id bigint NOT NULL,
    public_id uuid DEFAULT gen_random_uuid() NOT NULL,
    name character varying(100) NOT NULL,
    phone character varying(30) NOT NULL,
    resident_id_hash character varying(255) NOT NULL,
    resident_id_enc character varying(500),
    address character varying(255) NOT NULL,
    address_detail character varying(255),
    zip_code character varying(20) NOT NULL,
    status character varying(20) DEFAULT 'ACTIVE'::character varying NOT NULL,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT users_status_check CHECK (((status)::text = ANY ((ARRAY['ACTIVE'::character varying, 'INACTIVE'::character varying, 'DELETED'::character varying, 'SUSPENDED'::character varying, 'WITHDRAWN'::character varying])::text[])))
);


--
-- Name: users_id_seq; Type: SEQUENCE; Schema: core; Owner: -
--

CREATE SEQUENCE core.users_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: users_id_seq; Type: SEQUENCE OWNED BY; Schema: core; Owner: -
--

ALTER SEQUENCE core.users_id_seq OWNED BY core.users.id;


--
-- Name: wallet_transactions; Type: TABLE; Schema: core; Owner: -
--

CREATE TABLE core.wallet_transactions (
    id bigint NOT NULL,
    public_id uuid DEFAULT gen_random_uuid() NOT NULL,
    wallet_public_id uuid NOT NULL,
    transaction_type character varying(30) NOT NULL,
    amount numeric(15,2) NOT NULL,
    balance_after numeric(15,2) NOT NULL,
    related_type character varying(50),
    related_public_id uuid,
    description text,
    transacted_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT wallet_transactions_amount_check CHECK ((amount > (0)::numeric)),
    CONSTRAINT wallet_transactions_balance_after_check CHECK ((balance_after >= (0)::numeric)),
    CONSTRAINT wallet_transactions_transaction_type_check CHECK (((transaction_type)::text = ANY ((ARRAY['DEPOSIT'::character varying, 'INTEREST_PAYMENT'::character varying, 'PRINCIPAL_PAYMENT'::character varying, 'REFUND'::character varying, 'ADJUSTMENT'::character varying])::text[])))
);


--
-- Name: wallet_transactions_id_seq; Type: SEQUENCE; Schema: core; Owner: -
--

CREATE SEQUENCE core.wallet_transactions_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: wallet_transactions_id_seq; Type: SEQUENCE OWNED BY; Schema: core; Owner: -
--

ALTER SEQUENCE core.wallet_transactions_id_seq OWNED BY core.wallet_transactions.id;


--
-- Name: wallets; Type: TABLE; Schema: core; Owner: -
--

CREATE TABLE core.wallets (
    id bigint NOT NULL,
    public_id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_public_id uuid NOT NULL,
    balance numeric(15,2) DEFAULT 0 NOT NULL,
    deposit_bank_name character varying(50) NOT NULL,
    deposit_account_number character varying(50) NOT NULL,
    status character varying(20) DEFAULT 'ACTIVE'::character varying NOT NULL,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT wallets_balance_check CHECK ((balance >= (0)::numeric)),
    CONSTRAINT wallets_status_check CHECK (((status)::text = ANY ((ARRAY['ACTIVE'::character varying, 'SUSPENDED'::character varying, 'CLOSED'::character varying])::text[])))
);


--
-- Name: wallets_id_seq; Type: SEQUENCE; Schema: core; Owner: -
--

CREATE SEQUENCE core.wallets_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: wallets_id_seq; Type: SEQUENCE OWNED BY; Schema: core; Owner: -
--

ALTER SEQUENCE core.wallets_id_seq OWNED BY core.wallets.id;


--
-- Name: actual_metrics id; Type: DEFAULT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.actual_metrics ALTER COLUMN id SET DEFAULT nextval('ai.actual_metrics_id_seq'::regclass);


--
-- Name: approval_actions id; Type: DEFAULT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.approval_actions ALTER COLUMN id SET DEFAULT nextval('ai.approval_actions_id_seq'::regclass);


--
-- Name: approval_requests id; Type: DEFAULT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.approval_requests ALTER COLUMN id SET DEFAULT nextval('ai.approval_requests_id_seq'::regclass);


--
-- Name: bnpl_payment_draft_items id; Type: DEFAULT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.bnpl_payment_draft_items ALTER COLUMN id SET DEFAULT nextval('ai.bnpl_payment_draft_items_id_seq'::regclass);


--
-- Name: bnpl_payment_drafts id; Type: DEFAULT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.bnpl_payment_drafts ALTER COLUMN id SET DEFAULT nextval('ai.bnpl_payment_drafts_id_seq'::regclass);


--
-- Name: business_entity_refs id; Type: DEFAULT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.business_entity_refs ALTER COLUMN id SET DEFAULT nextval('ai.business_entity_refs_id_seq'::regclass);


--
-- Name: chat_messages id; Type: DEFAULT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.chat_messages ALTER COLUMN id SET DEFAULT nextval('ai.chat_messages_id_seq'::regclass);


--
-- Name: chat_sessions id; Type: DEFAULT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.chat_sessions ALTER COLUMN id SET DEFAULT nextval('ai.chat_sessions_id_seq'::regclass);


--
-- Name: disaster_risk_simulations id; Type: DEFAULT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.disaster_risk_simulations ALTER COLUMN id SET DEFAULT nextval('ai.disaster_risk_simulations_id_seq'::regclass);


--
-- Name: farm_advisory_cases id; Type: DEFAULT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.farm_advisory_cases ALTER COLUMN id SET DEFAULT nextval('ai.farm_advisory_cases_id_seq'::regclass);


--
-- Name: farm_advisory_results id; Type: DEFAULT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.farm_advisory_results ALTER COLUMN id SET DEFAULT nextval('ai.farm_advisory_results_id_seq'::regclass);


--
-- Name: incident_alerts id; Type: DEFAULT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.incident_alerts ALTER COLUMN id SET DEFAULT nextval('ai.incident_alerts_id_seq'::regclass);


--
-- Name: incidents id; Type: DEFAULT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.incidents ALTER COLUMN id SET DEFAULT nextval('ai.incidents_id_seq'::regclass);


--
-- Name: job_runs id; Type: DEFAULT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.job_runs ALTER COLUMN id SET DEFAULT nextval('ai.job_runs_id_seq'::regclass);


--
-- Name: llm_runs id; Type: DEFAULT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.llm_runs ALTER COLUMN id SET DEFAULT nextval('ai.llm_runs_id_seq'::regclass);


--
-- Name: mcp_servers id; Type: DEFAULT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.mcp_servers ALTER COLUMN id SET DEFAULT nextval('ai.mcp_servers_id_seq'::regclass);


--
-- Name: mcp_tool_calls id; Type: DEFAULT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.mcp_tool_calls ALTER COLUMN id SET DEFAULT nextval('ai.mcp_tool_calls_id_seq'::regclass);


--
-- Name: mcp_tools id; Type: DEFAULT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.mcp_tools ALTER COLUMN id SET DEFAULT nextval('ai.mcp_tools_id_seq'::regclass);


--
-- Name: model_versions id; Type: DEFAULT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.model_versions ALTER COLUMN id SET DEFAULT nextval('ai.model_versions_id_seq'::regclass);


--
-- Name: notification_outbox id; Type: DEFAULT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.notification_outbox ALTER COLUMN id SET DEFAULT nextval('ai.notification_outbox_id_seq'::regclass);


--
-- Name: observability_snapshots id; Type: DEFAULT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.observability_snapshots ALTER COLUMN id SET DEFAULT nextval('ai.observability_snapshots_id_seq'::regclass);


--
-- Name: ops_report_rca_refs id; Type: DEFAULT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.ops_report_rca_refs ALTER COLUMN id SET DEFAULT nextval('ai.ops_report_rca_refs_id_seq'::regclass);


--
-- Name: ops_reports id; Type: DEFAULT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.ops_reports ALTER COLUMN id SET DEFAULT nextval('ai.ops_reports_id_seq'::regclass);


--
-- Name: payment_request_publish_events id; Type: DEFAULT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.payment_request_publish_events ALTER COLUMN id SET DEFAULT nextval('ai.payment_request_publish_events_id_seq'::regclass);


--
-- Name: prediction_error_metrics id; Type: DEFAULT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.prediction_error_metrics ALTER COLUMN id SET DEFAULT nextval('ai.prediction_error_metrics_id_seq'::regclass);


--
-- Name: prediction_metrics id; Type: DEFAULT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.prediction_metrics ALTER COLUMN id SET DEFAULT nextval('ai.prediction_metrics_id_seq'::regclass);


--
-- Name: prediction_runs id; Type: DEFAULT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.prediction_runs ALTER COLUMN id SET DEFAULT nextval('ai.prediction_runs_id_seq'::regclass);


--
-- Name: prompt_versions id; Type: DEFAULT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.prompt_versions ALTER COLUMN id SET DEFAULT nextval('ai.prompt_versions_id_seq'::regclass);


--
-- Name: rca_feedback id; Type: DEFAULT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.rca_feedback ALTER COLUMN id SET DEFAULT nextval('ai.rca_feedback_id_seq'::regclass);


--
-- Name: rca_reports id; Type: DEFAULT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.rca_reports ALTER COLUMN id SET DEFAULT nextval('ai.rca_reports_id_seq'::regclass);


--
-- Name: report_incidents id; Type: DEFAULT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.report_incidents ALTER COLUMN id SET DEFAULT nextval('ai.report_incidents_id_seq'::regclass);


--
-- Name: report_metric_summaries id; Type: DEFAULT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.report_metric_summaries ALTER COLUMN id SET DEFAULT nextval('ai.report_metric_summaries_id_seq'::regclass);


--
-- Name: risk_analysis_reports id; Type: DEFAULT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.risk_analysis_reports ALTER COLUMN id SET DEFAULT nextval('ai.risk_analysis_reports_id_seq'::regclass);


--
-- Name: risk_analysis_targets id; Type: DEFAULT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.risk_analysis_targets ALTER COLUMN id SET DEFAULT nextval('ai.risk_analysis_targets_id_seq'::regclass);


--
-- Name: scaling_events id; Type: DEFAULT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.scaling_events ALTER COLUMN id SET DEFAULT nextval('ai.scaling_events_id_seq'::regclass);


--
-- Name: snapshot_items id; Type: DEFAULT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.snapshot_items ALTER COLUMN id SET DEFAULT nextval('ai.snapshot_items_id_seq'::regclass);


--
-- Name: bnpl_payment_request_items id; Type: DEFAULT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.bnpl_payment_request_items ALTER COLUMN id SET DEFAULT nextval('catalog.bnpl_payment_request_items_id_seq'::regclass);


--
-- Name: bnpl_payment_requests id; Type: DEFAULT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.bnpl_payment_requests ALTER COLUMN id SET DEFAULT nextval('catalog.bnpl_payment_requests_id_seq'::regclass);


--
-- Name: cart_items id; Type: DEFAULT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.cart_items ALTER COLUMN id SET DEFAULT nextval('catalog.cart_items_id_seq'::regclass);


--
-- Name: categories id; Type: DEFAULT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.categories ALTER COLUMN id SET DEFAULT nextval('catalog.categories_id_seq'::regclass);


--
-- Name: products id; Type: DEFAULT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.products ALTER COLUMN id SET DEFAULT nextval('catalog.products_id_seq'::regclass);


--
-- Name: admin_users id; Type: DEFAULT; Schema: core; Owner: -
--

ALTER TABLE ONLY core.admin_users ALTER COLUMN id SET DEFAULT nextval('core.admin_users_id_seq'::regclass);


--
-- Name: audit_logs id; Type: DEFAULT; Schema: core; Owner: -
--

ALTER TABLE ONLY core.audit_logs ALTER COLUMN id SET DEFAULT nextval('core.audit_logs_id_seq'::regclass);


--
-- Name: bss_scores id; Type: DEFAULT; Schema: core; Owner: -
--

ALTER TABLE ONLY core.bss_scores ALTER COLUMN id SET DEFAULT nextval('core.bss_scores_id_seq'::regclass);


--
-- Name: credit_limits id; Type: DEFAULT; Schema: core; Owner: -
--

ALTER TABLE ONLY core.credit_limits ALTER COLUMN id SET DEFAULT nextval('core.credit_limits_id_seq'::regclass);


--
-- Name: credit_usage_ledger id; Type: DEFAULT; Schema: core; Owner: -
--

ALTER TABLE ONLY core.credit_usage_ledger ALTER COLUMN id SET DEFAULT nextval('core.credit_usage_ledger_id_seq'::regclass);


--
-- Name: crop_repayment_policies id; Type: DEFAULT; Schema: core; Owner: -
--

ALTER TABLE ONLY core.crop_repayment_policies ALTER COLUMN id SET DEFAULT nextval('core.crop_repayment_policies_id_seq'::regclass);


--
-- Name: interest_ledger id; Type: DEFAULT; Schema: core; Owner: -
--

ALTER TABLE ONLY core.interest_ledger ALTER COLUMN id SET DEFAULT nextval('core.interest_ledger_id_seq'::regclass);


--
-- Name: loan_overdue_ledger id; Type: DEFAULT; Schema: core; Owner: -
--

ALTER TABLE ONLY core.loan_overdue_ledger ALTER COLUMN id SET DEFAULT nextval('core.loan_overdue_ledger_id_seq'::regclass);


--
-- Name: notifications id; Type: DEFAULT; Schema: core; Owner: -
--

ALTER TABLE ONLY core.notifications ALTER COLUMN id SET DEFAULT nextval('core.notifications_id_seq'::regclass);


--
-- Name: order_items id; Type: DEFAULT; Schema: core; Owner: -
--

ALTER TABLE ONLY core.order_items ALTER COLUMN id SET DEFAULT nextval('core.order_items_id_seq'::regclass);


--
-- Name: orders id; Type: DEFAULT; Schema: core; Owner: -
--

ALTER TABLE ONLY core.orders ALTER COLUMN id SET DEFAULT nextval('core.orders_id_seq'::regclass);


--
-- Name: payment_event_process_logs id; Type: DEFAULT; Schema: core; Owner: -
--

ALTER TABLE ONLY core.payment_event_process_logs ALTER COLUMN id SET DEFAULT nextval('core.payment_event_process_logs_id_seq'::regclass);


--
-- Name: principal_repayment_ledger id; Type: DEFAULT; Schema: core; Owner: -
--

ALTER TABLE ONLY core.principal_repayment_ledger ALTER COLUMN id SET DEFAULT nextval('core.principal_repayment_ledger_id_seq'::regclass);


--
-- Name: user_auth id; Type: DEFAULT; Schema: core; Owner: -
--

ALTER TABLE ONLY core.user_auth ALTER COLUMN id SET DEFAULT nextval('core.user_auth_id_seq'::regclass);


--
-- Name: users id; Type: DEFAULT; Schema: core; Owner: -
--

ALTER TABLE ONLY core.users ALTER COLUMN id SET DEFAULT nextval('core.users_id_seq'::regclass);


--
-- Name: wallet_transactions id; Type: DEFAULT; Schema: core; Owner: -
--

ALTER TABLE ONLY core.wallet_transactions ALTER COLUMN id SET DEFAULT nextval('core.wallet_transactions_id_seq'::regclass);


--
-- Name: wallets id; Type: DEFAULT; Schema: core; Owner: -
--

ALTER TABLE ONLY core.wallets ALTER COLUMN id SET DEFAULT nextval('core.wallets_id_seq'::regclass);


--
-- Name: actual_metrics actual_metrics_pkey; Type: CONSTRAINT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.actual_metrics
    ADD CONSTRAINT actual_metrics_pkey PRIMARY KEY (id);


--
-- Name: actual_metrics actual_metrics_public_id_key; Type: CONSTRAINT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.actual_metrics
    ADD CONSTRAINT actual_metrics_public_id_key UNIQUE (public_id);


--
-- Name: approval_actions approval_actions_pkey; Type: CONSTRAINT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.approval_actions
    ADD CONSTRAINT approval_actions_pkey PRIMARY KEY (id);


--
-- Name: approval_actions approval_actions_public_id_key; Type: CONSTRAINT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.approval_actions
    ADD CONSTRAINT approval_actions_public_id_key UNIQUE (public_id);


--
-- Name: approval_requests approval_requests_pkey; Type: CONSTRAINT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.approval_requests
    ADD CONSTRAINT approval_requests_pkey PRIMARY KEY (id);


--
-- Name: approval_requests approval_requests_public_id_key; Type: CONSTRAINT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.approval_requests
    ADD CONSTRAINT approval_requests_public_id_key UNIQUE (public_id);


--
-- Name: bnpl_payment_draft_items bnpl_payment_draft_items_pkey; Type: CONSTRAINT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.bnpl_payment_draft_items
    ADD CONSTRAINT bnpl_payment_draft_items_pkey PRIMARY KEY (id);


--
-- Name: bnpl_payment_draft_items bnpl_payment_draft_items_public_id_key; Type: CONSTRAINT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.bnpl_payment_draft_items
    ADD CONSTRAINT bnpl_payment_draft_items_public_id_key UNIQUE (public_id);


--
-- Name: bnpl_payment_drafts bnpl_payment_drafts_pkey; Type: CONSTRAINT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.bnpl_payment_drafts
    ADD CONSTRAINT bnpl_payment_drafts_pkey PRIMARY KEY (id);


--
-- Name: bnpl_payment_drafts bnpl_payment_drafts_public_id_key; Type: CONSTRAINT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.bnpl_payment_drafts
    ADD CONSTRAINT bnpl_payment_drafts_public_id_key UNIQUE (public_id);


--
-- Name: business_entity_refs business_entity_refs_pkey; Type: CONSTRAINT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.business_entity_refs
    ADD CONSTRAINT business_entity_refs_pkey PRIMARY KEY (id);


--
-- Name: business_entity_refs business_entity_refs_public_id_key; Type: CONSTRAINT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.business_entity_refs
    ADD CONSTRAINT business_entity_refs_public_id_key UNIQUE (public_id);


--
-- Name: business_entity_refs business_entity_refs_source_system_target_table_target_publ_key; Type: CONSTRAINT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.business_entity_refs
    ADD CONSTRAINT business_entity_refs_source_system_target_table_target_publ_key UNIQUE (source_system, target_table, target_public_id);


--
-- Name: chat_messages chat_messages_pkey; Type: CONSTRAINT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.chat_messages
    ADD CONSTRAINT chat_messages_pkey PRIMARY KEY (id);


--
-- Name: chat_messages chat_messages_public_id_key; Type: CONSTRAINT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.chat_messages
    ADD CONSTRAINT chat_messages_public_id_key UNIQUE (public_id);


--
-- Name: chat_sessions chat_sessions_pkey; Type: CONSTRAINT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.chat_sessions
    ADD CONSTRAINT chat_sessions_pkey PRIMARY KEY (id);


--
-- Name: chat_sessions chat_sessions_public_id_key; Type: CONSTRAINT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.chat_sessions
    ADD CONSTRAINT chat_sessions_public_id_key UNIQUE (public_id);


--
-- Name: disaster_risk_simulations disaster_risk_simulations_pkey; Type: CONSTRAINT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.disaster_risk_simulations
    ADD CONSTRAINT disaster_risk_simulations_pkey PRIMARY KEY (id);


--
-- Name: disaster_risk_simulations disaster_risk_simulations_public_id_key; Type: CONSTRAINT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.disaster_risk_simulations
    ADD CONSTRAINT disaster_risk_simulations_public_id_key UNIQUE (public_id);


--
-- Name: farm_advisory_cases farm_advisory_cases_pkey; Type: CONSTRAINT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.farm_advisory_cases
    ADD CONSTRAINT farm_advisory_cases_pkey PRIMARY KEY (id);


--
-- Name: farm_advisory_cases farm_advisory_cases_public_id_key; Type: CONSTRAINT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.farm_advisory_cases
    ADD CONSTRAINT farm_advisory_cases_public_id_key UNIQUE (public_id);


--
-- Name: farm_advisory_results farm_advisory_results_pkey; Type: CONSTRAINT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.farm_advisory_results
    ADD CONSTRAINT farm_advisory_results_pkey PRIMARY KEY (id);


--
-- Name: farm_advisory_results farm_advisory_results_public_id_key; Type: CONSTRAINT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.farm_advisory_results
    ADD CONSTRAINT farm_advisory_results_public_id_key UNIQUE (public_id);


--
-- Name: incident_alerts incident_alerts_incident_public_id_fingerprint_key; Type: CONSTRAINT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.incident_alerts
    ADD CONSTRAINT incident_alerts_incident_public_id_fingerprint_key UNIQUE (incident_public_id, fingerprint);


--
-- Name: incident_alerts incident_alerts_pkey; Type: CONSTRAINT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.incident_alerts
    ADD CONSTRAINT incident_alerts_pkey PRIMARY KEY (id);


--
-- Name: incident_alerts incident_alerts_public_id_key; Type: CONSTRAINT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.incident_alerts
    ADD CONSTRAINT incident_alerts_public_id_key UNIQUE (public_id);


--
-- Name: incidents incidents_dedup_key_key; Type: CONSTRAINT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.incidents
    ADD CONSTRAINT incidents_dedup_key_key UNIQUE (dedup_key);


--
-- Name: incidents incidents_pkey; Type: CONSTRAINT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.incidents
    ADD CONSTRAINT incidents_pkey PRIMARY KEY (id);


--
-- Name: incidents incidents_public_id_key; Type: CONSTRAINT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.incidents
    ADD CONSTRAINT incidents_public_id_key UNIQUE (public_id);


--
-- Name: job_runs job_runs_pkey; Type: CONSTRAINT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.job_runs
    ADD CONSTRAINT job_runs_pkey PRIMARY KEY (id);


--
-- Name: job_runs job_runs_public_id_key; Type: CONSTRAINT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.job_runs
    ADD CONSTRAINT job_runs_public_id_key UNIQUE (public_id);


--
-- Name: llm_runs llm_runs_pkey; Type: CONSTRAINT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.llm_runs
    ADD CONSTRAINT llm_runs_pkey PRIMARY KEY (id);


--
-- Name: llm_runs llm_runs_public_id_key; Type: CONSTRAINT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.llm_runs
    ADD CONSTRAINT llm_runs_public_id_key UNIQUE (public_id);


--
-- Name: mcp_servers mcp_servers_pkey; Type: CONSTRAINT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.mcp_servers
    ADD CONSTRAINT mcp_servers_pkey PRIMARY KEY (id);


--
-- Name: mcp_servers mcp_servers_public_id_key; Type: CONSTRAINT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.mcp_servers
    ADD CONSTRAINT mcp_servers_public_id_key UNIQUE (public_id);


--
-- Name: mcp_servers mcp_servers_server_name_key; Type: CONSTRAINT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.mcp_servers
    ADD CONSTRAINT mcp_servers_server_name_key UNIQUE (server_name);


--
-- Name: mcp_tool_calls mcp_tool_calls_pkey; Type: CONSTRAINT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.mcp_tool_calls
    ADD CONSTRAINT mcp_tool_calls_pkey PRIMARY KEY (id);


--
-- Name: mcp_tool_calls mcp_tool_calls_public_id_key; Type: CONSTRAINT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.mcp_tool_calls
    ADD CONSTRAINT mcp_tool_calls_public_id_key UNIQUE (public_id);


--
-- Name: mcp_tools mcp_tools_mcp_server_public_id_tool_name_key; Type: CONSTRAINT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.mcp_tools
    ADD CONSTRAINT mcp_tools_mcp_server_public_id_tool_name_key UNIQUE (mcp_server_public_id, tool_name);


--
-- Name: mcp_tools mcp_tools_pkey; Type: CONSTRAINT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.mcp_tools
    ADD CONSTRAINT mcp_tools_pkey PRIMARY KEY (id);


--
-- Name: mcp_tools mcp_tools_public_id_key; Type: CONSTRAINT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.mcp_tools
    ADD CONSTRAINT mcp_tools_public_id_key UNIQUE (public_id);


--
-- Name: model_versions model_versions_model_name_model_version_key; Type: CONSTRAINT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.model_versions
    ADD CONSTRAINT model_versions_model_name_model_version_key UNIQUE (model_name, model_version);


--
-- Name: model_versions model_versions_pkey; Type: CONSTRAINT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.model_versions
    ADD CONSTRAINT model_versions_pkey PRIMARY KEY (id);


--
-- Name: model_versions model_versions_public_id_key; Type: CONSTRAINT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.model_versions
    ADD CONSTRAINT model_versions_public_id_key UNIQUE (public_id);


--
-- Name: notification_outbox notification_outbox_pkey; Type: CONSTRAINT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.notification_outbox
    ADD CONSTRAINT notification_outbox_pkey PRIMARY KEY (id);


--
-- Name: notification_outbox notification_outbox_public_id_key; Type: CONSTRAINT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.notification_outbox
    ADD CONSTRAINT notification_outbox_public_id_key UNIQUE (public_id);


--
-- Name: observability_snapshots observability_snapshots_pkey; Type: CONSTRAINT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.observability_snapshots
    ADD CONSTRAINT observability_snapshots_pkey PRIMARY KEY (id);


--
-- Name: observability_snapshots observability_snapshots_public_id_key; Type: CONSTRAINT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.observability_snapshots
    ADD CONSTRAINT observability_snapshots_public_id_key UNIQUE (public_id);


--
-- Name: ops_report_rca_refs ops_report_rca_refs_pkey; Type: CONSTRAINT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.ops_report_rca_refs
    ADD CONSTRAINT ops_report_rca_refs_pkey PRIMARY KEY (id);


--
-- Name: ops_report_rca_refs ops_report_rca_refs_public_id_key; Type: CONSTRAINT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.ops_report_rca_refs
    ADD CONSTRAINT ops_report_rca_refs_public_id_key UNIQUE (public_id);


--
-- Name: ops_report_rca_refs ops_report_rca_refs_report_public_id_rca_report_public_id_key; Type: CONSTRAINT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.ops_report_rca_refs
    ADD CONSTRAINT ops_report_rca_refs_report_public_id_rca_report_public_id_key UNIQUE (report_public_id, rca_report_public_id);


--
-- Name: ops_reports ops_reports_pkey; Type: CONSTRAINT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.ops_reports
    ADD CONSTRAINT ops_reports_pkey PRIMARY KEY (id);


--
-- Name: ops_reports ops_reports_public_id_key; Type: CONSTRAINT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.ops_reports
    ADD CONSTRAINT ops_reports_public_id_key UNIQUE (public_id);


--
-- Name: payment_request_publish_events payment_request_publish_events_pkey; Type: CONSTRAINT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.payment_request_publish_events
    ADD CONSTRAINT payment_request_publish_events_pkey PRIMARY KEY (id);


--
-- Name: payment_request_publish_events payment_request_publish_events_public_id_key; Type: CONSTRAINT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.payment_request_publish_events
    ADD CONSTRAINT payment_request_publish_events_public_id_key UNIQUE (public_id);


--
-- Name: prediction_error_metrics prediction_error_metrics_pkey; Type: CONSTRAINT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.prediction_error_metrics
    ADD CONSTRAINT prediction_error_metrics_pkey PRIMARY KEY (id);


--
-- Name: prediction_error_metrics prediction_error_metrics_public_id_key; Type: CONSTRAINT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.prediction_error_metrics
    ADD CONSTRAINT prediction_error_metrics_public_id_key UNIQUE (public_id);


--
-- Name: prediction_metrics prediction_metrics_pkey; Type: CONSTRAINT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.prediction_metrics
    ADD CONSTRAINT prediction_metrics_pkey PRIMARY KEY (id);


--
-- Name: prediction_metrics prediction_metrics_public_id_key; Type: CONSTRAINT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.prediction_metrics
    ADD CONSTRAINT prediction_metrics_public_id_key UNIQUE (public_id);


--
-- Name: prediction_runs prediction_runs_pkey; Type: CONSTRAINT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.prediction_runs
    ADD CONSTRAINT prediction_runs_pkey PRIMARY KEY (id);


--
-- Name: prediction_runs prediction_runs_public_id_key; Type: CONSTRAINT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.prediction_runs
    ADD CONSTRAINT prediction_runs_public_id_key UNIQUE (public_id);


--
-- Name: prompt_versions prompt_versions_pkey; Type: CONSTRAINT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.prompt_versions
    ADD CONSTRAINT prompt_versions_pkey PRIMARY KEY (id);


--
-- Name: prompt_versions prompt_versions_prompt_key_prompt_version_key; Type: CONSTRAINT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.prompt_versions
    ADD CONSTRAINT prompt_versions_prompt_key_prompt_version_key UNIQUE (prompt_key, prompt_version);


--
-- Name: prompt_versions prompt_versions_public_id_key; Type: CONSTRAINT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.prompt_versions
    ADD CONSTRAINT prompt_versions_public_id_key UNIQUE (public_id);


--
-- Name: rca_feedback rca_feedback_pkey; Type: CONSTRAINT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.rca_feedback
    ADD CONSTRAINT rca_feedback_pkey PRIMARY KEY (id);


--
-- Name: rca_feedback rca_feedback_public_id_key; Type: CONSTRAINT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.rca_feedback
    ADD CONSTRAINT rca_feedback_public_id_key UNIQUE (public_id);


--
-- Name: rca_reports rca_reports_pkey; Type: CONSTRAINT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.rca_reports
    ADD CONSTRAINT rca_reports_pkey PRIMARY KEY (id);


--
-- Name: rca_reports rca_reports_public_id_key; Type: CONSTRAINT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.rca_reports
    ADD CONSTRAINT rca_reports_public_id_key UNIQUE (public_id);


--
-- Name: report_incidents report_incidents_pkey; Type: CONSTRAINT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.report_incidents
    ADD CONSTRAINT report_incidents_pkey PRIMARY KEY (id);


--
-- Name: report_incidents report_incidents_public_id_key; Type: CONSTRAINT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.report_incidents
    ADD CONSTRAINT report_incidents_public_id_key UNIQUE (public_id);


--
-- Name: report_incidents report_incidents_report_public_id_incident_public_id_key; Type: CONSTRAINT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.report_incidents
    ADD CONSTRAINT report_incidents_report_public_id_incident_public_id_key UNIQUE (report_public_id, incident_public_id);


--
-- Name: report_metric_summaries report_metric_summaries_pkey; Type: CONSTRAINT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.report_metric_summaries
    ADD CONSTRAINT report_metric_summaries_pkey PRIMARY KEY (id);


--
-- Name: report_metric_summaries report_metric_summaries_public_id_key; Type: CONSTRAINT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.report_metric_summaries
    ADD CONSTRAINT report_metric_summaries_public_id_key UNIQUE (public_id);


--
-- Name: risk_analysis_reports risk_analysis_reports_pkey; Type: CONSTRAINT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.risk_analysis_reports
    ADD CONSTRAINT risk_analysis_reports_pkey PRIMARY KEY (id);


--
-- Name: risk_analysis_reports risk_analysis_reports_public_id_key; Type: CONSTRAINT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.risk_analysis_reports
    ADD CONSTRAINT risk_analysis_reports_public_id_key UNIQUE (public_id);


--
-- Name: risk_analysis_targets risk_analysis_targets_pkey; Type: CONSTRAINT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.risk_analysis_targets
    ADD CONSTRAINT risk_analysis_targets_pkey PRIMARY KEY (id);


--
-- Name: risk_analysis_targets risk_analysis_targets_public_id_key; Type: CONSTRAINT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.risk_analysis_targets
    ADD CONSTRAINT risk_analysis_targets_public_id_key UNIQUE (public_id);


--
-- Name: scaling_events scaling_events_pkey; Type: CONSTRAINT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.scaling_events
    ADD CONSTRAINT scaling_events_pkey PRIMARY KEY (id);


--
-- Name: scaling_events scaling_events_public_id_key; Type: CONSTRAINT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.scaling_events
    ADD CONSTRAINT scaling_events_public_id_key UNIQUE (public_id);


--
-- Name: snapshot_items snapshot_items_pkey; Type: CONSTRAINT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.snapshot_items
    ADD CONSTRAINT snapshot_items_pkey PRIMARY KEY (id);


--
-- Name: snapshot_items snapshot_items_public_id_key; Type: CONSTRAINT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.snapshot_items
    ADD CONSTRAINT snapshot_items_public_id_key UNIQUE (public_id);


--
-- Name: bnpl_payment_request_items bnpl_payment_request_items_pkey; Type: CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.bnpl_payment_request_items
    ADD CONSTRAINT bnpl_payment_request_items_pkey PRIMARY KEY (id);


--
-- Name: bnpl_payment_requests bnpl_payment_requests_pkey; Type: CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.bnpl_payment_requests
    ADD CONSTRAINT bnpl_payment_requests_pkey PRIMARY KEY (id);


--
-- Name: bnpl_payment_requests bnpl_payment_requests_public_id_key; Type: CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.bnpl_payment_requests
    ADD CONSTRAINT bnpl_payment_requests_public_id_key UNIQUE (public_id);


--
-- Name: cart_items cart_items_pkey; Type: CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.cart_items
    ADD CONSTRAINT cart_items_pkey PRIMARY KEY (id);


--
-- Name: cart_items cart_items_public_id_key; Type: CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.cart_items
    ADD CONSTRAINT cart_items_public_id_key UNIQUE (public_id);


--
-- Name: categories categories_name_key; Type: CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.categories
    ADD CONSTRAINT categories_name_key UNIQUE (name);


--
-- Name: categories categories_pkey; Type: CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.categories
    ADD CONSTRAINT categories_pkey PRIMARY KEY (id);


--
-- Name: categories categories_public_id_key; Type: CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.categories
    ADD CONSTRAINT categories_public_id_key UNIQUE (public_id);


--
-- Name: products products_pkey; Type: CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.products
    ADD CONSTRAINT products_pkey PRIMARY KEY (id);


--
-- Name: products products_public_id_key; Type: CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.products
    ADD CONSTRAINT products_public_id_key UNIQUE (public_id);


--
-- Name: cart_items uq_cart_items_user_product; Type: CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.cart_items
    ADD CONSTRAINT uq_cart_items_user_product UNIQUE (user_public_id, product_public_id);


--
-- Name: admin_users admin_users_email_key; Type: CONSTRAINT; Schema: core; Owner: -
--

ALTER TABLE ONLY core.admin_users
    ADD CONSTRAINT admin_users_email_key UNIQUE (email);


--
-- Name: admin_users admin_users_pkey; Type: CONSTRAINT; Schema: core; Owner: -
--

ALTER TABLE ONLY core.admin_users
    ADD CONSTRAINT admin_users_pkey PRIMARY KEY (id);


--
-- Name: admin_users admin_users_public_id_key; Type: CONSTRAINT; Schema: core; Owner: -
--

ALTER TABLE ONLY core.admin_users
    ADD CONSTRAINT admin_users_public_id_key UNIQUE (public_id);


--
-- Name: ass_scores ass_scores_application_id_key; Type: CONSTRAINT; Schema: core; Owner: -
--

ALTER TABLE ONLY core.ass_scores
    ADD CONSTRAINT ass_scores_application_id_key UNIQUE (application_id);


--
-- Name: ass_scores ass_scores_pkey; Type: CONSTRAINT; Schema: core; Owner: -
--

ALTER TABLE ONLY core.ass_scores
    ADD CONSTRAINT ass_scores_pkey PRIMARY KEY (id);


--
-- Name: audit_logs audit_logs_pkey; Type: CONSTRAINT; Schema: core; Owner: -
--

ALTER TABLE ONLY core.audit_logs
    ADD CONSTRAINT audit_logs_pkey PRIMARY KEY (id);


--
-- Name: audit_logs audit_logs_public_id_key; Type: CONSTRAINT; Schema: core; Owner: -
--

ALTER TABLE ONLY core.audit_logs
    ADD CONSTRAINT audit_logs_public_id_key UNIQUE (public_id);


--
-- Name: bss_scores bss_scores_pkey; Type: CONSTRAINT; Schema: core; Owner: -
--

ALTER TABLE ONLY core.bss_scores
    ADD CONSTRAINT bss_scores_pkey PRIMARY KEY (id);


--
-- Name: bss_scores bss_scores_public_id_key; Type: CONSTRAINT; Schema: core; Owner: -
--

ALTER TABLE ONLY core.bss_scores
    ADD CONSTRAINT bss_scores_public_id_key UNIQUE (public_id);


--
-- Name: credit_limit_applications credit_limit_applications_pkey; Type: CONSTRAINT; Schema: core; Owner: -
--

ALTER TABLE ONLY core.credit_limit_applications
    ADD CONSTRAINT credit_limit_applications_pkey PRIMARY KEY (id);


--
-- Name: credit_limit_applications credit_limit_applications_public_id_key; Type: CONSTRAINT; Schema: core; Owner: -
--

ALTER TABLE ONLY core.credit_limit_applications
    ADD CONSTRAINT credit_limit_applications_public_id_key UNIQUE (public_id);


--
-- Name: credit_limits credit_limits_application_public_id_key; Type: CONSTRAINT; Schema: core; Owner: -
--

ALTER TABLE ONLY core.credit_limits
    ADD CONSTRAINT credit_limits_application_public_id_key UNIQUE (application_public_id);


--
-- Name: credit_limits credit_limits_pkey; Type: CONSTRAINT; Schema: core; Owner: -
--

ALTER TABLE ONLY core.credit_limits
    ADD CONSTRAINT credit_limits_pkey PRIMARY KEY (id);


--
-- Name: credit_limits credit_limits_public_id_key; Type: CONSTRAINT; Schema: core; Owner: -
--

ALTER TABLE ONLY core.credit_limits
    ADD CONSTRAINT credit_limits_public_id_key UNIQUE (public_id);


--
-- Name: credit_usage_ledger credit_usage_ledger_pkey; Type: CONSTRAINT; Schema: core; Owner: -
--

ALTER TABLE ONLY core.credit_usage_ledger
    ADD CONSTRAINT credit_usage_ledger_pkey PRIMARY KEY (id);


--
-- Name: credit_usage_ledger credit_usage_ledger_public_id_key; Type: CONSTRAINT; Schema: core; Owner: -
--

ALTER TABLE ONLY core.credit_usage_ledger
    ADD CONSTRAINT credit_usage_ledger_public_id_key UNIQUE (public_id);


--
-- Name: crop_repayment_policies crop_repayment_policies_crop_type_key; Type: CONSTRAINT; Schema: core; Owner: -
--

ALTER TABLE ONLY core.crop_repayment_policies
    ADD CONSTRAINT crop_repayment_policies_crop_type_key UNIQUE (crop_type);


--
-- Name: crop_repayment_policies crop_repayment_policies_pkey; Type: CONSTRAINT; Schema: core; Owner: -
--

ALTER TABLE ONLY core.crop_repayment_policies
    ADD CONSTRAINT crop_repayment_policies_pkey PRIMARY KEY (id);


--
-- Name: crop_repayment_policies crop_repayment_policies_public_id_key; Type: CONSTRAINT; Schema: core; Owner: -
--

ALTER TABLE ONLY core.crop_repayment_policies
    ADD CONSTRAINT crop_repayment_policies_public_id_key UNIQUE (public_id);


--
-- Name: farmer_documents farmer_documents_pkey; Type: CONSTRAINT; Schema: core; Owner: -
--

ALTER TABLE ONLY core.farmer_documents
    ADD CONSTRAINT farmer_documents_pkey PRIMARY KEY (id);


--
-- Name: farmer_profiles farmer_profiles_pkey; Type: CONSTRAINT; Schema: core; Owner: -
--

ALTER TABLE ONLY core.farmer_profiles
    ADD CONSTRAINT farmer_profiles_pkey PRIMARY KEY (id);


--
-- Name: farmer_profiles farmer_profiles_user_id_key; Type: CONSTRAINT; Schema: core; Owner: -
--

ALTER TABLE ONLY core.farmer_profiles
    ADD CONSTRAINT farmer_profiles_user_id_key UNIQUE (user_id);


--
-- Name: interest_ledger interest_ledger_pkey; Type: CONSTRAINT; Schema: core; Owner: -
--

ALTER TABLE ONLY core.interest_ledger
    ADD CONSTRAINT interest_ledger_pkey PRIMARY KEY (id);


--
-- Name: interest_ledger interest_ledger_public_id_key; Type: CONSTRAINT; Schema: core; Owner: -
--

ALTER TABLE ONLY core.interest_ledger
    ADD CONSTRAINT interest_ledger_public_id_key UNIQUE (public_id);


--
-- Name: loan_overdue_ledger loan_overdue_ledger_pkey; Type: CONSTRAINT; Schema: core; Owner: -
--

ALTER TABLE ONLY core.loan_overdue_ledger
    ADD CONSTRAINT loan_overdue_ledger_pkey PRIMARY KEY (id);


--
-- Name: loan_overdue_ledger loan_overdue_ledger_public_id_key; Type: CONSTRAINT; Schema: core; Owner: -
--

ALTER TABLE ONLY core.loan_overdue_ledger
    ADD CONSTRAINT loan_overdue_ledger_public_id_key UNIQUE (public_id);


--
-- Name: notifications notifications_pkey; Type: CONSTRAINT; Schema: core; Owner: -
--

ALTER TABLE ONLY core.notifications
    ADD CONSTRAINT notifications_pkey PRIMARY KEY (id);


--
-- Name: notifications notifications_public_id_key; Type: CONSTRAINT; Schema: core; Owner: -
--

ALTER TABLE ONLY core.notifications
    ADD CONSTRAINT notifications_public_id_key UNIQUE (public_id);


--
-- Name: order_items order_items_pkey; Type: CONSTRAINT; Schema: core; Owner: -
--

ALTER TABLE ONLY core.order_items
    ADD CONSTRAINT order_items_pkey PRIMARY KEY (id);


--
-- Name: orders orders_payment_request_public_id_key; Type: CONSTRAINT; Schema: core; Owner: -
--

ALTER TABLE ONLY core.orders
    ADD CONSTRAINT orders_payment_request_public_id_key UNIQUE (payment_request_public_id);


--
-- Name: orders orders_pkey; Type: CONSTRAINT; Schema: core; Owner: -
--

ALTER TABLE ONLY core.orders
    ADD CONSTRAINT orders_pkey PRIMARY KEY (id);


--
-- Name: orders orders_public_id_key; Type: CONSTRAINT; Schema: core; Owner: -
--

ALTER TABLE ONLY core.orders
    ADD CONSTRAINT orders_public_id_key UNIQUE (public_id);


--
-- Name: payment_event_process_logs payment_event_process_logs_event_id_key; Type: CONSTRAINT; Schema: core; Owner: -
--

ALTER TABLE ONLY core.payment_event_process_logs
    ADD CONSTRAINT payment_event_process_logs_event_id_key UNIQUE (event_id);


--
-- Name: payment_event_process_logs payment_event_process_logs_idempotency_key_key; Type: CONSTRAINT; Schema: core; Owner: -
--

ALTER TABLE ONLY core.payment_event_process_logs
    ADD CONSTRAINT payment_event_process_logs_idempotency_key_key UNIQUE (idempotency_key);


--
-- Name: payment_event_process_logs payment_event_process_logs_payment_request_public_id_key; Type: CONSTRAINT; Schema: core; Owner: -
--

ALTER TABLE ONLY core.payment_event_process_logs
    ADD CONSTRAINT payment_event_process_logs_payment_request_public_id_key UNIQUE (payment_request_public_id);


--
-- Name: payment_event_process_logs payment_event_process_logs_pkey; Type: CONSTRAINT; Schema: core; Owner: -
--

ALTER TABLE ONLY core.payment_event_process_logs
    ADD CONSTRAINT payment_event_process_logs_pkey PRIMARY KEY (id);


--
-- Name: principal_repayment_ledger principal_repayment_ledger_order_public_id_key; Type: CONSTRAINT; Schema: core; Owner: -
--

ALTER TABLE ONLY core.principal_repayment_ledger
    ADD CONSTRAINT principal_repayment_ledger_order_public_id_key UNIQUE (order_public_id);


--
-- Name: principal_repayment_ledger principal_repayment_ledger_pkey; Type: CONSTRAINT; Schema: core; Owner: -
--

ALTER TABLE ONLY core.principal_repayment_ledger
    ADD CONSTRAINT principal_repayment_ledger_pkey PRIMARY KEY (id);


--
-- Name: principal_repayment_ledger principal_repayment_ledger_public_id_key; Type: CONSTRAINT; Schema: core; Owner: -
--

ALTER TABLE ONLY core.principal_repayment_ledger
    ADD CONSTRAINT principal_repayment_ledger_public_id_key UNIQUE (public_id);


--
-- Name: interest_ledger uq_interest_ledger_credit_limit_due_date; Type: CONSTRAINT; Schema: core; Owner: -
--

ALTER TABLE ONLY core.interest_ledger
    ADD CONSTRAINT uq_interest_ledger_credit_limit_due_date UNIQUE (credit_limit_public_id, due_date);


--
-- Name: user_auth user_auth_pkey; Type: CONSTRAINT; Schema: core; Owner: -
--

ALTER TABLE ONLY core.user_auth
    ADD CONSTRAINT user_auth_pkey PRIMARY KEY (id);


--
-- Name: user_auth user_auth_user_public_id_key; Type: CONSTRAINT; Schema: core; Owner: -
--

ALTER TABLE ONLY core.user_auth
    ADD CONSTRAINT user_auth_user_public_id_key UNIQUE (user_public_id);


--
-- Name: users users_phone_key; Type: CONSTRAINT; Schema: core; Owner: -
--

ALTER TABLE ONLY core.users
    ADD CONSTRAINT users_phone_key UNIQUE (phone);


--
-- Name: users users_pkey; Type: CONSTRAINT; Schema: core; Owner: -
--

ALTER TABLE ONLY core.users
    ADD CONSTRAINT users_pkey PRIMARY KEY (id);


--
-- Name: users users_public_id_key; Type: CONSTRAINT; Schema: core; Owner: -
--

ALTER TABLE ONLY core.users
    ADD CONSTRAINT users_public_id_key UNIQUE (public_id);


--
-- Name: wallet_transactions wallet_transactions_pkey; Type: CONSTRAINT; Schema: core; Owner: -
--

ALTER TABLE ONLY core.wallet_transactions
    ADD CONSTRAINT wallet_transactions_pkey PRIMARY KEY (id);


--
-- Name: wallet_transactions wallet_transactions_public_id_key; Type: CONSTRAINT; Schema: core; Owner: -
--

ALTER TABLE ONLY core.wallet_transactions
    ADD CONSTRAINT wallet_transactions_public_id_key UNIQUE (public_id);


--
-- Name: wallets wallets_deposit_account_number_key; Type: CONSTRAINT; Schema: core; Owner: -
--

ALTER TABLE ONLY core.wallets
    ADD CONSTRAINT wallets_deposit_account_number_key UNIQUE (deposit_account_number);


--
-- Name: wallets wallets_pkey; Type: CONSTRAINT; Schema: core; Owner: -
--

ALTER TABLE ONLY core.wallets
    ADD CONSTRAINT wallets_pkey PRIMARY KEY (id);


--
-- Name: wallets wallets_public_id_key; Type: CONSTRAINT; Schema: core; Owner: -
--

ALTER TABLE ONLY core.wallets
    ADD CONSTRAINT wallets_public_id_key UNIQUE (public_id);


--
-- Name: wallets wallets_user_public_id_key; Type: CONSTRAINT; Schema: core; Owner: -
--

ALTER TABLE ONLY core.wallets
    ADD CONSTRAINT wallets_user_public_id_key UNIQUE (user_public_id);


--
-- Name: idx_ai_actual_metrics_service_measured_at; Type: INDEX; Schema: ai; Owner: -
--

CREATE INDEX idx_ai_actual_metrics_service_measured_at ON ai.actual_metrics USING btree (namespace, service_name, measured_at DESC);


--
-- Name: idx_ai_bnpl_payment_draft_items_product; Type: INDEX; Schema: ai; Owner: -
--

CREATE INDEX idx_ai_bnpl_payment_draft_items_product ON ai.bnpl_payment_draft_items USING btree (product_public_id);


--
-- Name: idx_ai_bnpl_payment_drafts_user_status; Type: INDEX; Schema: ai; Owner: -
--

CREATE INDEX idx_ai_bnpl_payment_drafts_user_status ON ai.bnpl_payment_drafts USING btree (user_public_id, draft_status);


--
-- Name: idx_ai_chat_messages_session_public_id; Type: INDEX; Schema: ai; Owner: -
--

CREATE INDEX idx_ai_chat_messages_session_public_id ON ai.chat_messages USING btree (session_public_id, created_at);


--
-- Name: idx_ai_chat_sessions_user_public_id; Type: INDEX; Schema: ai; Owner: -
--

CREATE INDEX idx_ai_chat_sessions_user_public_id ON ai.chat_sessions USING btree (user_public_id, created_at DESC);


--
-- Name: idx_ai_farm_advisory_cases_user_public_id; Type: INDEX; Schema: ai; Owner: -
--

CREATE INDEX idx_ai_farm_advisory_cases_user_public_id ON ai.farm_advisory_cases USING btree (user_public_id, created_at DESC);


--
-- Name: idx_ai_incidents_status_severity; Type: INDEX; Schema: ai; Owner: -
--

CREATE INDEX idx_ai_incidents_status_severity ON ai.incidents USING btree (incident_status, severity);


--
-- Name: idx_ai_llm_runs_job_run_public_id; Type: INDEX; Schema: ai; Owner: -
--

CREATE INDEX idx_ai_llm_runs_job_run_public_id ON ai.llm_runs USING btree (job_run_public_id, created_at DESC);


--
-- Name: idx_ai_mcp_tool_calls_job_run_public_id; Type: INDEX; Schema: ai; Owner: -
--

CREATE INDEX idx_ai_mcp_tool_calls_job_run_public_id ON ai.mcp_tool_calls USING btree (job_run_public_id, created_at DESC);


--
-- Name: idx_ai_mcp_tool_calls_session_public_id; Type: INDEX; Schema: ai; Owner: -
--

CREATE INDEX idx_ai_mcp_tool_calls_session_public_id ON ai.mcp_tool_calls USING btree (session_public_id, created_at DESC);


--
-- Name: idx_ai_observability_snapshots_llm_run_public_id; Type: INDEX; Schema: ai; Owner: -
--

CREATE INDEX idx_ai_observability_snapshots_llm_run_public_id ON ai.observability_snapshots USING btree (llm_run_public_id, created_at DESC);


--
-- Name: idx_ai_observability_snapshots_session_public_id; Type: INDEX; Schema: ai; Owner: -
--

CREATE INDEX idx_ai_observability_snapshots_session_public_id ON ai.observability_snapshots USING btree (session_public_id, created_at DESC);


--
-- Name: idx_ai_ops_report_rca_refs_report; Type: INDEX; Schema: ai; Owner: -
--

CREATE INDEX idx_ai_ops_report_rca_refs_report ON ai.ops_report_rca_refs USING btree (report_public_id, created_at DESC);


--
-- Name: idx_ai_prediction_metrics_service_target_time; Type: INDEX; Schema: ai; Owner: -
--

CREATE INDEX idx_ai_prediction_metrics_service_target_time ON ai.prediction_metrics USING btree (namespace, service_name, target_time DESC);


--
-- Name: idx_ai_report_metric_summaries_period; Type: INDEX; Schema: ai; Owner: -
--

CREATE INDEX idx_ai_report_metric_summaries_period ON ai.report_metric_summaries USING btree (period_start, period_end);


--
-- Name: idx_ai_risk_analysis_reports_user_public_id; Type: INDEX; Schema: ai; Owner: -
--

CREATE INDEX idx_ai_risk_analysis_reports_user_public_id ON ai.risk_analysis_reports USING btree (user_public_id, created_at DESC);


--
-- Name: idx_ai_risk_analysis_targets_target; Type: INDEX; Schema: ai; Owner: -
--

CREATE INDEX idx_ai_risk_analysis_targets_target ON ai.risk_analysis_targets USING btree (target_table, target_public_id);


--
-- Name: idx_ai_scaling_events_service_event_time; Type: INDEX; Schema: ai; Owner: -
--

CREATE INDEX idx_ai_scaling_events_service_event_time ON ai.scaling_events USING btree (namespace, service_name, event_time DESC);


--
-- Name: idx_ai_snapshot_items_snapshot_source; Type: INDEX; Schema: ai; Owner: -
--

CREATE INDEX idx_ai_snapshot_items_snapshot_source ON ai.snapshot_items USING btree (snapshot_public_id, source_type);


--
-- Name: ux_ai_job_runs_idempotency_key; Type: INDEX; Schema: ai; Owner: -
--

CREATE UNIQUE INDEX ux_ai_job_runs_idempotency_key ON ai.job_runs USING btree (idempotency_key) WHERE (idempotency_key IS NOT NULL);


--
-- Name: ux_ai_notification_outbox_idempotency_key; Type: INDEX; Schema: ai; Owner: -
--

CREATE UNIQUE INDEX ux_ai_notification_outbox_idempotency_key ON ai.notification_outbox USING btree (idempotency_key) WHERE (idempotency_key IS NOT NULL);


--
-- Name: idx_catalog_bnpl_payment_requests_user_public_id; Type: INDEX; Schema: catalog; Owner: -
--

CREATE INDEX idx_catalog_bnpl_payment_requests_user_public_id ON catalog.bnpl_payment_requests USING btree (user_public_id);


--
-- Name: idx_catalog_cart_items_user_public_id; Type: INDEX; Schema: catalog; Owner: -
--

CREATE INDEX idx_catalog_cart_items_user_public_id ON catalog.cart_items USING btree (user_public_id);


--
-- Name: idx_catalog_products_category_public_id; Type: INDEX; Schema: catalog; Owner: -
--

CREATE INDEX idx_catalog_products_category_public_id ON catalog.products USING btree (category_public_id);


--
-- Name: idx_core_audit_logs_admin_user_public_id; Type: INDEX; Schema: core; Owner: -
--

CREATE INDEX idx_core_audit_logs_admin_user_public_id ON core.audit_logs USING btree (admin_user_public_id);


--
-- Name: idx_core_bss_scores_user_period; Type: INDEX; Schema: core; Owner: -
--

CREATE INDEX idx_core_bss_scores_user_period ON core.bss_scores USING btree (user_public_id, period_type, period_year, period_month);


--
-- Name: idx_core_credit_limits_application_public_id; Type: INDEX; Schema: core; Owner: -
--

CREATE INDEX idx_core_credit_limits_application_public_id ON core.credit_limits USING btree (application_public_id);


--
-- Name: idx_core_credit_limits_user_public_id; Type: INDEX; Schema: core; Owner: -
--

CREATE INDEX idx_core_credit_limits_user_public_id ON core.credit_limits USING btree (user_public_id);


--
-- Name: idx_core_credit_usage_ledger_credit_limit_public_id; Type: INDEX; Schema: core; Owner: -
--

CREATE INDEX idx_core_credit_usage_ledger_credit_limit_public_id ON core.credit_usage_ledger USING btree (credit_limit_public_id);


--
-- Name: idx_core_credit_usage_ledger_order_public_id; Type: INDEX; Schema: core; Owner: -
--

CREATE INDEX idx_core_credit_usage_ledger_order_public_id ON core.credit_usage_ledger USING btree (order_public_id);


--
-- Name: idx_core_credit_usage_ledger_payment_request_public_id; Type: INDEX; Schema: core; Owner: -
--

CREATE INDEX idx_core_credit_usage_ledger_payment_request_public_id ON core.credit_usage_ledger USING btree (payment_request_public_id);


--
-- Name: idx_core_interest_ledger_credit_limit_public_id; Type: INDEX; Schema: core; Owner: -
--

CREATE INDEX idx_core_interest_ledger_credit_limit_public_id ON core.interest_ledger USING btree (credit_limit_public_id);


--
-- Name: idx_core_loan_overdue_credit_limit_public_id; Type: INDEX; Schema: core; Owner: -
--

CREATE INDEX idx_core_loan_overdue_credit_limit_public_id ON core.loan_overdue_ledger USING btree (credit_limit_public_id);


--
-- Name: idx_core_loan_overdue_user_public_id; Type: INDEX; Schema: core; Owner: -
--

CREATE INDEX idx_core_loan_overdue_user_public_id ON core.loan_overdue_ledger USING btree (user_public_id);


--
-- Name: idx_core_notifications_user_public_id; Type: INDEX; Schema: core; Owner: -
--

CREATE INDEX idx_core_notifications_user_public_id ON core.notifications USING btree (user_public_id);


--
-- Name: idx_core_order_items_order_public_id; Type: INDEX; Schema: core; Owner: -
--

CREATE INDEX idx_core_order_items_order_public_id ON core.order_items USING btree (order_public_id);


--
-- Name: idx_core_orders_payment_request_public_id; Type: INDEX; Schema: core; Owner: -
--

CREATE INDEX idx_core_orders_payment_request_public_id ON core.orders USING btree (payment_request_public_id);


--
-- Name: idx_core_orders_user_public_id; Type: INDEX; Schema: core; Owner: -
--

CREATE INDEX idx_core_orders_user_public_id ON core.orders USING btree (user_public_id);


--
-- Name: idx_core_payment_event_logs_payment_request_public_id; Type: INDEX; Schema: core; Owner: -
--

CREATE INDEX idx_core_payment_event_logs_payment_request_public_id ON core.payment_event_process_logs USING btree (payment_request_public_id);


--
-- Name: idx_core_principal_repayment_credit_limit_public_id; Type: INDEX; Schema: core; Owner: -
--

CREATE INDEX idx_core_principal_repayment_credit_limit_public_id ON core.principal_repayment_ledger USING btree (credit_limit_public_id);


--
-- Name: idx_core_principal_repayment_order_public_id; Type: INDEX; Schema: core; Owner: -
--

CREATE INDEX idx_core_principal_repayment_order_public_id ON core.principal_repayment_ledger USING btree (order_public_id);


--
-- Name: idx_core_user_auth_user_public_id; Type: INDEX; Schema: core; Owner: -
--

CREATE INDEX idx_core_user_auth_user_public_id ON core.user_auth USING btree (user_public_id);


--
-- Name: idx_core_users_public_id; Type: INDEX; Schema: core; Owner: -
--

CREATE INDEX idx_core_users_public_id ON core.users USING btree (public_id);


--
-- Name: idx_core_wallet_transactions_wallet_public_id; Type: INDEX; Schema: core; Owner: -
--

CREATE INDEX idx_core_wallet_transactions_wallet_public_id ON core.wallet_transactions USING btree (wallet_public_id);


--
-- Name: idx_core_wallets_user_public_id; Type: INDEX; Schema: core; Owner: -
--

CREATE INDEX idx_core_wallets_user_public_id ON core.wallets USING btree (user_public_id);


--
-- Name: approval_actions approval_actions_approval_request_public_id_fkey; Type: FK CONSTRAINT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.approval_actions
    ADD CONSTRAINT approval_actions_approval_request_public_id_fkey FOREIGN KEY (approval_request_public_id) REFERENCES ai.approval_requests(public_id) ON DELETE CASCADE;


--
-- Name: approval_requests approval_requests_mcp_tool_call_public_id_fkey; Type: FK CONSTRAINT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.approval_requests
    ADD CONSTRAINT approval_requests_mcp_tool_call_public_id_fkey FOREIGN KEY (mcp_tool_call_public_id) REFERENCES ai.mcp_tool_calls(public_id) ON DELETE SET NULL;


--
-- Name: bnpl_payment_draft_items bnpl_payment_draft_items_draft_public_id_fkey; Type: FK CONSTRAINT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.bnpl_payment_draft_items
    ADD CONSTRAINT bnpl_payment_draft_items_draft_public_id_fkey FOREIGN KEY (draft_public_id) REFERENCES ai.bnpl_payment_drafts(public_id) ON DELETE CASCADE;


--
-- Name: bnpl_payment_drafts bnpl_payment_drafts_llm_run_public_id_fkey; Type: FK CONSTRAINT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.bnpl_payment_drafts
    ADD CONSTRAINT bnpl_payment_drafts_llm_run_public_id_fkey FOREIGN KEY (llm_run_public_id) REFERENCES ai.llm_runs(public_id) ON DELETE SET NULL;


--
-- Name: bnpl_payment_drafts bnpl_payment_drafts_session_public_id_fkey; Type: FK CONSTRAINT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.bnpl_payment_drafts
    ADD CONSTRAINT bnpl_payment_drafts_session_public_id_fkey FOREIGN KEY (session_public_id) REFERENCES ai.chat_sessions(public_id) ON DELETE SET NULL;


--
-- Name: chat_messages chat_messages_llm_run_public_id_fkey; Type: FK CONSTRAINT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.chat_messages
    ADD CONSTRAINT chat_messages_llm_run_public_id_fkey FOREIGN KEY (llm_run_public_id) REFERENCES ai.llm_runs(public_id) ON DELETE SET NULL;


--
-- Name: chat_messages chat_messages_mcp_tool_call_public_id_fkey; Type: FK CONSTRAINT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.chat_messages
    ADD CONSTRAINT chat_messages_mcp_tool_call_public_id_fkey FOREIGN KEY (mcp_tool_call_public_id) REFERENCES ai.mcp_tool_calls(public_id) ON DELETE SET NULL;


--
-- Name: chat_messages chat_messages_session_public_id_fkey; Type: FK CONSTRAINT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.chat_messages
    ADD CONSTRAINT chat_messages_session_public_id_fkey FOREIGN KEY (session_public_id) REFERENCES ai.chat_sessions(public_id) ON DELETE CASCADE;


--
-- Name: farm_advisory_cases farm_advisory_cases_session_public_id_fkey; Type: FK CONSTRAINT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.farm_advisory_cases
    ADD CONSTRAINT farm_advisory_cases_session_public_id_fkey FOREIGN KEY (session_public_id) REFERENCES ai.chat_sessions(public_id) ON DELETE SET NULL;


--
-- Name: farm_advisory_results farm_advisory_results_advisory_case_public_id_fkey; Type: FK CONSTRAINT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.farm_advisory_results
    ADD CONSTRAINT farm_advisory_results_advisory_case_public_id_fkey FOREIGN KEY (advisory_case_public_id) REFERENCES ai.farm_advisory_cases(public_id) ON DELETE CASCADE;


--
-- Name: farm_advisory_results farm_advisory_results_llm_run_public_id_fkey; Type: FK CONSTRAINT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.farm_advisory_results
    ADD CONSTRAINT farm_advisory_results_llm_run_public_id_fkey FOREIGN KEY (llm_run_public_id) REFERENCES ai.llm_runs(public_id) ON DELETE SET NULL;


--
-- Name: incident_alerts incident_alerts_incident_public_id_fkey; Type: FK CONSTRAINT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.incident_alerts
    ADD CONSTRAINT incident_alerts_incident_public_id_fkey FOREIGN KEY (incident_public_id) REFERENCES ai.incidents(public_id) ON DELETE CASCADE;


--
-- Name: llm_runs llm_runs_job_run_public_id_fkey; Type: FK CONSTRAINT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.llm_runs
    ADD CONSTRAINT llm_runs_job_run_public_id_fkey FOREIGN KEY (job_run_public_id) REFERENCES ai.job_runs(public_id) ON DELETE SET NULL;


--
-- Name: llm_runs llm_runs_prompt_version_public_id_fkey; Type: FK CONSTRAINT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.llm_runs
    ADD CONSTRAINT llm_runs_prompt_version_public_id_fkey FOREIGN KEY (prompt_version_public_id) REFERENCES ai.prompt_versions(public_id) ON DELETE SET NULL;


--
-- Name: llm_runs llm_runs_session_public_id_fkey; Type: FK CONSTRAINT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.llm_runs
    ADD CONSTRAINT llm_runs_session_public_id_fkey FOREIGN KEY (session_public_id) REFERENCES ai.chat_sessions(public_id) ON DELETE SET NULL;


--
-- Name: mcp_tool_calls mcp_tool_calls_business_ref_public_id_fkey; Type: FK CONSTRAINT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.mcp_tool_calls
    ADD CONSTRAINT mcp_tool_calls_business_ref_public_id_fkey FOREIGN KEY (business_ref_public_id) REFERENCES ai.business_entity_refs(public_id) ON DELETE SET NULL;


--
-- Name: mcp_tool_calls mcp_tool_calls_job_run_public_id_fkey; Type: FK CONSTRAINT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.mcp_tool_calls
    ADD CONSTRAINT mcp_tool_calls_job_run_public_id_fkey FOREIGN KEY (job_run_public_id) REFERENCES ai.job_runs(public_id) ON DELETE SET NULL;


--
-- Name: mcp_tool_calls mcp_tool_calls_llm_run_public_id_fkey; Type: FK CONSTRAINT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.mcp_tool_calls
    ADD CONSTRAINT mcp_tool_calls_llm_run_public_id_fkey FOREIGN KEY (llm_run_public_id) REFERENCES ai.llm_runs(public_id) ON DELETE SET NULL;


--
-- Name: mcp_tool_calls mcp_tool_calls_mcp_server_public_id_fkey; Type: FK CONSTRAINT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.mcp_tool_calls
    ADD CONSTRAINT mcp_tool_calls_mcp_server_public_id_fkey FOREIGN KEY (mcp_server_public_id) REFERENCES ai.mcp_servers(public_id);


--
-- Name: mcp_tool_calls mcp_tool_calls_mcp_tool_public_id_fkey; Type: FK CONSTRAINT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.mcp_tool_calls
    ADD CONSTRAINT mcp_tool_calls_mcp_tool_public_id_fkey FOREIGN KEY (mcp_tool_public_id) REFERENCES ai.mcp_tools(public_id);


--
-- Name: mcp_tool_calls mcp_tool_calls_session_public_id_fkey; Type: FK CONSTRAINT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.mcp_tool_calls
    ADD CONSTRAINT mcp_tool_calls_session_public_id_fkey FOREIGN KEY (session_public_id) REFERENCES ai.chat_sessions(public_id) ON DELETE SET NULL;


--
-- Name: mcp_tools mcp_tools_mcp_server_public_id_fkey; Type: FK CONSTRAINT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.mcp_tools
    ADD CONSTRAINT mcp_tools_mcp_server_public_id_fkey FOREIGN KEY (mcp_server_public_id) REFERENCES ai.mcp_servers(public_id) ON DELETE CASCADE;


--
-- Name: observability_snapshots observability_snapshots_created_by_job_public_id_fkey; Type: FK CONSTRAINT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.observability_snapshots
    ADD CONSTRAINT observability_snapshots_created_by_job_public_id_fkey FOREIGN KEY (created_by_job_public_id) REFERENCES ai.job_runs(public_id) ON DELETE SET NULL;


--
-- Name: observability_snapshots observability_snapshots_incident_public_id_fkey; Type: FK CONSTRAINT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.observability_snapshots
    ADD CONSTRAINT observability_snapshots_incident_public_id_fkey FOREIGN KEY (incident_public_id) REFERENCES ai.incidents(public_id) ON DELETE SET NULL;


--
-- Name: observability_snapshots observability_snapshots_llm_run_public_id_fkey; Type: FK CONSTRAINT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.observability_snapshots
    ADD CONSTRAINT observability_snapshots_llm_run_public_id_fkey FOREIGN KEY (llm_run_public_id) REFERENCES ai.llm_runs(public_id) ON DELETE SET NULL;


--
-- Name: observability_snapshots observability_snapshots_session_public_id_fkey; Type: FK CONSTRAINT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.observability_snapshots
    ADD CONSTRAINT observability_snapshots_session_public_id_fkey FOREIGN KEY (session_public_id) REFERENCES ai.chat_sessions(public_id) ON DELETE SET NULL;


--
-- Name: ops_report_rca_refs ops_report_rca_refs_incident_public_id_fkey; Type: FK CONSTRAINT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.ops_report_rca_refs
    ADD CONSTRAINT ops_report_rca_refs_incident_public_id_fkey FOREIGN KEY (incident_public_id) REFERENCES ai.incidents(public_id) ON DELETE CASCADE;


--
-- Name: ops_report_rca_refs ops_report_rca_refs_rca_report_public_id_fkey; Type: FK CONSTRAINT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.ops_report_rca_refs
    ADD CONSTRAINT ops_report_rca_refs_rca_report_public_id_fkey FOREIGN KEY (rca_report_public_id) REFERENCES ai.rca_reports(public_id) ON DELETE CASCADE;


--
-- Name: ops_report_rca_refs ops_report_rca_refs_report_public_id_fkey; Type: FK CONSTRAINT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.ops_report_rca_refs
    ADD CONSTRAINT ops_report_rca_refs_report_public_id_fkey FOREIGN KEY (report_public_id) REFERENCES ai.ops_reports(public_id) ON DELETE CASCADE;


--
-- Name: ops_reports ops_reports_llm_run_public_id_fkey; Type: FK CONSTRAINT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.ops_reports
    ADD CONSTRAINT ops_reports_llm_run_public_id_fkey FOREIGN KEY (llm_run_public_id) REFERENCES ai.llm_runs(public_id) ON DELETE SET NULL;


--
-- Name: payment_request_publish_events payment_request_publish_events_draft_public_id_fkey; Type: FK CONSTRAINT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.payment_request_publish_events
    ADD CONSTRAINT payment_request_publish_events_draft_public_id_fkey FOREIGN KEY (draft_public_id) REFERENCES ai.bnpl_payment_drafts(public_id) ON DELETE CASCADE;


--
-- Name: prediction_error_metrics prediction_error_metrics_actual_metric_public_id_fkey; Type: FK CONSTRAINT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.prediction_error_metrics
    ADD CONSTRAINT prediction_error_metrics_actual_metric_public_id_fkey FOREIGN KEY (actual_metric_public_id) REFERENCES ai.actual_metrics(public_id) ON DELETE CASCADE;


--
-- Name: prediction_error_metrics prediction_error_metrics_prediction_metric_public_id_fkey; Type: FK CONSTRAINT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.prediction_error_metrics
    ADD CONSTRAINT prediction_error_metrics_prediction_metric_public_id_fkey FOREIGN KEY (prediction_metric_public_id) REFERENCES ai.prediction_metrics(public_id) ON DELETE CASCADE;


--
-- Name: prediction_metrics prediction_metrics_prediction_run_public_id_fkey; Type: FK CONSTRAINT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.prediction_metrics
    ADD CONSTRAINT prediction_metrics_prediction_run_public_id_fkey FOREIGN KEY (prediction_run_public_id) REFERENCES ai.prediction_runs(public_id) ON DELETE CASCADE;


--
-- Name: prediction_runs prediction_runs_model_version_public_id_fkey; Type: FK CONSTRAINT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.prediction_runs
    ADD CONSTRAINT prediction_runs_model_version_public_id_fkey FOREIGN KEY (model_version_public_id) REFERENCES ai.model_versions(public_id);


--
-- Name: rca_feedback rca_feedback_rca_report_public_id_fkey; Type: FK CONSTRAINT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.rca_feedback
    ADD CONSTRAINT rca_feedback_rca_report_public_id_fkey FOREIGN KEY (rca_report_public_id) REFERENCES ai.rca_reports(public_id) ON DELETE CASCADE;


--
-- Name: rca_reports rca_reports_incident_public_id_fkey; Type: FK CONSTRAINT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.rca_reports
    ADD CONSTRAINT rca_reports_incident_public_id_fkey FOREIGN KEY (incident_public_id) REFERENCES ai.incidents(public_id);


--
-- Name: rca_reports rca_reports_llm_run_public_id_fkey; Type: FK CONSTRAINT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.rca_reports
    ADD CONSTRAINT rca_reports_llm_run_public_id_fkey FOREIGN KEY (llm_run_public_id) REFERENCES ai.llm_runs(public_id) ON DELETE SET NULL;


--
-- Name: rca_reports rca_reports_snapshot_public_id_fkey; Type: FK CONSTRAINT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.rca_reports
    ADD CONSTRAINT rca_reports_snapshot_public_id_fkey FOREIGN KEY (snapshot_public_id) REFERENCES ai.observability_snapshots(public_id) ON DELETE SET NULL;


--
-- Name: report_incidents report_incidents_incident_public_id_fkey; Type: FK CONSTRAINT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.report_incidents
    ADD CONSTRAINT report_incidents_incident_public_id_fkey FOREIGN KEY (incident_public_id) REFERENCES ai.incidents(public_id) ON DELETE CASCADE;


--
-- Name: report_incidents report_incidents_report_public_id_fkey; Type: FK CONSTRAINT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.report_incidents
    ADD CONSTRAINT report_incidents_report_public_id_fkey FOREIGN KEY (report_public_id) REFERENCES ai.ops_reports(public_id) ON DELETE CASCADE;


--
-- Name: report_metric_summaries report_metric_summaries_report_public_id_fkey; Type: FK CONSTRAINT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.report_metric_summaries
    ADD CONSTRAINT report_metric_summaries_report_public_id_fkey FOREIGN KEY (report_public_id) REFERENCES ai.ops_reports(public_id) ON DELETE SET NULL;


--
-- Name: report_metric_summaries report_metric_summaries_snapshot_public_id_fkey; Type: FK CONSTRAINT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.report_metric_summaries
    ADD CONSTRAINT report_metric_summaries_snapshot_public_id_fkey FOREIGN KEY (snapshot_public_id) REFERENCES ai.observability_snapshots(public_id) ON DELETE SET NULL;


--
-- Name: risk_analysis_reports risk_analysis_reports_disaster_simulation_public_id_fkey; Type: FK CONSTRAINT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.risk_analysis_reports
    ADD CONSTRAINT risk_analysis_reports_disaster_simulation_public_id_fkey FOREIGN KEY (disaster_simulation_public_id) REFERENCES ai.disaster_risk_simulations(public_id) ON DELETE SET NULL;


--
-- Name: risk_analysis_reports risk_analysis_reports_llm_run_public_id_fkey; Type: FK CONSTRAINT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.risk_analysis_reports
    ADD CONSTRAINT risk_analysis_reports_llm_run_public_id_fkey FOREIGN KEY (llm_run_public_id) REFERENCES ai.llm_runs(public_id) ON DELETE SET NULL;


--
-- Name: risk_analysis_targets risk_analysis_targets_risk_analysis_report_public_id_fkey; Type: FK CONSTRAINT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.risk_analysis_targets
    ADD CONSTRAINT risk_analysis_targets_risk_analysis_report_public_id_fkey FOREIGN KEY (risk_analysis_report_public_id) REFERENCES ai.risk_analysis_reports(public_id) ON DELETE CASCADE;


--
-- Name: scaling_events scaling_events_prediction_metric_public_id_fkey; Type: FK CONSTRAINT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.scaling_events
    ADD CONSTRAINT scaling_events_prediction_metric_public_id_fkey FOREIGN KEY (prediction_metric_public_id) REFERENCES ai.prediction_metrics(public_id) ON DELETE SET NULL;


--
-- Name: snapshot_items snapshot_items_snapshot_public_id_fkey; Type: FK CONSTRAINT; Schema: ai; Owner: -
--

ALTER TABLE ONLY ai.snapshot_items
    ADD CONSTRAINT snapshot_items_snapshot_public_id_fkey FOREIGN KEY (snapshot_public_id) REFERENCES ai.observability_snapshots(public_id) ON DELETE CASCADE;


--
-- Name: bnpl_payment_request_items bnpl_payment_request_items_payment_request_public_id_fkey; Type: FK CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.bnpl_payment_request_items
    ADD CONSTRAINT bnpl_payment_request_items_payment_request_public_id_fkey FOREIGN KEY (payment_request_public_id) REFERENCES catalog.bnpl_payment_requests(public_id);


--
-- Name: bnpl_payment_request_items bnpl_payment_request_items_product_public_id_fkey; Type: FK CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.bnpl_payment_request_items
    ADD CONSTRAINT bnpl_payment_request_items_product_public_id_fkey FOREIGN KEY (product_public_id) REFERENCES catalog.products(public_id);


--
-- Name: cart_items cart_items_product_public_id_fkey; Type: FK CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.cart_items
    ADD CONSTRAINT cart_items_product_public_id_fkey FOREIGN KEY (product_public_id) REFERENCES catalog.products(public_id);


--
-- Name: products products_category_public_id_fkey; Type: FK CONSTRAINT; Schema: catalog; Owner: -
--

ALTER TABLE ONLY catalog.products
    ADD CONSTRAINT products_category_public_id_fkey FOREIGN KEY (category_public_id) REFERENCES catalog.categories(public_id);


--
-- Name: audit_logs audit_logs_admin_user_public_id_fkey; Type: FK CONSTRAINT; Schema: core; Owner: -
--

ALTER TABLE ONLY core.audit_logs
    ADD CONSTRAINT audit_logs_admin_user_public_id_fkey FOREIGN KEY (admin_user_public_id) REFERENCES core.admin_users(public_id);


--
-- Name: audit_logs audit_logs_user_public_id_fkey; Type: FK CONSTRAINT; Schema: core; Owner: -
--

ALTER TABLE ONLY core.audit_logs
    ADD CONSTRAINT audit_logs_user_public_id_fkey FOREIGN KEY (user_public_id) REFERENCES core.users(public_id);


--
-- Name: bss_scores bss_scores_application_public_id_fkey; Type: FK CONSTRAINT; Schema: core; Owner: -
--

ALTER TABLE ONLY core.bss_scores
    ADD CONSTRAINT bss_scores_application_public_id_fkey FOREIGN KEY (application_public_id) REFERENCES core.credit_limit_applications(public_id) ON DELETE SET NULL;


--
-- Name: bss_scores bss_scores_user_public_id_fkey; Type: FK CONSTRAINT; Schema: core; Owner: -
--

ALTER TABLE ONLY core.bss_scores
    ADD CONSTRAINT bss_scores_user_public_id_fkey FOREIGN KEY (user_public_id) REFERENCES core.users(public_id);


--
-- Name: credit_limits credit_limits_application_public_id_fkey; Type: FK CONSTRAINT; Schema: core; Owner: -
--

ALTER TABLE ONLY core.credit_limits
    ADD CONSTRAINT credit_limits_application_public_id_fkey FOREIGN KEY (application_public_id) REFERENCES core.credit_limit_applications(public_id);


--
-- Name: credit_limits credit_limits_user_public_id_fkey; Type: FK CONSTRAINT; Schema: core; Owner: -
--

ALTER TABLE ONLY core.credit_limits
    ADD CONSTRAINT credit_limits_user_public_id_fkey FOREIGN KEY (user_public_id) REFERENCES core.users(public_id);


--
-- Name: credit_usage_ledger credit_usage_ledger_credit_limit_public_id_fkey; Type: FK CONSTRAINT; Schema: core; Owner: -
--

ALTER TABLE ONLY core.credit_usage_ledger
    ADD CONSTRAINT credit_usage_ledger_credit_limit_public_id_fkey FOREIGN KEY (credit_limit_public_id) REFERENCES core.credit_limits(public_id);


--
-- Name: credit_usage_ledger credit_usage_ledger_order_public_id_fkey; Type: FK CONSTRAINT; Schema: core; Owner: -
--

ALTER TABLE ONLY core.credit_usage_ledger
    ADD CONSTRAINT credit_usage_ledger_order_public_id_fkey FOREIGN KEY (order_public_id) REFERENCES core.orders(public_id);


--
-- Name: farmer_documents fk98p6lv6putmqwr4oglgc8dpcy; Type: FK CONSTRAINT; Schema: core; Owner: -
--

ALTER TABLE ONLY core.farmer_documents
    ADD CONSTRAINT fk98p6lv6putmqwr4oglgc8dpcy FOREIGN KEY (application_id) REFERENCES core.credit_limit_applications(id);


--
-- Name: ass_scores fkc3e0me5ikap7ed2tj8f1xfps2; Type: FK CONSTRAINT; Schema: core; Owner: -
--

ALTER TABLE ONLY core.ass_scores
    ADD CONSTRAINT fkc3e0me5ikap7ed2tj8f1xfps2 FOREIGN KEY (application_id) REFERENCES core.credit_limit_applications(id);


--
-- Name: interest_ledger interest_ledger_credit_limit_public_id_fkey; Type: FK CONSTRAINT; Schema: core; Owner: -
--

ALTER TABLE ONLY core.interest_ledger
    ADD CONSTRAINT interest_ledger_credit_limit_public_id_fkey FOREIGN KEY (credit_limit_public_id) REFERENCES core.credit_limits(public_id);


--
-- Name: loan_overdue_ledger loan_overdue_ledger_credit_limit_public_id_fkey; Type: FK CONSTRAINT; Schema: core; Owner: -
--

ALTER TABLE ONLY core.loan_overdue_ledger
    ADD CONSTRAINT loan_overdue_ledger_credit_limit_public_id_fkey FOREIGN KEY (credit_limit_public_id) REFERENCES core.credit_limits(public_id);


--
-- Name: loan_overdue_ledger loan_overdue_ledger_interest_ledger_public_id_fkey; Type: FK CONSTRAINT; Schema: core; Owner: -
--

ALTER TABLE ONLY core.loan_overdue_ledger
    ADD CONSTRAINT loan_overdue_ledger_interest_ledger_public_id_fkey FOREIGN KEY (interest_ledger_public_id) REFERENCES core.interest_ledger(public_id);


--
-- Name: loan_overdue_ledger loan_overdue_ledger_principal_repayment_public_id_fkey; Type: FK CONSTRAINT; Schema: core; Owner: -
--

ALTER TABLE ONLY core.loan_overdue_ledger
    ADD CONSTRAINT loan_overdue_ledger_principal_repayment_public_id_fkey FOREIGN KEY (principal_repayment_public_id) REFERENCES core.principal_repayment_ledger(public_id);


--
-- Name: loan_overdue_ledger loan_overdue_ledger_user_public_id_fkey; Type: FK CONSTRAINT; Schema: core; Owner: -
--

ALTER TABLE ONLY core.loan_overdue_ledger
    ADD CONSTRAINT loan_overdue_ledger_user_public_id_fkey FOREIGN KEY (user_public_id) REFERENCES core.users(public_id);


--
-- Name: notifications notifications_user_public_id_fkey; Type: FK CONSTRAINT; Schema: core; Owner: -
--

ALTER TABLE ONLY core.notifications
    ADD CONSTRAINT notifications_user_public_id_fkey FOREIGN KEY (user_public_id) REFERENCES core.users(public_id);


--
-- Name: order_items order_items_order_public_id_fkey; Type: FK CONSTRAINT; Schema: core; Owner: -
--

ALTER TABLE ONLY core.order_items
    ADD CONSTRAINT order_items_order_public_id_fkey FOREIGN KEY (order_public_id) REFERENCES core.orders(public_id) ON DELETE CASCADE;


--
-- Name: orders orders_user_public_id_fkey; Type: FK CONSTRAINT; Schema: core; Owner: -
--

ALTER TABLE ONLY core.orders
    ADD CONSTRAINT orders_user_public_id_fkey FOREIGN KEY (user_public_id) REFERENCES core.users(public_id);


--
-- Name: principal_repayment_ledger principal_repayment_ledger_credit_limit_public_id_fkey; Type: FK CONSTRAINT; Schema: core; Owner: -
--

ALTER TABLE ONLY core.principal_repayment_ledger
    ADD CONSTRAINT principal_repayment_ledger_credit_limit_public_id_fkey FOREIGN KEY (credit_limit_public_id) REFERENCES core.credit_limits(public_id);


--
-- Name: principal_repayment_ledger principal_repayment_ledger_order_public_id_fkey; Type: FK CONSTRAINT; Schema: core; Owner: -
--

ALTER TABLE ONLY core.principal_repayment_ledger
    ADD CONSTRAINT principal_repayment_ledger_order_public_id_fkey FOREIGN KEY (order_public_id) REFERENCES core.orders(public_id);


--
-- Name: user_auth user_auth_user_public_id_fkey; Type: FK CONSTRAINT; Schema: core; Owner: -
--

ALTER TABLE ONLY core.user_auth
    ADD CONSTRAINT user_auth_user_public_id_fkey FOREIGN KEY (user_public_id) REFERENCES core.users(public_id);


--
-- Name: wallet_transactions wallet_transactions_wallet_public_id_fkey; Type: FK CONSTRAINT; Schema: core; Owner: -
--

ALTER TABLE ONLY core.wallet_transactions
    ADD CONSTRAINT wallet_transactions_wallet_public_id_fkey FOREIGN KEY (wallet_public_id) REFERENCES core.wallets(public_id);


--
-- Name: wallets wallets_user_public_id_fkey; Type: FK CONSTRAINT; Schema: core; Owner: -
--

ALTER TABLE ONLY core.wallets
    ADD CONSTRAINT wallets_user_public_id_fkey FOREIGN KEY (user_public_id) REFERENCES core.users(public_id);


--
-- PostgreSQL database dump complete
--


