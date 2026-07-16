import re
import pandas as pd
from collections import defaultdict

def parse_aco_log_triage(log_file_path):
    shaders_data = []
    current_shader = {}
    isa_block = []
    in_isa = False

    # Expressões Regulares para as métricas críticas
    re_shader_start = re.compile(r"ACO shader: (.+)")
    re_vgpr = re.compile(r"VGPRS:\s+(\d+)")
    re_sgpr = re.compile(r"SGPRS:\s+(\d+)")
    re_spill = re.compile(r"Scratch:\s+(\d+)\s+bytes")
    re_occupancy = re.compile(r"Occupancy:\s+(\d+)\s+waves")

    with open(log_file_path, 'r') as f:
        for line in f:
            if match := re_shader_start.search(line):
                if current_shader:
                    # Finaliza o shader anterior e compila as estatísticas da ISA
                    analyze_isa_block(current_shader, isa_block)
                    shaders_data.append(current_shader)
                
                current_shader = {
                    'name': match.group(1),
                    'vgprs': 0, 'sgprs': 0, 'spill_bytes': 0, 'occupancy': 0,
                    'v_dual_count': 0, 's_nop_count': 0, 's_waitcnt_count': 0, 's_delay_alu_count': 0,
                    'total_instructions': 0
                }
                isa_block = []
                in_isa = True
            
            # Extração de Métricas Estáticas
            elif match := re_vgpr.search(line): current_shader['vgprs'] = int(match.group(1))
            elif match := re_sgpr.search(line): current_shader['sgprs'] = int(match.group(1))
            elif match := re_spill.search(line): current_shader['spill_bytes'] = int(match.group(1))
            elif match := re_occupancy.search(line): current_shader['occupancy'] = int(match.group(1))
            
            # Coleta da ISA
            elif in_isa and line.strip() != "":
                isa_block.append(line.strip())

    if current_shader:
        analyze_isa_block(current_shader, isa_block)
        shaders_data.append(current_shader)

    return pd.DataFrame(shaders_data)

def analyze_isa_block(shader_dict, isa_lines):
    for line in isa_lines:
        if line.startswith("v_dual_"): shader_dict['v_dual_count'] += 1
        elif line.startswith("s_nop"): shader_dict['s_nop_count'] += 1
        elif line.startswith("s_waitcnt"): shader_dict['s_waitcnt_count'] += 1
        elif line.startswith("s_delay_alu"): shader_dict['s_delay_alu_count'] += 1
        
        # Filtra linhas que não são instruções (labels, comentários)
        if re.match(r"^[vsc]_", line):
            shader_dict['total_instructions'] += 1




# --- Execução e Filtros ---
df = parse_aco_log_triage("aco_compiler_output.log")

# Adiciona colunas computadas
df['stall_ratio'] = (df['s_nop_count'] + df['s_waitcnt_count'] + df['s_delay_alu_count']) / df['total_instructions']
df['vopd_ratio'] = df['v_dual_count'] / df['total_instructions']

# Filtro 1: Encontrar os shaders com pior uso de stalls e baixo VOPD
worst_offenders = df[(df['stall_ratio'] > 0.15) & (df['vopd_ratio'] < 0.05)].sort_values(by='stall_ratio', ascending=False)

print("Top Shaders com Anomalias de Stall / VOPD Ocioso:")
print(worst_offenders[['name', 'stall_ratio', 'vopd_ratio', 'occupancy', 'spill_bytes']].head(10))