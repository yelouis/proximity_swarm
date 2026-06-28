import os
import subprocess
import json

def run_python(code: str, timeout_sec: int = 10) -> str:
    """Executes python code in a secure sandboxed subprocess and returns stdout/stderr."""
    try:
        result = subprocess.run(
            ["python3", "-c", code],
            capture_output=True,
            text=True,
            timeout=timeout_sec
        )
        if result.returncode == 0:
            return result.stdout.strip() if result.stdout else "Code executed successfully with no output."
        else:
            return f"Execution Failed (Exit {result.returncode}):\n{result.stderr.strip()}"
    except subprocess.TimeoutExpired:
        return f"Execution timed out after {timeout_sec} seconds."
    except Exception as e:
        return f"Error executing python code: {str(e)}"

def read_file(path: str) -> str:
    """Reads a file from the workspace."""
    # To prevent escaping the workspace, we only allow relative paths
    if ".." in path or path.startswith("/"):
        return "Error: Path must be a relative path within the workspace."
        
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return f"Error: File '{path}' not found."
    except Exception as e:
        return f"Error reading file '{path}': {str(e)}"

def write_file(path: str, content: str) -> str:
    """Writes content to a file in the workspace."""
    if ".." in path or path.startswith("/"):
        return "Error: Path must be a relative path within the workspace."
        
    try:
        # Create directories if they don't exist
        os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return f"Successfully wrote to file '{path}'."
    except Exception as e:
        return f"Error writing file '{path}': {str(e)}"
