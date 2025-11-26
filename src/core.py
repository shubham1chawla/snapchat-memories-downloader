import logging
import os
import re
import shutil
import time
import zipfile
from datetime import datetime
from io import StringIO

import pandas as pd
import requests
from bs4 import BeautifulSoup
from exiftool import ExifToolHelper

from src.consts import MAX_RETRIES, DOWNLOAD_DELAYS_SEC
from src.utils import retry, is_system_file, get_already_downloaded_files, extract_latitude_longitude, get_extension

logger = logging.getLogger(__file__)


def _construct_dataframe(memories_html_path: str) -> pd.DataFrame:
    """
    Constructs a DataFrame from the memories HTML table, extracting download links and request types.
    """
    logger.info(f"Constructing dataframe from: '{memories_html_path}'")

    # Use pandas.read_html to quickly extract the table content
    with open(memories_html_path, "r") as file:
        html_content = file.read()
        # Read the first table found in the HTML content
        df = pd.read_html(StringIO(html_content))[0]

    # Renaming columns to match the new convention
    df = df.rename(columns={
        df.columns[0]: "timestamp_str",
        df.columns[1]: "media_type",
        df.columns[2]: "coordinates",
        df.columns[3]: "download_link",
    })

    # Converting timestamp string to long
    df["timestamp"] = df["timestamp_str"].apply(lambda ts_str: int(pd.to_datetime(ts_str, utc=True).timestamp() * 1000))

    # Updating media type
    df["media_type"] = df["media_type"].apply(lambda media_type: media_type.replace(' ', '_').lower())

    # Adding a new column for filename (without extension)
    df["file_name"] = df.apply(lambda r: f"{r["timestamp"]}_{r["media_type"]}", axis=1)

    # Adding a new column indicating whether file was extracted
    df["is_extracted"] = False

    # Extracting latitude and longitude
    def _apply(r):
        lat, lon = extract_latitude_longitude(r["coordinates"])
        r["lat"] = lat
        r["lon"] = lon
        return r

    df = df.apply(_apply, axis=1)

    # Prepare for extraction of URL and boolean indicator
    soup = BeautifulSoup(html_content, "html.parser")

    # Find all table data rows (tr)
    rows = soup.find("table").find("tbody").find_all("tr")

    # The first row is the header, so we skip it (index 0)
    data_rows = rows[1:]

    # Regex pattern to capture the URL and the boolean value from the onclick attribute:
    pattern = r"downloadMemories\('(.*?)', this, (true|false)\);"

    # Lists to store the extracted data
    extracted_links, extracted_booleans = [], []

    # Iterate through rows and extract data
    for row in data_rows:
        # Find the <a> tag which contains the onclick attribute
        a_tag = row.find("a", onclick=True)
        if a_tag and "onclick" in a_tag.attrs:
            onclick_content = a_tag["onclick"]
            match = re.search(pattern, onclick_content)
            if match:
                extracted_links.append(match.group(1))
                # Convert the extracted string boolean ("true" or "false") to a Python boolean
                extracted_booleans.append(match.group(2) == "true")
            else:
                extracted_links.append(None)
                extracted_booleans.append(None)
        else:
            extracted_links.append(None)
            extracted_booleans.append(None)

    # Add the new columns to the DataFrame
    df["download_link"] = extracted_links
    df["is_get_request"] = extracted_booleans

    # Returning constructed dataframe
    return df


@retry(max_retries=MAX_RETRIES, delay=DOWNLOAD_DELAYS_SEC)
def _fetch_response(download_link: str, is_get_request: bool) -> requests.Response:
    """Fetches response from the URL"""
    # Determine Request Method
    if is_get_request:
        # Corresponds to JS GET request with custom headers
        headers = {"X-Snap-Route-Tag": "mem-dmd", "User-Agent": "Mozilla/5.0"}
        response = requests.get(download_link, headers=headers, stream=True)
    else:
        # Corresponds to JS POST request
        # Split URL into base and parameters
        url_parts = download_link.split("?", 1)
        base_url = url_parts[0]
        payload = url_parts[1] if len(url_parts) > 1 else ""

        # The JS code uses application/x-www-form-urlencoded and sends parameters as body
        headers = {"Content-type": "application/x-www-form-urlencoded", "User-Agent": "Mozilla/5.0"}
        response = requests.post(base_url, data=payload, headers=headers, stream=True)

    # Handle response
    response.raise_for_status()  # Raise an exception for bad status codes (4xx or 5xx)
    return response


def _download_memories(df: pd.DataFrame, download_dir: str):
    """
    Downloads memories sequentially based on the data in the DataFrame.
    """

    # Create the download directory if it doesn't exist
    os.makedirs(download_dir, exist_ok=True)
    logger.info(f"Download directory created at: '{download_dir}'")

    total_downloads = len(df)
    completed_downloads = 0

    # Getting already downloaded files
    already_downloaded_files = get_already_downloaded_files(download_dir)
    logger.info(f"Already downloaded files count: {len(already_downloaded_files)}")

    # Creating file path column to dataframe
    df["file_path"] = None

    # Creating is zip column to dataframe
    df["is_zip"] = False

    for i, row in df.iterrows():
        download_link = row["download_link"]
        is_get_request = row["is_get_request"]
        file_name = row["file_name"]

        # Checking if file already downloaded
        if file_name in already_downloaded_files:
            file_path = already_downloaded_files[file_name]
            base_file_path = os.path.basename(file_path)
            _, extension = os.path.splitext(base_file_path)

            # Updating dataframe from already downloaded information
            df.loc[i, "file_path"] = file_path
            df.loc[i, "is_zip"] = extension == ".zip"
            df.loc[i, "is_extracted"] = "extracted" in file_name

            logger.info(f"Skipping row {i}: File already downloaded: '{base_file_path}'")
            continue

        # Checking if download link exists
        if not download_link:
            logger.warning(f"Skipping row {i}: Missing download link.")
            continue

        try:
            # Fetching response
            response = _fetch_response(download_link, is_get_request)

            # Determining extension from response
            extension = get_extension(response)

            # Checking if the downloaded file is a zip
            if extension == ".zip":
                df.loc[i, "is_zip"] = True

            # Constructing base file path
            base_file_path = f"{file_name}{extension}"

            # Adding file path to dataframe
            file_path = os.path.join(download_dir, base_file_path)
            df.loc[i, "file_path"] = file_path

            # Save the file content
            with open(file_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)

            completed_downloads += 1
            logger.info(f"[{completed_downloads}/{total_downloads}] Successfully downloaded: '{base_file_path}'")

        except requests.exceptions.HTTPError as e:
            logger.error(f"[{i + 1}/{total_downloads}] Download failed for '{download_link}': {e}.")
        except Exception as e:
            logger.error(f"[{i + 1}/{total_downloads}] An unexpected error occurred for '{download_link}': {e}")

        # Apply sequential delay
        if completed_downloads < total_downloads:
            logger.debug(f"Waiting for {DOWNLOAD_DELAYS_SEC} seconds...")
            time.sleep(DOWNLOAD_DELAYS_SEC)


def _handle_zips(df: pd.DataFrame, download_dir: str):
    """Handling zip file downloaded by extracting media archived in the zip"""

    # Filtering out non-zip files
    zip_df = df[df["is_zip"] == True]

    total_unzips = len(zip_df)
    completed_unzips = 0
    new_rows = []

    for _, row in zip_df.iterrows():
        zip_file_path = row["file_path"]
        zip_file_name = row["file_name"]

        # Use the file name (without .zip) as the temporary extraction folder name
        temp_extract_dir = os.path.join(download_dir, f"temp_{zip_file_name}")

        try:
            # Extract the ZIP file
            with zipfile.ZipFile(zip_file_path, 'r') as zip_ref:
                # Create the temporary directory inside the download folder
                os.makedirs(temp_extract_dir, exist_ok=True)
                zip_ref.extractall(temp_extract_dir)
                logger.debug(f"Successfully extracted to: '{temp_extract_dir}'")

            # Process extracted files, rename, and move
            extracted_files_count = 0
            for root, _, extractable_files in os.walk(temp_extract_dir):
                for i, extractable_file_name in enumerate(extractable_files):
                    # Ignore macOS resource files or system files
                    if is_system_file(extractable_file_name):
                        continue

                    # Extract file path in temp directory
                    extractable_file_path = os.path.join(root, extractable_file_name)
                    _, extension = os.path.splitext(extractable_file_name)

                    # Final file name to use for extracted file (zip_filename_extracted_index+1)
                    final_extracted_base_file_path = f"{zip_file_name}_extracted_{i + 1}{extension}"
                    final_extracted_file_path = os.path.join(download_dir, final_extracted_base_file_path)

                    # Move the file to the parent download directory
                    shutil.move(extractable_file_path, final_extracted_file_path)

                    # Creating new row entry for dataframe
                    new_row = row.copy()
                    new_row["file_name"] = os.path.splitext(final_extracted_base_file_path)[0]  # without extension
                    new_row["file_path"] = final_extracted_file_path
                    new_row["is_zip"] = False
                    new_row["is_extracted"] = True
                    new_rows.append(new_row)

                    extracted_files_count += 1

            completed_unzips += 1
            logger.info(
                f"[{completed_unzips}/{total_unzips}] Successfully moved {extracted_files_count} files to '{download_dir}'."
            )

        except zipfile.BadZipFile:
            logger.error(f"Error: The downloaded file '{zip_file_path}' is not a valid ZIP file.")
        except Exception as e:
            logger.error(f"Error processing ZIP file '{zip_file_path}': {e}")

        # Clean up the temporary folder
        finally:
            if os.path.exists(temp_extract_dir):
                shutil.rmtree(temp_extract_dir)
                logger.debug(f"Deleted temporary folder: {temp_extract_dir}")

    # Append new rows to the DataFrame
    for new_row in new_rows:
        df.loc[len(df)] = new_row

    logger.info(f"Added {len(new_rows)} new memories to dataframe!")


def _update_media_metadata_pyexiftool(file_path: str, timestamp_str: str, lat: float, lon: float):
    """
    Updates the metadata (Exif/XMP) of a media file using the pyexiftool library,
    which requires the external ExifTool utility to be installed.

    Also updates the OS-level access and modify time.
    """

    if not os.path.exists(file_path):
        logger.error(f"File not found: '{file_path}'")
        return

    # Parse Timestamp
    try:
        # Convert timestamp '2025-11-13 22:15:16 UTC' to the required Exif format
        dt_object = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S UTC")
        exif_datetime_format = dt_object.strftime("%Y:%m:%d %H:%M:%S")
    except ValueError as e:
        logger.error(f"Error parsing data for '{file_path}': {e}")
        return

    # Format the coordinates as D/M/S (or decimal) string with N/S/E/W suffix for GPSCoordinates tag
    # ExifTool can handle the conversion, but combining them is best for QuickTime
    gps_coordinate_string = f"{abs(lat)} {'N' if lat >= 0 else 'S'} {abs(lon)} {'E' if lon >= 0 else 'W'}"

    # Prepare Metadata Tags
    # We use both Date/Time tags to ensure both photo (.jpg) and video (.mp4) files are covered.
    # ExifTool automatically converts the absolute lat/lon values into the required
    # degrees, minutes, seconds (DMS) format and sets the reference tags (N/S/E/W).
    metadata_tags = {
        # Time and Date tags
        "XMP:DateTimeOriginal": exif_datetime_format,  # Primary XMP tag for time
        "XMP:CreateDate": exif_datetime_format,  # Secondary XMP tag
        "DateTimeOriginal": exif_datetime_format,  # Standard EXIF tag for original time
        "CreateDate": exif_datetime_format,  # XMP/QuickTime tag (useful for MP4)
        "ModifyDate": exif_datetime_format,  # Update the file modification date

        # GPS tags (ExifTool automatically calculates DMS from decimal degrees)
        "XMP:GPSLatitude": lat,
        "XMP:GPSLongitude": lon,
        "GPSLatitude": lat,
        "GPSLongitude": lon,

        # Optional: Set the reference direction explicitly if needed, but ExifTool can derive this
        # We need this to fix incorrect coordinate derivation by ExifTool
        "GPSLatitudeRef": 'N' if lat >= 0 else 'S',
        "GPSLongitudeRef": 'E' if lon >= 0 else 'W',

        # **CRITICAL for MP4 (QuickTime/XMP)** Mac and iPhone still don't show location of video! Need fix!
        "GPSCoordinates": gps_coordinate_string,  # Writes location in one tag for QuickTime/XMP
        "Location": gps_coordinate_string,  # Used by some readers
    }

    # Apply Metadata using pyexiftool
    base_file_path = os.path.basename(file_path)
    try:
        with ExifToolHelper() as et:
            # The execute_json method is used for writing. It handles escaping and execution.
            # -overwrite_original tells ExifTool to directly modify the file.
            et.execute(
                "-overwrite_original",
                # Map Python dictionary keys/values to ExifTool -TAG=VALUE format
                *[f"-{k}={v}" for k, v in metadata_tags.items()],
                file_path
            )

        logger.debug(f"Metadata updated successfully using pyexiftool: '{base_file_path}'")

    except FileNotFoundError:
        logger.error(f"Error: The external **ExifTool utility was not found**.")
        logger.error("Please ensure ExifTool is installed on your system and available in the PATH.")
    except Exception as e:
        logger.error(f"An error occurred during metadata writing for '{base_file_path}': {e}")

    # Changing date of capture to unix timestamp
    dt_object = pd.to_datetime(timestamp_str, utc=True)
    unix_timestamp = dt_object.timestamp()

    # Changing the OS-level timestamps
    try:
        # Set both access time and modification time to the capture time
        os.utime(file_path, (unix_timestamp, unix_timestamp))
        logger.debug(f"OS Filesystem timestamps updated: '{os.path.basename(file_path)}'")
    except Exception as e:
        logger.error(f"Failed to update filesystem time for {file_path}: {e}")


def _update_memories_metadata(df: pd.DataFrame):
    """Updates downloaded media's metadata to fix capture time and location"""

    # Filtering out zip files
    non_zip_df = df[df["is_zip"] == False]

    total_updates = len(non_zip_df)
    completed_updates = 0

    for i, row in non_zip_df.iterrows():
        file_path = row["file_path"]
        timestamp_str = row["timestamp_str"]
        lat = row["lat"]
        lon = row["lon"]
        base_file_path = os.path.basename(file_path)

        # Updating media
        _update_media_metadata_pyexiftool(file_path, timestamp_str, lat, lon)

        completed_updates += 1
        logger.info(f"[{completed_updates}/{total_updates}] Successfully updated: '{base_file_path}'")


def download_memories(memories_file_path: str, download_dir: str):
    """
    Downloads Snapchat memories from "memories_history.html" file provided by Snapchat when you export memories.

    :param memories_file_path: Path to "memories_history.html"
    :param download_dir: Path to directory where memories should be downloaded
    :return: None
    """

    logger.info("-" * 50)
    logger.info("** CONSTRUCTING DATAFRAME **")
    logger.info("-" * 50)

    # Constructing a dataframe from memories HTML file
    df = _construct_dataframe(memories_file_path)

    # Logging stats
    logger.info(f"Total memories: {df.shape[0]}")
    logger.info(f"Media Type(s):\n{df['media_type'].value_counts()}")
    logger.info(f"Missing download links: {df['download_link'].isna().sum()}")
    logger.info(f"Total not GET requests: {df['is_get_request'].eq(False).sum()}")

    logger.info("-" * 50)
    logger.info("** DOWNLOADING MEMORIES **")
    logger.info("-" * 50)

    # Start the sequential download process
    _download_memories(df, download_dir)

    # Logging stats
    logger.info(f"Total zip files: {df[df["is_zip"] == True].shape[0]}")

    logger.info("-" * 50)
    logger.info("** HANDLING ZIP FILES **")
    logger.info("-" * 50)

    # Unzipping zip and saving them in downloads folder
    _handle_zips(df, download_dir)

    logger.info("-" * 50)
    logger.info("** UPDATING METADATA **")
    logger.info("-" * 50)

    # Updating media's metadata to fix capture time and location
    _update_memories_metadata(df)

    logger.info("-" * 50)
    logger.info("** DONE **")
    logger.info("-" * 50)
