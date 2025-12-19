#!/usr/bin/env python3
"""
Fix all vhosts that have default_queue_type set to literal string "undefined"

Usage:
  python3 fix.py
"""

import json
import subprocess
import sys

# ANSI colors
YELLOW = "\033[0;33m"
GREEN = "\033[0;32m"
RED = "\033[0;31m"
NC = "\033[0m"


def main():
    print("Checking vhosts for default_queue_type set to literal 'undefined'...")
    print()

    cmd = ["rabbitmqctl", "list_vhosts", "name", "default_queue_type", "--formatter", "json"]
    print(f"  {YELLOW}$ {' '.join(cmd)}{NC}")

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"{RED}ERROR: {result.stderr}{NC}")
        sys.exit(1)

    vhosts = json.loads(result.stdout)
    print()

    fixed_count = 0
    for vhost in vhosts:
        name = vhost["name"]
        dqt = vhost.get("default_queue_type", "not_set")

        if dqt == "undefined":
            print(f"{RED}Found problematic metadata: vhost '{name}' has default_queue_type = '{dqt}'{NC}")
            fix_cmd = ["rabbitmqctl", "update_vhost_metadata", name, "--default-queue-type", "classic"]
            print(f"  {YELLOW}$ {' '.join(fix_cmd)}{NC}")
            subprocess.run(fix_cmd, check=True)
            fixed_count += 1
        else:
            print(f"{GREEN}ok: vhost '{name}' has default_queue_type = '{dqt}'{NC}")

    print()
    if fixed_count > 0:
        print(f"Fixed {fixed_count} vhost(s).")
    else:
        print("All vhosts are OK.")


if __name__ == "__main__":
    main()
