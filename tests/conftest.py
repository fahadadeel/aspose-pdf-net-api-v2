"""Shared test configuration."""

import sys
from pathlib import Path

# Ensure project root is on sys.path so tests can import modules directly
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
