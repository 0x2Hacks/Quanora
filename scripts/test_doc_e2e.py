#!/usr/bin/env python3
"""Quick test: generate a doc HTML and convert to PDF."""

import sys
import os

os.chdir('/home/wesley/chainpeer/workspace')
sys.path.insert(0, '/home/wesley/chainpeer')

from agent.infrastructure.tools.impl.tools.presentation import (
    generate_doc_html,
    convert_html_to_pdf,
)

# Step 1: Generate doc HTML
result = generate_doc_html(
    file_path="test_doc.html",
    title="Test Timeline Document",
    subtitle="A test of the doc template",
    section_label="03 / Attack Analysis",
    timeline_items=[
        {
            "day_label": "Day 1",
            "number": "01",
            "icon": "🔍",
            "item_title": "Initial Reconnaissance",
            "description": "The attacker performed initial reconnaissance of the target network using passive intelligence gathering techniques.",
            "highlight": "Critical",
        },
        {
            "day_label": "Day 3",
            "number": "02",
            "icon": "🎯",
            "item_title": "Spear Phishing Campaign",
            "description": "A targeted spear phishing email was sent to key personnel with a malicious attachment.",
        },
        {
            "day_label": "Day 5",
            "number": "03",
            "icon": "🔓",
            "item_title": "Initial Access Achieved",
            "description": "The attacker gained initial access through a compromised employee workstation.",
            "highlight": "High",
        },
    ],
)

print(f"generate_doc_html result: {result}")

# Step 2: Convert to PDF
pdf_result = convert_html_to_pdf(
    file_path="test_doc.html",
    output_path="test_doc.pdf",
)

print(f"convert_html_to_pdf result: {pdf_result}")
