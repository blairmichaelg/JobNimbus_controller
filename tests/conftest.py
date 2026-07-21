import pytest

from app.core.database import run_migrations as init_db

@pytest.fixture(autouse=True, scope="session")
def setup_test_db(tmp_path_factory):
    """
    Ensure the database is initialized with all tables (including pricing)
    for the test suite. We just point the DB_PATH to a temp file.
    """
    test_db = tmp_path_factory.mktemp("db") / "test_truck_server.db"
    
    import app.core.database
    app.core.database.get_db_path = lambda: test_db
    
    # Initialize schema
    init_db()
    
    yield
