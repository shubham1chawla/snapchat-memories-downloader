import logging
import os
import re
import time
from typing import Dict, Tuple

import requests

logger = logging.getLogger(__file__)


def retry(max_retries=3, delay=1, exceptions=(Exception,)):
    """Decorator to retry on exception"""

    def decorator(func):
        def wrapper(*args, **kwargs):
            attempts = 0
            while attempts < max_retries:
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    attempts += 1
                    logging.warning(f"Attempt {attempts} failed: {e}. Retrying in {delay} seconds...")
                    time.sleep(delay)
            raise Exception(f"Function {func.__name__} failed after {max_retries} attempts.")

        return wrapper

    return decorator


def is_system_file(file_name: str) -> bool:
    """Indicates whether file is system generated"""

    return file_name.startswith('__MACOSX') or file_name.startswith('.')


def get_already_downloaded_files(download_dir: str) -> Dict[str, str]:
    """Already downloaded filenames in the download directory"""
    files = {}
    for base_file_path in os.listdir(download_dir):
        # Ignore macOS resource files or system files
        if not is_system_file(base_file_path):
            file_name, _ = os.path.splitext(base_file_path)
            files[file_name] = os.path.join(download_dir, base_file_path)
    return files


def extract_latitude_longitude(coordinates: str) -> Tuple[float, float]:
    """
    Extracts lat/log from coordinate string following pattern 'Latitude, Longitude: number, number'
    """

    match = re.search(r"Latitude, Longitude: (-?\d+\.?\d*), (-?\d+\.?\d*)", coordinates)
    if not match:
        print(f"Invalid coordinate format: {coordinates}")
        lat, lon = 0.0, 0.0
    else:
        lat, lon = float(match.group(1)), float(match.group(2))
    return lat, lon


def get_extension(response: requests.Response) -> str:
    """Determine file extension"""

    # The server often suggests the filename in the Content-Disposition header.
    content_disp = response.headers.get("Content-Disposition")
    extension = ""

    if content_disp:
        # Attempt to extract file name from header
        match = re.search(r'filename="?([^"]+)"?', content_disp)
        if match:
            base_file_path = match.group(1)
            # Extract extension from base file path
            _, extension = os.path.splitext(base_file_path)
            extension = extension.lower() if extension else ".dat"

    return extension
