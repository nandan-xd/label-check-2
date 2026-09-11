import os
import requests
import time
from dotenv import load_dotenv


load_dotenv()


OCR_API_KEY = os.getenv("OCR_API_KEY")


def extract_text(image_file):
    if not OCR_API_KEY:
        raise ValueError("OCR_API_KEY is not configured.")

    image_file.seek(0)

    file_content = image_file.read()

    max_retries = 3

    for attempt in range(max_retries):

        try:
            files = {
                "file": (
                    image_file.filename,
                    file_content,
                    image_file.mimetype or "image/jpeg"
                )
            }

            data = {
                "apikey": OCR_API_KEY,
                "language": "eng",
                "isOverlayRequired": "false",
                "OCREngine": "2"
            }

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

            result = response.json()

            if result.get("IsErroredOnProcessing"):
                raise ValueError(
                    str(
                        result.get(
                            "ErrorMessage",
                            "OCR processing failed."
                        )
                    )
                )

            parsed_results = result.get(
                "ParsedResults",
                []
            )

            if not parsed_results:
                return ""

            text_parts = []

            for parsed_result in parsed_results:
                text = parsed_result.get(
                    "ParsedText",
                    ""
                )

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