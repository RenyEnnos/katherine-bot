BEGIN;

CREATE EXTENSION IF NOT EXISTS pgtap;
SELECT plan(51);

-- =================================================================
-- 1. RLS Enabled
-- =================================================================
SELECT ok(
  (SELECT relrowsecurity FROM pg_class WHERE oid = 'public.profiles'::regclass),
  'RLS is enabled on profiles'
);
SELECT ok(
  (SELECT relrowsecurity FROM pg_class WHERE oid = 'public.chat_logs'::regclass),
  'RLS is enabled on chat_logs'
);
SELECT ok(
  (SELECT relrowsecurity FROM pg_class WHERE oid = 'public.memories'::regclass),
  'RLS is enabled on memories'
);
SELECT ok(
  (SELECT relrowsecurity FROM pg_class WHERE oid = 'public.archival_extractions'::regclass),
  'RLS is enabled on archival_extractions'
);

-- 1b. FORCE RLS Enabled
SELECT ok(
  (SELECT relforcerowsecurity FROM pg_class WHERE oid = 'public.profiles'::regclass),
  'FORCE RLS is enabled on profiles'
);
SELECT ok(
  (SELECT relforcerowsecurity FROM pg_class WHERE oid = 'public.chat_logs'::regclass),
  'FORCE RLS is enabled on chat_logs'
);
SELECT ok(
  (SELECT relforcerowsecurity FROM pg_class WHERE oid = 'public.memories'::regclass),
  'FORCE RLS is enabled on memories'
);
SELECT ok(
  (SELECT relforcerowsecurity FROM pg_class WHERE oid = 'public.archival_extractions'::regclass),
  'FORCE RLS is enabled on archival_extractions'
);

-- =================================================================
-- 2. Table privileges for anon and authenticated (should have none)
-- =================================================================
SELECT table_privs_are('public', 'profiles', 'anon', ARRAY[]::text[]);
SELECT table_privs_are('public', 'chat_logs', 'anon', ARRAY[]::text[]);
SELECT table_privs_are('public', 'memories', 'anon', ARRAY[]::text[]);
SELECT table_privs_are('public', 'archival_extractions', 'anon', ARRAY[]::text[]);

SELECT table_privs_are('public', 'profiles', 'authenticated', ARRAY[]::text[]);
SELECT table_privs_are('public', 'chat_logs', 'authenticated', ARRAY[]::text[]);
SELECT table_privs_are('public', 'memories', 'authenticated', ARRAY[]::text[]);
SELECT table_privs_are('public', 'archival_extractions', 'authenticated', ARRAY[]::text[]);

-- PUBLIC is a pseudo-role not in pg_roles, so table_privs_are cannot look it up.
-- Use direct information_schema query instead.
SELECT is(
    (SELECT count(*) FROM information_schema.role_table_grants
     WHERE grantee = 'PUBLIC' AND table_name = 'profiles'),
    0,
    'PUBLIC has no privileges on profiles'
);
SELECT is(
    (SELECT count(*) FROM information_schema.role_table_grants
     WHERE grantee = 'PUBLIC' AND table_name = 'chat_logs'),
    0,
    'PUBLIC has no privileges on chat_logs'
);
SELECT is(
    (SELECT count(*) FROM information_schema.role_table_grants
     WHERE grantee = 'PUBLIC' AND table_name = 'memories'),
    0,
    'PUBLIC has no privileges on memories'
);
SELECT is(
    (SELECT count(*) FROM information_schema.role_table_grants
     WHERE grantee = 'PUBLIC' AND table_name = 'archival_extractions'),
    0,
    'PUBLIC has no privileges on archival_extractions'
);

-- =================================================================
-- 3. Service_role table privileges (exactly SELECT, INSERT, UPDATE, DELETE)
-- =================================================================
SELECT table_privs_are('public', 'profiles', 'service_role', ARRAY['SELECT', 'INSERT', 'UPDATE', 'DELETE']);
SELECT table_privs_are('public', 'chat_logs', 'service_role', ARRAY['SELECT', 'INSERT', 'UPDATE', 'DELETE']);
SELECT table_privs_are('public', 'memories', 'service_role', ARRAY['SELECT', 'INSERT', 'UPDATE', 'DELETE']);
SELECT table_privs_are('public', 'archival_extractions', 'service_role', ARRAY['SELECT', 'INSERT', 'UPDATE', 'DELETE']);

-- =================================================================
-- 4. No policies on any table
-- =================================================================
SELECT policies_are('public', 'profiles', ARRAY[]::text[]);
SELECT policies_are('public', 'chat_logs', ARRAY[]::text[]);
SELECT policies_are('public', 'memories', ARRAY[]::text[]);
SELECT policies_are('public', 'archival_extractions', ARRAY[]::text[]);

-- =================================================================
-- 5. Function privileges for match_memories
-- =================================================================
SELECT function_privs_are('public', 'match_memories', ARRAY['vector', 'double precision', 'integer', 'text'], 'anon', ARRAY[]::text[]);
SELECT function_privs_are('public', 'match_memories', ARRAY['vector', 'double precision', 'integer', 'text'], 'authenticated', ARRAY[]::text[]);
SELECT function_privs_are('public', 'match_memories', ARRAY['vector', 'double precision', 'integer', 'text'], 'service_role', ARRAY['EXECUTE']);

-- PUBLIC function privileges: use has_function_privilege directly
SELECT ok(
    NOT has_function_privilege('PUBLIC', 'public.match_memories(vector, double precision, integer, text)', 'EXECUTE'),
    'PUBLIC has no EXECUTE on match_memories'
);

-- =================================================================
-- 6. CHECK constraints on chat_logs (metadata only, no DML)
-- =================================================================
SELECT ok(
    (SELECT EXISTS(SELECT 1 FROM pg_constraint WHERE conname = 'chat_logs_role_check' AND conrelid = 'chat_logs'::regclass)),
    'chat_logs has chat_logs_role_check constraint'
);
SELECT ok(
    (SELECT EXISTS(SELECT 1 FROM pg_constraint WHERE conname = 'chat_logs_content_check' AND conrelid = 'chat_logs'::regclass)),
    'chat_logs has chat_logs_content_check constraint'
);

-- Verify constraint definitions (proves they would reject invalid data without needing DML)
SELECT is(
    (SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = 'chat_logs_role_check'),
    'CHECK ((role = ANY (ARRAY[''user''::text, ''assistant''::text])))',
    'chat_logs_role_check definition is correct'
);
SELECT is(
    (SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = 'chat_logs_content_check'),
    'CHECK ((char_length(content) > 0) AND (char_length(content) <= 10000))',
    'chat_logs_content_check definition is correct'
);

-- =================================================================
-- 7. Index existence (chat_logs)
-- =================================================================
SELECT has_index('public', 'chat_logs', 'chat_logs_user_id_created_at_id_idx');
SELECT index_is_type('public', 'chat_logs', 'chat_logs_user_id_created_at_id_idx', 'btree');
SELECT is(
    (SELECT pg_get_indexdef('chat_logs_user_id_created_at_id_idx'::regclass)),
    'CREATE INDEX chat_logs_user_id_created_at_id_idx ON public.chat_logs USING btree (user_id, created_at DESC, id DESC)',
    'Index columns and DESC order are correct'
);

-- =================================================================
-- 8. FK on chat_logs (no cascade)
-- =================================================================
SELECT ok(
    (SELECT EXISTS(SELECT 1 FROM pg_constraint WHERE conname = 'chat_logs_user_id_fkey' AND conrelid = 'chat_logs'::regclass)),
    'chat_logs has chat_logs_user_id_fkey'
);

-- Verify it does NOT have cascade
SELECT is(
    (SELECT confdeltype FROM pg_constraint WHERE conname = 'chat_logs_user_id_fkey'),
    'a'::"char",
    'chat_logs_user_id_fkey does NOT have ON DELETE CASCADE'
);

-- =================================================================
-- 9. Archival Extraction FKs and unique
-- =================================================================
SELECT is(
    (SELECT confdeltype FROM pg_constraint WHERE conname = 'archival_extractions_user_id_fkey'),
    'c'::"char",
    'archival_extractions_user_id_fkey has ON DELETE CASCADE'
);
SELECT is(
    (SELECT confdeltype FROM pg_constraint WHERE conname = 'archival_extractions_user_id_source_chat_log_id_fkey'),
    'c'::"char",
    'archival_extractions_user_id_source_chat_log_id_fkey has ON DELETE CASCADE'
);

SELECT ok(
    (SELECT EXISTS(SELECT 1 FROM pg_constraint WHERE conname = 'archival_extractions_user_id_fkey' AND conrelid = 'archival_extractions'::regclass)),
    'archival_extractions has archival_extractions_user_id_fkey'
);
SELECT ok(
    (SELECT EXISTS(SELECT 1 FROM pg_constraint WHERE conname = 'archival_extractions_user_id_source_chat_log_id_fkey' AND conrelid = 'archival_extractions'::regclass)),
    'archival_extractions has archival_extractions_user_id_source_chat_log_id_fkey'
);
SELECT has_index('public', 'archival_extractions', 'archival_extractions_idempotency_key_idx');

-- =================================================================
-- 10. Default privileges for new objects
-- =================================================================
CREATE TABLE public.test_new_table (id int);
CREATE SEQUENCE public.test_new_seq;
CREATE FUNCTION public.test_new_func() RETURNS void LANGUAGE sql AS $$ SELECT 1; $$;

-- Default privileges for new tables: verify no PUBLIC/anon/authenticated grants exist
SELECT is(
    (SELECT count(*) FROM information_schema.role_table_grants
     WHERE table_name = 'test_new_table' AND grantee IN ('PUBLIC', 'anon', 'authenticated')),
    0,
    'No default table privileges to PUBLIC/anon/authenticated'
);

-- Default privileges for new sequences
SELECT is(
    (SELECT count(*) FROM information_schema.role_usage_grants
     WHERE object_name = 'test_new_seq' AND grantee IN ('PUBLIC', 'anon', 'authenticated')),
    0,
    'No default sequence privileges to PUBLIC/anon/authenticated'
);

-- Default privileges for new functions
SELECT is(
    (SELECT count(*) FROM information_schema.role_routine_grants
     WHERE specific_name = (SELECT specific_name FROM information_schema.routines
                            WHERE routine_name = 'test_new_func')
     AND grantee IN ('PUBLIC', 'anon', 'authenticated')),
    0,
    'No default function privileges to PUBLIC/anon/authenticated'
);

-- =================================================================
-- 11. Sequence privileges on chat_logs_id_seq
-- =================================================================
SELECT sequence_privs_are('public', 'chat_logs_id_seq', 'service_role', ARRAY['USAGE'], 'service_role has USAGE on chat_logs_id_seq');

-- PUBLIC/anon/authenticated: direct count queries (these roles may not exist in pg_roles)
SELECT is(
    (SELECT count(*) FROM information_schema.role_usage_grants
     WHERE object_name = 'chat_logs_id_seq' AND grantee IN ('PUBLIC', 'anon', 'authenticated')),
    0,
    'No PUBLIC/anon/authenticated privileges on chat_logs_id_seq'
);

SELECT * FROM finish();
ROLLBACK;
