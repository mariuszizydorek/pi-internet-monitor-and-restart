-- Shared tables for every Pi. Each row is tagged with site_id.
-- Sync and Grafana both use the project secret key. This file is applied by
-- ./scripts/setup-supabase.sh and again whenever sync starts.

create table if not exists interface_samples (
    id bigint generated always as identity primary key,
    site_id text not null,
    local_id bigint not null,
    recorded_at timestamptz not null,
    iface text not null,
    carrier integer,
    operstate text,
    wifi_ssid text,
    wifi_signal_dbm integer,
    ipv4 text,
    dns_ok integer not null,
    ping_ok integer not null,
    fetch_ok integer not null,
    internet_ok integer not null,
    probes_json jsonb not null default '{}'::jsonb,
    unique (site_id, local_id)
);

create table if not exists router_checks (
    id bigint generated always as identity primary key,
    site_id text not null,
    local_id bigint not null,
    recorded_at timestamptz not null,
    gateway_ip text,
    ping_ok integer,
    rtt_ms double precision,
    deco_api_ok integer,
    wan_status text,
    client_count integer,
    cpu_usage double precision,
    mem_usage double precision,
    model text,
    firmware text,
    detail_json jsonb not null default '{}'::jsonb,
    unique (site_id, local_id)
);

create table if not exists speed_samples (
    id bigint generated always as identity primary key,
    site_id text not null,
    local_id bigint not null,
    recorded_at timestamptz not null,
    source text not null,
    download_mbps double precision,
    upload_mbps double precision,
    latency_ms double precision,
    detail_json jsonb not null default '{}'::jsonb,
    unique (site_id, local_id)
);

create table if not exists restart_events (
    id bigint generated always as identity primary key,
    site_id text not null,
    local_id bigint not null,
    recorded_at timestamptz not null,
    action text not null,
    detail text not null,
    unique (site_id, local_id)
);

create index if not exists idx_interface_site_time on interface_samples (site_id, recorded_at);
create index if not exists idx_router_site_time on router_checks (site_id, recorded_at);
create index if not exists idx_speed_site_time on speed_samples (site_id, recorded_at);
create index if not exists idx_restart_site_time on restart_events (site_id, recorded_at);

alter table interface_samples enable row level security;
alter table router_checks enable row level security;
alter table speed_samples enable row level security;
alter table restart_events enable row level security;
