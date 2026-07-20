BEGIN;

CREATE EXTENSION IF NOT EXISTS pgtap;
SELECT plan(59);

-- =================================================================
-- PHASE 1: Read-only assertions (query catalog only, no DML on protected tables)
-- =================================================================

-- 1. RLS Enabled
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

-- 2. Grants for anon and authenticated (they should have none on these tables)
SELECT table_privs_are('public', 'profiles', 'anon', ARRAY[]::text[]);
SELECT table_privs_are('public', 'chat_logs', 'anon', ARRAY[]::text[]);
SELECT table_privs_are('public', 'memories', 'anon', ARRAY[]::text[]);
SELECT table_privs_are('public', 'archival_extractions', 'anon', ARRAY[]::text[]);

SELECT table_privs_are('public', 'profiles', 'authenticated', ARRAY[]::text[]);
SELECT table_privs_are('public', 'chat_logs', 'authenticated', ARRAY[]::text[]);
SELECT table_privs_are('public', 'memories', 'authenticated', ARRAY[]::text[]);
SELECT table_privs_are('public', 'archival_extractions', 'authenticated', ARRAY[]::text[]);

SELECT table_privs_are('public', 'profiles', 'PUBLIC', ARRAY[]::text[]);
SELECT table_privs_are('public', 'chat_logs', 'PUBLIC', ARRAY[]::text[]);
SELECT table_privs_are('public', 'memories', 'PUBLIC', ARRAY[]::text[]);
SELECT table_privs_are('public', 'archival_extractions', 'PUBLIC', ARRAY[]::text[]);

-- 3. Grants for service_role (exactly SELECT, INSERT, UPDATE, DELETE)
SELECT table_privs_are('public', 'profiles', 'service_role', ARRAY['SELECT', 'INSERT', 'UPDATE', 'DELETE']);
SELECT table_privs_are('public', 'chat_logs', 'service_role', ARRAY['SELECT', 'INSERT', 'UPDATE', 'DELETE']);
SELECT table_privs_are('public', 'memories', 'service_role', ARRAY['SELECT', 'INSERT', 'UPDATE', 'DELETE']);
SELECT table_privs_are('public', 'archival_extractions', 'service_role', ARRAY['SELECT', 'INSERT', 'UPDATE', 'DELETE']);

-- 4. No client policies on any table
SELECT policies_are('public', 'profiles', ARRAY[]::text[]);
SELECT policies_are('public', 'chat_logs', ARRAY[]::text[]);
SELECT policies_are('public', 'memories', ARRAY[]::text[]);
SELECT policies_are('public', 'archival_extractions', ARRAY[]::text[]);

-- 5. Function privileges
SELECT function_privs_are('public', 'match_memories', ARRAY['vector', 'double precision', 'integer', 'text'], 'anon', ARRAY[]::text[]);
SELECT function_privs_are('public', 'match_memories', ARRAY['vector', 'double precision', 'integer', 'text'], 'authenticated', ARRAY[]::text[]);
SELECT function_privs_are('public', 'match_memories', ARRAY['vector', 'double precision', 'integer', 'text'], 'service_role', ARRAY['EXECUTE']);
SELECT function_privs_are('public', 'match_memories', ARRAY['vector', 'double precision', 'integer', 'text'], 'PUBLIC', ARRAY[]::text[]);

-- 6. Constraints on chat_logs (metadata check, no DML)
SELECT ok(
    (SELECT EXISTS(SELECT 1 FROM pg_constraint WHERE conname = 'chat_logs_role_check' AND conrelid = 'chat_logs'::regclass)),
    'chat_logs has chat_logs_role_check constraint'
);
SELECT ok(
    (SELECT EXISTS(SELECT 1 FROM pg_constraint WHERE conname = 'chat_logs_content_check' AND conrelid = 'chat_logs'::regclass)),
    'chat_logs has chat_logs_content_check constraint'
);

-- 7. Index existence
SELECT has_index('public', 'chat_logs', 'chat_logs_user_id_created_at_id_idx');
SELECT index_is_type('public', 'chat_logs', 'chat_logs_user_id_created_at_id_idx', 'btree');
SELECT is(
    (SELECT pg_get_indexdef('chat_logs_user_id_created_at_id_idx'::regclass)),
    'CREATE INDEX chat_logs_user_id_created_at_id_idx ON public.chat_logs USING btree (user_id, created_at DESC, id DESC)',
    'Index columns and DESC order are correct'
);

-- 8. FK testing (chat_logs does NOT have cascade)
SELECT ok(
    (SELECT EXISTS(SELECT 1 FROM pg_constraint WHERE conname = 'chat_logs_user_id_fkey' AND conrelid = 'chat_logs'::regclass)),
    'chat_logs has chat_logs_user_id_fkey'
);

-- 9. Archival Extraction FKs and unique
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

-- 10. Default privileges (creates new objects, no DML on protected tables)
CREATE TABLE public.test_new_table (id int);
CREATE SEQUENCE public.test_new_seq;
CREATE FUNCTION public.test_new_func() RETURNS void LANGUAGE sql AS $$ SELECT 1; $$;

SELECT table_privs_are('public', 'test_new_table', 'PUBLIC', ARRAY[]::text[], 'No default privileges for new tables to PUBLIC');
SELECT table_privs_are('public', 'test_new_table', 'anon', ARRAY[]::text[], 'No default privileges for new tables to anon');
SELECT table_privs_are('public', 'test_new_table', 'authenticated', ARRAY[]::text[], 'No default privileges for new tables to authenticated');

SELECT sequence_privs_are('public', 'test_new_seq', 'PUBLIC', ARRAY[]::text[], 'No default privileges for new seqs to PUBLIC');
SELECT sequence_privs_are('public', 'test_new_seq', 'anon', ARRAY[]::text[], 'No default privileges for new seqs to anon');
SELECT sequence_privs_are('public', 'test_new_seq', 'authenticated', ARRAY[]::text[], 'No default privileges for new seqs to authenticated');

SELECT function_privs_are('public', 'test_new_func', ARRAY[]::text[], 'PUBLIC', ARRAY[]::text[], 'No default privileges for new funcs to PUBLIC');
SELECT function_privs_are('public', 'test_new_func', ARRAY[]::text[], 'anon', ARRAY[]::text[], 'No default privileges for new funcs to anon');
SELECT function_privs_are('public', 'test_new_func', ARRAY[]::text[], 'authenticated', ARRAY[]::text[], 'No default privileges for new funcs to authenticated');

-- 11. Sequence privileges on chat_logs_id_seq
SELECT sequence_privs_are('public', 'chat_logs_id_seq', 'service_role', ARRAY['USAGE'], 'service_role has USAGE on chat_logs_id_seq');
SELECT sequence_privs_are('public', 'chat_logs_id_seq', 'PUBLIC', ARRAY[]::text[], 'No PUBLIC privilege on chat_logs_id_seq');
SELECT sequence_privs_are('public', 'chat_logs_id_seq', 'anon', ARRAY[]::text[], 'No anon privilege on chat_logs_id_seq');
SELECT sequence_privs_are('public', 'chat_logs_id_seq', 'authenticated', ARRAY[]::text[], 'No authenticated privilege on chat_logs_id_seq');

-- =================================================================
-- PHASE 2: Temporarily disable RLS for write tests (constraint validation)
-- FORCE RLS + no policies blocks all DML on protected tables even for the test user.
-- We temporarily disable RLS on profiles and chat_logs so that:
--   1. The fixture profile can be inserted
--   2. The prepared INSERTs reach the CHECK constraints rather than being
--      blocked by RLS default-deny
-- Since this runs inside a ROLLBACK transaction, the RLS state is restored
-- automatically when the test finishes.
-- =================================================================

ALTER TABLE public.profiles DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.chat_logs DISABLE ROW LEVEL SECURITY;

INSERT INTO public.profiles (user_id) VALUES ('test_user_constraint');

SELECT throws_ok(
    $$INSERT INTO public.chat_logs (user_id, role, content) VALUES ('test_user_constraint', 'admin', 'test')$$,
    '23514',
    'chat_logs_role_check rejects invalid role'
);

SELECT throws_ok(
    $$INSERT INTO public.chat_logs (user_id, role, content) VALUES ('test_user_constraint', 'user', repeat('a', 10001))$$,
    '23514',
    'chat_logs_content_check rejects long content'
);

SELECT throws_ok(
    $$INSERT INTO public.chat_logs (user_id, role, content) VALUES ('test_user_constraint', 'user', '')$$,
    '23514',
    'chat_logs_content_check rejects empty content'
);

-- RLS is automatically re-enabled when the transaction rolls back below.

SELECT * FROM finish();
ROLLBACK;
