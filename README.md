# Snapchat Memories Downloader and Metadata Processor

## 🌟 Project Overview

This command-line interface (CLI) application provides a robust and reliable way to download media from your Snapchat
memories export file and ensure that the downloaded files retain correct metadata, including the original capture time
and location coordinates.

### The Problem This Solves

When you request your memories history from Snapchat, they provide an HTML file (`memories_history.html`) containing
links to all your media. Manually downloading these files presents three significant issues:

1. **Annoying Popups & Manual Effort:** Browsers often trigger repetitive "Allow multiple file downloads" popups,
   requiring constant manual confirmation for every single photo or video. This script automates sequential downloading,
   and retries the download three times before skipping a memory.
2. **Handling ZIP Bundles:** Snapchat often bundles multiple memories (images/videos) into a single .zip file for
   download. This script automatically identifies and extracts these ZIP files, renames the contents to preserve the
   original timestamp, and adds the extracted files to the processing queue.
3. **Missing Metadata:** The files downloaded manually or directly from the HTML will have their filesystem creation
   time set to the moment of download, losing the original context of when the memory was captured. This script fixes
   this by updating the internal media metadata (EXIF/XMP) and the filesystem timestamps, ensuring that even files
   extracted from ZIP archives receive the correct capture time and location metadata.

This script automates the entire process, handles sequential downloading and retries, manages files bundled in ZIP
archives, and ensures your media files are accurately tagged with the original timestamp and GPS coordinates. You can
also resume the download process in between with ease, just run the script again!

> [!NOTE]
> The script has been tested on `MacOS`, downloading ~4000 memories starting 2016 and fixing metadata of ~5000 memories.

## ⚙️ Installation and Setup

### Prerequisites

You must have the following installed on your system:

1. **Python 3.12:** This is the minimum required Python version.
2. **uv:** A fast Python package installer and resolver.
3. **ExifTool:** This is a crucial, industry-standard external utility required for reading and writing complex
   metadata (like GPS and time) in image and video files (`.jpg`, `.png`, `.mp4`).
    - Installation: Please install ExifTool according to the instructions on the official
      website: https://exiftool.org/index.html. You must ensure the exiftool command is accessible from your system's
      command line (i.e., it is in your system's PATH).

### Python Dependencies

All dependencies are defined in the pyproject.toml file. Use uv to create a virtual environment and install them:

```shell
# Create a virtual environment
uv venv

# Activate the virtual environment (command varies by OS)
source .venv/bin/activate  # macOS/Linux
.venv\Scripts\activate.bat # Windows

# Install dependencies using uv
uv sync
```

### Obtaining Your Memories File

1. You must request your data from Snapchat and wait for the export to be processed:
2. Log in to the Snapchat web portal.
3. Navigate to Account Settings.
4. Go to the My Data section.
5. When selecting data types, only select Memories.
6. Select your desired date range or choose All Time.
7. For security reasons, Snapchat will typically only begin processing the request after a 72-hour waiting period.
8. After 72 hours, re-request the export if necessary, or wait for the initial processing to complete.
9. You will receive an email notifying you that the download is ready.
10. Download the ZIP file provided in the email link.
11. Extract the ZIP file. The target file for this script will be located at:
    [Your Downloaded Data Folder]/html/memories_history.html
12. Your download links are valid for 7 days of when you exported it, so ensure you run the script before the links
    expire.

## 🚀 Running the Application (CLI Usage)

The script is executed via the command line and requires two arguments, specified via flags.

Command Syntax

```shell
python main.py -m [MEMORIES_HTML_PATH] -d [OUTPUT_DOWNLOAD_DIRECTORY]
# OR
python main.py --memories_path [MEMORIES_HTML_PATH] --download_dir [OUTPUT_DOWNLOAD_DIRECTORY]
```

### Example

Assuming your project root is the current directory:

```shell
# Example using relative paths
python main.py -m ./data/mydata~123456/html/memories_history.html -d ./downloaded_memories
```

### Process Flow

The application executes the following sequence:

1. **Download All Media and ZIPs:** Iterates through the HTML, downloading all files (single media and ZIP bundles)
   sequentially.
2. **Extract ZIPs:** Automatically extracts contents from any downloaded ZIP files, renames the extracted media, and
   cleans up temporary folders.
3. **Update Metadata:** Applies the corrected capture time and GPS coordinates to all downloaded media files (single and
   extracted) by updating the internal media metadata (EXIF/XMP) and the filesystem timestamps.
