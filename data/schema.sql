-- The analytics slice of a travel agency's Customer-360 warehouse.
--
-- Table and column names match the production Postgres schema this project is
-- meant to run against, so the same SQL runs on the demo file and on the live
-- database. Only the tables a manager asks questions about are here; pipeline
-- tables (jobs, raw events, spend tracking) are left out on purpose.
--
-- Written in the subset of SQL that both Postgres and DuckDB accept. Postgres
-- enums are plain text here; their allowed values live in semantic/model.yaml.

CREATE TABLE agents (
  agent_id        uuid PRIMARY KEY,
  bitrix_user_id  text UNIQUE,
  full_name       text NOT NULL,
  team            text,                      -- 'sales' | 'support' | 'bot'
  is_bot          boolean NOT NULL DEFAULT false,
  is_active       boolean NOT NULL DEFAULT true,
  hired_at        date
);

CREATE TABLE customers (
  customer_id         uuid PRIMARY KEY,
  display_name        text,
  primary_phone_e164  text UNIQUE,
  nationality         text,                  -- 'Saudi', 'Egyptian', ...
  residence_city      text,                  -- 'Riyadh', 'Cairo', ...
  residence_country   char(2),               -- ISO code
  preferred_language  char(2),
  first_seen_at       timestamptz NOT NULL,
  last_seen_at        timestamptz
);

CREATE TABLE destinations (
  destination_id  int PRIMARY KEY,
  canonical_name  text NOT NULL UNIQUE,      -- English: 'Istanbul', 'Trabzon', ...
  country_code    char(2),
  region          text,
  kind            text                       -- 'city' | 'country' | 'region'
);

CREATE TABLE destination_aliases (
  alias_id        int PRIMARY KEY,
  destination_id  int NOT NULL REFERENCES destinations(destination_id),
  alias           text NOT NULL,             -- how customers write it: 'اسطنبول', 'استنبول'
  lang            char(2)
);

-- One row per conversation (a chat thread).
CREATE TABLE interactions (
  interaction_id          uuid PRIMARY KEY,
  customer_id             uuid REFERENCES customers(customer_id),
  agent_id                uuid REFERENCES agents(agent_id),
  deal_id                 uuid,
  channel                 text NOT NULL,     -- 'whatsapp' | 'instagram' | 'facebook' | 'telegram' | 'webchat'
  handled_by              text NOT NULL,     -- 'agent' | 'bot'
  is_bot_handled          boolean NOT NULL DEFAULT false,
  external_id             text NOT NULL,
  external_source         text NOT NULL,
  customer_phone_e164     text,
  started_at              timestamptz NOT NULL,
  ended_at                timestamptz,
  message_count           int NOT NULL DEFAULT 0,
  customer_message_count  int NOT NULL DEFAULT 0,
  agent_message_count     int NOT NULL DEFAULT 0,
  first_response_seconds  int,
  avg_response_seconds    int,
  is_after_hours          boolean,
  external_deal_id        text
);

-- Numbers computed from message metadata, never asked of a model.
CREATE TABLE interaction_metrics (
  interaction_id            uuid PRIMARY KEY REFERENCES interactions(interaction_id),
  first_response_seconds    int,
  median_response_seconds   int,
  max_response_gap_seconds  int,
  customer_message_count    int,
  agent_message_count       int,
  conversation_span_seconds int,
  after_hours               boolean,
  language_matched          boolean,
  followup_count            int NOT NULL DEFAULT 0,
  hours_to_first_followup   numeric(8,2)
);

-- AI pass 1: what the customer wanted.
CREATE TABLE interaction_analysis (
  analysis_id          uuid PRIMARY KEY,
  interaction_id       uuid NOT NULL UNIQUE REFERENCES interactions(interaction_id),
  model                text NOT NULL,
  language             char(2),
  intent               text,                 -- 'price_inquiry', 'booking_request', ...
  service              text NOT NULL DEFAULT 'unknown',
  service_raw          text,
  customer_nationality text,
  residence_city       text,
  date_start           date,
  date_end             date,
  nights               int,
  travelers_total      int,
  travelers_adults     int,
  travelers_children   int,
  budget_amount        numeric(12,2),
  budget_currency      char(3),
  buying_stage         text NOT NULL DEFAULT 'unknown',
  lead_temp            text NOT NULL DEFAULT 'unknown',
  is_decision_maker    boolean,
  summary_ar           text,
  confidence           numeric(3,2),
  created_at           timestamptz NOT NULL
);

-- One row per trip leg, so "Istanbul + Trabzon" is two rows.
CREATE TABLE interaction_destinations (
  id              int PRIMARY KEY,
  analysis_id     uuid NOT NULL REFERENCES interaction_analysis(analysis_id),
  destination_id  int REFERENCES destinations(destination_id),
  raw_name        text NOT NULL,
  role            text,                      -- 'origin' | 'destination' | 'stopover'
  leg_order       int,
  nights          int
);

-- AI pass 2: how well the agent handled it, on a 5-module rubric.
CREATE TABLE agent_evaluations (
  evaluation_id      uuid PRIMARY KEY,
  interaction_id     uuid NOT NULL UNIQUE REFERENCES interactions(interaction_id),
  agent_id           uuid REFERENCES agents(agent_id),
  prompt_version     text NOT NULL,
  rubric_version     text NOT NULL,
  model              text NOT NULL,
  input_type         text NOT NULL,          -- 'chat'
  final_score        numeric(5,2),           -- 0-100
  performance_level  text,                   -- 'Excellent' | 'Good' | 'Average' | 'Below Average'
  weight_applied     numeric(4,3),
  m1_reception       numeric(5,2),
  m2_offer           numeric(5,2),
  m3_objections      numeric(5,2),
  m4_followup        numeric(5,2),
  m5_closing         numeric(5,2),
  stage_reached      text,
  top_strength       text,
  top_weakness       text,
  contract_status    text NOT NULL DEFAULT 'ok',  -- 'ok' | 'contract_failed' | 'ungradeable' | 'unscoreable'
  gradeable          boolean NOT NULL DEFAULT true,
  created_at         timestamptz NOT NULL
);

-- Deals synced from the CRM (Bitrix24).
CREATE TABLE deals (
  deal_id          uuid PRIMARY KEY,
  bitrix_deal_id   text NOT NULL UNIQUE,
  customer_id      uuid REFERENCES customers(customer_id),
  agent_id         uuid REFERENCES agents(agent_id),
  title            text,
  category_id      text,
  stage_id         text,                     -- 'NEW', 'PREPARATION', ..., 'WON', 'LOSE'
  stage_semantic   char(1),                  -- 'P' open | 'S' won | 'F' lost
  is_closed        boolean NOT NULL DEFAULT false,
  amount           numeric(14,2),
  currency         char(3),
  source_channel   text,
  service          text NOT NULL DEFAULT 'unknown',
  lead_temp        text NOT NULL DEFAULT 'unknown',
  begin_date       date,
  close_date       date,
  created_at_src   timestamptz,
  modified_at_src  timestamptz,
  origin           text NOT NULL DEFAULT 'bitrix',
  ai_outcome       text
);

-- Promises an agent made in a conversation ("I'll send the offer tomorrow").
CREATE TABLE follow_ups (
  follow_up_id     uuid PRIMARY KEY,
  customer_id      uuid REFERENCES customers(customer_id),
  agent_id         uuid REFERENCES agents(agent_id),
  promised_in      uuid REFERENCES interactions(interaction_id),
  fulfilled_in     uuid REFERENCES interactions(interaction_id),
  promise_text     text,
  promised_at      timestamptz NOT NULL,
  due_at           timestamptz,
  fulfilled_at     timestamptz,
  hours_to_fulfil  numeric(8,2),
  status           text NOT NULL DEFAULT 'open',  -- 'open' | 'fulfilled' | 'late' | 'missed' | 'cancelled'
  channel          text
);
