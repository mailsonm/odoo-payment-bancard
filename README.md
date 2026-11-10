# Odoo Payment Bancard — Official Bancard S.A. Provider for Odoo 19

[![Odoo Version](https://img.shields.io/badge/odoo-19.0-blue.svg)](https://www.odoo.com)
[![License: LGPL-3](https://img.shields.io/badge/License-LGPL--3-blue.svg)](https://www.gnu.org/licenses/lgpl-3.0)
[![Test Suite](https://img.shields.io/badge/tests-100%25%20passing-brightgreen.svg)]()

Complete, production-ready, open-source integration between **Odoo 19 (Community & Enterprise)** and **Bancard S.A.** (Paraguay's leading payment processor).

---

## 🌐 Language Navigation / Navegação de Idioma / Navegación por Idioma
- [🇺🇸 English (EN)](#-english-en)
- [🇪🇸 Español (ES)](#-español-es)
- [🇧🇷 Português (PT-BR)](#-português-pt-br)

---

## 🇺🇸 English (EN)

### Overview
`odoo-payment-bancard` connects Odoo 19 with all three official payment rails of **Bancard S.A.**:

1. **Bancard vPOS 2.0 (`/vpos/api/0.3/`):**
   - Seamless checkout via official Iframe (`bancard-checkout-5.0.1.js`).
   - Single-buy transactions (`single_buy`).
   - Card tokenization & vault for up to 5 cards per customer (`cards/new`, `users_cards`, `charge`, `delete_card`).
   - 3-D Secure authentication support (`Bancard.Charge3DS.createForm`).
   - **Border PIX Support:** Automatic conversion from `BRL` and `USD` to `PYG` (Guaraníes).
   - Confirmation verification and rollbacks (`single_buy/rollback` with `PaymentNotFoundError` handling).

2. **Bancard VentasQR v1.2 in Point of Sale (`point_of_sale`):**
   - Dynamic Express QR generation directly on the cashier screen (`POST .../selling/generate-qr-express`).
   - `Basic base64("apps/" + public_key + ":" + private_key)` authentication.
   - Immediate cancellation and reversal (`PUT .../selling/payments/revert/{hook_alias}`).
   - Double-charge prevention: responds with `ConfirmedError` on late customer payment after cancellation, prompting Bancard's switch to trigger an auto-refund.
   - Real-time payment notifications via WebSocket (`BANCARD_QR_PAYMENT_STATUS`).

3. **Bancard Caja POS 3.0 in POS (Smart POS Physical Pinpad REST):**
   - Direct integration with smart Android physical counter pinpads (Smart POS T6, Hermes, Iris).
   - `POST /v1/external/pos/venta` with HS256 JWT authentication (5-minute expiration, `commerce` and `tstamp` claims).
   - Asynchronous status polling (`GET /v1/external/pos/venta/{txToken}`) every 3s.
   - Multi-read support: Chip card, Contactless NFC, Magstripe, Mobile Wallets (Billeteras) and QR.
   - Terminal voucher slip printing (`printVoucher: true`) on the physical machine's thermal printer.

### Architecture & Supported Models
- `payment.provider`: Bancard credentials, staging (`:8888`) and production endpoints, MD5 security tokens, iframe styling.
- `payment.transaction`: Native Odoo 19 payment notification pipeline (`_extract_reference`, `_search_by_reference`, `_extract_amount_data`, `_apply_updates`, `_send_refund_request`).
- `payment.token`: Stores customer's `bancard_alias_token` with remote token deletion on deactivation (`active=False`).
- `pos.config` & `pos.payment.method`: Granular configuration per branch/terminal (`bancard_qr_enabled`, `bancard_cajapos_enabled`, POS codes, API keys).
- `bancard.pos.qr.transaction`: POS QR audit records with logical soft delete (`active=False`).
- `bancard.pos.cajapos.transaction`: Physical terminal transactions log with complete authorization slip metadata.

### Installation
1. Clone this repository into your custom addons directory:
   ```bash
   git clone https://github.com/mailsonm/odoo-payment-bancard.git /path/to/custom_addons/odoo-payment-bancard
   ```
2. Add the path to your `odoo.conf`:
   ```ini
   addons_path = /path/to/odoo/addons,/path/to/custom_addons/odoo-payment-bancard
   ```
3. Update Apps List in Odoo and install **Payment Provider: Bancard (vPOS 2.0, POS QR & Caja POS 3.0)** (`payment_bancard`).

### Running Tests
Execute the automated test suite with Odoo's test runner:
```bash
odoo-bin -c /path/to/odoo.conf -d your_db -i payment_bancard --test-enable --stop-after-init
```

---

## 🇪🇸 Español (ES)

### Descripción General
`odoo-payment-bancard` conecta **Odoo 19 (Community & Enterprise)** con las tres vías oficiales de pago electrónico de **Bancard S.A.**:

1. **Bancard vPOS 2.0 (`/vpos/api/0.3/`):**
   - Checkout transparente vía Iframe oficial (`bancard-checkout-5.0.1.js`).
   - Compras individuales (`single_buy`).
   - Catastro y tokenización de hasta 5 tarjetas por cliente (`cards/new`, `users_cards`, `charge`, `delete_card`).
   - Soporte para autenticación 3-D Secure (`Bancard.Charge3DS.createForm`).
   - **Soporte PIX Frontera:** Conversión automática de `BRL` y `USD` a `PYG` (Guaraníes).
   - Verificación de confirmaciones y reversión (`single_buy/rollback` con tratamiento de `PaymentNotFoundError`).

2. **Bancard VentasQR v1.2 en Punto de Venta (`point_of_sale`):**
   - Generación de QR Dinámico Express en pantalla de caja (`POST .../selling/generate-qr-express`).
   - Autenticación `Basic base64("apps/" + public_key + ":" + private_key)`.
   - Reversión inmediata (`PUT .../selling/payments/revert/{hook_alias}`).
   - Protección contra cobro doble: responde con `ConfirmedError` ante pagos tardíos cancelados para estorno automático.
   - Notificación instantánea vía WebSocket (`BANCARD_QR_PAYMENT_STATUS`).

3. **Bancard Caja POS 3.0 en PDV (Terminal Físico / Pinpad REST):**
   - Accionamiento de terminales inteligentes Android de mostrador (Smart POS T6, Hermes, Iris).
   - `POST /v1/external/pos/venta` con autenticación JWT HS256 (validez 5 minutos, claims `commerce` y `tstamp`).
   - Polling asíncrono (`GET /v1/external/pos/venta/{txToken}`) cada 3s.
   - Multilectura: Tarjeta chip/contactless/banda, Billeteras móviles y QR.
   - Impresión de ticket en la propia terminal (`printVoucher: true`).

### Plan de Reversión (Rollback en 3 Líneas)
1. **Qué hacer en caso de falla:** Desmarcar `bancard_cajapos_enabled` o `bancard_qr_enabled` en la configuración del PDV (`pos.config`) y poner el proveedor en estado `disabled` en `payment.provider`.
2. **Tiempo estimado:** Menos de 1 minuto a través de la interfaz web, sin reiniciar el servidor Odoo.
3. **Quién decide:** Responsable de caja / Gerente de sucursal o Administrador del sistema.

---

## 🇧🇷 Português (PT-BR)

### Visão Geral
O `odoo-payment-bancard` integra o **Odoo 19 (Community & Enterprise)** com os três canais oficiais de pagamento da **Bancard S.A.** (Paraguai):

1. **Bancard vPOS 2.0 (`/vpos/api/0.3/`):**
   - Checkout transparente via Iframe oficial (`bancard-checkout-5.0.1.js`).
   - Pagamento avulso (`single_buy`).
   - Tokenização e cofre seguro de até 5 cartões por cliente (`cards/new`, `users_cards`, `charge`, `delete_card`).
   - Autenticação 3-D Secure (`Bancard.Charge3DS.createForm`).
   - **PIX Fronteira:** Conversão cambial automática de `BRL` e `USD` para `PYG` (Guaraníes).
   - Consulta e estorno com tratamento de idempotência (`single_buy/rollback`).

2. **Bancard VentasQR v1.2 no Ponto de Venda (`point_of_sale`):**
   - Geração de QR Dinâmico Express na tela do PDV (`POST .../selling/generate-qr-express`).
   - Autenticação `Basic base64("apps/" + public_key + ":" + private_key)`.
   - Cancelamento e reversão imediata (`PUT .../selling/payments/revert/{hook_alias}`).
   - Proteção contra cobrança dupla: resposta `ConfirmedError` para pagamentos tardios cancelados pelo caixa.
   - Notificação em tempo real via WebSocket (`BANCARD_QR_PAYMENT_STATUS`).

3. **Bancard Caja POS 3.0 no PDV (Smart POS / Terminal Pinpad Físico REST):**
   - Acionamento direto de maquininhas físicas de balcão Android (Smart POS T6, Hermes, Iris).
   - Chamada `POST /v1/external/pos/venta` autenticada via token JWT HS256.
   - Polling assíncrono de status a cada 3s com timeout e captura de boleta.
   - Suporte a chip, contactless, tarja magnética, carteiras digitais (Billeteras) e QR.
   - Impressão do voucher diretamente na impressora térmica da maquininha (`printVoucher: true`).

### Segurança e Boas Práticas
- **Zero Segredos Hardcoded:** Todas as chaves públicas, privadas e API keys residem exclusivamente no banco de dados com campos protegidos.
- **Proteção Anti-IDOR e RBAC:** Validação rigorosa de titularidade em todas as operações com cartões e exigência de grupos administrativos ou gerenciais para estornos manuais.
- **Exclusão Lógica Obrigatória:** Transações de auditoria contam com soft delete (`active=False`) prevenindo deleções acidentais.
- **Suíte TDD Completa:** 100% dos testes unitários aprovados em ambiente Odoo 19 TransactionCase.

---

## 📄 Licença
Distribuído sob os termos da licença **GNU Lesser General Public License v3.0 (LGPL-3)**. Consulte o arquivo [LICENSE](./LICENSE) para detalhes.

## 👨‍💻 Autor
- **Mailson Maia Alves** ([GitHub: @mailsonm](https://github.com/mailsonm))
