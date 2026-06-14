---
stepsCompleted: [1, 2, 3, 4]
inputDocuments: []
session_topic: 'Redesenhar o Pulse para ser real, operável e útil'
session_goals: 'Definir arquitetura de execução, UX de configuração e MVP com caso de uso de resumo de newsletters'
selected_approach: 'ai-recommended'
techniques_used: ['Five Whys', 'Dream Fusion Laboratory', 'Constraint Mapping']
ideas_generated: [13]
session_active: false
workflow_completed: true
context_file: ''
---

# Brainstorming Session Results

**Facilitator:** Fred
**Date:** 2026-06-14

---

## Session Overview

**Topic:** Redesenhar o Pulse para ser real, operável e útil
**Goals:** Definir arquitetura de execução, UX de configuração e MVP com caso de uso de resumo de newsletters

### Session Setup

Problema identificado em três camadas:
1. Implementação incompleta — Pulse existe como casca (PULSE.md, pulse-config.yaml, --pulse flag) mas sem motor real
2. Operação indefinida — não está claro como iniciar, agendar e manter o Pulse rodando
3. Caso de uso concreto: receber todo dia um resumo de emails de newsletter

---

## Technique Selection

**Approach:** AI-Recommended Techniques

**Recommended Techniques:**
- **Five Whys:** Diagnóstico da raiz — por que o Pulse nunca foi implementado corretamente
- **Dream Fusion Laboratory:** Idealização — começar com o Pulse impossível e fazer engenharia reversa até o viável
- **Constraint Mapping:** Aterramento — separar restrições reais das imaginárias para definir o MVP

**AI Rationale:** Sessão de redesign completo exigia primeiro entender o bloqueio histórico, depois sonhar sem limitações, e por fim aterrar na realidade com restrições concretas.

---

## Technique Execution Results

### Five Whys — Diagnóstico da Raiz

**Cadeia causal descoberta:**
1. O Pulse foi priorizado depois porque outras features eram mais urgentes no início
2. A maioria das demandas do Pulse dependia de outros conectores funcionando (Gmail, Calendar, web)
3. A ordem foi uma escolha consciente: primeiro os conectores, depois o motor
4. A casca existente (--pulse, PULSE.md) foi criada antes de saber como o sistema todo funcionaria
5. **Raiz:** A estrutura atual do Pulse pode não ser adequada — temos liberdade para redesenhar do zero

**Breakthrough:** Fred confirmou que as estruturas existentes do Pulse não são sagradas e podem ser completamente revisadas.

---

### Dream Fusion Laboratory — Visão Ideal do Pulse

**[Execução #1]: Event-Free Activator**
*Concept:* Pulse resolve o problema de "não tem evento". Monitora o mundo e age proativamente — emails, preços, sensores, dados de treino — sem precisar que o usuário dispare nada.
*Novelty:* Não é um agendador de tarefas. É um observador inteligente que decide o que é urgente agora vs. o que vai para o resumo.

**[Execução #2]: Criticality Routing**
*Concept:* Dois canais: coisas críticas notificam na hora, coisas normais se acumulam para entrega no horário ideal. O Pulse decide o canal baseado no contexto do sanctum.
*Novelty:* O Pulse decide o canal, não o usuário — baseado em mapeamentos de "o que é crítico nesse período".

**[Execução #3]: Adaptive Scheduler**
*Concept:* Pulse aprende padrões sem configuração explícita. Emails chegam todo dia às 10h → ele internaliza isso. Se rodar às 10:01 e os emails não chegaram todos, ele reagenda sozinho.
*Novelty:* Backoff inteligente com aprendizado de padrão temporal — não é cron fixo.

**[Execução #4]: Dual Operating Modes**
*Concept:* Modo Intent ("quero receber sempre um resumo") onde Pulse decide o timing autonomamente. Modo Fixed ("às 10:00 sempre") onde o usuário controla explicitamente.
*Novelty:* O operador escolhe o quanto de autonomia quer delegar. Mesma tarefa, duas filosofias de controle.

**[Execução #5]: Natural Language → Config Compiler**
*Concept:* YANA age como tradutor — o usuário descreve em linguagem natural o que quer, e a YANA gera/atualiza a configuração do Pulse. O arquivo de config é output, não input primário.
*Novelty:* Reduz barreira de entrada a zero. Usuário avançado pode editar YAML direto; usuário normal só conversa.

**[Execução #6]: Result-Driven Criticality**
*Concept:* A tarefa define o que fazer, não o que é urgente. YANA avalia o resultado usando o contexto do sanctum e decide o canal de entrega.
*Novelty:* Urgência é inteligência, não configuração. O mesmo resultado pode ser urgente numa semana e irrelevante na seguinte.

**[Execução #7]: Pulse Task Schema v1**
*Concept:* Uma tarefa Pulse tem três campos: `observe` (o que monitorar e com que fonte), `schedule` (fixo ou adaptativo), `deliver` (o que fazer com o resultado).
*Novelty:* Simples o suficiente para ser gerado por linguagem natural, mas estruturado o suficiente para execução confiável.

**[Execução #8]: Pulse as Separate Service**
*Concept:* Pulse não é uma flag da YANA — é um servidor independente. Pode rodar em Windows hoje, na cloud amanhã, ou em múltiplos lugares simultaneamente.
*Novelty:* Desacopla o motor de execução da interface de conversa. A YANA "fala" com o Pulse via protocolo, não internamente.

**[Execução #9]: Distributed Pulse Problem**
*Concept:* Se Pulse roda em cloud E no Windows, qual executa? Precisa de coordenação — um nó líder, ou tarefas particionadas. Problema real de sistemas distribuídos, não de conectividade.
*Novelty:* A portabilidade cria um problema de orquestração distribuída que o design precisa antecipar, mesmo que hoje seja single-node.

**[Execução #10]: Pulse as Cron-like Executable**
*Concept:* Pulse é um executável independente com loop de agendamento interno — roda como processo no Windows hoje, empacota como container amanhã, ou vai como sidecar junto de uma instância YANA distribuída.
*Novelty:* A unidade de deploy é o Pulse, não a YANA. Segue o padrão sidecar — cada YANA pode ter seu Pulse acoplado.

**[Execução #11]: Session as Pulse Inbox**
*Concept:* Pulse entrega resultados numa sessão YANA. Se há sessão ativa, entrega ali. Se não há, cria uma sessão "Pulse" centralizada que acumula todas as notificações.
*Novelty:* Sem notificação push, sem email, sem sistema externo. A própria conversa com YANA é o canal de entrega.

**[Execução #12]: Pulse Session as Persistent Log**
*Concept:* Sessões criadas pelo Pulse são sessões normais — entram no histórico, alimentam o sanctum como qualquer conversa.
*Novelty:* Os resultados do Pulse ficam disponíveis para contexto futuro. YANA pode aprender com o histórico de execuções.

**[Execução #13]: YANA as Sole Pulse Operator**
*Concept:* O usuário nunca toca na configuração do Pulse diretamente. Toda criação, edição e remoção de tarefas passa pela YANA via linguagem natural.
*Novelty:* Elimina a necessidade de documentar formato de config para o usuário. O contrato de configuração é interno — entre YANA e Pulse.

---

### Constraint Mapping — Restrições Reais vs. Imaginárias

| Restrição | Classificação | Estratégia MVP |
|---|---|---|
| Contenção de recursos (múltiplos crons simultâneos) | Real — gerenciável | Fila de execução simples |
| Starvation de tarefas | Imaginária para MVP | Ignorar — poucas tarefas |
| Falha silenciosa | Real — crítica | Log + entrega de erro na sessão |
| Backoff/retry | Real | 3 tentativas, intervalo exponencial |
| Coordenação distribuída | Real — futura | Não abordar no MVP |

---

## Idea Organization and Prioritization

### Temas Identificados

**Tema 1 — Arquitetura & Motor de Execução** *(fundação)*
Pulse como executável independente, cron-like, containerizável, padrão sidecar.

**Tema 2 — Modelo de Tarefa & Configuração** *(fundação)*
Schema `observe + schedule + deliver`, YANA como único operador, linguagem natural como interface, modos Fixed e Intent.

**Tema 3 — Inteligência & Adaptação** *(diferencial)*
Observador proativo, scheduler adaptativo, urgência calculada pelo resultado + sanctum, criticality routing.

**Tema 4 — Entrega & Persistência** *(diferencial)*
Sessão YANA como inbox, sessões Pulse no histórico normal, alimentando o sanctum.

### Priorização

**Alta prioridade (MVP):** Temas 1 e 2 — sem motor e sem schema de tarefa, nada funciona
**Média prioridade (pós-MVP):** Temas 3 e 4 — tornam o Pulse inteligente e integrado

---

## Action Plans

### Prioridade 1 — Motor de Execução *(desbloqueia tudo)*

1. Criar `orchestrator/pulse/runner.py` — loop cron-like independente com APScheduler
2. Definir contrato de execução: carrega tarefas do config, executa, registra resultado
3. Implementar backoff/retry básico (3 tentativas, intervalo exponencial)
4. Logging de falha que entrega resultado na sessão Pulse
5. Entry point próprio: `python -m pulse` (separado do `main.py`)

### Prioridade 2 — Schema de Tarefa & Configuração *(define o contrato)*

1. Definir schema YAML de tarefa: `observe`, `schedule`, `deliver`
2. Criar `orchestrator/pulse/config_loader.py` — lê e valida tarefas
3. Implementar modo Fixed (horário explícito no config)
4. Adicionar capacidade à YANA de criar/editar tarefas via conversa natural

### Prioridade 3 — Entrega via Sessão *(torna o MVP utilizável)*

1. Pulse cria sessão YANA quando não há sessão ativa
2. Resultados das tarefas entram como mensagens nessa sessão
3. Sessão fica no histórico normal — alimenta o sanctum

### Prioridade 4 — Inteligência Adaptativa *(diferencial, pós-MVP)*

1. Scheduler aprende padrões de horário por observação
2. Urgência calculada pela YANA com base no resultado + sanctum
3. Modo Intent (YANA decide o timing autonomamente)

### Quick Win

Com Gmail connector pronto + Prioridades 1 e 2 implementadas: tarefa Fixed que roda às 10h, busca emails de newsletter e entrega o resumo na sessão YANA.

---

## Session Summary and Insights

**Total de ideias geradas:** 13
**Técnicas utilizadas:** Five Whys, Dream Fusion Laboratory, Constraint Mapping

**Key Achievements:**
- Diagnóstico completo de por que o Pulse nunca foi implementado
- Liberdade total confirmada para redesenhar a estrutura existente
- Visão clara do Pulse ideal com casos de uso concretos
- Arquitetura MVP bem delineada e priorizada

**Breakthrough Moments:**
- Fred confirmou que as estruturas existentes (--pulse, PULSE.md, pulse-config.yaml) podem ser completamente revisadas
- Pulse é fundamentalmente diferente de um scheduler: é um observador proativo que decide urgência com inteligência
- YANA como único operador elimina a necessidade de o usuário entender o formato de configuração
- Padrão sidecar/container antecipa portabilidade sem over-engineering o MVP

**Session Reflections:**
A sessão revelou que o Pulse não é uma feature faltando implementação — é uma feature que precisa ser redefenida. O caminho mais curto para o MVP é construir o motor e o schema primeiro, sem se preocupar com inteligência adaptativa, e validar com o caso de uso concreto de resumo de newsletters via Gmail.
