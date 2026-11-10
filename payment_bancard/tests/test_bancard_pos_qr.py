# -*- coding: utf-8 -*-
import base64
from unittest.mock import patch, MagicMock

from odoo.exceptions import ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged('post_install', '-at_install', 'payment_bancard')
class TestBancardPosQr(TransactionCase):
    """Suíte TDD para a Integração PDV Bancard VentasQR v1.2 por Filial Piloto (Etapa 3)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company

        cls.journal_bank = cls.env['account.journal'].search([
            ('type', '=', 'bank'),
            ('company_id', '=', cls.company.id),
        ], limit=1)
        if not cls.journal_bank:
            cls.journal_bank = cls.env['account.journal'].create({
                'name': 'Banco Bancard QR',
                'code': 'BCQR',
                'type': 'bank',
                'company_id': cls.company.id,
            })

        cls.pm_bancard_qr = cls.env['pos.payment.method'].create({
            'name': 'Bancard QR / PIX',
            'journal_id': cls.journal_bank.id,
            'use_payment_terminal': 'bancard_qr',
            'company_id': cls.company.id,
        })

        # Filial Piloto com Bancard QR habilitado
        cls.pos_config_pilot = cls.env['pos.config'].create({
            'name': 'PDV Filial Piloto (Bancard QR)',
            'company_id': cls.company.id,
            'bancard_qr_enabled': True,
            'bancard_qr_environment': 'test',
            'bancard_commerce_code': '7851',
            'bancard_branch_code': '1',
            'bancard_qr_public_key': 'qr_pub_key_abc123',
            'bancard_qr_private_key': 'qr_priv_key_xyz789',
            'payment_method_ids': [(4, cls.pm_bancard_qr.id)],
        })

        # Outra Filial onde o rollout ainda está desativado
        cls.pos_config_disabled = cls.env['pos.config'].create({
            'name': 'PDV Filial 02 (Sem Rollout QR)',
            'company_id': cls.company.id,
            'bancard_qr_enabled': False,
        })

    def test_01_pilot_branch_feature_flag_enforcement(self):
        """Garante que apenas filiais com bancard_qr_enabled=True podem gerar QR Dinâmico no PDV."""
        with self.assertRaises(ValidationError):
            self.pm_bancard_qr.bancard_qr_create_order({
                'pos_config_id': self.pos_config_disabled.id,
                'amount': 45000,
                'description': 'Venta Farmacia Filial 02',
                'pos_order_uuid': 'uuid-disabled-01',
            })

    def test_02_generate_qr_express_and_basic_auth_apps_prefix(self):
        """Verifica geração de QR Express (POST generate-qr-express) e cabeçalho Basic Auth com prefixo apps/."""
        expected_raw = "apps/qr_pub_key_abc123:qr_priv_key_xyz789"
        expected_b64 = base64.b64encode(expected_raw.encode('utf-8')).decode('utf-8')
        auth_header = self.pos_config_pilot._bancard_qr_get_auth_header()
        self.assertEqual(
            auth_header,
            f"Basic {expected_b64}",
            "A API VentasQR v1.2 exige o prefixo 'apps/' antes da public_key no Basic Auth!"
        )

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            'status': 'success',
            'qr_express': {
                'hook_alias': 'QR_FA_MATRIZ_0001',
                'url': 'https://comercios.bancard.com.py/qr/QR_FA_MATRIZ_0001.png',
                'qr_data': '00020101021226380014py.com.bancard...',
            },
            'supported_clients': [{'name': 'Tpago', 'logo_url': 'https://comercios.bancard.com.py/tpago.png'}],
        }

        with patch('requests.Session.request', return_value=mock_resp) as mock_req:
            res = self.pm_bancard_qr.bancard_qr_create_order({
                'pos_config_id': self.pos_config_pilot.id,
                'amount': 75000.0,
                'description': 'Pedido POS 0001',
                'pos_order_uuid': 'uuid-pilot-0001',
            })
            self.assertEqual(res.get('status'), 'success')
            self.assertEqual(res.get('hook_alias'), 'QR_FA_MATRIZ_0001')
            self.assertIn('000201010212', res.get('qr_data', ''))

            # Verificar URL e payload enviados (valor inteiro em PYG)
            called_url = mock_req.call_args.kwargs.get('url') or mock_req.call_args[1].get('url')
            self.assertIn('/external-commerce/api/0.1/commerces/7851/branches/1/selling/generate-qr-express', called_url)
            sent_json = mock_req.call_args.kwargs.get('json') or mock_req.call_args[1].get('json')
            self.assertEqual(sent_json['amount'], 75000)
            self.assertIsInstance(sent_json['amount'], int)

        qr_tx = self.env['bancard.pos.qr.transaction'].search([('name', '=', 'QR_FA_MATRIZ_0001')], limit=1)
        self.assertTrue(qr_tx)
        self.assertEqual(qr_tx.state, 'pending')

    def test_03_webhook_confirmation_and_anti_double_charge_on_reverted_qr(self):
        """
        Verifica a regra crítica de homologação Bancard VentasQR:
        1) Se o QR está 'pending', o webhook confirma ('Confirmed') e muda o estado para 'confirmed'.
        2) Se o caixa cancelou/reverteu o QR ('revert_requested'), e um webhook tardio chega depois,
           o backend DEVE rejeitar com 'ConfirmedError' para provocar o estorno automático na Bancard.
        """
        from odoo.addons.payment_bancard.controllers.main import BancardController
        ctrl = BancardController()

        # Caso 1: QR pendente normal -> Confirma com sucesso
        qr_tx_ok = self.env['bancard.pos.qr.transaction'].create({
            'name': 'QR_HOOK_OK_100',
            'pos_config_id': self.pos_config_pilot.id,
            'payment_method_id': self.pm_bancard_qr.id,
            'amount': 50000,
            'description': 'Venda Normal POS',
            'state': 'pending',
        })

        webhook_ok = {
            'operation': {
                'type': 'payment_SDP',
                'payment': {
                    'hook_alias': 'QR_HOOK_OK_100',
                    'amount': 50000,
                    'currency': 'PYG',
                    'branch_code': '1',
                    'ticket_number': 'TCK_QR_100',
                    'authorization_number': 'AUTH_QR_100',
                },
            }
        }
        resp_ok, http_code_ok = ctrl._process_pos_qr_webhook_payload(self.env, webhook_ok)
        self.assertEqual(http_code_ok, 200)
        self.assertEqual(resp_ok['status'], 'success')
        self.assertEqual(resp_ok['messages'][0]['key'], 'Confirmed')
        self.assertEqual(qr_tx_ok.state, 'confirmed')

        # F-01 Caso 1b: Reenvio idempotente (replay) de transação já confirmada
        resp_replay, http_code_replay = ctrl._process_pos_qr_webhook_payload(self.env, webhook_ok)
        self.assertEqual(http_code_replay, 200)
        self.assertEqual(resp_replay['status'], 'success')

        # F-01 Caso 1c: Rejeição por divergência de valor (AmountMismatchError)
        qr_tx_mismatch = self.env['bancard.pos.qr.transaction'].create({
            'name': 'QR_HOOK_MISMATCH_101',
            'pos_config_id': self.pos_config_pilot.id,
            'payment_method_id': self.pm_bancard_qr.id,
            'amount': 50000,
            'description': 'Venda Normal POS',
            'state': 'pending',
        })
        webhook_mismatch = {
            'operation': {
                'type': 'payment_SDP',
                'payment': {
                    'hook_alias': 'QR_HOOK_MISMATCH_101',
                    'amount': 999999,  # Divergente dos 50.000 registrados
                    'currency': 'PYG',
                    'branch_code': '1',
                },
            }
        }
        resp_mismatch, http_code_mismatch = ctrl._process_pos_qr_webhook_payload(self.env, webhook_mismatch)
        self.assertEqual(http_code_mismatch, 400)
        self.assertEqual(resp_mismatch['status'], 'error')
        self.assertEqual(resp_mismatch['messages'][0]['key'], 'AmountMismatchError')
        self.assertEqual(qr_tx_mismatch.state, 'pending')

        # Caso 2: QR revertido pelo operador de caixa por timeout/desistência -> Webhook tardio deve retornar ConfirmedError!
        qr_tx_reverted = self.env['bancard.pos.qr.transaction'].create({
            'name': 'QR_HOOK_REVERTED_200',
            'pos_config_id': self.pos_config_pilot.id,
            'payment_method_id': self.pm_bancard_qr.id,
            'amount': 95000,
            'description': 'Venda Cancelada no Caixa',
            'state': 'pending',
        })

        mock_revert_resp = MagicMock()
        mock_revert_resp.status_code = 200
        mock_revert_resp.json.return_value = {'status': 'success'}

        with patch('requests.Session.request', return_value=mock_revert_resp):
            revert_res = self.pm_bancard_qr.bancard_qr_revert_order({
                'pos_config_id': self.pos_config_pilot.id,
                'hook_alias': 'QR_HOOK_REVERTED_200',
            })
            self.assertEqual(revert_res.get('status'), 'success')
            self.assertEqual(qr_tx_reverted.state, 'revert_requested')

        # Agora simula chegada de callback tardio para o QR que já sofreu revert
        webhook_late = {
            'operation': {
                'type': 'payment_SDP',
                'payment': {
                    'hook_alias': 'QR_HOOK_REVERTED_200',
                    'amount': 95000,
                    'currency': 'PYG',
                    'branch_code': '1',
                },
            }
        }
        resp_late, http_code_late = ctrl._process_pos_qr_webhook_payload(self.env, webhook_late)
        self.assertEqual(resp_late['status'], 'error')
        self.assertEqual(resp_late['messages'][0]['key'], 'ConfirmedError')
        self.assertEqual(qr_tx_reverted.state, 'revert_requested')

        # 3) Verificar regra rígida de Soft Delete (proibição de unlink físico)
        with self.assertRaises(ValidationError):
            qr_tx_ok.unlink()
        qr_tx_ok.write({'active': False})
        self.assertFalse(qr_tx_ok.active)
