# -*- coding: utf-8 -*-
import logging

from odoo import fields, models
from odoo.addons.payment_bancard import const

_logger = logging.getLogger(__name__)


class PaymentToken(models.Model):
    _inherit = 'payment.token'

    bancard_alias_token = fields.Char(
        string="Bancard Alias Token",
        help="Token temporário/alias da Bancard para cobranças 1-click e exclusão.",
        readonly=True,
    )
    bancard_card_masked_number = fields.Char(
        string="Cartão Mascarado",
        readonly=True,
    )
    bancard_card_expiration_date = fields.Char(
        string="Data de Validade",
        readonly=True,
    )
    bancard_card_brand = fields.Char(
        string="Bandeira do Cartão",
        readonly=True,
    )
    bancard_card_id = fields.Integer(
        string="Bancard Card ID",
        readonly=True,
    )
    bancard_card_type = fields.Selection(
        selection=[('credit', 'Crédito'), ('debit', 'Débito')],
        string="Tipo de Cartão",
        readonly=True,
    )

    def _bancard_remote_delete_token(self):
        """Remove o cartão tokenizado na API da Bancard quando inativado."""
        for token in self.filtered(lambda t: t.provider_code == 'bancard' and t.bancard_alias_token):
            try:
                provider = token.provider_id.sudo()
                user_id = token.partner_id.id
                md5_token = provider._bancard_generate_token(
                    'delete_card',
                    user_id=user_id,
                    alias_token=token.bancard_alias_token,
                )
                endpoint = const.BANCARD_ENDPOINTS['users_cards'].format(user_id=user_id)
                payload = {
                    'public_key': provider.bancard_public_key,
                    'operation': {
                        'token': md5_token,
                        'alias_token': token.bancard_alias_token,
                    },
                }
                provider._bancard_make_request(endpoint, payload, method='DELETE')
            except Exception as err:
                _logger.warning(
                    "Bancard: Falha ao remover token remoto %s na Bancard: %s",
                    token.id, err,
                )

    def write(self, vals):
        if vals.get('active') is False:
            self._bancard_remote_delete_token()
        return super().write(vals)
