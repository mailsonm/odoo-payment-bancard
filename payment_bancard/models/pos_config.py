# -*- coding: utf-8 -*-
import base64

from odoo import _, fields, models
from odoo.exceptions import ValidationError
from odoo.tools.sql import column_exists

from odoo.addons.payment_bancard import const


class PosConfig(models.Model):
    _inherit = 'pos.config'

    bancard_qr_enabled = fields.Boolean(
        string="Habilitar Bancard VentasQR (Rollout Filial)",
        default=False,
        help="Ativa a geração de QR Dinâmico Express da Bancard neste Ponto de Venda (permite rollout gradual iniciando pela filial piloto).",
    )
    bancard_qr_environment = fields.Selection(
        selection=[
            ('test', 'Staging / Homologação (:8888)'),
            ('production', 'Produção'),
        ],
        string="Ambiente VentasQR",
        default='test',
        required=False,
    )
    bancard_commerce_code = fields.Char(
        string="Código de Comércio Bancard (VentasQR)",
        help="Código do comércio fornecido pela Bancard (ex: 7851).",
    )
    bancard_branch_code = fields.Char(
        string="Código de Sucursal Bancard (VentasQR)",
        default='1',
        help="Código da sucursal desta filial na Bancard (ex: 1, 2, etc.).",
    )
    bancard_qr_public_key = fields.Char(
        string="Chave Pública VentasQR",
        groups='base.group_system',
        help="Chave pública específica para a API VentasQR (enviada com prefixo apps/ no Basic Auth).",
    )
    bancard_qr_private_key = fields.Char(
        string="Chave Privada VentasQR",
        groups='base.group_system',
        help="Chave privada específica para a API VentasQR.",
    )

    # === Bancard Caja POS 3.0 (Terminal Físico / Pinpad REST) ===
    bancard_cajapos_enabled = fields.Boolean(
        string="Habilitar Bancard Caja POS 3.0 (Terminal Físico)",
        default=False,
        help="Ativa a integração direta com a maquininha física Bancard neste Ponto de Venda (Rollout gradual por filial piloto).",
    )
    bancard_cajapos_environment = fields.Selection(
        selection=[
            ('test', 'Staging / QA (:8888 ou Host Teste)'),
            ('production', 'Produção'),
        ],
        string="Ambiente Caja POS 3.0",
        default='test',
        required=False,
    )
    bancard_cajapos_base_url = fields.Char(
        string="URL Base Customizada Caja POS",
        help="Deixe em branco para usar a URL padrão do ambiente selecionado.",
    )
    bancard_cajapos_commerce_code = fields.Char(
        string="Código de Comércio (commerceCode)",
        help="Código de comércio fornecido pela Bancard para Caja POS (ex: ROSHKA-COMMERCE-TEST).",
    )
    bancard_cajapos_api_key = fields.Char(
        string="API Key (Segredo JWT HS256)",
        groups='base.group_system',
        help="Chave secreta compartilhada para assinar os tokens JWT via HMAC-SHA256.",
    )
    bancard_cajapos_pos_code = fields.Char(
        string="Código do Terminal POS Físico (posCode)",
        help="Código único da maquininha física instalada neste caixa (ex: pos2342 ou p652000010658).",
    )
    bancard_cajapos_provider_id = fields.Char(
        string="Provider ID (4 dígitos)",
        default='0001',
        help="Identificador do provedor na Bancard. Deve conter exatamente 4 dígitos (ex: 0001).",
    )
    bancard_cajapos_print_voucher = fields.Boolean(
        string="Imprimir Comprovante no Terminal POS",
        default=True,
        help="Se marcado, a maquininha física imprime o cupom diretamente após aprovação da transação.",
    )

    def _bancard_qr_get_base_url(self):
        self.ensure_one()
        if self.bancard_qr_environment == 'production':
            return const.BANCARD_QR_PRODUCTION_URL
        return const.BANCARD_QR_STAGING_URL

    def _bancard_qr_get_credentials(self):
        """Obtém commerce_code, branch_code, public_key e private_key da filial ou do provider padrão."""
        self.ensure_one()
        config_sudo = self.sudo()
        provider = self.env['payment.provider'].sudo().search([
            ('code', '=', 'bancard'),
            ('company_id', 'in', [self.company_id.id, False]),
        ], limit=1)

        commerce_code = (config_sudo.bancard_commerce_code or (provider and provider.bancard_commerce_code) or '').strip()
        branch_code = (config_sudo.bancard_branch_code or (provider and provider.bancard_branch_code) or '1').strip()
        pub_key = (config_sudo.bancard_qr_public_key or (provider and provider.bancard_qr_public_key) or '').strip()
        priv_key = (config_sudo.bancard_qr_private_key or (provider and provider.bancard_qr_private_key) or '').strip()

        if not commerce_code or not branch_code or not pub_key or not priv_key:
            raise ValidationError(
                _("Credenciais Bancard VentasQR incompletas na configuração do PDV '%s'. Verifique Código de Comércio, Sucursal e Chaves VentasQR.", self.display_name)
            )
        return commerce_code, branch_code, pub_key, priv_key

    def _bancard_qr_get_auth_header(self):
        """Gera o cabeçalho HTTP Basic Auth oficial: Basic base64('apps/' + public_key + ':' + private_key)."""
        self.ensure_one()
        _commerce, _branch, pub_key, priv_key = self._bancard_qr_get_credentials()
        raw_credentials = f"apps/{pub_key}:{priv_key}"
        encoded = base64.b64encode(raw_credentials.encode('utf-8')).decode('utf-8')
        return f"Basic {encoded}"

    def _bancard_cajapos_get_base_url(self):
        self.ensure_one()
        if self.bancard_cajapos_base_url:
            return self.bancard_cajapos_base_url.strip().rstrip('/')
        if self.bancard_cajapos_environment == 'production':
            return const.BANCARD_CAJAPOS_PRODUCTION_URL
        return const.BANCARD_CAJAPOS_STAGING_URL

    def _bancard_cajapos_get_credentials(self):
        """Valida e retorna os dados de conexão do Caja POS 3.0."""
        self.ensure_one()
        config_sudo = self.sudo()
        provider = self.env['payment.provider'].sudo().search([
            ('code', '=', 'bancard'),
            ('company_id', 'in', [self.company_id.id, False]),
        ], limit=1)

        commerce_code = (config_sudo.bancard_cajapos_commerce_code or (provider and provider.bancard_commerce_code) or '').strip()
        api_key = (config_sudo.bancard_cajapos_api_key or (provider and provider.bancard_private_key) or '').strip()
        pos_code = (config_sudo.bancard_cajapos_pos_code or '').strip()
        provider_id = (config_sudo.bancard_cajapos_provider_id or '0001').strip()

        if not commerce_code:
            raise ValidationError(_("Código de comercio (commerceCode) no configurado para Caja POS 3.0."))
        if not api_key:
            raise ValidationError(_("API Key (Secreto JWT) no configurada para Caja POS 3.0."))
        if not pos_code:
            raise ValidationError(_("Código del Terminal POS Físico (posCode) no configurado en este PDV."))
        if not provider_id or len(provider_id) != 4 or not provider_id.isdigit():
            raise ValidationError(
                _("providerId debe contener exactamente 4 dígitos numéricos (regex: ^\\d{4}$). Valor actual: '%s'", provider_id)
            )

        return {
            'commerce_code': commerce_code,
            'api_key': api_key,
            'pos_code': pos_code,
            'provider_id': provider_id,
            'print_voucher': bool(config_sudo.bancard_cajapos_print_voucher),
        }

