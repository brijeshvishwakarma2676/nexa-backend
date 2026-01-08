-- Migration: Add auth_provider and birthday columns to users table
-- Run this on the production MySQL database

ALTER TABLE users 
ADD COLUMN auth_provider VARCHAR(20) DEFAULT 'local' NOT NULL AFTER google_id;

ALTER TABLE users 
ADD COLUMN birthday DATE NULL AFTER cover_url;

-- Verify the changes
DESCRIBE users;
