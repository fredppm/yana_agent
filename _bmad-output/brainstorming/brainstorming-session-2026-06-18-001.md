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

## Conclusão Final — Decisão de Não Implementar (2026-06-18)

**Motivo:** Não existe solução viável sem risco inaceitável.

| Opção | Problema |
|---|---|
| WhatsApp Business API (oficial) | Exige número empresarial, não funciona com número pessoal |
| Baileys / whatsapp-web.js (unofficial) | Viola ToS do WhatsApp, risco real de ban do número pessoal (2–8 semanas) |
| Evolution API | Mesmo risco — wrapper do Baileys |

**O design está correto** — a arquitetura do connector, o padrão de unread state, a integração com Pulse, tudo resolvido. O bloqueio é externo: o WhatsApp não oferece API oficial para uso pessoal.

**Quando reavaliar:**
- Meta lançar API oficial para contas pessoais
- Surgir solução que não exija contornar ToS
- Usuário aceitar usar número dedicado (descartado por criar identidade dupla)

**O que fica documentado:** O design completo do connector está pronto para ser implementado assim que a viabilidade técnica mudar.
