"""
Test runner for Tradingfin3.0
=============================
"""

import pytest
import sys
import os

if __name__ == "__main__":
    # Run all tests
    sys.exit(pytest.main([__file__, "-v", "--tb=short"]))
