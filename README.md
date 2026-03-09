# Investigação de Errata de Silício na Arquitetura AMD RDNA3 (GFX11)

Este projeto tem como objetivo investigar, isolar e contornar possíveis bugs físicos e limitações de design na arquitetura RDNA3, focando em problemas de escalonamento (s_delay_alu), perigos de emissão dupla (VOPD) e violações de memória severas.

## Estrutura de Pastas e Ferramental (Atualizado)

Todo o ferramental é mantido de forma isolada neste repositório para não poluir o sistema operacional do host.

- `scripts/setup_env.sh`: Script principal para configuração do ambiente de desenvolvimento. Instala dependências do sistema e compila o driver RADV (Mesa) em conjunto com a ferramenta Fossilize a partir das fontes.
- `scripts/gpu_test_runner.sh`: Utilitário para padronizar as execuções. Permite alternar os compiladores (Valve ACO ou AMD LLVM), habilitar VOPD ou wave32 e gera logs robustos que incluem uso de memória (VRAM) e despejos UMR em caso de travamentos.
- `scripts/test_fossilize.sh`: Script utilitário para compilar shaders para SPIR-V usando `glslangValidator` e extrair o código de máquina (ISA) via `fossilize-disasm` simultaneamente para os compialdores ACO e LLVM.
- `src/`: Diretório contendo os shaders (ex: `test_vopd.comp`) para sintetização de comportamento.
- `lib/`: (Gerado) Contém os códigos fonte brutos das dependências como o repositório Mesa (RADV) e o Fossilize.
- `build/`: (Gerado) Contém os artefatos de build intermediários e a pasta `build/install/`, que atua como o ambiente isolado (prefixo de instalação) contendo as bibliotecas dinâmicas do RADV e binários do Fossilize, além do arquivo JSON ICD.
- `logs/`: (Gerado) Pasta onde os logs detalhados e versionados são salvos contendo estatísticas da GPU, UMR memory dumps e os stdouts/stderrs de cada execução de teste.

## Instalação e Preparação

Clone o repositório e execute o script de instalação isolado:

```bash
./scripts/setup_env.sh
```

## Executando Testes de Escalonamento

Para injetar as variáveis de ambiente e alternar entre os compiladores LLVM e ACO, utilize o test runner base:

```bash
./scripts/gpu_test_runner.sh --compiler LLVM --vopd --debug-crash -- <comando_teste>
```

Para dissecar shaders específicos através do Fossilize:

```bash
./scripts/test_fossilize.sh src/test_vopd.comp
```

A saída de compilação ISA para ambos os backends será colocada ao lado do seu arquivo fonte (`test_vopd_aco.asm` e `test_vopd_llvm.asm`).
