"""Regex patterns for NLP text parsing."""

import re

# Extract all numbers from text
NUMBER_PATTERN = re.compile(r'\b\d+\b')

# Order type patterns
ORDER_TYPE_PATTERNS = {
    "custom": re.compile(r'\b(кастом|custom)\b', re.IGNORECASE),
    "short": re.compile(r'\b(шорт|short)\b', re.IGNORECASE),
    "call": re.compile(r'\b(колл|call)\b', re.IGNORECASE),
    "ad request": re.compile(r'\b(ad\s*request|ад\s*реквест)\b', re.IGNORECASE),
}

# File keywords
FILE_PATTERN = re.compile(r'\b(файл|file|файлов|files)\b', re.IGNORECASE)

# Report keywords
REPORT_PATTERN = re.compile(r'\b(репорт|report|статистика|stats|стат)\b', re.IGNORECASE)
