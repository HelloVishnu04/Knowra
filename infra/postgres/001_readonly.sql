DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'knowra_reader') THEN
        CREATE ROLE knowra_reader LOGIN PASSWORD 'reader-password'
            NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
    END IF;
END
$$;

GRANT CONNECT ON DATABASE omnirag TO knowra_reader;
GRANT USAGE ON SCHEMA public TO knowra_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO knowra_reader;
ALTER DEFAULT PRIVILEGES FOR ROLE "user" IN SCHEMA public
    GRANT SELECT ON TABLES TO knowra_reader;
