import argparse
import json
import subprocess
import time
import os
import shutil

def run_benchmark(spec_path, models):
    print(f"Starting benchmark for spec: {spec_path}")
    print(f"Models to evaluate: {models}")
    
    with open(spec_path, 'r') as f:
        spec = json.load(f)
        
    results = {}
    
    for model in models:
        print(f"\n{'='*50}\nEvaluating model: {model}\n{'='*50}")
        # Update spec for this model
        spec["swarm_provider"] = "ollama"
        spec["model"] = model
        
        # Write temporary spec
        temp_spec = "temp_run.json"
        with open(temp_spec, 'w') as f:
            json.dump(spec, f)
            
        # Clear previous state
        if os.path.exists(".proximity_swarm"):
            shutil.rmtree(".proximity_swarm")
            
        start_time = time.time()
        
        try:
            # Run headless
            process = subprocess.Popen(
                ["python3", "supervisor.py", "--run-spec", temp_spec, "--gc-workspace"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            
            # Wait for it to finish
            stdout, stderr = process.communicate()
            if process.returncode != 0:
                print(f"Supervisor failed with exit code {process.returncode}")
                print(f"STDOUT:\n{stdout}")
                print(f"STDERR:\n{stderr}")
            elif stderr:
                print(f"STDERR:\n{stderr}")
            
            elapsed = time.time() - start_time
            
            # Read artifacts
            try:
                import glob
                graph_dir = os.path.join(".proximity_swarm", "graph")
                snapshot_file = os.path.join(graph_dir, "snapshot.json")
                run_files = sorted(glob.glob(os.path.join(graph_dir, "run_*.json")))
                
                graph_data = {}
                if run_files:
                    with open(run_files[-1], 'r') as rf:
                        graph_data = json.load(rf)
                elif os.path.exists(snapshot_file):
                    with open(snapshot_file, 'r') as sf:
                        snap = json.load(sf)
                        graph_data = {"nodes": snap.get("nodes", {})}
                        try:
                            import logic_graph
                            graph_data["validated_path"] = logic_graph.validated_path_to_goal()
                        except Exception:
                            graph_data["validated_path"] = []
                else:
                    import logic_graph
                    graph_data = logic_graph.to_artifact_json()
                    
                nodes = graph_data.get("nodes", {})
                validated_path = graph_data.get("validated_path") or []
            except Exception as e:
                nodes = {}
                validated_path = []
                print(f"Error reading logic graph: {e}")
                
            validated_steps = sum(1 for n in nodes.values() if n.get("status") == "validated")
            dead_ends = sum(1 for n in nodes.values() if n.get("status") == "refuted")
            
            results[model] = {
                "time_seconds": round(elapsed, 2),
                "total_nodes": len(nodes),
                "validated_steps": validated_steps,
                "dead_ends": dead_ends,
                "success": len(validated_path) > 0,
                "path_length": len(validated_path)
            }
            
        except KeyboardInterrupt:
            print("Benchmark interrupted.")
            break
        except Exception as e:
            print(f"Error running model {model}: {e}")
            results[model] = {"error": str(e)}
        finally:
            if os.path.exists(temp_spec):
                os.remove(temp_spec)
                
    print("\n\n" + "="*50)
    print("BENCHMARK RESULTS")
    print("="*50)
    print(f"{'Model':<20} | {'Success':<8} | {'Nodes':<6} | {'Valid':<6} | {'Dead':<6} | {'Time (s)':<8}")
    print("-" * 65)
    for model, res in results.items():
        if "error" in res:
            print(f"{model:<20} | ERROR: {res['error']}")
        else:
            success = "Yes" if res["success"] else "No"
            print(f"{model:<20} | {success:<8} | {res['total_nodes']:<6} | {res['validated_steps']:<6} | {res['dead_ends']:<6} | {res['time_seconds']:<8}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Cross-model benchmark driver")
    parser.add_argument("--spec", required=True, help="Path to run spec JSON")
    parser.add_argument("--models", required=True, help="Comma-separated list of local models")
    args = parser.parse_args()
    
    models_list = [m.strip() for m in args.models.split(",")]
    run_benchmark(args.spec, models_list)
