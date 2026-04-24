create table if not exists public.app_configurations (
    id uuid primary key default gen_random_uuid(),
    tenant_id uuid not null references public.tenants (id) on delete cascade,
    app_id text not null unique,
    hmac_secret text not null,
    allowed_origins text[] not null default '{}'::text[],
    status text not null default 'active'
        check (status in ('active', 'disabled', 'rotating')),
    last_rotated_at timestamptz,
    created_by uuid references auth.users (id),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index if not exists app_configurations_tenant_idx
    on public.app_configurations (tenant_id);

create or replace function public.app_configurations_set_updated_at()
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

drop trigger if exists app_configurations_before_update_updated_at on public.app_configurations;
create trigger app_configurations_before_update_updated_at
    before update on public.app_configurations
    for each row
    execute function public.app_configurations_set_updated_at();

alter table public.app_configurations enable row level security;

create policy app_configurations_select_tenant on public.app_configurations
    for select to authenticated
    using (
        tenant_id = public.get_my_tenant_id()
        and public.has_tenant_role(array['member', 'admin', 'super_admin']::text[])
    );

create policy app_configurations_insert_tenant on public.app_configurations
    for insert to authenticated
    with check (
        tenant_id = public.get_my_tenant_id()
        and public.has_tenant_role(array['admin', 'super_admin']::text[])
    );

create policy app_configurations_update_tenant on public.app_configurations
    for update to authenticated
    using (
        tenant_id = public.get_my_tenant_id()
        and public.has_tenant_role(array['admin', 'super_admin']::text[])
    )
    with check (
        tenant_id = public.get_my_tenant_id()
        and public.has_tenant_role(array['admin', 'super_admin']::text[])
    );

create policy app_configurations_delete_tenant on public.app_configurations
    for delete to authenticated
    using (
        tenant_id = public.get_my_tenant_id()
        and public.has_tenant_role(array['super_admin']::text[])
    );

grant select, insert, update, delete on public.app_configurations to authenticated;
grant all on table public.app_configurations to service_role;
grant execute on function public.app_configurations_set_updated_at() to service_role;
