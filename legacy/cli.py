#!/usr/bin/env python3
import sys
import subprocess

def main():
    # Forward all CLI arguments to terminal_dashboard.py
    subprocess.run([sys.executable, "terminal_dashboard.py"] + sys.argv[1:])

if __name__ == "__main__":
    main()
