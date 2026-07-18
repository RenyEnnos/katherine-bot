BEGIN;

CREATE EXTENSION IF NOT EXISTS pgtap;
SELECT plan(55);

-- 1. RLS Enabled (pgTAP has no tables_are_enabled helper; check pg_class.relrowsecurity directly)
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

-- 3. Grants for service_role
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

-- 6. Constraints on chat_logs
SELECT has_check('public', 'chat_logs', 'chat_logs_role_check');
SELECT has_check('public', 'chat_logs', 'chat_logs_content_check');

INSERT INTO public.profiles (user_id) VALUES ('test_user_constraint');

PREPARE invalid_role AS INSERT INTO public.chat_logs (user_id, role, content) VALUES ('test_user_constraint', 'admin', 'test');
SELECT throws_ok('invalid_role', '23514');

PREPARE long_content AS INSERT INTO public.chat_logs (user_id, role, content) VALUES ('test_user_constraint', 'user', repeat('a', 10001));
SELECT throws_ok('long_content', '23514');

PREPARE empty_content AS INSERT INTO public.chat_logs (user_id, role, content) VALUES ('test_user_constraint', 'user', '');
SELECT throws_ok('empty_content', '23514');

-- 7. Index existence
SELECT has_index('public', 'chat_logs', 'chat_logs_user_id_created_at_id_idx');
SELECT index_is_type('public', 'chat_logs', 'chat_logs_user_id_created_at_id_idx', 'btree');
SELECT is(
    (SELECT pg_get_indexdef('chat_logs_user_id_created_at_id_idx'::regclass)),
    'CREATE INDEX chat_logs_user_id_created_at_id_idx ON public.chat_logs USING btree (user_id, created_at DESC, id DESC)',
    'Index columns and DESC order are correct'
);

-- 8. FK testing (chat_logs does NOT have cascade)
SELECT has_fk('public', 'chat_logs', 'chat_logs_user_id_fkey');


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

SELECT has_fk('public', 'archival_extractions', 'archival_extractions_user_id_fkey');
SELECT has_fk('public', 'archival_extractions', 'archival_extractions_user_id_source_chat_log_id_fkey');
SELECT has_index('public', 'archival_extractions', 'archival_extractions_idempotency_key_idx');

-- Test default privileges by creating new objects
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

-- Exact privilege on the identity sequence used by the backend (least privilege)
SELECT sequence_privs_are('public', 'chat_logs_id_seq', 'service_role', ARRAY['USAGE'], 'service_role has USAGE on chat_logs_id_seq');
SELECT sequence_privs_are('public', 'chat_logs_id_seq', 'PUBLIC', ARRAY[]::text[], 'No PUBLIC privilege on chat_logs_id_seq');
SELECT sequence_privs_are('public', 'chat_logs_id_seq', 'anon', ARRAY[]::text[], 'No anon privilege on chat_logs_id_seq');
SELECT sequence_privs_are('public', 'chat_logs_id_seq', 'authenticated', ARRAY[]::text[], 'No authenticated privilege on chat_logs_id_seq');






SELECT * FROM finish();
ROLLBACK;
