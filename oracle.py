import subprocess
import os

def evaluate_oracle(node, workspace_dir):
    """
    Evaluates the oracle for a given node.
    Returns: (passed: bool, message: str)
    """
    oracle = node.get("oracle", {})
    if not oracle:
        return True, "No oracle specified, assuming valid."
        
    oracle_type = oracle.get("type", "none")
    oracle_spec = oracle.get("spec", "")
    
    if oracle_type == "none":
        return False, "Unverifiable node."
        
    if oracle_type == "shell":
        try:
            result = subprocess.run(
                oracle_spec,
                shell=True,
                cwd=workspace_dir,
                capture_output=True,
                text=True,
                timeout=30
            )
            if result.returncode == 0:
                return True, "Shell oracle passed."
            else:
                return False, f"Shell oracle failed: {result.stderr or result.stdout}"
        except subprocess.TimeoutExpired:
            return False, "Shell oracle timed out."
        except Exception as e:
            return False, f"Shell oracle error: {e}"
            
    if oracle_type == "numeric":
        try:
            # We evaluate numeric Python scripts that print "True" or exit 0.
            result = subprocess.run(
                ["python3", "-c", oracle_spec],
                cwd=workspace_dir,
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode == 0:
                return True, "Numeric oracle passed."
            else:
                return False, f"Numeric oracle failed: {result.stderr}"
        except subprocess.TimeoutExpired:
            return False, "Numeric oracle timed out."
        except Exception as e:
            return False, f"Numeric oracle error: {e}"
            
    if oracle_type == "symbolic":
        try:
            result = subprocess.run(
                ["python3", "-c", f"import sympy\n{oracle_spec}"],
                cwd=workspace_dir,
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode == 0:
                return True, "Symbolic oracle passed."
            else:
                return False, f"Symbolic oracle failed: {result.stderr}"
        except Exception as e:
            return False, f"Symbolic oracle error: {e}"
            
    if oracle_type == "checker_model":
        # Handled by the judge externally
        return None, "Defer to checker_model"
        
    return False, f"Unknown oracle type: {oracle_type}"
