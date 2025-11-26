import argparse
import logging
import os

from src.core import download_memories

# Configure logging to display messages to the console
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__file__)


def main():
    """
    Parses command-line arguments and initiates the memory download process.
    """

    parser = argparse.ArgumentParser(
        description="Download and process media files from a Snapchat memories history HTML file."
    )

    # Argument 1: Input HTML file path (required)
    parser.add_argument(
        "-m", "--memories_path",
        type=str,
        help="The full path to the memories history HTML file (e.g., /path/to/memories_history.html)."
    )

    # Argument 2: Output download directory (required)
    parser.add_argument(
        "-d", "--download_dir",
        type=str,
        help="The path to the directory where media files will be downloaded and processed."
    )

    args = parser.parse_args()

    # Validate the input HTML file path
    if not os.path.exists(args.memories_path):
        logger.error(f"Error: Input file not found at {args.memories_path}")
        return

    # Ensure the download directory exists (or create it)
    os.makedirs(args.download_dir, exist_ok=True)

    logger.info(f"Using memories file: '{args.memories_path}'")
    logger.info(f"Saving media to directory: '{args.download_dir}'")

    # Downloading memories
    download_memories(args.memories_path, args.download_dir)


if __name__ == "__main__":
    main()
