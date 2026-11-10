# -*- coding: utf-8 -*-
import hmac
import logging
import pprint

from werkzeug import urls

from odoo import _, fields, models
from odoo.exceptions import ValidationError

from odoo.addons.payment_bancard import const

_logger = logging.getLogger(__name__)


class PaymentTransaction(models.Model):
    _inherit = 'payment.transaction'

    bancard_process_id = fields.Char(
        string="Bancard Process ID",
        help="Process ID retornado pelo Bancard single_buy ou charge para renderização do iframe.",
        readonly=True,
        copy=False,
    )
    bancard_shop_process_id = fields.Integer(
        string="Bancard Shop Process ID",
        help="Identificador numérico único enviado à Bancard (shop_process_id).",
        readonly=True,
        copy=False,
        index=True,
    )
    bancard_authorization_number = fields.Char(
        string="Número de Autorização",
        readonly=True,
        copy=False,
    )
    bancard_ticket_number = fields.Char(
        string="Número de Ticket",
        readonly=True,
        copy=False,
    )
    bancard_response_code = fields.Char(
        string="Código de Resposta Bancard",
        readonly=True,
        copy=False,
    )
    bancard_response_description = fields.Char(
        string="Descrição da Resposta",
        readonly=True,
        copy=False,
    )
    bancard_extended_description = fields.Char(
        string="Descrição Estendida",
        readonly=True,
        copy=False,
    )
    bancard_security_info = fields.Text(
        string="Informação de Segurança Bancard",
        readonly=True,
        copy=False,
    )
    bancard_is_zimple = fields.Boolean(
        string="Pagar com Zimple",
        default=False,
    )
    bancard_is_pix = fields.Boolean(
        string="Pagar com PIX (Fronteira)",
        default=False,
    )
    bancard_pyg_amount = fields.Float(
        string="Valor Convertido em PYG",
        readonly=True,
        copy=False,
        help="Valor efetivamente enviado à Bancard em Guaraníes (PYG) após conversão cambial.",
    )
    bancard_promotions = fields.Char(
        string="Promoções Bancard",
        help="Parâmetro adicional de promoções (ex: 027VS ORO000045).",
    )

    def _bancard_get_pyg_amount_and_currency(self):
        """Retorna (amount_str, 'PYG') convertendo BRL/USD para PYG caso necessário."""
        self.ensure_one()
        pyg_currency = (
            self.env.ref('base.PYG', raise_if_not_found=False)
            or self.env['res.currency'].search([('name', '=', 'PYG')], limit=1)
        )
        if not self.currency_id or self.currency_id.name == 'PYG' or not pyg_currency:
            pyg_amount = round(self.amount, 2)
        else:
            company = self.company_id or self.provider_id.company_id or self.env.company
            converted = self.currency_id._convert(
                self.amount,
                pyg_currency,
                company,
                fields.Date.context_today(self),
                round=True,
            )
            pyg_amount = round(converted, 2)

        self.bancard_pyg_amount = pyg_amount
        return f"{pyg_amount:.2f}", 'PYG'

    def _bancard_format_description(self):
        """Retorna a descrição truncada em no máximo 20 caracteres (regra oficial Bancard SDK)."""
        self.ensure_one()
        raw_desc = f"FA {self.reference or self.id}".strip()
        return raw_desc[:const.BANCARD_DESCRIPTION_MAX_LEN]

    def _get_specific_processing_values(self, processing_values):
        res = super()._get_specific_processing_values(processing_values)
        if self.provider_code != 'bancard':
            return res

        if not self.bancard_process_id:
            self._bancard_create_single_buy()

        return {
            'bancard_process_id': self.bancard_process_id,
            'bancard_shop_process_id': self.bancard_shop_process_id,
            'bancard_checkout_js_url': self.provider_id._bancard_get_checkout_js_url(),
            'bancard_iframe_styles': self.provider_id._bancard_get_iframe_styles(),
            'bancard_enable_pix': self.provider_id.bancard_enable_pix,
            'bancard_pyg_amount': self.bancard_pyg_amount,
        }

    def _bancard_create_single_buy(self):
        """Inicia uma transação single_buy na API vPOS 2.0 e retorna o process_id."""
        self.ensure_one()
        provider = self.provider_id.sudo()

        if not self.bancard_shop_process_id:
            self.bancard_shop_process_id = self.id

        amount_str, currency_str = self._bancard_get_pyg_amount_and_currency()
        token = provider._bancard_generate_token(
            'single_buy',
            shop_process_id=self.bancard_shop_process_id,
            amount=amount_str,
            currency=currency_str,
        )

        base_url = provider.get_base_url()
        return_url = urls.url_join(
            base_url,
            f'/payment/bancard/return?shop_process_id={self.bancard_shop_process_id}',
        )
        cancel_url = urls.url_join(
            base_url,
            f'/payment/bancard/cancel?shop_process_id={self.bancard_shop_process_id}',
        )

        operation_data = {
            'token': token,
            'shop_process_id': self.bancard_shop_process_id,
            'amount': amount_str,
            'currency': currency_str,
            'additional_data': self.bancard_promotions or '',
            'description': self._bancard_format_description(),
            'return_url': return_url,
            'cancel_url': cancel_url,
        }

        if self.bancard_is_zimple:
            operation_data['zimple'] = 'S'
            if self.partner_id.phone:
                operation_data['additional_data'] = self.partner_id.phone

        payload = {
            'public_key': provider.bancard_public_key,
            'operation': operation_data,
        }

        result = provider._bancard_make_request(
            const.BANCARD_ENDPOINTS['single_buy'],
            payload,
        )

        process_id = result.get('process_id')
        if not process_id:
            raise ValidationError(_("Bancard: La API no retornó un process_id válido."))

        self.bancard_process_id = process_id
        return process_id

    def _bancard_charge_with_token(self, alias_token, number_of_payments=1):
        """Executa cobrança com cartão tokenizado (1-Click / 3DS) via /vpos/api/0.3/charge."""
        self.ensure_one()
        provider = self.provider_id.sudo()

        if not self.bancard_shop_process_id:
            self.bancard_shop_process_id = self.id

        amount_str, currency_str = self._bancard_get_pyg_amount_and_currency()
        token = provider._bancard_generate_token(
            'charge',
            shop_process_id=self.bancard_shop_process_id,
            amount=amount_str,
            currency=currency_str,
            alias_token=alias_token,
        )

        base_url = provider.get_base_url()
        return_url = urls.url_join(
            base_url,
            f'/payment/bancard/return?shop_process_id={self.bancard_shop_process_id}',
        )

        operation_data = {
            'token': token,
            'shop_process_id': self.bancard_shop_process_id,
            'amount': amount_str,
            'number_of_payments': int(number_of_payments or 1),
            'currency': currency_str,
            'additional_data': self.bancard_promotions or '',
            'description': self._bancard_format_description(),
            'alias_token': alias_token,
            'return_url': return_url,
        }

        payload = {
            'public_key': provider.bancard_public_key,
            'operation': operation_data,
        }

        result = provider._bancard_make_request(
            const.BANCARD_ENDPOINTS['charge'],
            payload,
        )

        if 'confirmation' in result:
            self._process('bancard', {'operation': result['confirmation']})
        elif 'operation' in result:
            op = result['operation']
            if 'process_id' in op:
                self.bancard_process_id = op['process_id']
            else:
                self._process('bancard', result)

        return result

    def _bancard_get_confirmation(self):
        """Consulta ativamente o status da transação na Bancard (single_buy/confirmations)."""
        self.ensure_one()
        provider = self.provider_id.sudo()
        shop_process_id = self.bancard_shop_process_id or self.id

        token = provider._bancard_generate_token(
            'get_confirmation',
            shop_process_id=shop_process_id,
        )
        payload = {
            'public_key': provider.bancard_public_key,
            'operation': {
                'token': token,
                'shop_process_id': shop_process_id,
            },
        }
        result = provider._bancard_make_request(
            const.BANCARD_ENDPOINTS['confirmations'],
            payload,
        )
        if 'confirmation' in result:
            self._process('bancard', {'operation': result['confirmation']})
        return result

    def _bancard_rollback(self):
        """Executa rollback da transação na Bancard tratando PaymentNotFoundError graciosamente."""
        self.ensure_one()
        provider = self.provider_id.sudo()
        shop_process_id = self.bancard_shop_process_id or self.id

        token = provider._bancard_generate_token(
            'rollback',
            shop_process_id=shop_process_id,
        )
        payload = {
            'public_key': provider.bancard_public_key,
            'operation': {
                'token': token,
                'shop_process_id': shop_process_id,
                'amount': '0.00',
            },
        }
        result = provider._bancard_make_request(
            const.BANCARD_ENDPOINTS['rollback'],
            payload,
        )
        if result.get('status') == 'success' or result.get('key') == 'PaymentNotFoundError':
            if not self.source_transaction_id and self.state != 'cancel':
                msg = _("Transação revertida (rollback) na Bancard.")
                if self.state in ('draft', 'pending', 'authorized'):
                    self._set_canceled(state_message=msg)
                else:
                    self.write({'state': 'cancel', 'state_message': msg})
        return result

    def action_bancard_query_confirmation(self):
        """Botão administrativo para consultar status na Bancard."""
        self.ensure_one()
        self._bancard_get_confirmation()
        return True

    def action_bancard_rollback(self):
        """Botão administrativo para reverter transação na Bancard."""
        self.ensure_one()
        self._bancard_rollback()
        return True

    def _send_refund_request(self):
        """Override Odoo 19 (sem argumento amount_to_refund): executa rollback na transação origem."""
        if self.provider_code != 'bancard':
            return super()._send_refund_request()

        source_tx = self.source_transaction_id or self
        shop_process_id = source_tx.bancard_shop_process_id or source_tx.id
        provider = self.provider_id.sudo()

        token = provider._bancard_generate_token(
            'rollback',
            shop_process_id=shop_process_id,
        )
        payload = {
            'public_key': provider.bancard_public_key,
            'operation': {
                'token': token,
                'shop_process_id': shop_process_id,
                'amount': '0.00',
            },
        }
        result = provider._bancard_make_request(
            const.BANCARD_ENDPOINTS['rollback'],
            payload,
        )
        if result.get('status') == 'success' or result.get('key') == 'PaymentNotFoundError':
            self._set_done()
            if source_tx != self and source_tx.state != 'cancel':
                source_tx.bancard_response_description = _("Revertida vía Rollback Bancard")
        else:
            self._set_error(_("No fue posible revertir la transacción en Bancard."))

    # === Pipeline de Notificación Nativo de Odoo 19 ===

    @staticmethod
    def _extract_reference(provider_code, payment_data):
        if provider_code != 'bancard':
            return super(PaymentTransaction, PaymentTransaction)._extract_reference(
                provider_code, payment_data
            )
        operation = payment_data.get('operation', payment_data)
        shop_process_id = operation.get('shop_process_id')
        if shop_process_id is not None:
            return str(shop_process_id)
        return payment_data.get('reference')

    def _search_by_reference(self, provider_code, payment_data):
        tx = super()._search_by_reference(provider_code, payment_data)
        if provider_code != 'bancard' or tx:
            return tx

        operation = payment_data.get('operation', payment_data)
        shop_process_id = operation.get('shop_process_id')
        if shop_process_id:
            try:
                sp_id = int(shop_process_id)
            except (ValueError, TypeError):
                sp_id = False
            if sp_id:
                tx = self.search([
                    ('bancard_shop_process_id', '=', sp_id),
                    ('provider_code', '=', 'bancard'),
                ], limit=1)
                if not tx:
                    tx = self.search([
                        ('id', '=', sp_id),
                        ('provider_code', '=', 'bancard'),
                    ], limit=1)
        return tx

    def _extract_amount_data(self, payment_data):
        if self.provider_code != 'bancard':
            return super()._extract_amount_data(payment_data)

        operation = payment_data.get('operation', payment_data)
        received_token = operation.get('token')
        amount = operation.get('amount')
        currency = operation.get('currency', 'PYG')
        shop_process_id = operation.get('shop_process_id') or self.bancard_shop_process_id or self.id

        # F-02: Token y Amount son estrictamente obligatorios en la confirmación Bancard vPOS
        if not received_token:
            _logger.error("Bancard: Token ausente en la confirmación del shop_process_id=%s", shop_process_id)
            raise ValidationError(_("Bancard: Token de confirmación ausente en el payload!"))

        if amount is None:
            _logger.error("Bancard: Monto (amount) ausente en la confirmación del shop_process_id=%s", shop_process_id)
            raise ValidationError(_("Bancard: Monto (amount) ausente en el payload de confirmación!"))

        expected_token = self.provider_id.sudo()._bancard_generate_token(
            'confirm',
            shop_process_id=shop_process_id,
            amount=amount,
            currency=currency,
        )
        if not hmac.compare_digest(str(received_token), str(expected_token)):
            _logger.error(
                "Bancard: Token MD5 inválido en la confirmación del shop_process_id=%s",
                shop_process_id,
            )
            raise ValidationError(_("Bancard: Firma MD5 de confirmación inválida!"))

        if amount is None:
            return None

        # Si la transacción original fue en BRL o USD y convertida a PYG, validamos contra bancard_pyg_amount
        if self.currency_id.name != 'PYG' and self.bancard_pyg_amount:
            if abs(float(amount) - self.bancard_pyg_amount) > 1.0:
                raise ValidationError(
                    _("Bancard: Divergencia de monto convertido a PYG (esperado %s, recibido %s).",
                      self.bancard_pyg_amount, amount)
                )
            return None

        return {
            'amount': float(amount),
            'currency_code': currency,
        }

    def _apply_updates(self, payment_data):
        if self.provider_code != 'bancard':
            return super()._apply_updates(payment_data)

        operation = payment_data.get('operation', payment_data)
        response = operation.get('response')
        response_code = operation.get('response_code') or operation.get('response_details') or ''
        response_description = operation.get('response_description', '')
        extended_description = operation.get('extended_response_description', '')
        auth_number = operation.get('authorization_number', '')
        ticket_number = operation.get('ticket_number', '')
        security_info = operation.get('security_information', {})

        self.write({
            'provider_reference': str(ticket_number or auth_number or self.bancard_shop_process_id or self.id),
            'bancard_authorization_number': str(auth_number) if auth_number else False,
            'bancard_ticket_number': str(ticket_number) if ticket_number else False,
            'bancard_response_code': str(response_code) if response_code else False,
            'bancard_response_description': response_description,
            'bancard_extended_description': extended_description,
            'bancard_security_info': pprint.pformat(security_info) if security_info else False,
        })

        if response == 'S' and response_code == '00':
            self._set_done()
        elif response == 'N' or (response_code and response_code != '00'):
            readable = const.BANCARD_RESPONSE_CODES.get(
                response_code, response_description or _("Pagamento recusado")
            )
            msg = f"[{response_code}] {readable}"
            if extended_description:
                msg = f"{msg} — {extended_description}"
            self._set_error(msg)
        else:
            self._set_pending(
                state_message=response_description or _("Aguardando confirmação da Bancard.")
            )
