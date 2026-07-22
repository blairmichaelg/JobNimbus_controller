import importlib

from app.workers.settings import WorkerSettings

def test_worker_settings_functions_resolvable():
    for func_path in WorkerSettings.functions:
        module_path, func_name = func_path.rsplit(".", 1)
        module = importlib.import_module(module_path)
        func = getattr(module, func_name)
        assert callable(func), f"{func_path} is not callable"
