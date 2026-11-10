# Payment Provider: Bancard (vPOS 2.0, POS VentasQR v1.2 & Caja POS 3.0) — Odoo 19

---

## 🇧🇷 Português (PT-BR)

### O que resolve
Integra o **Odoo 19 Community & Enterprise** às três APIs oficiais de pagamento eletrônico da **Bancard S.A.** (Paraguai):
1. **Bancard vPOS 2.0 (`/vpos/api/0.3/`):** Checkout transparente via Iframe (`bancard-checkout-5.0.1.js`), pagamentos avulsos (`single_buy`), catastro e tokenização de até 5 cartões por cliente (`cards/new`, `users_cards`, `charge`, `delete_card`), suporte a 3DS (`Bancard.Charge3DS.createForm`), **PIX Fronteira** com conversão cambial automática de `BRL`/`USD` para `PYG` (Guaraníes), consulta de confirmações e estorno (`single_buy/rollback`).
2. **Bancard VentasQR v1.2 no PDV (`point_of_sale`):** Geração de QR Dinâmico Express (`POST .../selling/generate-qr-express`) diretamente na tela do caixa com autenticação `Basic base64("apps/" + public_key + ":" + private_key)`, reversão imediata (`PUT .../selling/payments/revert/{hook_alias}`), proteção de homologação contra cobrança dupla (`revert_requested` $\rightarrow$ `ConfirmedError`) e confirmação em tempo real via WebSocket (`BANCARD_QR_PAYMENT_STATUS`).
3. **Bancard Caja POS 3.0 no PDV (Terminal Físico / Pinpad REST):** Acionamento direto da maquininha física de balcão (Smart POS Android T6, Hermes, Iris) via `POST /v1/external/pos/venta` com autenticação JWT HS256, polling assíncrono (`GET /v1/external/pos/venta/{txToken}`) a cada 3s, suporte a `readType` (Cartão Chip/Contactless/Tarja, Billetera e QR), impressão de comprovante na própria maquininha (`printVoucher: true`) e registro completo de auditoria.

### Modelos Tocados
- `payment.provider`: Credenciais vPOS 2.0 e VentasQR, URLs de staging (`:8888`) e produção, geração de tokens MD5 e estilos do iframe.
- `payment.transaction`: Pipeline de notificação nativo do Odoo 19 (`_extract_reference`, `_search_by_reference`, `_extract_amount_data`, `_apply_updates`, `_send_refund_request`), conversão `BRL`/`USD` $\rightarrow$ `PYG` e truncamento seguro de `description` em 20 caracteres.
- `payment.token`: Armazenamento de `bancard_alias_token` e remoção remota automática ao inativar (`active=False`).
- `pos.config` & `pos.payment.method`: Configuração por filial piloto (`bancard_qr_enabled`, `bancard_cajapos_enabled`, `bancard_cajapos_pos_code`, `bancard_cajapos_provider_id`, `bancard_cajapos_api_key`) e seleção de terminais `bancard_qr` e `bancard_cajapos`.
- `bancard.pos.qr.transaction`: Registro auditável de QR Express gerados no PDV com Soft Delete obrigatório (`active=False`).
- `bancard.pos.cajapos.transaction`: Registro auditável de transações enviadas para as maquininhas físicas no PDV, com captura de ticket, autorização, dados do cartão e do terminal físico.

### Decisões Técnicas (O Porquê)
- **Rollout por Filial Piloto:** Os campos `bancard_qr_enabled` e `bancard_cajapos_enabled` em `pos.config` permitem a ativação controlada e isolada do QR Dinâmico ou das maquininhas físicas por filial/PDV (iniciando em uma filial piloto a ser definida pela gestão operacional), garantindo que as demais filiais da rede continuem operando normalmente sem impacto.
- **Proteção Anti-IDOR e RBAC:** Todas as rotas de listagem/cobrança de cartões validam a titularidade do `partner_id` contra o usuário autenticado, e rotas de confirmação/rollback manual exigem grupo gerencial/administrador.
- **Reversão Segura no PDV (`ConfirmedError`):** Conforme exigência de certificação da Bancard, se o operador de caixa cancelar um QR e o cliente pagar atrasado, o webhook responde `ConfirmedError` para que o switch da Bancard estorne o pagamento automaticamente.
- **Autonomia da Maquininha Física:** No Caja POS 3.0, a opção `printVoucher: true` transfere a impressão do comprovante financeiro diretamente para a impressora térmica da maquininha Android da Bancard, poupando a impressora de cupom fiscal do PDV.

### Plano de Reversão (Rollback em 3 Linhas)
1. **O que fazer se falhar:** Desmarcar `bancard_cajapos_enabled` e/ou `bancard_qr_enabled` no `pos.config` do PDV em teste e definir `state = 'disabled'` no provedor Bancard em `payment.provider`.
2. **Em quanto tempo:** Imediato ($< 1$ minuto pela interface administrativa, sem reiniciar o Odoo).
3. **Quem decide:** Gerente da Sucursal Piloto / Responsável do Caixa ou Administrador de TI (`Mailson Maia Alves`).

---

## 🇪🇸 Español (ES)

### Qué resuelve
Integra **Odoo 19 Community & Enterprise** con las tres APIs oficiales de **Bancard S.A.** (Paraguay):
1. **Bancard vPOS 2.0 (`/vpos/api/0.3/`):** Checkout Iframe (`bancard-checkout-5.0.1.js`), compra ocasional (`single_buy`), catastro de hasta 5 tarjetas por cliente (`cards/new`, `charge`), soporte 3DS (`Charge3DS`), **PIX Frontera** con conversión automática `BRL`/`USD` $\rightarrow$ `PYG`, confirmación y rollback (`single_buy/rollback` tratando `PaymentNotFoundError`).
2. **Bancard VentasQR v1.2 en Punto de Venta (`point_of_sale`):** Generación de QR Express dinámico por sucursal (`commerce_code` / `branch_code`), reversión (`PUT .../selling/payments/revert/{hook_alias}`), bloqueo contra doble cobro (`revert_requested` $\rightarrow$ `ConfirmedError`) y notificación instantánea por WebSocket.
3. **Bancard Caja POS 3.0 en Punto de Venta (Terminal Físico / Pinpad REST):** Activación directa del terminal físico de mostrador (Smart POS Android T6, Hermes, Iris) vía `POST /v1/external/pos/venta` con autenticación JWT HS256, polling asíncrono (`GET /v1/external/pos/venta/{txToken}`), soporte multilectura (Tarjeta, Billetera y QR) e impresión de voucher en el propio POS.

---

## 🇺🇸 English (EN)

### Overview
Integrates **Odoo 19 Community & Enterprise** with **Bancard S.A.** (Paraguay) official payment APIs:
1. **Bancard vPOS 2.0 (`/vpos/api/0.3/`):** Iframe Checkout (`bancard-checkout-5.0.1.js`), single buy, card tokenization (up to 5 cards per customer), 3DS support (`Charge3DS`), border PIX with automatic `BRL`/`USD` $\rightarrow$ `PYG` currency conversion, confirmation polling, and rollback.
2. **Bancard VentasQR v1.2 in POS (`point_of_sale`):** Dynamic QR Express generation per branch (`commerce_code` / `branch_code`), immediate reversal (`revert_requested`), certification-compliant late callback rejection (`ConfirmedError`), and real-time WebSocket notifications.
3. **Bancard Caja POS 3.0 in POS (Physical Terminal / Pinpad REST):** Direct trigger of counter physical payment devices (Smart POS Android T6, Hermes, Iris) via `POST /v1/external/pos/venta` with HS256 JWT auth, async polling (`GET /v1/external/pos/venta/{txToken}`), multi-read support (Card Chip/NFC/Magstripe, Mobile Wallet, QR), and direct slip printing (`printVoucher: true`).
