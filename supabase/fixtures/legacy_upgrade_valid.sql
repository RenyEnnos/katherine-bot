-- Valid legacy data for upgrade testing
-- These rows should pass the hardening migration constraints.

INSERT INTO public.profiles (user_id) VALUES ('legacy_user_valid');
INSERT INTO public.chat_logs (user_id, role, content) VALUES ('legacy_user_valid', 'user', 'legacy message');
