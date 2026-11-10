# -*- coding: utf-8 -*-
import base64
import hashlib
import hmac
import json
import logging
import pprint
import time
import requests

from odoo import _, models
from odoo.exceptions import ValidationError

from odoo.addons.payment_bancard import const

_logger = logging.getLogger(__name__)


class PosPaymentMethod(models.Model):
    _inherit = 'pos.payment.method'

    def _get_payment_terminal_selection(self):
        return super()._get_payment_terminal_selection() + [
            ('bancard_qr', 'Bancard QR / PIX (VentasQR v1.2)'),
            ('bancard_cajapos', 'Bancard Terminal Físico (Caja POS 3.0)'),
        ]

    def _bancard_qr_request(self, pos_config, method, endpoint, payload=None):
        """Executa requisição HTTP autenticada à API Bancard VentasQR v1.2."""
        url = f"{pos_config._bancard_qr_get_base_url()}{endpoint}"
        headers = {
            'Authorization': pos_config._bancard_qr_get_auth_header(),
            'Content-Type': 'application/json',
            'Accept': 'application/json',
        }
        _logger.info("Bancard VentasQR Request [%s] %s", method, url)
        try:
            with requests.Session() as session:
                response = session.request(
                    method=method,
                    url=url,
                    json=payload,
                    headers=headers,
                    timeout=25,
                    verify=True,
                )
            try:
                result = response.json()
            except ValueError as err:
                raise ValidationError(
                    _("Bancard VentasQR: Respuesta no-JSON del servidor (HTTP %s).", response.status_code)
                ) from err

            if response.status_code >= 400 or result.get('status') == 'error':
                messages = result.get('messages', [])
                error_msgs = [
                    f"{m.get('key', 'Error')}: {m.get('description', '')}"
                    for m in messages
                ]
                detail = '; '.join(error_msgs) if error_msgs else pprint.pformat(result)
                raise ValidationError(_("Error Bancard VentasQR: %s", detail))

            return result
        except requests.exceptions.RequestException as err:
            _logger.error("Bancard VentasQR RequestException: %s", err)
            raise ValidationError(_("Fallo de conexión con la API Bancard VentasQR: %s", str(err))) from err

    def bancard_qr_create_order(self, infos):
        """
        Genera un QR Express dinámico para cobro en la caja POS.
        Endpoint oficial: POST /external-commerce/api/0.1/commerces/{commerce_code}/branches/{branch_code}/selling/generate-qr-express
        """
        self.ensure_one()
        pos_config_id = infos.get('pos_config_id')
        pos_config = self.env['pos.config'].sudo().browse(int(pos_config_id)).exists() if pos_config_id else False
        if not pos_config and infos.get('pos_session_id'):
            session = self.env['pos.session'].sudo().browse(int(infos['pos_session_id'])).exists()
            pos_config = session.config_id if session else False

        if not pos_config or not pos_config.bancard_qr_enabled:
            raise ValidationError(
                _("El terminal Bancard VentasQR no está habilitado para esta sucursal/PDV. Active 'Habilitar Bancard VentasQR' en los ajustes del Punto de Venta.")
            )

        commerce_code, branch_code, _pub, _priv = pos_config._bancard_qr_get_credentials()
        amount_int = int(round(float(infos.get('amount') or 0)))
        if amount_int <= 0:
            raise ValidationError(_("El monto del cobro vía Bancard QR en PYG debe ser mayor a cero."))

        description = (infos.get('description') or f"Venta {pos_config.name}").strip()[:60]
        endpoint = (
            f"/external-commerce/api/{const.BANCARD_QR_API_VERSION}"
            f"/commerces/{commerce_code}/branches/{branch_code}/selling/generate-qr-express"
        )
        payload = {
            'amount': amount_int,
            'description': description,
        }

        result = self._bancard_qr_request(pos_config, 'POST', endpoint, payload)
        qr_express = result.get('qr_express', {})
        hook_alias = qr_express.get('hook_alias')
        if not hook_alias:
            raise ValidationError(_("Bancard VentasQR no retornó un hook_alias válido."))

        qr_tx = self.env['bancard.pos.qr.transaction'].sudo().create({
            'name': hook_alias,
            'pos_config_id': pos_config.id,
            'pos_session_id': infos.get('pos_session_id') or (pos_config.current_session_id.id if pos_config.current_session_id else False),
            'payment_method_id': self.id,
            'pos_order_uuid': infos.get('pos_order_uuid') or '',
            'amount': amount_int,
            'description': description,
            'qr_image_url': qr_express.get('url') or '',
            'qr_data': qr_express.get('qr_data') or '',
            'state': 'pending',
        })

        return {
            'status': 'success',
            'qr_transaction_id': qr_tx.id,
            'hook_alias': hook_alias,
            'qr_image_url': qr_express.get('url') or '',
            'qr_data': qr_express.get('qr_data') or '',
            'amount': amount_int,
            'supported_clients': result.get('supported_clients', []),
        }

    def bancard_qr_revert_order(self, infos):
        """
        Revierte/cancela un QR Express en la caja POS y lo marca como revert_requested
        para impedir confirmación tardía (regla obligatoria de homologación Bancard).
        Endpoint oficial: PUT /external-commerce/api/0.1/commerces/{commerce_code}/branches/{branch_code}/selling/payments/revert/{hook_alias}
        """
        self.ensure_one()
        hook_alias = (infos.get('hook_alias') or '').strip()
        if not hook_alias:
            raise ValidationError(_("hook_alias es obligatorio para revertir el QR Bancard."))

        qr_tx = self.env['bancard.pos.qr.transaction'].sudo().search([
            ('name', '=', hook_alias),
        ], limit=1)

        pos_config = qr_tx.pos_config_id if qr_tx else False
        if not pos_config and infos.get('pos_config_id'):
            pos_config = self.env['pos.config'].sudo().browse(int(infos['pos_config_id'])).exists()

        if not pos_config:
            raise ValidationError(_("Configuración de PDV no localizada para revertir el QR %s.", hook_alias))

        # Marcar imediatamente como revert_requested antes mesmo da resposta de rede para blindar contra race condition de webhook!
        if qr_tx:
            qr_tx.write({'state': 'revert_requested'})

        commerce_code, branch_code, _pub, _priv = pos_config._bancard_qr_get_credentials()
        endpoint = (
            f"/external-commerce/api/{const.BANCARD_QR_API_VERSION}"
            f"/commerces/{commerce_code}/branches/{branch_code}/selling/payments/revert/{hook_alias}"
        )

        try:
            self._bancard_qr_request(pos_config, 'PUT', endpoint, payload={})
        except ValidationError as err:
            _logger.warning("Bancard VentasQR aviso ao reverter %s: %s", hook_alias, err)

        return {
            'status': 'success',
            'hook_alias': hook_alias,
            'state': 'revert_requested',
        }

    def bancard_qr_check_status(self, hook_alias):
        """Consulta o status local da transação QR no banco do Odoo."""
        self.ensure_one()
        qr_tx = self.env['bancard.pos.qr.transaction'].sudo().search([
            ('name', '=', hook_alias),
        ], limit=1)
        if not qr_tx:
            return {'status': 'error', 'state': 'not_found'}
        return {
            'status': 'success',
            'state': qr_tx.state,
            'hook_alias': qr_tx.name,
            'authorization_number': qr_tx.authorization_number,
            'ticket_number': qr_tx.ticket_number,
        }

    # =========================================================================
    # BANCARD CAJA POS 3.0 (Terminal Físico / Pinpad REST)
    # =========================================================================

    @staticmethod
    def _bancard_cajapos_build_jwt(commerce_code, api_key):
        """
        Gera um JWT assinado com HS256 conforme Seção 3 do Manual Caja POS 3.0:
        - Header: {"alg": "HS256", "typ": "JWT"}
        - Payload: {"commerce": commerce_code, "tstamp": unix_epoch}
        - Secret: api_key (bytes UTF-8 tal qual, sem decodificação Base64)
        - Vigência: 5 minutos
        """
        header = {"alg": "HS256", "typ": "JWT"}
        tstamp = int(time.time())
        payload = {"commerce": str(commerce_code), "tstamp": tstamp}

        header_b64 = base64.urlsafe_b64encode(
            json.dumps(header, separators=(',', ':')).encode('utf-8')
        ).decode('utf-8').rstrip('=')

        payload_b64 = base64.urlsafe_b64encode(
            json.dumps(payload, separators=(',', ':')).encode('utf-8')
        ).decode('utf-8').rstrip('=')

        message = f"{header_b64}.{payload_b64}".encode('utf-8')
        signature = hmac.new(api_key.encode('utf-8'), message, hashlib.sha256).digest()
        signature_b64 = base64.urlsafe_b64encode(signature).decode('utf-8').rstrip('=')

        return f"{header_b64}.{payload_b64}.{signature_b64}"

    def _bancard_cajapos_request(self, pos_config, method, endpoint, payload=None):
        """Executa requisição HTTP autenticada com Bearer JWT à API Bancard Caja POS 3.0."""
        creds = pos_config._bancard_cajapos_get_credentials()
        jwt_token = self._bancard_cajapos_build_jwt(creds['commerce_code'], creds['api_key'])

        url = f"{pos_config._bancard_cajapos_get_base_url()}{endpoint}"
        headers = {
            'Authorization': f"Bearer {jwt_token}",
            'Content-Type': 'application/json',
            'Accept': 'application/json',
        }
        _logger.info("Bancard Caja POS 3.0 Request [%s] %s", method, url)
        try:
            with requests.Session() as session:
                response = session.request(
                    method=method,
                    url=url,
                    json=payload,
                    headers=headers,
                    timeout=25,
                    verify=True,
                )
            try:
                result = response.json()
            except ValueError as err:
                raise ValidationError(
                    _("Bancard Caja POS: Respuesta no-JSON del servidor (HTTP %s).", response.status_code)
                ) from err

            if response.status_code >= 400 or result.get('status') == 'error' or result.get('type') in ('SECURITY', 'SYSTEM', 'VALIDATION', 'INTERNAL', 'DATABASE'):
                err_code = result.get('code') or ''
                err_msg = result.get('message') or result.get('description') or ''
                err_detail = result.get('detail')
                detail_str = f" ({err_detail})" if err_detail else ""
                full_err = f"[{err_code}] {err_msg}{detail_str}".strip()
                _logger.error("Bancard Caja POS Error: %s", full_err or pprint.pformat(result))
                raise ValidationError(_("Error Bancard Caja POS: %s", full_err or pprint.pformat(result)))

            return result
        except requests.exceptions.RequestException as err:
            _logger.error("Bancard Caja POS RequestException: %s", err)
            raise ValidationError(_("Fallo de conexión con la API Bancard Caja POS: %s", str(err))) from err

    def bancard_cajapos_create_sale(self, infos):
        """
        Inicia una venta en la terminal POS física Bancard (POST /v1/external/pos/venta).
        Envía los datos de la orden/factura y aguarda que el pagador pase la tarjeta en el dispositivo.
        """
        self.ensure_one()
        pos_config_id = infos.get('pos_config_id')
        pos_config = self.env['pos.config'].sudo().browse(int(pos_config_id)).exists() if pos_config_id else False
        if not pos_config and infos.get('pos_session_id'):
            session = self.env['pos.session'].sudo().browse(int(infos['pos_session_id'])).exists()
            pos_config = session.config_id if session else False

        if not pos_config or not pos_config.bancard_cajapos_enabled:
            raise ValidationError(
                _("La integración Bancard Caja POS 3.0 no está habilitada para esta sucursal/PDV. Active 'Habilitar Bancard Caja POS 3.0' en los ajustes del Punto de Venta.")
            )

        creds = pos_config._bancard_cajapos_get_credentials()
        amount_int = int(round(float(infos.get('amount') or 0)))
        if amount_int <= 0:
            raise ValidationError(_("El monto del cobro en la terminal Bancard en PYG debe ser mayor a cero."))

        bill_number = str(infos.get('bill_number') or f"REC-{int(time.time())}").strip()
        endpoint = const.BANCARD_CAJAPOS_ENDPOINTS['venta']

        payload = {
            'commerceCode': creds['commerce_code'],
            'posCode': creds['pos_code'],
            'providerId': creds['provider_id'],
            'billNumber': bill_number,
            'amount': amount_int,
            'amountChange': 0,
            'currencyCode': const.BANCARD_CAJAPOS_CURRENCY_CODE,
            'txType': const.BANCARD_CAJAPOS_TX_TYPE_CONTADO,
            'printVoucher': creds['print_voucher'],
        }

        result = self._bancard_cajapos_request(pos_config, 'POST', endpoint, payload)
        tx_token = result.get('token')
        if not tx_token:
            raise ValidationError(_("Bancard Caja POS no retornó un token de transacción válido."))

        cajapos_tx = self.env['bancard.pos.cajapos.transaction'].sudo().create({
            'name': tx_token,
            'pos_config_id': pos_config.id,
            'pos_session_id': infos.get('pos_session_id') or (pos_config.current_session_id.id if pos_config.current_session_id else False),
            'payment_method_id': self.id,
            'pos_order_uuid': infos.get('pos_order_uuid') or '',
            'bill_number': bill_number,
            'pos_code': creds['pos_code'],
            'provider_id': creds['provider_id'],
            'amount': amount_int,
            'state': 'payment_pending',
            'response_payload': pprint.pformat(result),
        })

        return {
            'status': 'success',
            'cajapos_tx_id': cajapos_tx.id,
            'tx_token': tx_token,
            'payment_status': result.get('status', 'PAYMENT_PENDING'),
            'amount': amount_int,
            'bill_number': bill_number,
        }

    def bancard_cajapos_check_status(self, pos_config_id, tx_token):
        """
        Consulta el estado actual de la transacción en la terminal física (GET /v1/external/pos/venta/{txToken}).
        Actualiza el registro de auditoría local y retorna los datos de recibo cuando finaliza.
        """
        self.ensure_one()
        pos_config = self.env['pos.config'].sudo().browse(int(pos_config_id)).exists()
        if not pos_config:
            raise ValidationError(_("Configuración de PDV no localizada para consultar la transacción %s.", tx_token))

        endpoint = const.BANCARD_CAJAPOS_ENDPOINTS['consulta'].format(token=tx_token)
        result = self._bancard_cajapos_request(pos_config, 'GET', endpoint)

        tx = self.env['bancard.pos.cajapos.transaction'].sudo().search([
            ('name', '=', tx_token),
        ], limit=1)

        raw_status = (result.get('status') or '').strip()
        state_map = {
            'CREATED': 'created',
            'PAYMENT_PENDING': 'payment_pending',
            'PAYMENT_CONFIRMED': 'payment_confirmed',
            'PAYMENT_REJECTED': 'payment_rejected',
            'PAYMENT_CANCELLED': 'payment_cancelled',
            'CANCELLED': 'cancelled',
        }
        mapped_state = state_map.get(raw_status, 'error')

        add_info = result.get('additionalInfo', {}) or {}
        b_info = add_info.get('bancardInfo', {}) or {}

        vals = {
            'state': mapped_state,
            'response_payload': pprint.pformat(result),
        }

        if b_info:
            vals.update({
                'ticket_number': b_info.get('ticketNumber') or result.get('ticketNumber') or '',
                'authorization_code': b_info.get('authorizationCode') or '',
                'date_time': b_info.get('dateTime') or '',
                'amount_buy': str(b_info.get('amountBuy') or ''),
                'amount_change': str(b_info.get('amountChange') or ''),
                'installment_number': str(b_info.get('installmentNumber') or ''),
                'payment_description': b_info.get('paymentDescription') or '',
                'card_last_numbers': b_info.get('cardLastNumbers') or '',
                'cardholder_name': b_info.get('cardholderName') or '',
                'read_type': b_info.get('readType') or '',
                'issuer_id': str(b_info.get('issuerId') or ''),
                'account_type': str(b_info.get('accountType') or ''),
                'merchant_code': b_info.get('merchantCode') or '',
                'device_model': b_info.get('deviceModel') or '',
                'device_serial': b_info.get('deviceSerial') or '',
                'device_version': b_info.get('deviceVersion') or '',
                'response_code': b_info.get('responseCode') or result.get('resultCode') or '',
                'response_message': b_info.get('responseMessage') or result.get('description') or '',
            })

        if tx:
            tx.write(vals)

        is_final = raw_status in const.BANCARD_CAJAPOS_FINAL_STATES
        return {
            'status': 'success',
            'payment_status': raw_status,
            'mapped_state': mapped_state,
            'is_final': is_final,
            'ticket_number': vals.get('ticket_number'),
            'authorization_code': vals.get('authorization_code'),
            'card_last_numbers': vals.get('card_last_numbers'),
            'cardholder_name': vals.get('cardholder_name'),
            'read_type': vals.get('read_type'),
            'response_message': vals.get('response_message'),
        }

