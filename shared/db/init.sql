-- AscenAI shared database initialization
-- Creates the database extensions and initial schema

-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Create separate schemas for logical isolation (optional; all services share same DB)
-- Tables are created by SQLAlchemy at startup (init_db) or via Alembic migrations
