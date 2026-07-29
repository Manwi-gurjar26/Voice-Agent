-- Creates the application and test databases.
-- Run once as a superuser:
--   psql -U postgres -h localhost -f scripts/bootstrap_db.sql
--
-- CREATE DATABASE cannot run inside a transaction block, so this file uses
-- \gexec to skip creation when the database already exists.

SELECT 'CREATE DATABASE voiceagent'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'voiceagent')\gexec

SELECT 'CREATE DATABASE voiceagent_test'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'voiceagent_test')\gexec
