-- Invalid legacy data for upgrade testing (should fail the hardening migration)
-- These rows violate the constraints that the hardening migration adds.

INSERT INTO public.profiles (user_id) VALUES ('legacy_user_invalid');
INSERT INTO public.chat_logs (user_id, role, content) VALUES ('legacy_user_invalid', 'user', '');
