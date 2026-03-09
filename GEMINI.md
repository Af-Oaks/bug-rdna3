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

## Estrutura do Projeto e Fluxo de Compilação Customizada

O projeto foi reestruturado para suportar o desenvolvimento isolado da nossa própria versão do compilador (ACO Custom):

*   **`custom_mesa_layer/`**: Contém estritamente os arquivos fonte modificados do nosso compilador ACO. Esta pasta espelha o caminho do Mesa (ex: `custom_mesa_layer/src/amd/compiler/`). As modificações na heurística de hardware (remoção de s_delay_alu, forçar VOPD) ocorrerão **aqui**.
*   **`scripts/`**: Contém todos os scripts utilitários.
    *   `setup_env.sh`: Inicializa dependências e compila o driver RADV **Original** (`build/install`).
    *   `build_custom_aco.sh`: Sincroniza o `custom_mesa_layer` para dentro da árvore do Mesa e compila nossa versão isolada do driver para `build/install_custom`.
    *   `gpu_test_runner.sh`: Padronizador de execução aceitando `--compiler [ACO_ORIGINAL|ACO_CUSTOM|LLVM]`.
    *   `test_fossilize.sh`: Extrai e compara o Assembly (ISA) de todas as 3 versões de compiladores e gera um arquivo de diff summary.
*   **`src/`** (Testes): Cada teste de hardware deve possuir sua própria subpasta auto-contida (ex: `src/test_vopd/test_vopd.comp`). Todos os artefatos de compilação (`.spv`, `.foz`, `.asm`, `.diff`) correspondentes a essa execução serão salvos ao lado do código fonte, garantindo limpeza visual e rastreabilidade.
*   **`lib/`**: Repositórios base clonados (`mesa`, `Fossilize`) (Ignorado no Git).
*   **`build/`**: Artefatos intermediários e os prefixos `install/` e `install_custom/` (Ignorado no Git).
*   **`logs/`**: Métricas de telemetria e core dumps (Ignorado no Git).

## Executando Experimentos e Modificando o Compilador

**1. Alterando o Compilador:**
Modifique livremente os arquivos em `custom_mesa_layer/src/amd/compiler/` (ex: `aco_scheduler.cpp`).
Após salvar, aplique a nova versão na máquina compilando o seu driver customizado:

```bash
./scripts/build_custom_aco.sh
```

**2. Inspecionando o Comportamento (Diff):**
Para dissecar shaders e observar a diferença entre o escalonamento Original, o da AMD (LLVM) e o seu Customizado:

```bash
./scripts/test_fossilize.sh src/test_vopd/test_vopd.comp
```
O script gerará o arquivo `src/test_vopd/test_vopd_summary.diff` contendo exatamente quais instruções a sua modificação no compilador adicionou ou removeu em relação ao hardware de fábrica.