# utils.py

import os
import re
import time
import requests
import json
import logging # NEW: Import logging
from telegram.utils.helpers import escape_markdown as escape_markdown_v2

# NEW: Create a single, named logger for the entire application
LOGGER = logging.getLogger("SecureFetchBot")

# NEW: Function to configure the logger with a minimalist, colored format
def setup_logger():
    handler = logging.StreamHandler()
    log_format = "[%(asctime)s] [%(levelname)-8s] %(message)s"
    
    try:
        from colorlog import ColoredFormatter
        formatter = ColoredFormatter(
            '%(log_color)s' + log_format,
            datefmt='%Y-%m-%d %H:%M:%S',
            log_colors={
                'DEBUG': 'cyan',
                'INFO': 'green',
                'WARNING': 'yellow',
                'ERROR': 'red',
                'CRITICAL': 'red,bg_white',
            }
        )
    except ImportError:
        formatter = logging.Formatter(log_format, datefmt='%Y-%m-%d %H:%M:%S')

    handler.setFormatter(formatter)
    LOGGER.addHandler(handler)
    LOGGER.setLevel(logging.INFO)

DOWNLOAD_PATH = os.path.join(os.getcwd(), "downloads")

def escape_markdown(text):
    return escape_markdown_v2(str(text), version=2)

def format_bytes(byte_count):
    if byte_count is None: return "0 B"
    power = 1024; n = 0
    power_labels = {0: 'B', 1: 'KB', 2: 'MB', 3: 'GB', 4: 'TB'}
    while byte_count >= power and n < len(power_labels) - 1:
        byte_count /= power; n += 1
    return f"{byte_count:.2f} {power_labels[n]}"

def format_time(seconds):
    if seconds is None or seconds < 0 or seconds == float('inf'): return "N/A"
    m, s = divmod(seconds, 60); h, m = divmod(m, 60)
    return f"{int(h):02d}:{int(m):02d}:{int(s):02d}"

def progress_bar(percentage):
    if percentage > 100: percentage = 100
    if percentage < 0: percentage = 0
    filled_blocks = int(round(percentage / 10))
    return f"[{'■' * filled_blocks}{'□' * (10 - filled_blocks)}]"

def parse_filename(name):
    name = name.replace('.', ' ').replace('_', ' ')
    patterns = [r'\b(1080p|720p|2160p|4k|480p)\b', r'\b(x264|x265|h264|h265|avc|hevc)\b', r'\b\d{4}\b']
    details = []
    for p in patterns:
        match = re.search(p, name, re.IGNORECASE)
        if match:
            details.append(match.group(0))
            name = re.sub(p, '', name, flags=re.IGNORECASE)
    clean_name = ' '.join(name.split()).title()
    return f"{clean_name} ({' '.join(details)})" if details else clean_name

def fetch_root_dir_id(account_id: str) -> str | None:
    url = "https://buzzheavier.com/api/fs"
    headers = {"Authorization": f"Bearer {account_id}"}
    try:
        LOGGER.info("Fetching BuzzHeavier Root Directory ID...") # NEW
        response = requests.get(url, headers=headers, timeout=10)
        data = response.json()
        if response.status_code == 200 and data.get('code') == 200 and 'id' in data.get('data', {}):
            root_id = data['data']['id']
            LOGGER.info(f"Successfully fetched Root ID: {root_id}") # NEW
            return root_id
        else:
            error_message = data.get('message', f"HTTP Status {response.status_code}")
            LOGGER.critical(f"API Error from BuzzHeavier: {error_message}") # MODIFIED
            return None
    except requests.exceptions.RequestException as e:
        LOGGER.critical(f"Could not connect to BuzzHeavier API. Error: {e}") # MODIFIED
    except json.JSONDecodeError:
        LOGGER.critical("Received invalid JSON from BuzzHeavier API.") # MODIFIED
    return None

class UploadProgressTracker:
    def __init__(self, file_object, callback, file_size):
        self._file = file_object
        self.size = file_size
        self.read_so_far = 0
        self._callback = callback
        self._start_time = time.time()
        self._last_update_time = 0

    def read(self, size=-1):
        chunk = self._file.read(size)
        if chunk:
            self.read_so_far += len(chunk)
            current_time = time.time()
            if current_time - self._last_update_time > 2:
                self._callback(self.read_so_far, self.size, self._start_time)
                self._last_update_time = current_time
        return chunk

    def __len__(self):
        return self.size
