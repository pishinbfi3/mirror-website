#!/usr/bin/env python3
"""Main entry point for Bale SSH Bot."""

import sys
import time
import os
import traceback
from datetime import datetime
from typing import Optional

from .config import BotConfig
from .handler import BaleBotHandler


def setup_environment():
    """Setup environment for GitHub Actions."""
    # Ensure temp directory exists
    os.makedirs("/tmp", exist_ok=True)
    
    # Log start time
    with open("/tmp/bale-bot-startup.log", "w") as f:
        f.write(f"Bot started at {datetime.now().isoformat()}\n")
        f.write(f"Python: {sys.version}\n")
        f.write(f"PID: {os.getpid()}\n")


def cleanup_old_files():
    """Clean up old temporary files."""
    import glob
    
    patterns = [
        "/tmp/bale_output_*.txt",
        "/tmp/command-output-*.txt"
    ]
    
    current_time = time.time()
    max_age = 3600  # 1 hour
    
    for pattern in patterns:
        for filepath in glob.glob(pattern):
            try:
                if current_time - os.path.getmtime(filepath) > max_age:
                    os.unlink(filepath)
            except Exception:
                pass


def main():
    """Main bot execution loop."""
    print("🤖 Bale SSH Bot starting...")
    
    # Setup
    setup_environment()
    cleanup_old_files()
    
    try:
        # Load configuration
        config = BotConfig.from_env()
        print(f"✅ Configuration loaded")
        print(f"   Chat ID: {config.chat_id[:10]}...")
        
    except ValueError as e:
        print(f"❌ Configuration error: {e}")
        sys.exit(1)
    
    # Initialize bot handler
    handler = BaleBotHandler(config)
    print(f"✅ Bot handler initialized")
    
    # Get last update offset
    offset = handler.get_offset()
    print(f"📝 Last offset: {offset}")
    
    processed_messages = 0
    max_empty_iterations = 3  # Stop after 3 empty polls
    empty_count = 0
    
    # Process updates continuously
    try:
        while empty_count < max_empty_iterations:
            # Get updates
            updates = handler.get_updates(offset)
            
            if not updates:
                empty_count += 1
                print(f"⏳ No new messages ({empty_count}/{max_empty_iterations})")
                
                # Check if we're near GitHub Actions timeout (5 minutes warning)
                # GitHub Actions timeout is usually 6 hours, so we're fine
                continue
            
            # Reset empty counter when we get messages
            empty_count = 0
            print(f"📨 Processing {len(updates)} update(s)")
            
            for update in updates:
                update_id = update.get("update_id", 0)
                offset = max(offset, update_id + 1)
                
                # Extract message
                message = update.get("message") or update.get("edited_message")
                if not message:
                    continue
                
                # Check chat ID
                chat = message.get("chat", {})
                chat_id = str(chat.get("id"))
                
                # Only respond to configured chat
                if chat_id != config.chat_id:
                    print(f"⚠️ Ignoring message from unauthorized chat: {chat_id}")
                    continue
                
                # Extract text
                text = message.get("text") or message.get("caption", "").strip()
                if not text:
                    continue
                
                message_id = message.get("message_id")
                
                print(f"💬 Processing: {text[:50]}...")
                
                # Process command
                try:
                    response, file_path = handler.process_command(text)
                    
                    # Send response
                    success = handler.send_message(response, message_id)
                    
                    # Send file if exists
                    if file_path and os.path.exists(file_path):
                        handler.send_file(file_path, f"Output for: {text[:100]}")
                        try:
                            os.unlink(file_path)
                        except Exception:
                            pass
                    
                    if success:
                        processed_messages += 1
                        print(f"✅ Response sent")
                    else:
                        print(f"❌ Failed to send response")
                        
                except Exception as e:
                    error_msg = f"❌ Error processing command: {str(e)}"
                    print(error_msg)
                    traceback.print_exc()
                    handler.send_message(f"❌ Internal error: {str(e)}", message_id)
            
            # Save offset after processing each batch
            handler.save_offset(offset)
            
            # Small delay to prevent rate limiting
            time.sleep(1)
    
    except KeyboardInterrupt:
        print("\n⚠️ Bot interrupted")
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        traceback.print_exc()
    finally:
        # Final offset save
        handler.save_offset(offset)
        print(f"\n📊 Summary:")
        print(f"   Processed messages: {processed_messages}")
        print(f"   Final offset: {offset}")
    
    print("👋 Bot finished")


if __name__ == "__main__":
    main()
