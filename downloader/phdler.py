import sys
from functions import process_download

def main():
    if len(sys.argv) < 2:
        print("Usage: phdler.py <url>")
        sys.exit(1)

    url = sys.argv[1]
    dest = "downloads"

    parts = process_download(url, dest)

    print("DONE PARTS:")
    for p in parts:
        print(p)

if __name__ == "__main__":
    main()
