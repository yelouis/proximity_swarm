import os
import json
import logging
import datetime
from agent_runner import STATE_DIR, TOMBSTONES_FILE

WORKSPACES_DIR = os.path.join(os.getcwd(), ".proximity_swarm", "workspaces")

def cleanup_workspace(dry_run=False):
    """
    Opt-in garbage collection for workspace tombstone files.
    Safely resolves paths to ensure they are strictly inside the WORKSPACES_DIR.
    Writes a deletion manifest before removing any files.
    """
    if not os.path.exists(TOMBSTONES_FILE):
        logging.info("No tombstones.json found. Nothing to clean.")
        return True
        
    try:
        with open(TOMBSTONES_FILE, 'r') as f:
            tombstones_data = json.load(f)
    except Exception as e:
        logging.error(f"Failed to read tombstones.json: {e}")
        return False
        
    # Handle both old and new schema
    tombstones = tombstones_data if isinstance(tombstones_data, list) else tombstones_data.get("dead_ends", [])
    
    files_to_delete = []
    
    # 1. Jail validation
    real_workspaces_dir = os.path.realpath(WORKSPACES_DIR)
    
    for t in tombstones:
        file_path = t.get("file_path")
        if not file_path or file_path == "unknown":
            continue
            
        real_path = os.path.realpath(file_path)
        
        # Security: Jail check
        if not real_path.startswith(real_workspaces_dir):
            logging.warning(f"SECURITY WARNING: Skipping path outside workspace jail: {file_path}")
            continue
            
        if os.path.exists(real_path) and os.path.isfile(real_path):
            if real_path not in files_to_delete:
                files_to_delete.append(real_path)
                
    if not files_to_delete:
        logging.info("No valid workspace files found for garbage collection.")
        return True
        
    # 2. Write Manifest
    timestamp = datetime.datetime.now().strftime("%Y-%m-%dT%H-%M-%S-%f")
    manifest_path = os.path.join(STATE_DIR, f"gc_manifest_{timestamp}.json")
    
    manifest_data = {
        "timestamp": timestamp,
        "dry_run": dry_run,
        "files_deleted": files_to_delete
    }
    
    try:
        with open(manifest_path, 'w') as f:
            json.dump(manifest_data, f, indent=2)
        logging.info(f"Wrote GC manifest: {manifest_path}")
    except Exception as e:
        logging.error(f"Failed to write GC manifest. Aborting cleanup: {e}")
        return False
        
    # 3. Dry-run abort
    if dry_run:
        logging.info(f"Dry-run active. Would have deleted {len(files_to_delete)} files.")
        return True
        
    # 4. Perform actual deletions
    success_count = 0
    for path in files_to_delete:
        try:
            os.remove(path)
            success_count += 1
        except Exception as e:
            logging.error(f"Failed to remove {path}: {e}")
            
    logging.info(f"Workspace GC complete. Deleted {success_count} files.")
    return True

if __name__ == "__main__":
    # If run standalone, default to dry-run
    import sys
    dry_run = "--commit" not in sys.argv
    if dry_run:
        print("Running in dry-run mode. Pass --commit to actually delete files.")
    cleanup_workspace(dry_run=dry_run)
