# RevivaX - MVP (Minimum Viable Product)

## 1. Visão do Produto

RevivaX é um sistema avançado de recuperação de arquivos apagados com
painel administrativo via navegador. Ele combina varredura profunda por
assinatura binária (file carving) com monitoramento inteligente de
discos (SMART), oferecendo recuperação real e diagnóstico completo do
hardware.

------------------------------------------------------------------------

## 2. Problema

Usuários comuns e técnicos enfrentam:

-   Perda acidental de arquivos importantes
-   Formatação indevida de discos
-   Falhas inesperadas de HD/SSD
-   Falta de ferramentas simples com interface amigável
-   Ausência de diagnóstico integrado de saúde do disco

------------------------------------------------------------------------

## 3. Público-Alvo

-   Técnicos de informática
-   Profissionais de TI
-   Usuários avançados
-   Pequenas assistências técnicas
-   Profissionais forenses digitais

------------------------------------------------------------------------

## 4. Proposta de Valor

-   Recuperação profunda por assinatura
-   Interface simples via navegador
-   Monitoramento SMART integrado
-   Modo forense (somente leitura)
-   Executável standalone para Windows/Linux

------------------------------------------------------------------------

## 5. Stack Tecnológica

### Backend

-   Python 3.11+
-   Flask ou FastAPI
-   pytsk3 (The Sleuth Kit)
-   psutil
-   pySMART
-   subprocess (smartctl)

### Frontend

-   HTML
-   TailwindCSS
-   JavaScript

### Empacotamento

-   PyInstaller

------------------------------------------------------------------------

## 6. Arquitetura do Sistema

RevivaX/ │ ├── core/ │ ├── scanner.py │ ├── carver.py │ ├── recovery.py
│ └── smart_monitor.py │ ├── web/ │ ├── app.py │ ├── templates/ │ └──
static/ │ ├── logs/ ├── recovered/ └── main.py

------------------------------------------------------------------------

## 7. Funcionalidades do MVP

### 7.1 Recovery Engine

-   Varredura rápida
-   Varredura profunda por assinatura
-   Recuperação de:
    -   JPG
    -   PNG
    -   MP4
    -   PDF
-   Seleção de disco ou partição
-   Barra de progresso

### 7.2 Disk Intelligence

-   Temperatura do disco
-   Espaço total/usado/livre
-   Status SMART
-   Tempo estimado de vida útil
-   Tempo de atividade

### 7.3 Painel Web

-   Dashboard de discos
-   Botão "Iniciar varredura"
-   Lista de arquivos encontrados
-   Filtro por tipo
-   Download do arquivo recuperado
-   Logs técnicos

------------------------------------------------------------------------

## 8. Diferenciais Técnicos

-   File Carving real por assinatura binária
-   Leitura em modo somente leitura
-   Estimativa de chance de recuperação
-   Classificação automática por tipo
-   Sistema modular escalável

------------------------------------------------------------------------

## 9. Roadmap de Desenvolvimento

### Fase 1

-   Estrutura base do projeto
-   Scanner simples
-   Interface básica

### Fase 2

-   Implementação de file carving
-   Integração SMART
-   Logs detalhados

### Fase 3

-   Otimização de performance
-   Empacotamento executável
-   Testes em múltiplos sistemas

------------------------------------------------------------------------

## 10. Empacotamento Final

pip install pyinstaller

pyinstaller --onefile --noconsole main.py

Saída: dist/RevivaX.exe

------------------------------------------------------------------------

## 11. Visão Futura

-   Versão Pro com recuperação avançada de sistemas de arquivos
-   Suporte a RAID
-   Versão Enterprise com relatórios forenses completos
-   Sistema SaaS híbrido

------------------------------------------------------------------------

RevivaX --- Dando vida novamente aos seus dados.
