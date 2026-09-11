# LabelCheck

LabelCheck is a Flask-based product-label scanning and compliance verification application.

## Overview

The application allows users to capture or upload product-label images and processes them through:

- OCR-based text extraction
- Gemini-powered structured product information extraction
- Legal Metrology rule checks using PostgreSQL
- Advanced FSSAI license-number format validation
- AI-based visual legibility screening
- PDF compliance report generation

The application supports multiple images of the same product so that information printed on different sides, seals, caps, stickers or other areas can be considered together.

## Technology Stack

- Python
- Flask
- OCR.space API
- Google Gemini API
- PostgreSQL
- Neon
- ReportLab
- Gunicorn
- HTML / CSS / JavaScript

## Database

The compliance rules are stored in a PostgreSQL table named:

`legal_rules`

The application reads the rules from the database using the `DATABASE_URL` environment variable.

The current rule database focuses on the Packaged Commodities scope of Legal Metrology.

## Environment Variables

Configure these variables locally or in the deployment platform:

```text
OCR_API_KEY=your_ocr_api_key
GEMINI_API_KEY=your_gemini_api_key
GEMINI_MODEL=gemini-3.6-flash
DATABASE_URL=your_neon_postgresql_connection_string