#!/usr/bin/env python3
# =====================================================================
# pdelete.py - High-Performance Parallel Branch Deletion Script
# =====================================================================
import os
import sys
import argparse
import subprocess
import signal
import multiprocessing
import time
from queue import Empty

def worker_delete(queue):
    """Worker process: pulls directory branches from the queue and deletes them natively."""
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    while True:
        try:
            dir_path = queue.get(timeout=1)
            if dir_path is None:
                break  # Poison pill
            # Run native rm -rf on this directory branch
            subprocess.run(["rm", "-rf", dir_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Empty:
            continue
        except Exception as e:
            print(f"\nWorker error: {e}")
            break

def cleanup_workers(workers, queue):
    """Terminates all running worker processes."""
    print("\n[!] Interrupt received. Killing active worker processes...")
    while not queue.empty():
        try:
            queue.get_nowait()
        except Empty:
            break
    for p in workers:
        p.terminate()
        p.join()
    print("[!] Cleanup complete. Exiting.")
    sys.exit(1)

def main():
    parser = argparse.ArgumentParser(description="Balanced Parallel Branch Directory Deletion tool")
    parser.add_argument("-d", "--directory", required=True, help="Absolute path to target directory")
    parser.add_argument("-p", "--processes", type=int, required=True, help="Number of parallel processes to use")
    args = parser.parse_args()

    target_dir = os.path.abspath(args.directory)

    # Safety checks
    if not os.path.isdir(target_dir):
        print(f"Error: Directory '{target_dir}' does not exist.")
        sys.exit(1)

    if target_dir in ["/", "/home", "/root"]:
        print(f"Error: Deleting system directory '{target_dir}' is blocked for safety.")
        sys.exit(1)

    print("Scanning directory structure for parallel branches (depth 2)...")
    start_time = time.time()

    # 1. Collect subdirectories at depth 2 (e.g., target_dir/client-X/dir-Y)
    # This is metadata-only and finishes in seconds even for massive filesystems
    delete_targets = []
    try:
        # Find directories at exactly depth 2
        find_dirs = subprocess.run(
            ["find", target_dir, "-mindepth", "2", "-maxdepth", "2", "-type", "d"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            check=True
        )
        delete_targets = [line for line in find_dirs.stdout.splitlines() if line]
    except subprocess.CalledProcessError as e:
        print(f"Error scanning directories: {e.stderr}")
        sys.exit(1)

    # If no depth-2 subdirectories exist, default to depth-1 subdirectories or files
    if not delete_targets:
        try:
            delete_targets = [os.path.join(target_dir, x) for x in os.listdir(target_dir)]
        except Exception as e:
            print(f"Error listing directory: {e}")
            sys.exit(1)

    total_branches = len(delete_targets)
    scan_time = time.time() - start_time
    print(f"Scan complete. Found {total_branches:,} deletion branches in {scan_time:.2f} seconds.")

    if total_branches == 0:
        print(f"Directory is empty. Removing target folder...")
        subprocess.run(["rm", "-rf", target_dir], check=True)
        print("Done.")
        sys.exit(0)

    # Initialize communication queue
    manager = multiprocessing.Manager()
    queue = manager.Queue()

    # 2. Spawn worker processes
    workers = []
    
    # Handle Ctrl+C
    def handle_sigint(signum, frame):
        cleanup_workers(workers, queue)
    signal.signal(signal.SIGINT, handle_sigint)

    for _ in range(args.processes):
        p = multiprocessing.Process(target=worker_delete, args=(queue,))
        p.start()
        workers.append(p)

    # 3. Queue the directories to be deleted
    print(f"Queueing branches for parallel processing...")
    for path in delete_targets:
        queue.put(path)

    # Send poison pills to stop workers
    for _ in range(args.processes):
        queue.put(None)

    print("=============================================")
    print(f" Starting parallel delete of: {target_dir}")
    print(f" Workers: {args.processes}")
    print(f" Deletion branches: {total_branches:,}")
    print("=============================================")

    # Monitor progress
    delete_start_time = time.time()
    while any(p.is_alive() for p in workers):
        time.sleep(0.5)
        # Display elapsed time feedback
        elapsed = time.time() - delete_start_time
        sys.stdout.write(f"\rDeleting... Elapsed time: {elapsed:.1f}s")
        sys.stdout.flush()

    for p in workers:
        p.join()

    # Final parent directory cleanup
    print("\nBranches deleted. Cleaning up remaining parent directories...")
    try:
        subprocess.run(["rm", "-rf", target_dir], check=True)
        print("Done! Target directory successfully deleted.")
    except Exception as e:
        print(f"Error removing parent folder: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
