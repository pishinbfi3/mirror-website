import os
import sys
import sqlite3
import requests
import zipfile
import time
from pathlib import Path
from urllib.parse import urlparse
from prettytable import PrettyTable
from bs4 import BeautifulSoup

# ترجیح yt_dlp
try:
    import yt_dlp as youtube_dl
except ImportError:
    import youtube_dl


#####################################################################
# ZIP + SPLIT SYSTEM
#####################################################################

def zip_folder(folder_path, zip_path):
    folder_path = Path(folder_path)
    zip_path = Path(zip_path)

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(folder_path):
            for file in files:
                full_path = os.path.join(root, file)
                arcname = os.path.relpath(full_path, folder_path)
                zipf.write(full_path, arcname)
    return str(zip_path)


def split_file(file_path, chunk_size=10 * 1024 * 1024):
    file_path = Path(file_path)
    parts = []

    with open(file_path, "rb") as f:
        index = 1
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            part_name = f"{file_path}.part{index:03d}"
            with open(part_name, "wb") as p:
                p.write(chunk)
            parts.append(str(part_name))
            index += 1
    return parts


#####################################################################
# DOWNLOADER (اصلاح‌شده برای yt-dlp)
#####################################################################

def download_video(url, output_dir):
    outtmpl = f"{output_dir}/%(title)s.%(ext)s"

    ydl_opts = {
        "outtmpl": outtmpl,
        "format": "best",
        "ignoreerrors": True,
        "no_warnings": False,
        "nooverwrites": True,
    }

    with youtube_dl.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])

    # پیدا کردن فایل دانلودشده
    folder = Path(output_dir)
    files = list(folder.glob("*"))
    if not files:
        return None

    return str(files[0])


#####################################################################
# MAIN WORKFLOW
#####################################################################

def process_download(url, dest):
    """دانلود → ZIP → SPLIT → خروجی تکه‌ها"""
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)

    print("[+] Downloading...")
    downloaded_file = download_video(url, dest)
    if not downloaded_file:
        raise Exception("دانلود انجام نشد!")

    print("[+] Zipping...")
    zip_path = dest / "package.zip"
    zip_folder(dest, zip_path)

    print("[+] Splitting...")
    parts = split_file(zip_path)

    print("[+] آماده برای ارسال:", parts)
    return parts
