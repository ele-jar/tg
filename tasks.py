# tasks.py

import os
import time
import re
import requests
import libtorrent as lt
from urllib.parse import urlparse, unquote

from utils import (
    escape_markdown, format_bytes, format_time, progress_bar, 
    UploadProgressTracker, DOWNLOAD_PATH
)

def get_http_filename(url):
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        with requests.head(url, allow_redirects=True, timeout=15, headers=headers) as r:
            r.raise_for_status()
            if "content-disposition" in r.headers:
                d = r.headers['content-disposition']
                fnames = re.findall("filename\*?=([^;]+)", d, re.IGNORECASE)
                if fnames:
                    fname = fnames[0].strip().strip("'\"")
                    if fname.lower().startswith("utf-8''"): fname = unquote(fname[7:])
                    return fname
            return unquote(os.path.basename(urlparse(r.url).path))
    except requests.RequestException as e:
        print(f"Failed to get filename from URL {url}: {e}")
        return None

def download_http(url, filename, update_status_callback):
    filepath = os.path.join(DOWNLOAD_PATH, filename)
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        with requests.get(url, stream=True, allow_redirects=True, timeout=30, headers=headers) as r:
            r.raise_for_status()
            total_size = int(r.headers.get('content-length', 0))
            downloaded = 0
            start_time = time.time()
            last_update_time = 0
            with open(filepath, 'wb') as f:
                for chunk in r.iter_content(chunk_size=1024*1024):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        current_time = time.time()
                        if current_time - last_update_time > 2:
                            elapsed = current_time - start_time
                            speed = downloaded / elapsed if elapsed > 0 else 0
                            progress = (downloaded / total_size) * 100 if total_size > 0 else 0
                            eta = ((total_size - downloaded) / speed) if speed > 0 else -1
                            msg = (f"*Status:* Downloading `{escape_markdown(filename)}`\n"
                                   f"{progress_bar(progress)} {escape_markdown(f'{progress:.2f}%')}\n"
                                   f"`{escape_markdown(format_bytes(downloaded))}` of `{escape_markdown(format_bytes(total_size))}`\n"
                                   f"*Speed:* {escape_markdown(f'{format_bytes(speed)}/s')}\n*ETA:* {escape_markdown(format_time(eta))}")
                            update_status_callback(msg)
                            last_update_time = current_time
        return filepath, downloaded
    except Exception as e:
        print(f"HTTP Download failed for {filename}: {e}")
        return None, 0

def download_magnet(magnet_link, filename, update_status_callback):
    ses = lt.session({'listen_interfaces': '0.0.0.0:6881'})
    params = {'save_path': DOWNLOAD_PATH}
    try:
        handle = lt.add_magnet_uri(ses, magnet_link, params)
        ses.start_dht()
        while not handle.has_metadata(): time.sleep(1)
        info = handle.get_torrent_info()
        sanitized_torrent_name = re.sub(r'[<>:"/\\|?*]', '_', info.name())
        last_update_time = 0
        while not handle.status().is_seeding:
            s = handle.status(); current_time = time.time()
            if current_time - last_update_time > 2:
                state = ['queued','checking','dl metadata','downloading','finished','seeding'][s.state]
                eta = (s.total_wanted - s.total_wanted_done) / s.download_rate if s.download_rate > 0 else -1
                msg = (f"*Status:* {escape_markdown(state.capitalize())} `{escape_markdown(sanitized_torrent_name)}`\n"
                       f"{progress_bar(s.progress * 100)} {escape_markdown(f'{s.progress * 100:.2f}%')}\n"
                       f"`{escape_markdown(format_bytes(s.total_wanted_done))}` of `{escape_markdown(format_bytes(s.total_wanted))}`\n"
                       f"*Speed:* {escape_markdown(f'{format_bytes(s.download_rate)}/s')}\n"
                       f"*Peers:* {escape_markdown(f'{s.num_peers} (S:{s.num_seeds}, L:{s.num_leechers})')}\n*ETA:* {escape_markdown(format_time(eta))}")
                update_status_callback(msg); last_update_time = current_time
            time.sleep(1)
        original_path = os.path.join(DOWNLOAD_PATH, sanitized_torrent_name)
        final_path = os.path.join(DOWNLOAD_PATH, filename)
        if os.path.exists(original_path): os.rename(original_path, final_path); return final_path, info.total_size()
        else: raise FileNotFoundError(f"Torrent file not found: {original_path}")
    except Exception as e: print(f"Torrent download failed: {e}"); return None, 0
    finally: ses.pause()

def upload_file(filepath, final_filename, update_status_callback, account_id, root_dir_id):
    upload_url = f"https://w.buzzheavier.com/{root_dir_id}/{final_filename}"
    headers = {"Authorization": f"Bearer {account_id}"}
    file_size = os.path.getsize(filepath)

    def progress_callback(uploaded, total, start_time):
        elapsed = time.time() - start_time
        speed = uploaded / elapsed if elapsed > 0 else 0
        percentage = (uploaded / total) * 100 if total > 0 else 0
        eta = ((total - uploaded) / speed) if speed > 0 else -1
        msg = (f"*Status:* Uploading `{escape_markdown(final_filename)}`\n"
               f"{progress_bar(percentage)} {escape_markdown(f'{percentage:.2f}%')}\n"
               f"`{escape_markdown(format_bytes(uploaded))}` of `{escape_markdown(format_bytes(file_size))}`\n"
               f"*Speed:* {escape_markdown(f'{format_bytes(speed)}/s')}\n*ETA:* {escape_markdown(format_time(eta))}")
        update_status_callback(msg)

    try:
        with open(filepath, 'rb') as f:
            data = UploadProgressTracker(f, progress_callback, file_size)
            response = requests.put(upload_url, data=data, headers=headers, timeout=10800)
            response.raise_for_status()
        buzz_link = response.text.strip()
        return file_size, buzz_link
    except Exception as e:
        print(f"Upload failed for {final_filename}: {e}")
        return None, None

def worker_task(url, final_filename, user_id, chat_id, context, account_id, root_dir_id, update_status_callback, on_complete_callback):
    filepath, size = (None, 0)
    try:
        update_status_callback(f"*Status:* Preparing task for `{escape_markdown(final_filename)}`\.")
        if url.startswith("magnet:"): filepath, size = download_magnet(url, final_filename, update_status_callback)
        else: filepath, size = download_http(url, final_filename, update_status_callback)
        if not filepath: update_status_callback(f"❌ *Download failed for* `{escape_markdown(final_filename)}`\."); return

        with context.bot_data['data_lock']:
            context.bot_data['stats']['downloaded'] += size
            context.bot_data['save_stats']()

        upload_size, buzz_link = upload_file(filepath, final_filename, update_status_callback, account_id, root_dir_id)
        if upload_size and buzz_link:
            with context.bot_data['data_lock']:
                context.bot_data['stats']['uploaded'] += upload_size
                context.bot_data['saved_links'][final_filename] = buzz_link
                context.bot_data['save_stats']()
            final_message = f"✅ *Upload successful\!*\n\n*File:* `{escape_markdown(final_filename)}`\n*Link:* {escape_markdown(buzz_link)}"
            context.bot.send_message(chat_id, final_message, parse_mode='MarkdownV2', disable_web_page_preview=True)
            update_status_callback(f"✅ *Task complete for:* `{escape_markdown(final_filename)}`")
        else: update_status_callback(f"❌ *Upload failed for* `{escape_markdown(final_filename)}`\.")
    finally:
        if filepath and os.path.exists(filepath): os.remove(filepath)
        on_complete_callback()
