# Installation Guide

## Quick Start

1. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

   Or using pip3:
   ```bash
   pip3 install -r requirements.txt
   ```

2. **Verify installation**:
   ```bash
   python3 -c "import requests, bs4, backoff, pandas; print('All dependencies installed!')"
   ```

## Alternative Installation Methods

### Using pip with user flag (if you don't have admin rights)
```bash
pip install --user -r requirements.txt
```

### Using virtual environment (recommended)
```bash
# Create virtual environment
python3 -m venv venv

# Activate it
# On macOS/Linux:
source venv/bin/activate
# On Windows:
# venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### Using setup.py
```bash
pip install -e .
```

## Troubleshooting

### ModuleNotFoundError

If you see `ModuleNotFoundError: No module named 'X'`, install the missing module:
```bash
pip install X
```

### Permission denied errors

Use the `--user` flag:
```bash
pip install --user -r requirements.txt
```

### Python version issues

This project requires Python 3.8+. Check your version:
```bash
python3 --version
```

If you need to install Python 3.8+, visit https://www.python.org/downloads/

## Required Dependencies

- `requests` - HTTP library
- `beautifulsoup4` - HTML parsing
- `lxml` - XML/HTML parser backend
- `python-dateutil` - Date parsing utilities
- `backoff` - Retry logic with exponential backoff
- `pandas` - Data manipulation
- `openpyxl` - Excel file support for pandas

All dependencies are listed in `requirements.txt`.
