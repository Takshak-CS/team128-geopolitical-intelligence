import os


BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(BACKEND_DIR)
OUTPUTS_DIR = os.path.join(ROOT_DIR, "outputs")
TEMPORAL_OUTPUTS_DIR = os.path.join(OUTPUTS_DIR, "temporal")


def root_file(*parts: str) -> str:
    return os.path.join(ROOT_DIR, *parts)


def output_file(*parts: str) -> str:
    path = os.path.join(OUTPUTS_DIR, *parts)
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    return path


def ensure_directories() -> None:
    os.makedirs(OUTPUTS_DIR, exist_ok=True)
    os.makedirs(TEMPORAL_OUTPUTS_DIR, exist_ok=True)
