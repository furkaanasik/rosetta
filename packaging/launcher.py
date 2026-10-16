"""PyInstaller entry point for the Rosetta engine sidecar."""

from rosetta_engine.cli import app

if __name__ == "__main__":
    app(prog_name="rosetta-engine")
