#!/usr/bin/env python3
"""Quick test: generate a PPT HTML and convert to PDF."""

import sys
import os

# Change to workspace directory
os.chdir('/home/wesley/chainpeer/workspace')

sys.path.insert(0, '/home/wesley/chainpeer')

from agent.infrastructure.tools.impl.tools.presentation import (
    generate_ppt_html,
    convert_html_to_pdf,
)

# Step 1: Generate PPT HTML
result = generate_ppt_html(
    file_path="test_ppt.html",
    title="Test Presentation",
    subtitle="A test of the new template",
    author="Test Author",
    date="2026-05-30",
    target="Test Audience",
    version="1.0",
    slides=[
        {
            "section_label": "01 / Overview",
            "left_title": "Market Overview",
            "left_subtitle": "Q1 2026 Performance",
            "right_title": "Key Findings",
            "right_subtitle": "Analysis of market trends",
            "points": [
                "S&P 500 returned 8.2% in Q1 2026",
                "Technology sector led with 12.4% gains",
                "Bond yields declined 30bps across the curve",
                "International markets underperformed US equities",
            ],
        },
        {
            "section_label": "02 / Analysis",
            "left_title": "Deep Dive",
            "left_subtitle": "Sector rotation patterns",
            "right_title": "Sector Analysis",
            "right_subtitle": "Cyclical vs Defensive allocation",
            "points": [
                "Cyclical sectors outperformed by 400bps",
                "Energy and Financials showed strongest momentum",
                "Defensive sectors lagged as risk appetite increased",
            ],
        },
    ],
    end_text="THANK YOU",
    end_subtitle="Questions & Discussion",
)

print(f"generate_ppt_html result: {result}")

# Step 2: Convert to PDF
pdf_result = convert_html_to_pdf(
    file_path="test_ppt.html",
    output_path="test_ppt.pdf",
)

print(f"convert_html_to_pdf result: {pdf_result}")
