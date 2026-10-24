-- Refuse ambiguous legacy case variants instead of silently merging accounts.
CREATE UNIQUE INDEX users_email_lower_uidx ON users (lower(email));
