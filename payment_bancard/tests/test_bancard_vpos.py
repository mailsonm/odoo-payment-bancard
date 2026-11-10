# -*- coding: utf-8 -*-
import hashlib
from unittest.mock import patch, MagicMock

from odoo.exceptions import ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged('post_install', '-at_install', 'payment_bancard')
class TestBancardVpos(TransactionCase):
    """Suíte TDD para o Core Bancard vPOS 2.0 no Odoo 19 (Etapa 1)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.currency_pyg = cls.env.ref('base.PYG', raise_if_not_found=False) or cls.env['res.currency'].search([('name', '=', 'PYG')], limit=1)
        cls.currency_brl = cls.env.ref('base.BRL', raise_if_not_found=False) or cls.env['res.currency'].search([('name', '=', 'BRL')], limit=1)
        cls.currency_usd = cls.env.ref('base.USD', raise_if_not_found=False) or cls.env['res.currency'].search([('name', '=', 'USD')], limit=1)

        if cls.currency_pyg:
            cls.currency_pyg.sudo().write({'active': True})
        if cls.currency_brl:
            cls.currency_brl.sudo().write({'active': True})
        if cls.currency_usd:
            cls.currency_usd.sudo().write({'active': True})

        cls.partner = cls.env['res.partner'].create({
            'name': 'Cliente Fronteira PJC',
            'email': 'cliente.pjc@americana.com.py',
            'phone': '+595981000111',
        })

        cls.provider = cls.env['payment.provider'].create({
            'name': 'Bancard Test Provider',
            'code': 'bancard',
            'state': 'test',
            'company_id': cls.env.company.id,
            'bancard_public_key': 'pub_test_key_12345678901234567890',
            'bancard_private_key': 'priv_test_key_12345678901234567890',
            'bancard_enable_pix': True,
        })

        cls.payment_method = cls.env['payment.method'].search([('code', '=', 'card')], limit=1)
        if not cls.payment_method:
            cls.payment_method = cls.env['payment.method'].create({
                'name': 'Card',
                'code': 'card',
                'support_tokenization': True,
                'support_refund': 'full_only',
            })

    def _create_tx(self, reference='FA-TEST-0001', amount=150000.0, currency=None, **kwargs):
        vals = {
            'provider_id': self.provider.id,
            'payment_method_id': self.payment_method.id,
            'reference': reference,
            'amount': amount,
            'currency_id': (currency or self.currency_pyg).id,
            'partner_id': self.partner.id,
        }
        vals.update(kwargs)
        return self.env['payment.transaction'].create(vals)

    def test_01_provider_urls_and_currencies(self):
        """Verifica URLs da API vPOS 2.0, Checkout JS v5.0.1 e moedas suportadas (PYG, BRL, USD)."""
        self.assertEqual(
            self.provider._bancard_get_api_url(),
            'https://vpos.infonet.com.py:8888',
            "Em modo test, a URL base deve apontar para a porta 8888 de staging da Bancard."
        )
        self.assertIn(
            'bancard-checkout-5.0.1.js',
            self.provider._bancard_get_checkout_js_url(),
            "A URL do script JS deve usar a versão estável 5.0.1 do bancard-checkout-js."
        )

        self.provider.write({'state': 'enabled'})
        self.assertEqual(
            self.provider._bancard_get_api_url(),
            'https://vpos.infonet.com.py',
            "Em modo produção (enabled), a URL base deve apontar para vpos.infonet.com.py."
        )
        self.provider.write({'state': 'test'})

        default_currencies = self.provider._get_default_payment_method_codes()
        self.assertIn('card', default_currencies)

    def test_02_md5_token_generation_and_description_truncation(self):
        """Verifica geração exata de tokens MD5 e truncamento de description em 20 caracteres no single_buy."""
        priv = self.provider.bancard_private_key
        expected_single_buy = hashlib.md5(f"{priv}101150000.00PYG".encode('utf-8')).hexdigest()
        token_single_buy = self.provider._bancard_generate_token(
            'single_buy',
            shop_process_id=101,
            amount='150000.00',
            currency='PYG',
        )
        self.assertEqual(token_single_buy, expected_single_buy)

        expected_charge = hashlib.md5(f"{priv}102charge150000.00PYGtok_abc".encode('utf-8')).hexdigest()
        token_charge = self.provider._bancard_generate_token(
            'charge',
            shop_process_id=102,
            amount='150000.00',
            currency='PYG',
            alias_token='tok_abc',
        )
        self.assertEqual(token_charge, expected_charge)

        tx = self._create_tx(reference='FA-SUPER-LONG-ORDER-REFERENCE-2026-0099', amount=150000.0)
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {'status': 'success', 'process_id': 'proc_12345'}

        with patch('requests.Session.request', return_value=mock_resp) as mock_req:
            process_id = tx._bancard_create_single_buy()
            self.assertEqual(process_id, 'proc_12345')
            sent_payload = mock_req.call_args.kwargs.get('json') or mock_req.call_args[1].get('json')
            operation = sent_payload['operation']
            self.assertLessEqual(
                len(operation['description']),
                20,
                "A documentação oficial da Bancard exige que description tenha no máximo 20 caracteres!"
            )
            self.assertEqual(operation['amount'], '150000.00')
            self.assertEqual(operation['currency'], 'PYG')

    def test_03_multicurrency_brl_to_pyg_conversion_and_pix(self):
        """Verifica conversão automática de BRL para PYG na fronteira e envio de flag PIX."""
        tx_brl = self._create_tx(
            reference='FA-BRL-PIX-01',
            amount=100.0,
            currency=self.currency_brl,
            bancard_is_pix=True,
        )
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {'status': 'success', 'process_id': 'proc_pix_999'}

        with patch('requests.Session.request', return_value=mock_resp) as mock_req:
            process_id = tx_brl._bancard_create_single_buy()
            self.assertEqual(process_id, 'proc_pix_999')
            sent_payload = mock_req.call_args.kwargs.get('json') or mock_req.call_args[1].get('json')
            operation = sent_payload['operation']
            self.assertEqual(operation['currency'], 'PYG', "A Bancard exige que a liquidação ocorra em PYG.")
            self.assertGreater(float(operation['amount']), 100.0, "O valor em BRL deve ter sido convertido para PYG.")
            self.assertGreater(tx_brl.bancard_pyg_amount, 100.0)

    def test_04_odoo19_notification_pipeline_approved_and_rejected(self):
        """Verifica o pipeline de webhook do Odoo 19 (_search_by_reference, _extract_amount_data, _apply_updates)."""
        tx = self._create_tx(reference='FA-WEBHOOK-01', amount=85000.0)
        tx.bancard_shop_process_id = tx.id

        priv = self.provider.bancard_private_key
        valid_confirm_token = hashlib.md5(
            f"{priv}{tx.bancard_shop_process_id}confirm85000.00PYG".encode('utf-8')
        ).hexdigest()

        webhook_data = {
            'operation': {
                'token': valid_confirm_token,
                'shop_process_id': tx.bancard_shop_process_id,
                'response': 'S',
                'response_details': '00',
                'amount': '85000.00',
                'currency': 'PYG',
                'authorization_number': 'AUTH9988',
                'ticket_number': 'TCK7766',
                'response_description': 'Transaccion aprobada',
                'security_information': {
                    'card_source': 'L',
                    'card_country': 'PRY',
                    'version': '0.3',
                    'risk_index': '0.1',
                },
            }
        }

        tx._process('bancard', webhook_data)
        self.assertEqual(tx.state, 'done', "Transação com response='S' e response_code='00' deve ficar 'done'.")
        self.assertEqual(tx.bancard_authorization_number, 'AUTH9988')
        self.assertEqual(tx.bancard_ticket_number, 'TCK7766')

        # Testar rejeição de token MD5 adulterado
        tx_tampered = self._create_tx(reference='FA-WEBHOOK-02', amount=85000.0)
        tx_tampered.bancard_shop_process_id = tx_tampered.id
        bad_webhook = {
            'operation': {
                'token': 'invalid_md5_token_0000000000000000',
                'shop_process_id': tx_tampered.bancard_shop_process_id,
                'response': 'S',
                'response_details': '00',
                'amount': '85000.00',
                'currency': 'PYG',
            }
        }
        with self.assertRaises(ValidationError):
            tx_tampered._process('bancard', bad_webhook)

        # F-02: Testar rejeição obrigatória de payload sem token
        tx_no_token = self._create_tx(reference='FA-WEBHOOK-03', amount=85000.0)
        tx_no_token.bancard_shop_process_id = tx_no_token.id
        no_token_webhook = {
            'operation': {
                'shop_process_id': tx_no_token.bancard_shop_process_id,
                'response': 'S',
                'response_details': '00',
                'amount': '85000.00',
                'currency': 'PYG',
            }
        }
        with self.assertRaises(ValidationError):
            tx_no_token._process('bancard', no_token_webhook)

    def test_05_rollback_and_refund_handling_payment_not_found(self):
        """Verifica que _bancard_rollback trata tanto status=success quanto PaymentNotFoundError sem quebrar."""
        tx = self._create_tx(reference='FA-ROLLBACK-01', amount=50000.0)
        tx.bancard_shop_process_id = tx.id
        tx._set_done()

        # Caso 1: PaymentNotFoundError (compra abandonada sem pagamento efetivo na Bancard)
        mock_resp_not_found = MagicMock()
        mock_resp_not_found.status_code = 404
        mock_resp_not_found.json.return_value = {
            'status': 'error',
            'messages': [{'level': 'error', 'key': 'PaymentNotFoundError', 'description': 'Pago no encontrado'}],
        }

        with patch('requests.Session.request', return_value=mock_resp_not_found):
            res = tx._bancard_rollback()
            self.assertEqual(res.get('key'), 'PaymentNotFoundError')
            self.assertEqual(tx.state, 'cancel')

        # Caso 2: Reembolso padrão Odoo 19 via _send_refund_request() (sem argumentos)
        tx2 = self._create_tx(reference='FA-ROLLBACK-02', amount=60000.0)
        tx2.bancard_shop_process_id = tx2.id
        tx2._set_done()

        mock_resp_ok = MagicMock()
        mock_resp_ok.status_code = 200
        mock_resp_ok.json.return_value = {'status': 'success', 'messages': []}

        with patch('requests.Session.request', return_value=mock_resp_ok):
            refund_tx = tx2._create_child_transaction(60000.0, is_refund=True)
            refund_tx._send_refund_request()
            self.assertEqual(refund_tx.state, 'done')
