#!/usr/bin/env python
"""
Database Initialization Script for ReelSearch.
Creates tables, indexes, triggers, and helper functions in PostgreSQL.
"""
import sys
import os

# Add backend directory to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend")))

from app.core.database import init_db_pool, run_migrations, close_db_pool

if __name__ == "__main__":
    print("Connecting to PostgreSQL and running migrations...")
    try:
        init_db_pool()
        run_migrations()
        print("Database schema successfully created and verified!")
    except Exception as e:
        print(f"Error initializing database: {e}")
        sys.exit(1)
    finally:
        close_db_pool()
