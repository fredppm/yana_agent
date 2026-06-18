---
stepsCompleted: [1, 2, 3]
inputDocuments: []
session_topic: 'WhatsApp Connector for YANA'
session_goals: 'Brainstorm how to implement a full WhatsApp connector — send, receive, monitor groups — with special attention to the unread message problem (YANA reading messages should not mark them as read for the user)'
selected_approach: 'ai-recommended'
techniques_used: ['Question Storming', 'Assumption Reversal', 'Cross-Pollination']
ideas_generated: []
context_file: ''
---

# Brainstorming Session Results

**Facilitator:** Fred
**Date:** 2026-06-18

## Session Overview

**Topic:** WhatsApp Connector for YANA
**Goals:** Brainstorm full connector implementation — send messages via YANA, receive/monitor messages and groups, handle unread state without marking messages as read prematurely

### Key Problem Statement

When YANA reads messages on behalf of the user, WhatsApp may mark them as "read" (blue ticks), causing the user to lose track of genuinely unread content. This is the central tension to solve.

### Session Setup

_Fresh session — starting from zero on WhatsApp connector architecture._

---

## Technique 1 — Question Storming

**Focus:** Map the unknown space before solving anything.

### Questions Generated (50+)

**Protocolo / Entrega**
- Como a msg chega ao destinatário?
- Como é marcado como recebido vs lido?
- Como fica se meu celular não estiver online?
- O evento de leitura é broadcast para todos os dispositivos ou só o que abriu?
- Existe um "dispositivo primário" com prioridade?
- O que acontece com mensagens que chegam enquanto estou offline — backfill ao reconectar?

**Unread State (problema central)**
- Como o WhatsApp "sabe" que uma mensagem foi lida — é o app que sinaliza, ou é o servidor?
- Dá para remarcar msg como não lida depois de lida?
- Se o WhatsApp tem "marcar como não lida" no app, isso é só UI local ou vai pro servidor?
- É possível ler mensagens sem abrir a conversa — só "espiar" o payload?
- Se a YANA processar a msg no web e eu abrir no celular — o lido já foi?
- Posso ter a YANA conectada sem aparecer como "online"?
- O status "online" e o "lido" são eventos separados?
- Se a YANA só ouvir mas nunca abrir a conversa, o tick fica em 2 (entregue) mas não azul — possível via API?

**Multi-dispositivo**
- Como é a competição de msgs entre dispositivos (celular + web + desktop)?
- Quando múltiplos dispositivos estão conectados, qual "consume" a mensagem?
- Se eu estiver no celular e a YANA no Web, as mensagens chegam nas duas ao mesmo tempo?

**WhatsApp Business API**
- Business API ajuda em algo para esse caso de uso?
- Qual a diferença real entre pessoal e Business API em termos de acesso programático?
- Business API tem custo por mensagem?
- Tem sandbox para testar sem risco de banimento?

**Criptografia e Segurança**
- Criptografia E2E atrapalha acesso programático?
- Se E2E, como qualquer API acessa o conteúdo — o cliente decripta localmente?
- A YANA precisa rodar com acesso à chave privada do meu número?
- Existe modo de ler só metadados sem decriptar conteúdo?

**Conteúdo e Limites**
- Qual o tamanho máximo de mensagem?
- WhatsApp formata texto (negrito, itálico, código) — YANA precisa saber a sintaxe?
- Posso mandar mensagem formatada via API ou só texto puro?
- A YANA pode enviar áudio como mensagem de voz ou só como arquivo?
- Posso reagir a mensagens via API?

**Edge Cases de Contatos**
- O que acontece se mandar msg pra alguém que não tem WhatsApp?
- Se alguém parou de ter WhatsApp ou trocou de telefone, tem como identificar?
- Tem como fazer "check" se número é WhatsApp antes de tentar enviar?
- O que a YANA faz se receber spam? Ou grupo com 500 pessoas?

**Status / Mídia**
- Status/Stories têm alguma utilidade nesses casos?
- Ver o Story de alguém marca como visto — mesmo problema do unread?
- Msgs deletadas se comportam como?

**Arquitetura YANA**
- O connector roda no mesmo processo ou como serviço separado?
- Se o celular precisar estar online, o connector morre quando o celular trava — como lidar?
- O connector precisa de número dedicado ou usa meu número pessoal?
- O connector vai persistir mensagens no PostgreSQL ou só passa pra YANA e esquece?
- Como o connector sabe quais conversas monitorar — todas, ou só as configuradas?

**Implementação / Mercado**
- Existem libs open source que já resolvem isso (Baileys, whatsapp-web.js)?
- Essas libs violam ToS do WhatsApp?
- O Meta bane contas que usam automação — qual o risco real?
- Twilio ou outros providers valem a pena vs self-hosted?
- Existe projeto open source de "agente pessoal no WhatsApp" que já resolveu isso?

**UX / Interação**
- YANA deveria perguntar antes de enviar toda mensagem ou só em algumas?
- Se eu pedir pra YANA mandar msg às 23h, ela manda na hora ou espera?
- Quando YANA recebe msg pra mim, avisa por voz, notificação, ou só quando eu perguntar?
- Existe modo "YANA só monitora" vs "YANA responde autonomamente"?
- E se a YANA gerar resposta ofensiva — tem camada de revisão antes de enviar?

---

## Technique 2 — Assumption Reversal

**Focus:** Desafiar suposições centrais para revelar soluções não óbvias.

### Ideas Generated

**[Unread #1]: Separação Assimétrica**
_Concept:_ YANA opera em modo "write-only" para envio e "notify-only" para recebimento — nunca abre conversas, só injeta mensagens e escuta eventos de chegada. O ato de enviar pode triggerar abertura de sessão.
_Novelty:_ Separa "saber que chegou" de "ler o que chegou" — expõe que envio e leitura podem ser acoplados na mesma sessão.

**[Unread #2]: Número Único Inegociável** _(restrição confirmada)_
_Concept:_ Usar número separado é inviável — cria duplicação de identidade para todos os contatos.
_Novelty:_ Confirma que o connector deve operar no número pessoal do usuário.

**[Unread #3]: Estado de Leitura Deve Viver no WhatsApp** _(restrição confirmada)_
_Concept:_ YANA não pode criar camada paralela de "lido/não lido" — o celular do Fred precisa refletir corretamente o que ele ainda não viu. Zero apps extras.
_Novelty:_ Elimina qualquer solução que exija app secundário ou dashboard separado.

**[Unread #4]: YANA em Modo Silencioso** _(solução principal)_
_Concept:_ Em Baileys/whatsapp-web.js, o read receipt é um evento separado que o cliente escolhe explicitamente enviar. YANA processa mensagens sem chamar `markChatRead()` — ticks ficam em cinza, celular mantém indicador de não lido.
_Novelty:_ Resolve o problema central sem gambiarra — o protocolo já suporta isso nativamente. Risco 1 (multi-device sync) precisa de validação empírica.

**[Unread #5]: Read Receipt Explícito**
_Concept:_ YANA só manda `markChatRead()` quando o usuário confirmar que leu — ao responder ou por comando explícito.
_Novelty:_ O usuário controla o "lido" conscientemente.

**[Unread #6]: Ticks Cinzas como Padrão** _(aceito pelo usuário)_
_Concept:_ Ticks azuis só aparecem quando Fred responde explicitamente. Socialmente aceitável — muita gente desativa confirmação de leitura.
_Novelty:_ O comportamento "estranho" já existe nativamente no WhatsApp, não vai parecer bug.

**[Send #1]: Confirmação Universal — Sem Exceções** _(decisão de design)_
_Concept:_ YANA nunca envia nada autonomamente. 100% das ações de envio requerem confirmação explícita. A latência de geração do LLM é a janela natural de revisão.
_Novelty:_ A latência do LLM vira feature de segurança. YANA é rascunhadora e curadora, não agente autônomo de comunicação.

**[Voice #1]: Agente de Voz Bidirecional**
_Concept:_ YANA recebe msg → lê em voz alta para Fred (mãos ocupadas) → Fred responde por voz → YANA gera texto → Fred confirma por voz → envia.
_Novelty:_ WhatsApp completamente hands-free. Loop inteiro sem tocar no celular.

**[Voice #2]: Tradução e Interpretação em Tempo Real**
_Concept:_ YANA não lê a mensagem literalmente — entrega briefing: "João perguntou se você confirma a reunião de amanhã às 15h. Parece urgente, mandou 3 vezes."
_Novelty:_ YANA age como chefe de gabinete, não leitor de tela.

**[Groups #1]: Curador de Grupos Silenciados** _(high value)_
_Concept:_ YANA monitora grupos em mudo e gera resumo diário ou sob demanda. Transforma cemitério de notificações em fonte de inteligência curada.
_Novelty:_ Você some dos grupos socialmente sem perder contexto relevante.

**[Groups #2]: Radar de Menção**
_Concept:_ Em grupos ignorados, YANA detecta quando o nome do usuário é mencionado e avisa imediatamente por voz. O resto permanece em mudo.
_Novelty:_ Presença seletiva — você existe nos grupos sem precisar acompanhá-los.

**[Groups #3]: Resumo por Comando de Voz**
_Concept:_ "YANA, o que rolou no grupo do trabalho hoje?" → briefing em 30 segundos por voz.
_Novelty:_ Grupos viram banco de dados consultável por linguagem natural.

**[Groups #4]: Modo Monitor-Only para Grupos** _(decisão de design)_
_Concept:_ Grupos: só leitura e sumarização, nunca envia. 1-a-1: leitura + envio com confirmação. YANA nunca fala em grupo por Fred.
_Novelty:_ Elimina risco de resposta inadequada em grupo. Separação clara por tipo de conversa.

**[Contacts #1]: VIP como Feature Futura**
_Concept:_ MVP trata todos os contatos igualmente. Priorização VIP vem depois via área de contatos do YANA.
_Novelty:_ Simplifica o connector inicial sem fechar a possibilidade futura.

**[Arch #1]: Arquitetura Batch** _(decisão de design)_
_Concept:_ Connector conecta periodicamente (ex: a cada 5 min), coleta mensagens novas, processa, desconecta. Delay aceitável pelo usuário.
_Novelty:_ Reduz risco de ban do WhatsApp e consumo de recursos. Sem daemon persistente.

**[Arch #2]: WhatsApp como Fonte do Pulse** _(decisão de arquitetura)_
_Concept:_ O Pulse já tem infraestrutura de observação periódica. O connector WhatsApp é mais um "observador" registrado no Pulse — a cada ciclo coleta mensagens junto com calendar, email, etc.
_Novelty:_ Sem novo serviço ou daemon. Reutiliza arquitetura existente completamente.

---

## Technique 3 — Cross-Pollination (Gmail Connector)

**Focus:** Extrair padrões do GmailConnector e aplicar ao WhatsApp.

### Ideas Generated

**[Cross #1]: mark_read como Comando Explícito** _(solução confirmada)_
_Concept:_ Gmail já implementa `mark_read` como `@command` separado — fetch não marca como lido automaticamente. WhatsApp connector porta o mesmo padrão: `fetch_messages()` não chama `markChatRead()`. Só `mark_read(chat_id)` faz isso.
_Novelty:_ O Gmail resolveu esse problema por design. É portabilidade de padrão, não invenção.

**[Cross #2]: Lazy Auth com Token Persistido**
_Concept:_ Gmail usa token OAuth em arquivo, reconexão automática. Baileys salva credenciais de sessão WhatsApp Web em arquivo local. Mesmo padrão: primeira vez = setup manual, depois = reconexão silenciosa.
_Novelty:_ Zero código novo de auth — é o `_build_service()` pattern com arquivo de sessão.

**[Cross #3]: Polling via Pulse como @event**
_Concept:_ Gmail tem `new_important_email` como `@event` "called by PULSE scheduler". WhatsApp tem `new_message` com a mesma abordagem — Pulse chama `unread_chats()` a cada ciclo batch.
_Novelty:_ Connector sem daemon próprio. Plugado no Pulse existente.

---

## Estrutura do Connector (Design Emergente)

```python
class WhatsAppConnector(Connector):
    # Queries — leitura sem side effects, nunca chama markChatRead()
    @query  unread_chats()              # lista chats com msgs novas
    @query  messages(chat_id, limit)    # busca msgs de uma conversa
    @query  group_summary(group_id)     # resumo de grupo para YANA sumarizar

    # Commands — ações explícitas
    @command send_message(to, body)     # envia após confirmação do usuário
    @command mark_read(chat_id)         # marca lido SOMENTE quando usuário confirmar

    # Events — polling via Pulse
    @event  new_message                 # Pulse chama unread_chats() a cada ciclo
```

**Decisões de design confirmadas:**
- Número pessoal do Fred (não número separado)
- Batch mode (não sessão persistente)
- Confirmação obrigatória para qualquer envio
- Grupos: monitor-only, nunca envia
- Ticks cinzas são aceitáveis como padrão
- Integra no Pulse existente, não novo daemon
- Auth: sessão Baileys salva em arquivo (como Gmail token)

---

## Viabilidade Técnica — Pesquisa de Fontes Primárias (2026-06-18)

### Opções avaliadas

| Opção | Veredicto | Motivo |
|---|---|---|
| WhatsApp Business API (oficial Meta) | ❌ Inviável | Exige número empresarial verificado; não funciona com número pessoal |
| Baileys / whatsapp-web.js | ⚠️ Risco real | Viola ToS, ban é comportamental — ver análise abaixo |
| Evolution API | ⚠️ Mesmo risco | Wrapper do Baileys — herda todos os riscos |

### Análise de risco de ban — Baileys (fontes primárias)

**O que é fato verificado:**
- Baileys viola explicitamente os ToS do WhatsApp ("unauthorized or automated means", "APIs that function substantially the same as our Services")
- O próprio README do Baileys reconhece isso: _"The maintainers do not condone the use of this application in practices that violate the Terms of Service of WhatsApp"_
- Casos reais de ban documentados nos issues do projeto: [#1983](https://github.com/WhiskeySockets/Baileys/issues/1983), [#1869](https://github.com/WhiskeySockets/Baileys/issues/1869), [#2075](https://github.com/WhiskeySockets/Baileys/issues/2075)

**O que a pesquisa anterior errou:**
- "2–8 semanas de ban" era **tempo de apelação**, não tempo até ser banido. Bans reais ocorrem em **dias**.
- Severidade foi inflada — fontes citadas eram blogs com interesse comercial, sem dados primários.

**O que múltiplas fontes convergem:**
- Detecção é **baseada em comportamento**, não no método de conexão
- Triggers de alto risco: mensagens para desconhecidos, velocidade >60 msgs/hora, reply ratio <15%, mensagens idênticas em massa
- Triggers de baixo risco: contatos conhecidos, cadência humana, sem broadcast

**Para o caso de uso do Fred (assistente pessoal, contatos conhecidos, batch a cada 5+ min):**
- Nenhum dos comportamentos de alto risco estaria presente
- Risco existente mas significativamente menor do que estimado inicialmente

**O que não é verificado:**
- baileys-antiban: claims do autor não têm teste independente; autor tem interesse comercial

### Decisão final

**Não implementar agora** — a violação de ToS cria risco para o número pessoal do Fred, mesmo que o comportamento seja de baixo risco. A assimetria (perder acesso ao número pessoal vs. ganho de conveniência) não justifica.

**O design técnico está completo** — arquitetura, unread state, integração com Pulse, tudo resolvido. O bloqueio é de política, não de engenharia.

### Quando reavaliar

- Meta lançar API oficial para contas pessoais
- Surgir solução que não exija contornar ToS
- Fred aceitar usar número dedicado (descartado nesta sessão — cria identidade dupla para contatos)
- Meta relaxar enforcement para uso pessoal de baixo volume
