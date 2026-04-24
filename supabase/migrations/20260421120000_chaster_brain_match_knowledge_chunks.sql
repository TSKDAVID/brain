-- Vector similarity search for Chaster Brain FAQ RAG (service role / RPC).

create or replace function public.match_knowledge_chunks(
    query_embedding vector(1536),
    p_tenant_id uuid,
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
        (1 - (kc.embedding <=> query_embedding))::double precision as similarity
    from public.knowledge_chunks kc
    where kc.tenant_id = p_tenant_id
    order by kc.embedding <=> query_embedding
    limit greatest(1, least(match_count, 30));
$$;

grant execute on function public.match_knowledge_chunks(vector(1536), uuid, int) to service_role;
