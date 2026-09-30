-- Deco internet details, mesh nodes, and clients.
-- Applied with the other SQL files when a Supabase access token is configured.

alter table router_checks add column if not exists connect_type text;
alter table router_checks add column if not exists wan_ip text;
alter table router_checks add column if not exists wan_gateway text;
alter table router_checks add column if not exists dns_primary text;
alter table router_checks add column if not exists lan_ip text;

create table if not exists deco_nodes (
    id bigint generated always as identity primary key,
    site_id text not null,
    local_id bigint not null,
    recorded_at timestamptz not null,
    mac text,
    name text,
    role text,
    model text,
    firmware text,
    ip text,
    inet_status text,
    group_status text,
    unique (site_id, local_id)
);

create table if not exists deco_clients (
    id bigint generated always as identity primary key,
    site_id text not null,
    local_id bigint not null,
    recorded_at timestamptz not null,
    mac text,
    name text,
    ip text,
    online integer not null,
    connection text,
    up_kbps integer,
    down_kbps integer,
    client_type text,
    unique (site_id, local_id)
);

create index if not exists idx_deco_nodes_site_time on deco_nodes (site_id, recorded_at);
create index if not exists idx_deco_clients_site_time on deco_clients (site_id, recorded_at);

alter table deco_nodes enable row level security;
alter table deco_clients enable row level security;

create or replace view deco_nodes_latest as
select n.site_id, n.recorded_at, n.mac, n.name, n.role, n.model, n.firmware, n.ip, n.inet_status, n.group_status
from deco_nodes n
join (
    select site_id, max(recorded_at) as recorded_at
    from deco_nodes
    group by site_id
) latest on latest.site_id = n.site_id and latest.recorded_at = n.recorded_at;

create or replace view deco_clients_latest as
select c.site_id, c.recorded_at, c.mac, c.name, c.ip, c.online, c.connection, c.up_kbps, c.down_kbps, c.client_type
from deco_clients c
join (
    select site_id, max(recorded_at) as recorded_at
    from deco_clients
    group by site_id
) latest on latest.site_id = c.site_id and latest.recorded_at = c.recorded_at;
