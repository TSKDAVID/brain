-- FAQ retrieval without external embedding APIs: pg_trgm similarity + optional null embeddings.
-- Groq (and similar) do not provide text-embedding endpoints; Chaster Brain uses Postgres for match quality.

create extension if not exists pg_trgm;

drop index if exists public.knowledge_chunks_embedding_hnsw_cosine_idx;

alter table public.knowledge_chunks alter column embedding drop not null;

create index if not exists knowledge_chunks_chunk_text_trgm_idx
    on public.knowledge_chunks using gin (chunk_text gin_trgm_ops);

create or replace function public.match_knowledge_chunks_trgm(
    p_tenant_id uuid,
    search_query text,
    match_count int default 5
)
returns table (
    id uuid,
    chunk_text text,
    similarity double precision
)
language sql
stable
security definer
set search_path = public
as $$
    select
        kc.id,
        kc.chunk_text,
        greatest(0.0, least(1.0, similarity(kc.chunk_text, search_query)))::double precision as similarity
    from public.knowledge_chunks kc
    where kc.tenant_id = p_tenant_id
      and length(btrim(coalesce(search_query, ''))) > 0
    order by kc.chunk_text <-> search_query
    limit greatest(1, least(coalesce(match_count, 5), 30));
$$;

grant execute on function public.match_knowledge_chunks_trgm(uuid, text, int) to service_role;
