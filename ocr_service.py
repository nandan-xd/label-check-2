import os
import requests
from dotenv import load_dotenv
import time

load_dotenv()

OCR_API_KEY = os.getenv("OCR_API_KEY")


def extract_text(image_file):
    if not OCR_API_KEY:
        raise ValueError("OCR_API_KEY is not configured.")

    image_file.seek(0)

    files = {
        "file": (
            image_file.filename,
            image_file.read(),
            image_file.mimetype or "image/jpeg"
        )
    }

    data = {
        "apikey": OCR_API_KEY,
        "language": "eng",
        "isOverlayRequired": "false",
        "OCREngine": "2"
    }


    max_retries = 3

    for attempt in range(max_retries):
        try:
            response = requests.post(
                "https://api.ocr.space/parse/image",
                files=files,
                data=data,
                timeout=30
            )

            # Temporary OCR.space problem
            if response.status_code == 503:
                if attempt < max_retries - 1:
                    time.sleep(2 * (attempt + 1))
                    continue

                raise ValueError(
                    "OCR service is temporarily unavailable. "
                    "Please try again in a few seconds."
                )

            response.raise_for_status()
            data = response.json()

            if data.get("IsErroredOnProcessing"):
                raise ValueError(
                    str(
                        data.get(
                            "ErrorMessage",
                            "OCR processing failed."
                        )
                    )
                )

            parsed_results = data.get("ParsedResults", [])

            if not parsed_results:
                return ""

            text_parts = []

            for result in parsed_results:
                text = result.get("ParsedText", "")
                if text:
                    text_parts.append(text)

            return "\n".join(text_parts)

        except requests.RequestException as e:
            if attempt < max_retries - 1:
                time.sleep(2 * (attempt + 1))
                continue

            raise ValueError(
                f"OCR service unavailable: {e}"
            ) from e

    return ""