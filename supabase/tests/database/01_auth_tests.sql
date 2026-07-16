BEGIN;

CREATE EXTENSION IF NOT EXISTS pgtap;
SELECT plan(31);

-- 1. RLS Enabled
SELECT tables_are_enabled(
    ARRAY['profiles', 'chat_logs', 'memories', 'archival_extractions'],
    'RLS is enabled for all 4 tables'
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
    (SELECT string_agg(a.attname, ',' ORDER BY i.indkey::text)
     FROM pg_index i
     JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY((string_to_array(i.indkey::text, ' ')::int2[]))
     WHERE i.indexrelid = 'chat_logs_user_id_created_at_id_idx'::regclass),
    'user_id,created_at,id',
    'Index columns are correct'
);

-- 8. FK testing (chat_logs does NOT have cascade)
SELECT has_fk('public', 'chat_logs', 'chat_logs_user_id_fkey');

-- 9. Archival Extraction FKs and unique
SELECT has_fk('public', 'archival_extractions', 'archival_extractions_user_id_fkey');
SELECT has_fk('public', 'archival_extractions', 'archival_extractions_user_id_source_chat_log_id_fkey');
SELECT has_index('public', 'archival_extractions', 'archival_extractions_idempotency_key_idx');

SELECT * FROM finish();
ROLLBACK;
