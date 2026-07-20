-- 20240101000002_secure_server_owned_tables.sql
-- Hardening migration: RLS, grants, constraints, and defaults.

-- =================================================================
-- 0. PREFLIGHT: Validate legacy data before making any changes.
-- =================================================================
DO $$
DECLARE
    v_invalid_role   int;
    v_empty_content  int;
    v_long_content   int;
BEGIN
    -- Check chat_logs for:
    -- * role different from 'user' or 'assistant'
    -- * empty content
    -- * content above 10,000 characters

    SELECT count(*) INTO v_invalid_role
    FROM public.chat_logs
    WHERE role NOT IN ('user', 'assistant');

    SELECT count(*) INTO v_empty_content
    FROM public.chat_logs
    WHERE char_length(content) = 0 OR content IS NULL;

    SELECT count(*) INTO v_long_content
    FROM public.chat_logs
    WHERE char_length(content) > 10000;

    IF v_invalid_role > 0 OR v_empty_content > 0 OR v_long_content > 0 THEN
        RAISE EXCEPTION 'Cannot apply hardening: legacy data contains incompatible rows'
            USING ERRCODE = '23514';
    END IF;
END $$;

-- =================================================================
-- 1. Enable RLS + FORCE RLS on all sensitive tables
-- =================================================================
ALTER TABLE public.profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.chat_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.memories ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.archival_extractions ENABLE ROW LEVEL SECURITY;

ALTER TABLE public.profiles FORCE ROW LEVEL SECURITY;
ALTER TABLE public.chat_logs FORCE ROW LEVEL SECURITY;
ALTER TABLE public.memories FORCE ROW LEVEL SECURITY;
ALTER TABLE public.archival_extractions FORCE ROW LEVEL SECURITY;

-- =================================================================
-- 2. Remove permissive policies
-- =================================================================
DROP POLICY IF EXISTS "Users can select their own archival extractions" ON public.archival_extractions;

-- =================================================================
-- 3. Revoke all privileges from anon, authenticated, and PUBLIC
-- =================================================================
REVOKE ALL PRIVILEGES ON TABLE public.profiles FROM anon, authenticated;
REVOKE ALL PRIVILEGES ON TABLE public.chat_logs FROM anon, authenticated;
REVOKE ALL PRIVILEGES ON TABLE public.memories FROM anon, authenticated;
REVOKE ALL PRIVILEGES ON TABLE public.archival_extractions FROM anon, authenticated;

REVOKE ALL PRIVILEGES ON TABLE public.profiles FROM PUBLIC;
REVOKE ALL PRIVILEGES ON TABLE public.chat_logs FROM PUBLIC;
REVOKE ALL PRIVILEGES ON TABLE public.memories FROM PUBLIC;
REVOKE ALL PRIVILEGES ON TABLE public.archival_extractions FROM PUBLIC;

-- =================================================================
-- 4. Revoke previous service_role privileges, then grant exact minimal set
-- =================================================================
REVOKE ALL PRIVILEGES ON TABLE public.profiles FROM service_role;
REVOKE ALL PRIVILEGES ON TABLE public.chat_logs FROM service_role;
REVOKE ALL PRIVILEGES ON TABLE public.memories FROM service_role;
REVOKE ALL PRIVILEGES ON TABLE public.archival_extractions FROM service_role;

GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.profiles TO service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.chat_logs TO service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.memories TO service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.archival_extractions TO service_role;

-- =================================================================
-- 5. Sequence privileges (minimal)
-- =================================================================
-- Revoke everything from service_role on the sequence, then grant only USAGE
REVOKE ALL PRIVILEGES ON SEQUENCE public.chat_logs_id_seq FROM service_role;
GRANT USAGE ON SEQUENCE public.chat_logs_id_seq TO service_role;

REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public FROM PUBLIC, anon, authenticated;

-- Also revoke service_role from ALL sequences and grant only chat_logs_id_seq
REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public FROM service_role;
GRANT USAGE ON SEQUENCE public.chat_logs_id_seq TO service_role;

-- =================================================================
-- 6. Secure match_memories function
-- =================================================================
REVOKE EXECUTE ON FUNCTION public.match_memories(vector, float, int, text) FROM PUBLIC, anon, authenticated;
REVOKE EXECUTE ON FUNCTION public.match_memories(vector, float, int, text) FROM service_role;
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

-- =================================================================
-- 7. Add constraints to chat_logs
-- =================================================================
DO $$
BEGIN
  ALTER TABLE public.chat_logs
    ADD CONSTRAINT chat_logs_role_check CHECK (role IN ('user', 'assistant')),
    ADD CONSTRAINT chat_logs_content_check CHECK (char_length(content) > 0 AND char_length(content) <= 10000);
END $$;

-- =================================================================
-- 8. Add index to chat_logs
-- =================================================================
CREATE INDEX IF NOT EXISTS chat_logs_user_id_created_at_id_idx ON public.chat_logs (user_id, created_at DESC, id DESC);

-- =================================================================
-- 9. Hardening future objects
-- =================================================================
ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON TABLES FROM PUBLIC, anon, authenticated;
ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON SEQUENCES FROM PUBLIC, anon, authenticated;
ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON FUNCTIONS FROM PUBLIC, anon, authenticated;
