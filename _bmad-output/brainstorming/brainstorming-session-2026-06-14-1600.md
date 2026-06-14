---
stepsCompleted: [1, 2, 3]
inputDocuments: []
session_topic: 'Sanctum: o que é e por que o editor trava ao fechar'
session_goals: 'Entender o conceito de sanctum e diagnosticar o problema de travamento no fechamento'
selected_approach: 'ai-recommended'
techniques_used: ['Analogical Thinking', 'Five Whys', 'Reverse Brainstorming']
ideas_generated: []
context_file: ''
---

# Brainstorming Session Results

**Facilitator:** Fred
**Date:** 2026-06-14

## Session Overview

**Topic:** Sanctum — o que é e por que o editor trava ao fechar
**Goals:** Entender o conceito de sanctum e gerar hipóteses para o travamento no fechamento de sessão

### Session Setup

_Sessão iniciada com dois eixos: conceitual (o que é sanctum) e diagnóstico (bug de travamento)._

## Technique Selection

**Approach:** AI-Recommended Techniques
**Analysis Context:** Sanctum concept + editor freeze bug with focus on mental model clarity and root cause diagnosis

**Recommended Techniques:**

- **Analogical Thinking:** Construir modelo mental sólido do sanctum via analogias — revela assunções escondidas sobre o design
- **Five Whys:** Furar até a causa raiz do editor travar no fechamento
- **Reverse Brainstorming:** "Como garantir que o editor trave?" — inverte o problema, confirma hipóteses e revela o que Five Whys pode ter perdido

**AI Rationale:** Dois eixos distintos (conceitual + diagnóstico) pedem técnicas complementares. Analogical Thinking alinha o modelo mental antes de entrar no bug. Five Whys estrutura o diagnóstico. Reverse Brainstorming valida e amplia as hipóteses via inversão.

---

## Technique Execution Results

### Analogical Thinking + Exploração Arquitetural

**Analogia fundação:** O sanctum é como o save file de um RPG — carregado no boot para que o personagem "seja ele mesmo" de novo.

**Ideas Generated:**

**[Conceitual #1]: Bayesian Memory Block**
*Concept:* Cada memória tem um confidence score (0–1). Sobe com evidências consistentes, desce com contradições. Fato novo não sobrescreve — desafia o score existente. YANA não "sabe" — ela tem graus de crença atualizados por sessão.
*Novelty:* Distingue certeza de achismo. Permite que YANA pergunte "você tá mais estressado que o normal?" baseado em delta, não em impressão.

**[Padrão #2]: Baseline Pessoal Calibrado**
*Concept:* YANA não mede em escala absoluta — mede desvio do normal do dono. Xingamento no Fred carioca = ruído de fundo. Frequência 3x acima do baseline = sinal real.
*Novelty:* Evita falso positivo em pessoas naturalmente expressivas. O detector é relativo ao dono, não universal.

**[Arquitetura #3]: Sensor Layer → Memory Layer**
*Concept:* Sensores coletam evidência bruta (Garmin FC, PS5 playtime, localização, geladeira via HA). Memory layer interpreta e atualiza confidence scores. YANA nunca age no sensor — age no padrão inferido.
*Novelty:* Separação limpa entre coleta e interpretação. Sensor errado não corrompe memória — apenas não contribui pro score.

**[Tipagem #4]: Fato vs Padrão como tipos distintos**
*Concept:* Fatos são discretos, verificáveis, declarados explicitamente ("Fred usa Garmin"). Padrões são inferidos, probabilísticos, emergem de N observações ao longo do tempo.
*Novelty:* O upgrade fato→padrão requer threshold de evidências + confirmação contextual. Padrão temporário tem decaimento — não vira verdade permanente.

**[Fix #5]: Close sem bloqueio**
*Concept:* Remover chamada LLM síncrona do sanctum_writer do fluxo de close. Sessão fecha limpo. Raw session log (arquivo) continua sendo escrito — nada irrecuperável se perde.
*Novelty:* Separa o que é I/O rápido (log) do que é processamento lento (extração LLM). Close nunca trava.

**[Arquitetura #6]: Memory Tool Avaliada, Não Reinventada**
*Concept:* Em vez de construir memória do zero, avaliar ferramentas existentes (Mem0, Zep, e outras) que já resolvem storage + retrieval + extração semântica. Sanctum markdown vira legado gradual.
*Novelty:* Critério de avaliação inclui qualidade da ferramenta — não é só "usar qualquer coisa". Decisão de qual ferramenta fica em aberto até avaliação.

---

## Decisões e Next Steps

### Decisão imediata
- **Remover sanctum_writer do fluxo de close** — sessão fecha sem bloqueio. Raw log já é suficiente para não perder contexto.

### Backlog arquitetural
- **Avaliar ferramentas de memória** (Mem0, Zep, e concorrentes) contra critérios de qualidade a definir. Não está bloqueado em nenhuma ferramenta específica.
- **Modelar Fato vs Padrão** com confidence scores — base para memória robusta quando a ferramenta for escolhida.
- **Sensor layer** (Garmin, Home Assistant, PS5, localização) — deixado como backlog futuro. Requer modelagem de como padrões são criados e mantidos.

### Em aberto
- RAG vs destilado para recuperação de sessões passadas — a ser decidido junto com a escolha da memory tool.
- Critérios formais de avaliação de ferramentas de memória.
