-- 중간보고서 그림 5(Supabase Schema Visualizer ERD) 촬영용 스키마.
-- 실제 코드(app/db/models.py)와 동일 구조. Supabase SQL Editor에 전체 붙여넣고 Run.

create table apps (
  id bigint generated always as identity primary key,
  name varchar(100) unique not null,
  repo_url varchar(300) not null,
  branch varchar(100) not null default 'main',
  framework varchar(50) not null,
  health_path varchar(100) not null default '/healthz',
  port integer not null default 8080,
  namespace varchar(100) not null default 'default',
  image_repo varchar(300) not null default '',
  current_sha varchar(40) not null default '',
  status varchar(30) not null default 'unknown',
  env_vars jsonb not null default '[]',
  created_at timestamptz not null default now()
);

create table builds (
  id bigint generated always as identity primary key,
  app_id bigint not null references apps(id),
  status varchar(30) not null default 'pending',
  image_tag varchar(40) not null default '',
  workflow_name varchar(120) not null default '',
  log_ref varchar(200) not null default '',
  started_at timestamptz not null default now(),
  finished_at timestamptz
);

create table experiments (
  id bigint generated always as identity primary key,
  app_id bigint not null references apps(id),
  chaos_type varchar(40) not null,
  params jsonb not null default '{}',
  status varchar(30) not null default 'pending',
  crd_name varchar(120) not null default '',
  baseline_metrics jsonb not null default '{}',
  fault_metrics jsonb not null default '{}',
  recovery_metrics jsonb not null default '{}',
  baseline_r double precision,
  r_index double precision,
  target_r double precision not null default 0.7,
  started_at timestamptz not null default now(),
  finished_at timestamptz
);

create table agent_iterations (
  id bigint generated always as identity primary key,
  experiment_id bigint not null references experiments(id),
  iteration integer not null,
  observer_output text not null default '',
  analyst_output text not null default '',
  recommender_output text not null default '',
  params_before jsonb not null default '{}',
  params_after jsonb not null default '{}',
  r_index double precision,
  verdict varchar(30) not null default '',
  llm_cost_usd double precision not null default 0.0,
  created_at timestamptz not null default now()
);
