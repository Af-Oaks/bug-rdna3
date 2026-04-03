import re
import networkx as nx
import logging

logging.basicConfig(level=logging.INFO, format='%(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Heurística RDNA 3: Latência de dependência (em ciclos/instruções)
LATENCY_MAP = {
    'v_mul_f32': 5,
    'v_add_f32': 5,
    'global_load_dword': 12  # Simplificação de latência de L1/L0
}

def build_dependency_dag_and_analyze(isa_lines):
    """
    Reconstrói o DAG a partir do código linear e analisa a eficiência do agendamento.
    """
    G = nx.DiGraph()
    
    # Rastreio de qual nó (linha de instrução) escreveu pela última vez em um registrador
    last_writer = {}
    
    re_instruction = re.compile(r"^([a-z0-9_]+)\s+([vsc]\d+)(?:,\s*(.*))?")
    re_regs = re.compile(r"([vs]\d+)")

    # 1. Construção do Grafo (DAG)
    for i, line in enumerate(isa_lines):
        match = re_instruction.match(line.strip())
        if not match: continue
        
        opcode = match.group(1)
        dst_reg = match.group(2)
        operands_str = match.group(3) if match.group(3) else ""
        
        src_regs = re_regs.findall(operands_str)
        
        # Adiciona o nó representando a instrução
        G.add_node(i, opcode=opcode, dst=dst_reg, line=line.strip())
        
        # Cria as arestas direcionadas (RAW Hazards) dos produtores para este consumidor
        for src in src_regs:
            if src in last_writer:
                producer_idx = last_writer[src]
                latency = LATENCY_MAP.get(G.nodes[producer_idx]['opcode'], 1)
                G.add_edge(producer_idx, i, reg=src, latency_required=latency)
                
        # Atualiza quem é o dono atual do registrador de destino
        last_writer[dst_reg] = i

    # 2. Análise da Reordenação (Scheduler Displacement & Stall Detection)
    # Vamos verificar todas as arestas de dependência e ver se o agendador 
    # conseguiu espaçá-las o suficiente para esconder a latência de hardware.
    
    stalls_injetados = 0
    
    for producer, consumer, edge_data in G.edges(data=True):
        distancia_agendada = consumer - producer
        latencia_necessaria = edge_data['latency_required']
        reg = edge_data['reg']
        
        producer_opcode = G.nodes[producer]['opcode']
        consumer_opcode = G.nodes[consumer]['opcode']
        
        # O cálculo matemático de ocultação de latência:
        # \Delta_{cycles} = Pos_{consumer} - Pos_{producer}
        delta_cycles = distancia_agendada
        
        if delta_cycles < latencia_necessaria:
            # O agendador FALHOU em separar as instruções o suficiente.
            # O hardware precisará engolir um Stall (bolha no pipeline).
            logger.warning(
                f"⚠️ PERDA DE DESEMPENHO (Stall Iminente): "
                f"L{producer} ({producer_opcode}) -> L{consumer} ({consumer_opcode}) via {reg}. "
                f"Espaçamento: {delta_cycles} instrs. Latência exigida: {latencia_necessaria} instrs."
            )
            stalls_injetados += (latencia_necessaria - delta_cycles)
            
            # Se fosse no RDNA 3, o compilador seria forçado a injetar um s_delay_alu aqui.
            # Se for RDNA 2, o próprio silício vai travar (Hardware Interlock).
        else:
            logger.debug(
                f"✅ Latência Oculta com Sucesso: L{producer} -> L{consumer}. "
                f"Distância: {delta_cycles} >= {latencia_necessaria}"
            )

    logger.info(f"Análise do DAG concluída. Ciclos de Stall Teóricos Acumulados: {stalls_injetados}")
    return G

# --- Exemplo Simulado ---
# Note como o v_add está colado no global_load, sem NENHUMA instrução útil no meio
# para esconder a latência de memória. O Agendador não conseguiu fazer seu trabalho.
exemplo_pos_scheduler = [
    "global_load_dword v0, v1, s0", # Produz v0 (Latência alta, ex: 12)
    "v_mul_f32 v2, v3, v4",         # Instrução independente (Ocupa 1 ciclo)
    "v_add_f32 v5, v0, v2"          # Consome v0. Distância física = 2. Faltam 10 ciclos!
]

grafo = build_dependency_dag_and_analyze(exemplo_pos_scheduler)