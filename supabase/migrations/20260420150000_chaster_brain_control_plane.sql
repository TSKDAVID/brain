create table if not exists public.brain_runtime_control (
    id uuid primary key default gen_random_uuid(),
    tenant_id uuid not null references public.tenants (id) on delete cascade,
    is_running boolean not null default true,
    mode text not null default 'automatic' check (mode in ('automatic', 'manual')),
    updated_by uuid references auth.users (id),
    updated_at timestamptz not null default now(),
    created_at timestamptz not null default now(),
    unique (tenant_id)
);

create table if not exists public.brain_parameters (
    id uuid primary key default gen_random_uuid(),
    tenant_id uuid not null references public.tenants (id) on delete cascade,
    confidence_threshold double precision not null default 0.6 check (confidence_threshold >= 0 and confidence_threshold <= 1),
    max_context_chunks integer not null default 8 check (max_context_chunks between 1 and 30),
    response_tone text not null default 'professional',
    mcp_enabled boolean not null default true,
    updated_by uuid references auth.users (id),
    updated_at timestamptz not null default now(),
    created_at timestamptz not null default now(),
    unique (tenant_id)
);

create table if not exists public.brain_index_jobs (
    id uuid primary key default gen_random_uuid(),
    tenant_id uuid not null references public.tenants (id) on delete cascade,
    source_type text not null check (source_type in ('text', 'url', 'document')),
    source_ref text,
    payload jsonb not null default '{}'::jsonb,
    status text not null default 'queued' check (status in ('queued', 'processing', 'completed', 'failed')),
    error_message text,
    requested_by uuid references auth.users (id),
    requested_at timestamptz not null default now(),
    processed_at timestamptz
);

create index if not exists brain_index_jobs_tenant_requested_idx
    on public.brain_index_jobs (tenant_id, requested_at desc);

create table if not exists public.brain_metrics_daily (
    id uuid primary key default gen_random_uuid(),
    tenant_id uuid not null references public.tenants (id) on delete cascade,
    metric_date date not null default current_date,
    total_requests integer not null default 0,
    faq_requests integer not null default 0,
    personal_requests integer not null default 0,
    low_confidence_count integer not null default 0,
    blocked_request_count integer not null default 0,
    avg_confidence double precision not null default 0,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (tenant_id, metric_date)
);

create or replace function public.brain_control_set_updated_at()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
    new.updated_at := now();
    return new;
end;
$$;

drop trigger if exists brain_runtime_control_before_update on public.brain_runtime_control;
create trigger brain_runtime_control_before_update
    before update on public.brain_runtime_control
    for each row
    execute function public.brain_control_set_updated_at();

drop trigger if exists brain_parameters_before_update on public.brain_parameters;
create trigger brain_parameters_before_update
    before update on public.brain_parameters
    for each row
    execute function public.brain_control_set_updated_at();

drop trigger if exists brain_metrics_daily_before_update on public.brain_metrics_daily;
create trigger brain_metrics_daily_before_update
    before update on public.brain_metrics_daily
    for each row
    execute function public.brain_control_set_updated_at();

alter table public.brain_runtime_control enable row level security;
alter table public.brain_parameters enable row level security;
alter table public.brain_index_jobs enable row level security;
alter table public.brain_metrics_daily enable row level security;

drop policy if exists brain_runtime_control_tenant_all on public.brain_runtime_control;
create policy brain_runtime_control_tenant_all on public.brain_runtime_control
    for all to authenticated
    using (
        tenant_id = public.get_my_tenant_id()
        and public.has_tenant_role(array['member', 'admin', 'super_admin']::text[])
    )
    with check (
        tenant_id = public.get_my_tenant_id()
        and public.has_tenant_role(array['admin', 'super_admin']::text[])
    );

drop policy if exists brain_parameters_tenant_all on public.brain_parameters;
create policy brain_parameters_tenant_all on public.brain_parameters
    for all to authenticated
    using (
        tenant_id = public.get_my_tenant_id()
        and public.has_tenant_role(array['member', 'admin', 'super_admin']::text[])
    )
    with check (
        tenant_id = public.get_my_tenant_id()
        and public.has_tenant_role(array['admin', 'super_admin']::text[])
    );

drop policy if exists brain_index_jobs_tenant_all on public.brain_index_jobs;
create policy brain_index_jobs_tenant_all on public.brain_index_jobs
    for all to authenticated
    using (
        tenant_id = public.get_my_tenant_id()
        and public.has_tenant_role(array['member', 'admin', 'super_admin']::text[])
    )
    with check (
        tenant_id = public.get_my_tenant_id()
        and public.has_tenant_role(array['member', 'admin', 'super_admin']::text[])
    );

drop policy if exists brain_metrics_daily_tenant_select on public.brain_metrics_daily;
create policy brain_metrics_daily_tenant_select on public.brain_metrics_daily
    for select to authenticated
    using (
        tenant_id = public.get_my_tenant_id()
        and public.has_tenant_role(array['member', 'admin', 'super_admin']::text[])
    );

drop policy if exists brain_metrics_daily_tenant_write on public.brain_metrics_daily;
create policy brain_metrics_daily_tenant_write on public.brain_metrics_daily
    for all to authenticated
    using (
        tenant_id = public.get_my_tenant_id()
        and public.has_tenant_role(array['admin', 'super_admin']::text[])
    )
    with check (
        tenant_id = public.get_my_tenant_id()
        and public.has_tenant_role(array['admin', 'super_admin']::text[])
    );

grant select, insert, update, delete on public.brain_runtime_control to authenticated;
grant select, insert, update, delete on public.brain_parameters to authenticated;
grant select, insert, update, delete on public.brain_index_jobs to authenticated;
grant select, insert, update, delete on public.brain_metrics_daily to authenticated;
grant all on table public.brain_runtime_control to service_role;
grant all on table public.brain_parameters to service_role;
grant all on table public.brain_index_jobs to service_role;
grant all on table public.brain_metrics_daily to service_role;

grant execute on function public.brain_control_set_updated_at() to service_role;
