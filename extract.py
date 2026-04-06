import re
import json
import random
from pathlib import Path

def extract_deterministic_shaders(log_path: str, output_json: str, seed: int = 42):
    log_file = Path(log_path)
    if not log_file.exists():
        raise FileNotFoundError(f"File not found: {log_path}")

    # Using your original regex patterns that match your Mesa build's output
    re_shader_start = re.compile(r'shader:\s*MESA_SHADER_')
    re_blake3 = re.compile(r'source_blake3:\s*\{(.*?)\}')
    
    # ---------------------------------------------------------
    # PASS 1: Profiling & Metric Gathering (Low Memory)
    # ---------------------------------------------------------
    print(f"[Pass 1] Streaming {log_path} to profile metrics (Memory Safe)...")
    
    shaders = {}
    current_hash = None
    
    with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
        for line in f:
            # Detect the start of a new shader block
            if re_shader_start.search(line):
                current_hash = None # Reset until we find its blake3 hash
                continue
                
            if current_hash is None:
                hash_match = re_blake3.search(line)
                if hash_match:
                    raw_hash = hash_match.group(1)
                    # Clean up the hash format like your original script did
                    current_hash = raw_hash.replace(', ', '_').replace('0x', '')
                    
                    if current_hash not in shaders:
                        shaders[current_hash] = {
                            "blake3_hash": current_hash,
                            "v_dual_instructions": 0,
                            "s_delay_alu_instructions": 0
                        }
                continue
            
            # Fast substring checks (bypassing regex for speed)
            if "v_dual_" in line:
                shaders[current_hash]["v_dual_instructions"] += line.count("v_dual_")
            if "s_delay_alu" in line:
                shaders[current_hash]["s_delay_alu_instructions"] += line.count("s_delay_alu")

    shader_pool = list(shaders.values())
    print(f"Total unique shaders found: {len(shader_pool)}")
    
    if len(shader_pool) == 0:
        print("CRITICAL: Still no shaders found. Let's verify the text format manually.")
        return

    # ---------------------------------------------------------
    # SELECTION PHASE (Deterministic Sorting)
    # ---------------------------------------------------------
    final_selection_map = {} 
    
    # CATEGORY 1: Top 20 s_delay_alu
    shader_pool.sort(key=lambda x: (-x['s_delay_alu_instructions'], x['blake3_hash']))
    for s in shader_pool[:20]:
        final_selection_map[s['blake3_hash']] = 'top_s_delay_alu'
    shader_pool = shader_pool[20:]
    
    # CATEGORY 2: Top 20 v_dual_
    shader_pool.sort(key=lambda x: (-x['v_dual_instructions'], x['blake3_hash']))
    for s in shader_pool[:20]:
        final_selection_map[s['blake3_hash']] = 'top_v_dual'
    shader_pool = shader_pool[20:]
    
    # CATEGORY 3: 20 Random Baselines
    shader_pool.sort(key=lambda x: x['blake3_hash'])
    random.seed(seed)
    sample_size = min(20, len(shader_pool))
    for s in random.sample(shader_pool, sample_size):
        final_selection_map[s['blake3_hash']] = 'random_baseline'

    # ---------------------------------------------------------
    # PASS 2: Assembly Payload Extraction
    # ---------------------------------------------------------
    print(f"[Pass 2] Extracting raw ISA payloads for the selected shaders...")
    
    final_results = {h: {
        "blake3_hash": h,
        "category": final_selection_map[h],
        "metrics": shaders[h],
        "assembly_snippet": []
    } for h in final_selection_map}
    
    current_hash = None
    capture_active = False

    with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
        for line in f:
            if re_shader_start.search(line):
                capture_active = False
                current_hash = None
                
            if current_hash is None:
                hash_match = re_blake3.search(line)
                if hash_match:
                    raw_hash = hash_match.group(1)
                    current_hash = raw_hash.replace(', ', '_').replace('0x', '')
                    capture_active = current_hash in final_results
                    if capture_active:
                        final_results[current_hash]["assembly_snippet"].append(line)
                continue
            
            if capture_active:
                final_results[current_hash]["assembly_snippet"].append(line)

    # Clean up the output structure
    output_list = []
    for h, data in final_results.items():
        data["assembly_snippet"] = "".join(data["assembly_snippet"]).strip()
        metrics = data.pop("metrics")
        data["metrics"] = {
            "v_dual_instructions": metrics["v_dual_instructions"],
            "s_delay_alu_instructions": metrics["s_delay_alu_instructions"]
        }
        output_list.append(data)
        
    output_list.sort(key=lambda x: x['blake3_hash'])

    # ---------------------------------------------------------
    # FINALIZATION
    # ---------------------------------------------------------
    print(f"Sampling complete. Saving {len(output_list)} deterministic shaders to {output_json}...")
    with open(output_json, 'w', encoding='utf-8') as out_f:
        json.dump(output_list, out_f, indent=4)

if __name__ == "__main__":
    extract_deterministic_shaders(
        log_path="/home/methos/Documents/faculdade/TCC_bug_amd/isa_dumps/raw_dump.log", 
        output_json="rdna3_pipeline_samples.json",
        seed=42
    )