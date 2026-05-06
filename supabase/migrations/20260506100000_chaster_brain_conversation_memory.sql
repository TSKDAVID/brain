-- Rolling-summary memory store for chat conversations.
-- Each row keeps a compressed summary of all messages older than the most recent
-- N turns so we can keep prompts small while preserving context.

create table if not exists public.brain_conversation_summaries (
    conversation_id uuid primary key references public.conversations (id) on delete cascade,
    tenant_id uuid not null references public.tenants (id) on delete cascade,
    summary_text text not null default '',
    summarized_through_message_id uuid references public.messages (id) on delete set null,
    summarized_message_count integer not null default 0 check (summarized_message_count >= 0),
    version integer not null default 1 check (version >= 1),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index if not exists brain_conversation_summaries_tenant_idx
    on public.brain_conversation_summaries (tenant_id, conversation_id);

create or replace function public.brain_conversation_summaries_set_updated_at()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
    new.updated_at := now();
    new.version := coalesce(old.version, 1) + 1;
    return new;
end;
$$;

drop trigger if exists brain_conversation_summaries_before_update
    on public.brain_conversation_summaries;
create trigger brain_conversation_summaries_before_update
    before update on public.brain_conversation_summaries
    for each row
    execute function public.brain_conversation_summaries_set_updated_at();

alter table public.brain_conversation_summaries enable row level security;

drop policy if exists brain_conversation_summaries_tenant_select
    on public.brain_conversation_summaries;
create policy brain_conversation_summaries_tenant_select on public.brain_conversation_summaries
    for select to authenticated
    using (
        tenant_id = public.get_my_tenant_id()
        and public.has_tenant_role(array['member', 'admin', 'super_admin']::text[])
    );

drop policy if exists brain_conversation_summaries_tenant_write
    on public.brain_conversation_summaries;
create policy brain_conversation_summaries_tenant_write on public.brain_conversation_summaries
    for all to authenticated
    using (
        tenant_id = public.get_my_tenant_id()
        and public.has_tenant_role(array['admin', 'super_admin']::text[])
    )
    with check (
        tenant_id = public.get_my_tenant_id()
        and public.has_tenant_role(array['admin', 'super_admin']::text[])
    );

grant select, insert, update, delete on public.brain_conversation_summaries to authenticated;
grant all on table public.brain_conversation_summaries to service_role;
grant execute on function public.brain_conversation_summaries_set_updated_at() to service_role;
