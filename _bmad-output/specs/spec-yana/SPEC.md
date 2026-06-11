---
id: SPEC-yana
companions:
  - architecture.md
  - roadmap.md
sources: []
---

> **Canonical contract.** This SPEC and the files in `companions:` are the complete, preservation-validated contract for what to build, test, and validate.

# YANA — You Are Not Alone

## Why

Fred vive em múltiplos contextos simultâneos — engenheiro sênior numa empresa grande, dono de casa, marido, entusiasta de PS4 e whiskey, alguém que monitora a própria saúde via Garmin. Nenhuma ferramenta hoje o conhece em todos esses papéis. Assistentes genéricos não distinguem contexto; serviços especializados não se conectam; apps de produtividade não têm memória de quem você é. YANA existe para ser a presença constante que transita fluentemente entre cada versão de Fred, age de forma autônoma quando relevante, e evolui com o tempo — uma parceira de vida, não uma ferramenta de tarefas.

## Capabilities

- id: CAP-1
  intent: YANA detecta o facet ativo do usuário (Home, Husband, Engineer, Relax, Health) a partir do contexto da conversa e adapta tom, profundidade e abordagem sem precisar ser instruída.
  success: Em 10 interações variadas cobrindo todos os 5 facets, YANA ativa o facet correto em pelo menos 9 sem instrução explícita.

- id: CAP-2
  intent: YANA gerencia agenda e lembretes consolidando duas contas Google (trabalho e pessoal) numa visão coerente, surfacando conflitos e lacunas.
  success: Fred consegue pedir "o que tenho amanhã?" e receber uma visão consolidada das duas contas sem precisar especificar qual.

- id: CAP-3
  intent: YANA assiste Fred no contexto de trabalho — rascunhos de comunicação, revisão de texto, brainstorming técnico e framing de decisões — com precisão de par técnico, sem paternalismo.
  success: Fred usa YANA para ao menos um entregável de trabalho real (email, doc, decisão) e não precisa reescrever o output do zero.

- id: CAP-4
  intent: YANA funciona como life coach — detecta sinais de stress, facilita reflexão sobre dificuldades do dia a dia, e ajuda Fred a comunicar melhor com sua esposa, sem tomar partido.
  success: Fred consegue ter uma conversa não-técnica com YANA sobre algo pessoal e sai com mais clareza ou com uma mensagem pronta para enviar.

- id: CAP-5
  intent: YANA pesquisa compras, compara alternativas, monitora preços de itens rastreados e prepara carrinhos prontos para compra — aplicando a lente "pesquisa antes de comprar" por padrão.
  success: Fred pede pesquisa de um produto e recebe: melhor opção com justificativa, preço atual vs histórico, e link/carrinho prontos. Nenhuma compra ocorre sem confirmação.

- id: CAP-6
  intent: YANA gerencia tarefas domésticas, coordena processos burocráticos multi-etapa e sinaliza oportunidades de automação via connectors configurados.
  success: Fred consegue delegar um processo burocrático com múltiplos passos e receber um plano de ação com próximos passos e comunicações rascunhadas.

- id: CAP-7
  intent: YANA opera autonomamente (PULSE) — monitorando preços, digerindo emails das duas contas Google, revisando agenda das próximas 48h, e respondendo a triggers de connectors ativos — sem precisar ser acionada.
  success: YANA roda um ciclo PULSE completo e produz um digest acionável sem intervenção.

- id: CAP-8
  intent: YANA distingue quem está falando por perfil de voz e adapta comportamento, tom e acesso a contexto conforme o perfil detectado.
  success: Fred e sua esposa conseguem interagir com suas respectivas instâncias YANA e o contexto privado de um não vaza para o outro.

- id: CAP-9
  intent: YANA aceita voz como canal de input/output via STT/TTS, tornando a interação natural em contexto doméstico.
  success: Fred consegue ter uma conversa completa com YANA por voz sem precisar de teclado.

- id: CAP-10
  intent: YANA roteia tarefas entre múltiplos modelos de LLM conforme custo e complexidade, via configuração plugável, sem estar presa a um único provedor.
  success: A troca de provedor exige apenas edição de `providers.yaml`, sem código.

## Constraints

- YANA não pode estar presa ao Claude Code CLI — o sistema deve funcionar via API direta.
- Cada pessoa tem sua própria instância YANA com sanctum privado; memória compartilhada existe apenas para contexto doméstico explícito (arquivo compartilhado na Fase 2).
- A infra roda local primeiro; a arquitetura deve suportar migração para nuvem sem reescrita de lógica.
- Nenhuma compra, envio de mensagem ou ação irreversível ocorre sem confirmação explícita do usuário.
- Integrações externas são connectors plugáveis — habilitados/desabilitados via config, sem alterar o core.
- Configuração de modelos, connectors e PULSE via arquivos YAML/TOML, sem código.
- **Voz é o canal primário de interação com YANA**, incluindo o First Breath. Texto é canal secundário (ex: mensagens WhatsApp rascunhadas por YANA).
- WhatsApp é connector de saída (YANA rascunha mensagens de texto para envio via WhatsApp) — não é canal de input para YANA.

## Non-goals

- Interface visual, app mobile ou dashboard web (não nesta visão).
- Substituir serviços especializados: médico, psicólogo, advogado, financeiro.
- Acesso direto a contas bancárias ou execução de transações financeiras.
- Automação total sem supervisão humana em qualquer ação com consequências externas.
- YANA para múltiplas pessoas além de Fred e sua esposa na fase inicial.

## Success signal

Fred acorda, pergunta por voz "como está meu dia?" e YANA responde consolidando agenda das duas contas Google, alertas de preço dos itens rastreados, e estado físico do Garmin — sem ter pedido cada coisa separadamente. YANA reconhece quem está falando, detecta o facet e adapta o tom.

## Assumptions

- O agent skill `skills/agent-yana/` já construído representa a camada de identidade/comportamento correta para Fase 1.
- O orquestrador é o próximo artefato — simples primeiro, melhora depois.
- Memória compartilhada entre YANA-Fred e YANA-Esposa = arquivo YAML compartilhado (mais simples; revisável na Fase 2).
- Garmin = polling periódico pelo PULSE (Connect IQ push é Fase 3+).
- WhatsApp e outros connectors de mensagem = fora de escopo por agora; arquitetura de connectors os suporta quando o momento chegar.
- Home Assistant = connector plugável; comportamento exato (webhook only vs. polling) definido na implementação do connector.

## Open Questions

- Identificação por perfil de voz (CAP-8): qual biblioteca/serviço? (decisão necessária antes de implementar Fase 2)
