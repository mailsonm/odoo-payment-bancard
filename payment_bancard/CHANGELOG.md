# Changelog — `payment_bancard`

## [19.0.2.0.0] - 2026-10-22
### Added
- Integração nativa no Ponto de Venda (`point_of_sale`) com a **API Bancard Caja POS 3.0 REST** (`use_payment_terminal = 'bancard_cajapos'`) para acionamento direto de maquininhas físicas de balcão (Smart POS Android T6, Hermes, Iris).
- Autenticação por **JWT HS256** assinado com API Key, validade de 5 minutos, claims `commerce` e `tstamp` Unix epoch conforme Seção 3 do Manual Oficial V3.0.
- Endpoints implementados: disparo de venda assíncrona (`POST /v1/external/pos/venta`) com `providerId` de 4 dígitos, `posCode`, `billNumber`, `amount`, `currencyCode: '600'`, `txType: 'VENTA_CONTADO'` e impressão de comprovante na maquininha (`printVoucher: true`).
- Polling assíncrono inteligente (`GET /v1/external/pos/venta/{txToken}`) com captura completa dos dados de comprovante (`ticketNumber`, `authorizationCode`, `cardLastNumbers`, `cardholderName`, `readType: T/B/QR`, `deviceModel`, `deviceSerial`) e tratamento de terminal offline (`tx1020`/`tx1021`) e cancelamentos.
- Novo modelo de auditoria de balcão `bancard.pos.cajapos.transaction` com visões em lista `<list>`, formulário detalhado, notebook de comprovante, statusbar e Soft Delete (`active=False`).
- Driver JavaScript OWL para o PDV (`payment_bancard_cajapos.js`) integrado ao `pos_store` e tratamento visual de espera do cartão.
- Suíte de testes TDD adicionais (`TestBancardCajaPos`) cobrindo 100% dos cenários (geração JWT, validação de providerId, disparo de venda, polling com recibo, cancelamento e terminal offline).

## [19.0.1.0.0] - 2026-10-20
### Added
- Port completo e refatorado do conector **Bancard vPOS 2.0** para a arquitetura do **Odoo 19 Community** (`_search_by_reference`, `_extract_reference`, `_extract_amount_data`, `_apply_updates`, `_send_refund_request` e `@payment/interactions/payment_form`).
- Suporte a **PIX Fronteira** e conversão automática de transações em `BRL` e `USD` para `PYG` (Guaraníes).
- Integração nativa no Ponto de Venda (`point_of_sale`) com a **API Bancard VentasQR v1.2** (`use_payment_terminal = 'bancard_qr'`), cabeçalho `Basic base64("apps/" + public_key + ":" + private_key)`, rollout por filial piloto (`pos.config.bancard_qr_enabled`), reversão com bloqueio de cobrança dupla (`revert_requested` $\rightarrow$ `ConfirmedError`) e WebSocket (`BANCARD_QR_PAYMENT_STATUS`).
- Suíte de testes automatizados TDD (`TestBancardVpos`, `TestBancardControllers`, `TestBancardPosQr`) cobrindo MD5 tokens, truncamento de 20 caracteres em `description`, Anti-IDOR, limite de 5 cartões, `PaymentNotFoundError` no rollback e fluxo completo VentasQR.
