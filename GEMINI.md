Investigação de Errata de Silício na Arquitetura AMD RDNA3 (GFX11)

Visão Geral e Hardware:
O objetivo deste projeto é investigar, isolar e contornar possíveis bugs físicos e limitações de design na arquitetura RDNA3 (especificamente na GPU AMD Radeon RX 7800 XT - matriz Navi 32, ISA GFX1101) rodando em ambiente Linux. O foco central está na discrepância entre a vazão teórica (TFLOPS) e a realizada, suspeita de ser causada por falhas no escalonamento de hardware e na emissão de instruções.

Hipóteses Microarquiteturais a Serem Testadas:

    O Perigo s_delay_alu: O escalonador de hardware da RDNA3 parece incapaz de rastrear dependências de dados de forma eficiente no novo pipeline dual-issue, forçando compiladores (Mesa ACO e AMD LLVM) a inserir agressivamente ciclos de estol via software (s_delay_alu). Queremos modificar o compilador para remover essas proteções e observar os Wave Hangs e corrupções.

    Fragilidade do VOPD (Dual-Issue): A capacidade de executar duas instruções VALU simultaneamente (Wave32) exige condições quase perfeitas (ausência de conflitos de banco de VGPRs). Queremos forçar a compilação com e sem VOPD para medir a penalidade real.

    Violações de Memória (MEMVIOL): O tratamento de acessos OOB (Out-of-Bounds) na GFX11 causa falhas de segmentação severas (VM Faults) que exigem reset da GPU (amdgpu.gpu_recovery=1).

Ferramental e Stack Tecnológico:

    API Gráfica: Vulkan (via representação intermediária SPIR-V).

    Driver de Vídeo: RADV (Mesa 3D) executado em userspace (UMD).

    Compiladores Alvo: Valve ACO (nativo do RADV, focado em latência e jogos) e AMD LLVM (compilador proprietário, focado em LLVM IR).

    Framework de Teste: Fossilize (Valve) para sintetizar ambientes Vulkan (PSOs) e dissecar SPIR-V para ISA nativa offline (fossilize-disasm).

    Observabilidade de Baixo Nível: Ferramenta AMD UMR (User Mode Register Debugger) para extrair o estado das Waves, conteúdo de registradores (SGPRs/VGPRs) e o PC (Program Counter) exato no momento de um travamento da GPU. Variáveis de ambiente como RADV_DEBUG=shaders,hang,nocache.

## Estrutura do Projeto

O projeto foi reestruturado para maior organização:

*   **`scripts/`**: Contém todos os scripts utilitários.
    *   `setup_env.sh`: Inicializa as dependências, baixa e compila isoladamente o Mesa RADV e o Fossilize.
    *   `gpu_test_runner.sh`: Padronizador de testes com injeção de variáveis RADV e dumps UMR automáticos.
    *   `test_fossilize.sh`: Disseca e compara a compilação do ISA via Fossilize para ACO e LLVM.
*   **`src/`** (ou shaders): Código-fonte e compute shaders (ex: `test_vopd.comp`) para validação das hipóteses.
*   **`lib/`**: Repositórios clonados (Mesa, Fossilize) isolados do host (ignorados no Git).
*   **`build/`**: Artefatos de compilação e o prefixo de instalação (install) que detém a versão customizada do RADV (ignorados no Git).
*   **`logs/`**: Métricas de execução, logs standard e dumps crús do UMR em caso de crash (ignorados no Git).