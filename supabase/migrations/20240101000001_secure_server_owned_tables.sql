-- 20240101000001_secure_server_owned_tables.sql

-- 1. Enable RLS on all sensitive tables
ALTER TABLE public.profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.chat_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.memories ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.archival_extractions ENABLE ROW LEVEL SECURITY;

-- 2. Remove permissive policies
DROP POLICY IF EXISTS "Users can select their own archival extractions" ON public.archival_extractions;

-- 3. Revoke all privileges from anon and authenticated
REVOKE ALL PRIVILEGES ON TABLE public.profiles FROM anon, authenticated;
REVOKE ALL PRIVILEGES ON TABLE public.chat_logs FROM anon, authenticated;
REVOKE ALL PRIVILEGES ON TABLE public.memories FROM anon, authenticated;
REVOKE ALL PRIVILEGES ON TABLE public.archival_extractions FROM anon, authenticated;

-- Also revoke from PUBLIC to be safe
REVOKE ALL PRIVILEGES ON TABLE public.profiles FROM PUBLIC;
REVOKE ALL PRIVILEGES ON TABLE public.chat_logs FROM PUBLIC;
REVOKE ALL PRIVILEGES ON TABLE public.memories FROM PUBLIC;
REVOKE ALL PRIVILEGES ON TABLE public.archival_extractions FROM PUBLIC;

-- 4. Grant explicit minimal privileges to service_role
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.profiles TO service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.chat_logs TO service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.memories TO service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.archival_extractions TO service_role;

-- Grant usage on sequences to service_role
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO service_role;

-- Revoke usage on sequences from PUBLIC, anon, authenticated
REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public FROM PUBLIC, anon, authenticated;

-- 5. Secure match_memories function
REVOKE EXECUTE ON FUNCTION public.match_memories(vector, float, int, text) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.match_memories(vector, float, int, text) TO service_role;

-- Replace function to ensure explicit schema references and search_path
CREATE OR REPLACE FUNCTION public.match_memories(
  query_embedding vector(384),
  match_threshold float,
  match_count int,
  filter_user_id text
)
RETURNS TABLE (
  id uuid,
  content text,
  metadata jsonb,
  similarity float
)
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = public, extensions
AS $$
BEGIN
  RETURN QUERY
  SELECT
    memories.id,
    memories.content,
    memories.metadata,
    1 - (memories.embedding <=> query_embedding) AS similarity
  FROM public.memories
  WHERE 1 - (memories.embedding <=> query_embedding) > match_threshold
  AND memories.user_id = filter_user_id
  ORDER BY memories.embedding <=> query_embedding
  LIMIT match_count;
END;
$$;

-- 6. Add constraints to chat_logs
DO $$
BEGIN
  -- We assume existing data is either valid or we just fail explicitly. The requirements say:
  -- "detecte dados incompatíveis; falhe explicitamente; não apague dados; não trunque conteúdo; não corrija registros silenciosamente."
  -- Creating the constraint will automatically scan existing rows and fail if invalid.

  ALTER TABLE public.chat_logs
    ADD CONSTRAINT chat_logs_role_check CHECK (role IN ('user', 'assistant')),
    ADD CONSTRAINT chat_logs_content_check CHECK (char_length(content) > 0 AND char_length(content) <= 10000);
END $$;

-- 7. Add index to chat_logs
CREATE INDEX IF NOT EXISTS chat_logs_user_id_created_at_id_idx ON public.chat_logs (user_id, created_at DESC, id DESC);


-- 8. Hardening future objects
ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON TABLES FROM PUBLIC, anon, authenticated;
ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON SEQUENCES FROM PUBLIC, anon, authenticated;
ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON FUNCTIONS FROM PUBLIC, anon, authenticated;
