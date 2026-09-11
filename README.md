# LabelCheck

LabelCheck is an AI-assisted product label verification system designed to extract important information from packaged commodity labels and evaluate the extracted information against predefined regulatory requirements.

## Features

- Product label image upload
- OCR-based text extraction
- AI-assisted structured data extraction
- Extraction of important label information such as:
  - Product name
  - Category
  - MRP
  - Net quantity
  - Manufacturing date
  - Expiry / Best Before date
  - Batch number
  - Manufacturer
  - Packer
  - Importer
  - Consumer care details
  - Country of origin
  - Unit sale price
  - FSSAI licence number
- Structured JSON representation of extracted information
- Evidence-based extraction with confidence/status indicators
- Compliance checking against predefined regulatory rules
- PostgreSQL database support for storing compliance rules
- Support for multiple product-label images

## Technology Stack

### Backend
- Python
- Flask

### OCR
- OCR-based text extraction

### AI
- Google Gemini API

### Database
- PostgreSQL
- Neon PostgreSQL

### Other
- REST APIs
- JSON
- Regular expressions for text processing and validation
- Environment variables for configuration

## Project Structure

```text
LabelCheck/
│
├── app.py
├── ocr_service.py
├── gemini_extractor.py
├── compliance_engine.py
├── requirements.txt
├── .env
│
├── templates/
│   └── index.html
│
└── README.md