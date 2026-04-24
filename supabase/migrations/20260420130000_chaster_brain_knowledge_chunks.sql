create extension if not exists vector;

create table if not exists public.knowledge_chunks (
    id uuid primary key default gen_random_uuid(),
    tenant_id uuid not null references public.tenants (id) on delete cascade,
    document_id uuid not null references public.knowledge_base_documents (id) on delete cascade,
    chunk_index integer not null,
    chunk_text text not null,
    metadata jsonb not null default '{}'::jsonb,
    embedding vector(1536) not null,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (document_id, chunk_index)
);

create index if not exists knowledge_chunks_tenant_document_idx
    on public.knowledge_chunks (tenant_id, document_id);

create index if not exists knowledge_chunks_embedding_hnsw_cosine_idx
    on public.knowledge_chunks using hnsw (embedding vector_cosine_ops);

create or replace function public.knowledge_chunks_set_updated_at()
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

drop trigger if exists knowledge_chunks_before_update_updated_at on public.knowledge_chunks;
create trigger knowledge_chunks_before_update_updated_at
    before update on public.knowledge_chunks
    for each row
    execute function public.knowledge_chunks_set_updated_at();

alter table public.knowledge_chunks enable row level security;

create policy knowledge_chunks_select_tenant on public.knowledge_chunks
    for select to authenticated
    using (
        tenant_id = public.get_my_tenant_id()
        and public.has_tenant_role(array['member', 'admin', 'super_admin']::text[])
    );

create policy knowledge_chunks_insert_tenant on public.knowledge_chunks
    for insert to authenticated
    with check (
        tenant_id = public.get_my_tenant_id()
        and public.has_tenant_role(array['admin', 'super_admin']::text[])
    );

create policy knowledge_chunks_update_tenant on public.knowledge_chunks
    for update to authenticated
    using (
        tenant_id = public.get_my_tenant_id()
        and public.has_tenant_role(array['admin', 'super_admin']::text[])
    )
    with check (
        tenant_id = public.get_my_tenant_id()
        and public.has_tenant_role(array['admin', 'super_admin']::text[])
    );

create policy knowledge_chunks_delete_tenant on public.knowledge_chunks
    for delete to authenticated
    using (
        tenant_id = public.get_my_tenant_id()
        and public.has_tenant_role(array['admin', 'super_admin']::text[])
    );

grant select, insert, update, delete on public.knowledge_chunks to authenticated;
grant all on table public.knowledge_chunks to service_role;
grant execute on function public.knowledge_chunks_set_updated_at() to service_role;

do $$
declare
    companies_rls_enabled boolean;
    kb_docs_rls_enabled boolean;
begin
    select c.relrowsecurity
      into companies_rls_enabled
      from pg_class c
      join pg_namespace n on n.oid = c.relnamespace
     where n.nspname = 'public' and c.relname = 'companies';

    select c.relrowsecurity
      into kb_docs_rls_enabled
      from pg_class c
      join pg_namespace n on n.oid = c.relnamespace
     where n.nspname = 'public' and c.relname = 'knowledge_base_documents';

    if companies_rls_enabled is distinct from true then
        raise exception 'RLS must remain enabled on public.companies';
    end if;
    if kb_docs_rls_enabled is distinct from true then
        raise exception 'RLS must remain enabled on public.knowledge_base_documents';
    end if;
end;
$$;
