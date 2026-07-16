BEGIN;

-- Include pgTAP
CREATE EXTENSION IF NOT EXISTS pgtap;

SELECT plan(22);

-- 1. RLS Enabled
SELECT tables_are_enabled(
    ARRAY['profiles', 'chat_logs', 'memories', 'archival_extractions'],
    'RLS is enabled for all 4 tables'
);

-- 2. Grants for anon and authenticated (they should have none on these tables)
SELECT table_privs_are(
    'public', 'profiles', 'anon', ARRAY[]::text[],
    'anon has no privileges on profiles'
);
SELECT table_privs_are(
    'public', 'chat_logs', 'anon', ARRAY[]::text[],
    'anon has no privileges on chat_logs'
);
SELECT table_privs_are(
    'public', 'profiles', 'authenticated', ARRAY[]::text[],
    'authenticated has no privileges on profiles'
);
SELECT table_privs_are(
    'public', 'chat_logs', 'authenticated', ARRAY[]::text[],
    'authenticated has no privileges on chat_logs'
);

-- 3. Grants for service_role
SELECT table_privs_are(
    'public', 'profiles', 'service_role', ARRAY['SELECT', 'INSERT', 'UPDATE', 'DELETE', 'TRUNCATE', 'REFERENCES', 'TRIGGER'],
    'service_role has all privileges on profiles'
);
SELECT table_privs_are(
    'public', 'chat_logs', 'service_role', ARRAY['SELECT', 'INSERT', 'UPDATE', 'DELETE', 'TRUNCATE', 'REFERENCES', 'TRIGGER'],
    'service_role has all privileges on chat_logs'
);

-- 4. No client policies on archival_extractions
SELECT policies_are(
    'public', 'archival_extractions', ARRAY[]::text[],
    'No policies exist on archival_extractions'
);

-- 5. Function privileges
SELECT function_privs_are(
    'public', 'match_memories', ARRAY['vector', 'double precision', 'integer', 'text'], 'anon', ARRAY[]::text[],
    'anon cannot execute match_memories'
);
SELECT function_privs_are(
    'public', 'match_memories', ARRAY['vector', 'double precision', 'integer', 'text'], 'authenticated', ARRAY[]::text[],
    'authenticated cannot execute match_memories'
);
SELECT function_privs_are(
    'public', 'match_memories', ARRAY['vector', 'double precision', 'integer', 'text'], 'service_role', ARRAY['EXECUTE'],
    'service_role can execute match_memories'
);
SELECT function_privs_are(
    'public', 'match_memories', ARRAY['vector', 'double precision', 'integer', 'text'], 'PUBLIC', ARRAY[]::text[],
    'PUBLIC cannot execute match_memories'
);

-- 6. Constraints on chat_logs
SELECT has_check('public', 'chat_logs', 'chat_logs_role_check', 'chat_logs role constraint exists');
SELECT has_check('public', 'chat_logs', 'chat_logs_content_check', 'chat_logs content constraint exists');

-- Add dummy user for testing constraints
INSERT INTO public.profiles (user_id) VALUES ('test_user_constraint');

-- 7. Invalid role is rejected
PREPARE invalid_role AS INSERT INTO public.chat_logs (user_id, role, content) VALUES ('test_user_constraint', 'admin', 'test');
SELECT throws_ok(
    'invalid_role',
    '23514',
    NULL,
    'Invalid role rejected'
);

-- 8. Content over 10000 chars is rejected
PREPARE long_content AS INSERT INTO public.chat_logs (user_id, role, content) VALUES ('test_user_constraint', 'user', repeat('a', 10001));
SELECT throws_ok(
    'long_content',
    '23514',
    NULL,
    'Content > 10000 chars rejected'
);

-- 9. Empty content is rejected
PREPARE empty_content AS INSERT INTO public.chat_logs (user_id, role, content) VALUES ('test_user_constraint', 'user', '');
SELECT throws_ok(
    'empty_content',
    '23514',
    NULL,
    'Empty content rejected'
);

-- 10. Valid content is accepted
PREPARE valid_insert AS INSERT INTO public.chat_logs (user_id, role, content) VALUES ('test_user_constraint', 'user', 'hello');
SELECT lives_ok('valid_insert', 'Valid chat_logs insert works');

-- 11. Index existence
SELECT has_index('public', 'chat_logs', 'chat_logs_user_id_created_at_id_idx', 'Index exists on chat_logs');
SELECT index_is_type('public', 'chat_logs', 'chat_logs_user_id_created_at_id_idx', 'btree', 'Index is btree');

-- 12. FK testing
SELECT has_fk('public', 'chat_logs', 'chat_logs_user_id_fkey', 'FK from chat_logs to profiles exists');

-- Testing cascade
INSERT INTO public.profiles (user_id) VALUES ('cascade_test');
INSERT INTO public.chat_logs (user_id, role, content) VALUES ('cascade_test', 'user', 'msg');
DELETE FROM public.profiles WHERE user_id = 'cascade_test';
SELECT is_empty(
    'SELECT * FROM public.chat_logs WHERE user_id = ''cascade_test''',
    'chat_logs cascaded on delete'
);


SELECT * FROM finish();
ROLLBACK;
