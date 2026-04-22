#!/usr/bin/env python3
"""
Send files to Bale (Telegram-like) with chunking support for files > 10MB
Bale file size limit: 10MB per message
"""

import os
import sys
import json
import requests
import base64
import math
from pathlib import Path
from typing import List, Dict, Any

class BaleFileSender:
    """Handle file sending to Bale API with automatic chunking"""
    
    # Bale API limits
    MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB in bytes
    CHUNK_SIZE = 9 * 1024 * 1024      # 9MB per chunk to be safe
    
    def __init__(self, bot_token: str, chat_id: str):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.base_url = f"https://tapi.bale.ai/bot{bot_token}"
        
    def send_message(self, text: str, parse_mode: str = "Markdown") -> bool:
        """Send a simple text message"""
        try:
            url = f"{self.base_url}/sendMessage"
            payload = {
                "chat_id": self.chat_id,
                "text": text,
                "parse_mode": parse_mode
            }
            response = requests.post(url, json=payload, timeout=30)
            return response.status_code == 200
        except Exception as e:
            print(f"Error sending message: {e}")
            return False
    
    def send_document(self, file_path: str, caption: str = "") -> bool:
        """Send a document file, automatically chunk if too large"""
        file_size = os.path.getsize(file_path)
        
        if file_size <= self.MAX_FILE_SIZE:
            # Send directly
            return self._send_single_document(file_path, caption)
        else:
            # Split and send as chunks
            return self._send_chunked_document(file_path, caption)
    
    def _send_single_document(self, file_path: str, caption: str = "") -> bool:
        """Send a single document file"""
        try:
            url = f"{self.base_url}/sendDocument"
            
            with open(file_path, 'rb') as f:
                files = {'document': (os.path.basename(file_path), f, 'application/zip')}
                data = {'chat_id': self.chat_id}
                
                if caption:
                    data['caption'] = caption
                
                response = requests.post(url, data=data, files=files, timeout=60)
                return response.status_code == 200
        except Exception as e:
            print(f"Error sending single document: {e}")
            return False
    
    def _send_chunked_document(self, file_path: str, caption: str = "") -> bool:
        """Split large file into chunks and send each chunk"""
        file_name = os.path.basename(file_path)
        file_size = os.path.getsize(file_path)
        num_chunks = math.ceil(file_size / self.CHUNK_SIZE)
        
        # Send info message about chunking
        info_msg = f"📦 *File is large ({file_size / 1024 / 1024:.1f}MB)*\n"
        info_msg += f"📁 {file_name}\n"
        info_msg += f"🔪 Splitting into {num_chunks} chunks (max 9MB each)\n"
        info_msg += f"⏳ Sending to Bale..."
        self.send_message(info_msg)
        
        # Split and send chunks
        success_count = 0
        with open(file_path, 'rb') as f:
            for i in range(num_chunks):
                chunk_data = f.read(self.CHUNK_SIZE)
                chunk_file_name = f"{file_name}.part{i+1:03d}"
                
                # Save chunk temporarily
                chunk_path = f"/tmp/{chunk_file_name}"
                with open(chunk_path, 'wb') as chunk_f:
                    chunk_f.write(chunk_data)
                
                # Send chunk
                chunk_caption = f"{caption}\n\n📦 Part {i+1}/{num_chunks} of {file_name}" if caption else f"📦 Part {i+1}/{num_chunks} of {file_name}"
                
                if self._send_single_document(chunk_path, chunk_caption):
                    success_count += 1
                    print(f"Sent chunk {i+1}/{num_chunks}")
                else:
                    print(f"Failed to send chunk {i+1}/{num_chunks}")
                
                # Clean up temp file
                os.remove(chunk_path)
                
                # Small delay to avoid rate limiting
                import time
                time.sleep(1)
        
        # Send summary
        if success_count == num_chunks:
            summary = f"✅ *All {num_chunks} chunks sent successfully!*\n"
            summary += f"📁 Original: {file_name}\n"
            summary += f"📦 Size: {file_size / 1024 / 1024:.1f}MB\n"
            summary += f"💡 To reassemble: `cat {file_name}.part* > {file_name}`"
            self.send_message(summary)
            return True
        else:
            summary = f"⚠️ *Partial upload*: {success_count}/{num_chunks} chunks sent\n"
            summary += f"📁 {file_name}"
            self.send_message(summary)
            return False
    
    def send_status_with_file(self, status: str, message: str, file_path: str = None) -> None:
        """Send status message with optional file attachment"""
        
        # First send status message
        self.send_message(message)
        
        # Then send file if exists
        if file_path and os.path.exists(file_path):
            caption = f"📎 Attached: {os.path.basename(file_path)}"
            self.send_document(file_path, caption)

def main():
    """Main function to handle command line arguments"""
    # Read from environment variables or command line
    bot_token = os.environ.get('BALE_BOT_TOKEN')
    chat_id = os.environ.get('BALE_CHAT_ID')
    file_path = os.environ.get('FILE_TO_SEND')
    status = os.environ.get('STATUS', 'unknown')
    message = os.environ.get('MESSAGE', '')
    
    if not bot_token or not chat_id:
        print("Error: BALE_BOT_TOKEN and BALE_CHAT_ID must be set")
        sys.exit(1)
    
    if not file_path:
        print("Error: FILE_TO_SEND environment variable not set")
        sys.exit(1)
    
    if not os.path.exists(file_path):
        print(f"Error: File not found: {file_path}")
        sys.exit(1)
    
    # Create sender instance
    sender = BaleFileSender(bot_token, chat_id)
    
    # Send status with file
    if not message:
        message = f"{status.upper()}: Mirror operation completed"
    
    sender.send_status_with_file(status, message, file_path)
    
    print("File sent to Bale successfully")

if __name__ == "__main__":
    main()
