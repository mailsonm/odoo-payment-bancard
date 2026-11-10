# -*- coding: utf-8 -*-
import hashlib
import logging
import pprint
import requests

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

from odoo.addons.payment_bancard import const

_logger = logging.getLogger(__name__)


class PaymentProvider(models.Model):
    _inherit = 'payment.provider'

    code = fields.Selection(
        selection_add=[('bancard', "Bancard")],
        ondelete={'bancard': 'set default'},
    )

    bancard_public_key = fields.Char(
        string="Chave Pública vPOS (Public Key)",
        help="Chave pública de 32 caracteres fornecida pela Bancard para o vPOS 2.0.",
        required_if_provider='bancard',
        groups='base.group_system',
    )
    bancard_private_key = fields.Char(
        string="Chave Privada vPOS (Private Key)",
        help="Chave privada de 40 caracteres fornecida pela Bancard para geração de tokens MD5.",
        required_if_provider='bancard',
        groups='base.group_system',
    )
    bancard_enable_pix = fields.Boolean(
        string="Habilitar PIX (Fronteira BRL -> PYG)",
        default=True,
        help="Permite pagamentos via PIX Online pela Bancard com conversão automática de BRL para PYG.",
    )
    bancard_commerce_code = fields.Char(
        string="Código de Comércio (VentasQR / Tpago)",
        help="Código identificador do comércio na Bancard para QR Dinâmico no PDV.",
        groups='base.group_system',
    )
    bancard_branch_code = fields.Char(
        string="Código de Sucursal Padrão",
        default='1',
        help="Código padrão da sucursal cadastrada na Bancard para QR Dinâmico.",
        groups='base.group_system',
    )
    bancard_qr_public_key = fields.Char(
        string="Chave Pública VentasQR",
        help="Chave pública da API VentasQR (utilizada com prefixo apps/ no Basic Auth).",
        groups='base.group_system',
    )
    bancard_qr_private_key = fields.Char(
        string="Chave Privada VentasQR",
        help="Chave privada da API VentasQR.",
        groups='base.group_system',
    )

    # Personalização de estilos do Iframe Bancard Checkout JS v5.0.1
    bancard_form_background_color = fields.Char(
        string="Cor de Fundo do Formulário",
        default='#ffffff',
    )
    bancard_button_background_color = fields.Char(
        string="Cor de Fundo do Botão",
        default='#006400',
    )
    bancard_button_text_color = fields.Char(
        string="Cor do Texto do Botão",
        default='#ffffff',
    )
    bancard_button_border_color = fields.Char(
        string="Cor da Borda do Botão",
        default='#006400',
    )
    bancard_input_background_color = fields.Char(
        string="Cor de Fundo dos Campos",
        default='#ffffff',
    )
    bancard_input_text_color = fields.Char(
        string="Cor do Texto dos Campos",
        default='#333333',
    )
    bancard_input_placeholder_color = fields.Char(
        string="Cor do Placeholder",
        default='#999999',
    )

    @api.depends('code')
    def _compute_feature_support_fields(self):
        super()._compute_feature_support_fields()
        for provider in self.filtered(lambda p: p.code == 'bancard'):
            provider.support_tokenization = True
            provider.support_refund = 'full_only'

    def _get_default_payment_method_codes(self):
        default_codes = super()._get_default_payment_method_codes()
        if self.code != 'bancard':
            return default_codes
        return const.DEFAULT_PAYMENT_METHOD_CODES

    def _get_supported_currencies(self):
        supported_currencies = super()._get_supported_currencies()
        if self.code == 'bancard':
            supported_currencies = supported_currencies.filtered(
                lambda c: c.name in const.SUPPORTED_CURRENCIES
            )
        return supported_currencies

    def _bancard_get_api_url(self):
        self.ensure_one()
        if self.state == 'enabled':
            return const.BANCARD_PRODUCTION_URL
        return const.BANCARD_STAGING_URL

    def _bancard_get_qr_api_url(self):
        self.ensure_one()
        if self.state == 'enabled':
            return const.BANCARD_QR_PRODUCTION_URL
        return const.BANCARD_QR_STAGING_URL

    def _bancard_get_checkout_js_url(self):
        self.ensure_one()
        base_url = self._bancard_get_api_url()
        return f"{base_url}/checkout/javascript/dist/bancard-checkout-{const.BANCARD_CHECKOUT_JS_VERSION}.js"

    def _bancard_get_iframe_styles(self):
        self.ensure_one()
        return {
            'form-background-color': self.bancard_form_background_color or '#ffffff',
            'button-background-color': self.bancard_button_background_color or '#006400',
            'button-text-color': self.bancard_button_text_color or '#ffffff',
            'button-border-color': self.bancard_button_border_color or '#006400',
            'input-background-color': self.bancard_input_background_color or '#ffffff',
            'input-text-color': self.bancard_input_text_color or '#333333',
            'input-placeholder-color': self.bancard_input_placeholder_color or '#999999',
        }

    def _bancard_generate_token(self, operation_type, **kwargs):
        """Gera o hash MD5 estrito exigido pela documentação oficial do Bancard vPOS 2.0."""
        self.ensure_one()
        pk = (self.sudo().bancard_private_key or '').strip()

        if operation_type == 'single_buy':
            token_str = f"{pk}{kwargs['shop_process_id']}{kwargs['amount']}{kwargs['currency']}"
        elif operation_type == 'confirm':
            token_str = f"{pk}{kwargs['shop_process_id']}confirm{kwargs['amount']}{kwargs['currency']}"
        elif operation_type == 'get_confirmation':
            token_str = f"{pk}{kwargs['shop_process_id']}get_confirmation"
        elif operation_type == 'rollback':
            token_str = f"{pk}{kwargs['shop_process_id']}rollback0.00"
        elif operation_type == 'cards_new':
            token_str = f"{pk}{kwargs['card_id']}{kwargs['user_id']}request_new_card"
        elif operation_type == 'users_cards':
            token_str = f"{pk}{kwargs['user_id']}request_user_cards"
        elif operation_type == 'charge':
            token_str = (
                f"{pk}{kwargs['shop_process_id']}charge"
                f"{kwargs['amount']}{kwargs['currency']}{kwargs['alias_token']}"
            )
        elif operation_type == 'delete_card':
            token_str = f"{pk}delete_card{kwargs['user_id']}{kwargs['alias_token']}"
        else:
            raise ValidationError(_("Bancard: Tipo de operação desconhecido: %s", operation_type))

        return hashlib.md5(token_str.encode('utf-8')).hexdigest()

    def _bancard_make_request(self, endpoint, payload=None, method='POST'):
        """Executa chamadas HTTPS à API vPOS 2.0 da Bancard com tratamento de erros oficial."""
        self.ensure_one()
        url = f"{self._bancard_get_api_url()}{endpoint}"
        headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json',
        }

        _logger.info("Bancard vPOS Request [%s] %s", method, url)

        try:
            with requests.Session() as session:
                response = session.request(
                    method=method,
                    url=url,
                    json=payload,
                    headers=headers,
                    timeout=30,
                    verify=True,
                )
            try:
                result = response.json()
            except ValueError as err:
                raise ValidationError(
                    _("Bancard: Respuesta inválida (no-JSON) del servidor HTTP %s.", response.status_code)
                ) from err

            if response.status_code >= 400 or result.get('status') == 'error':
                messages = result.get('messages', [])
                first_key = messages[0].get('key', '') if messages else ''
                # En la operación de rollback, PaymentNotFoundError indica que el comprador abandonó
                # el checkout antes de pagar — el SDK oficial Python lo trata como cancelación limpia.
                if endpoint.endswith('/rollback') and first_key == 'PaymentNotFoundError':
                    return {
                        'status': 'error',
                        'key': 'PaymentNotFoundError',
                        'messages': messages,
                    }

                error_msgs = [
                    f"{m.get('key', 'Error')}: {m.get('description', '')}"
                    for m in messages
                ]
                error_detail = '; '.join(error_msgs) if error_msgs else pprint.pformat(result)
                _logger.error("Bancard vPOS API Error: %s", error_detail)
                raise ValidationError(_("Error en la comunicación con Bancard: %s", error_detail))

            return result

        except requests.exceptions.Timeout as err:
            _logger.error("Bancard vPOS Timeout: %s", url)
            raise ValidationError(_("Tiempo límite agotado al conectar con Bancard.")) from err
        except requests.exceptions.ConnectionError as err:
            _logger.error("Bancard vPOS ConnectionError: %s", err)
            raise ValidationError(_("No fue posible conectar con el servidor de Bancard.")) from err
        except requests.exceptions.RequestException as err:
            _logger.error("Bancard vPOS RequestException: %s", err)
            raise ValidationError(_("Error en la solicitud a Bancard: %s", str(err))) from err
